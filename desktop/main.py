"""Desktop app: the web UI in a native window, saving straight to Downloads.

    python desktop/main.py               # native window (pywebview)
    python desktop/main.py --browser     # dev: open in your browser instead
    URLtoVideo.exe --smoke-test          # CI: end-to-end check of a build

In a PyInstaller build, yt-dlp and ffmpeg are bundled in bin/. yt-dlp is
copied to the user's app-data folder on first run so `yt-dlp -U` can update
it in place (Program Files isn't writable); ffmpeg is used where it is.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from werkzeug.serving import make_server  # noqa: E402

from core import ytdlp  # noqa: E402
from core.jobs import JobManager  # noqa: E402
from web.app import create_app  # noqa: E402

APP_NAME = "URL to Video"
FROZEN = getattr(sys, "frozen", False)
# PyInstaller unpacks data files to sys._MEIPASS; in development use desktop/bin.
BUNDLE_BIN = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "bin"
EXE = ".exe" if ytdlp.IS_WINDOWS else ""
UPDATE_EVERY = 24 * 3600


def default_data_dir():
    if os.environ.get("URLTOVIDEO_DATA_DIR"):
        return Path(os.environ["URLTOVIDEO_DATA_DIR"])
    if ytdlp.IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / "url-to-video"


def redirect_output(data_dir):
    # A windowed PyInstaller build has no console: sys.stdout/stderr are None,
    # which breaks anything that prints. Send it all to a log file instead.
    if sys.stdout is None or sys.stderr is None:
        log = open(data_dir / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def setup_tools(data_dir):
    """Returns (Tools, updatable): updatable when yt-dlp is our own standalone copy."""
    bundled_ytdlp = BUNDLE_BIN / f"yt-dlp{EXE}"
    ffmpeg_dir = str(BUNDLE_BIN) if (BUNDLE_BIN / f"ffmpeg{EXE}").is_file() else None
    if not bundled_ytdlp.is_file():
        return ytdlp.Tools(ytdlp=ytdlp.find_ytdlp(), ffmpeg_dir=ffmpeg_dir), False
    user_ytdlp = data_dir / "bin" / bundled_ytdlp.name
    if not user_ytdlp.is_file():
        user_ytdlp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_ytdlp, user_ytdlp)
    return ytdlp.Tools(ytdlp=str(user_ytdlp), ffmpeg_dir=ffmpeg_dir), True


def update_ytdlp_daily(tools, data_dir):
    stamp = data_dir / "yt-dlp-updated"
    if stamp.exists() and time.time() - stamp.stat().st_mtime < UPDATE_EVERY:
        return
    try:
        ok, out = ytdlp.self_update(tools)
        print(f"[yt-dlp -U] {out}")
        if ok:
            stamp.touch()
    except Exception as e:  # offline, blocked by antivirus, etc.: keep the current copy
        print(f"[yt-dlp -U] failed: {e}")


class Desktop:
    """Desktop-only behaviour the web app calls into (see web/app.py)."""

    def __init__(self, data_dir, tools):
        self.settings_path = data_dir / "settings.json"
        self.tools = tools
        self.allowed_host = None  # set once the server has a port
        self.ytdlp_version = ""
        try:
            self.settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = {}
        saved = self.settings.get("output_dir")
        if not saved or not Path(saved).is_dir():
            self.settings["output_dir"] = str(Path.home() / "Downloads")

    @property
    def output_dir(self):
        return self.settings["output_dir"]

    def get_settings(self):
        return {"output_dir": self.output_dir, "ytdlp_version": self.ytdlp_version}

    def set_output_dir(self, path):
        path = Path(str(path)).expanduser()
        if not path.is_dir():
            raise ValueError("That folder doesn't exist.")
        if not os.access(path, os.W_OK):
            raise ValueError("That folder isn't writable.")
        self.settings["output_dir"] = str(path)
        self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")

    def open_file(self, path):
        if ytdlp.IS_WINDOWS:
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])

    def reveal(self, path):
        if ytdlp.IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])


class JsApi:
    """Exposed to the page as window.pywebview.api (native dialogs)."""

    def __init__(self):
        self._window = None  # underscore: pywebview doesn't expose it to JS

    def choose_folder(self):
        import webview
        folder = getattr(webview, "FileDialog", None)
        kind = folder.FOLDER if folder else webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(kind)
        return result[0] if result else None


def start_server(data_dir, max_concurrent=2):
    tools, updatable = setup_tools(data_dir)
    desktop = Desktop(data_dir, tools)
    manager = JobManager(
        tools,
        out_dir_for=lambda job_id: desktop.output_dir,
        work_dir=data_dir,
        max_concurrent=max_concurrent,
        keep_files_on_remove=True,
    )
    app = create_app(manager, desktop=desktop)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    desktop.allowed_host = f"127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def background():
        if updatable:
            update_ytdlp_daily(tools, data_dir)
        try:
            desktop.ytdlp_version = ytdlp.version(tools)
        except Exception as e:
            print(f"[yt-dlp --version] failed: {e}")

    threading.Thread(target=background, daemon=True).start()
    return f"http://{desktop.allowed_host}/", manager, server


def main():
    parser = argparse.ArgumentParser(prog="URLtoVideo")
    parser.add_argument("--browser", action="store_true", help="open in the default browser (development)")
    parser.add_argument("--smoke-test", action="store_true", help="run an end-to-end self test and exit")
    args = parser.parse_args()

    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    redirect_output(data_dir)

    if args.smoke_test:
        from desktop.smoke_test import run
        sys.exit(run(data_dir))

    url, manager, server = start_server(data_dir)

    try:
        if args.browser:
            import webbrowser
            print(f"Serving on {url} (Ctrl+C to quit)")
            webbrowser.open(url)
            threading.Event().wait()
        else:
            import webview
            api = JsApi()
            api._window = webview.create_window(APP_NAME, url, js_api=api, width=860, height=700, min_size=(480, 420))
            webview.start()
    except KeyboardInterrupt:
        pass
    finally:
        manager.shutdown()
        server.shutdown()


if __name__ == "__main__":
    main()
