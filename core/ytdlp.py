"""Run the yt-dlp executable as a subprocess.

yt-dlp is run as a separate program (not imported) so the desktop build can
update it in place with `yt-dlp -U`. Sites change often enough that a frozen
copy stops working, and this way users get fixes without a new app release.
"""
import os
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

IS_WINDOWS = sys.platform == "win32"
# Keep yt-dlp/ffmpeg from flashing console windows in the windowed desktop app.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0

# Prefer native MP4/M4A streams so no re-encode is needed; otherwise take the
# best available and let ffmpeg merge/convert to MP4.
QUALITIES = {
    "best": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
    "1080": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b[height<=1080]/b",
    "720": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b[height<=720]/b",
    "480": "bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480][ext=mp4]/bv*[height<=480]+ba/b[height<=480]/b",
}

# Machine-readable markers on yt-dlp's stdout, parsed by run_download().
PROGRESS_TEMPLATE = (
    "download:[prog] %(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
    "%(progress.total_bytes_estimate)s|%(progress._speed_str)s|%(progress._eta_str)s"
)
POSTPROCESS_TEMPLATE = "postprocess:[pp] %(progress.status)s"


class Cancelled(Exception):
    pass


@dataclass
class Tools:
    ytdlp: str
    ffmpeg_dir: Optional[str] = None  # None: let yt-dlp find ffmpeg on PATH


def find_ytdlp(extra_dirs=()):
    """Locate yt-dlp: $YTDLP_PATH, the given dirs, next to this Python (a venv's
    bin/Scripts), then PATH."""
    if os.environ.get("YTDLP_PATH"):
        return os.environ["YTDLP_PATH"]
    name = "yt-dlp.exe" if IS_WINDOWS else "yt-dlp"
    for d in [*extra_dirs, Path(sys.executable).parent]:
        candidate = Path(d) / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("yt-dlp")
    if not found:
        raise FileNotFoundError("yt-dlp not found. Install it or set YTDLP_PATH.")
    return found


def kill_tree(proc):
    """Stop yt-dlp and the ffmpeg it started. The Windows yt-dlp.exe is a
    PyInstaller bootloader with a child process, so killing only the top PID
    would leave the real download running."""
    if proc.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, creationflags=NO_WINDOW)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


@dataclass
class DownloadResult:
    path: str
    title: Optional[str] = None


@dataclass
class _Progress:
    on_update: Callable[..., None]
    title: Optional[str] = None
    path: Optional[str] = None
    errors: list = field(default_factory=list)


def _int(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _known(s):
    s = s.strip()
    return "" if s in ("NA", "None") or s.startswith("Unknown") else s


def _handle_line(line, st):
    if line.startswith("[prog] "):
        done, total, estimate, speed, eta = (line[7:].split("|") + [""] * 5)[:5]
        done, total = _int(done) or 0, _int(total) or _int(estimate)
        st.on_update(
            stage="Downloading",
            progress=round(done / total * 100, 1) if total else None,
            speed=_known(speed),
            eta=_known(eta),
        )
    elif line.startswith("[pp] started"):
        st.on_update(stage="Converting to MP4", progress=None, speed="", eta="")
    elif line.startswith("[title] "):
        st.title = line[8:]
        st.on_update(title=st.title)
    elif line.startswith("[file] "):
        st.path = line[7:]
    elif line.startswith("ERROR: "):
        # Drop yt-dlp's "please report this issue..." boilerplate.
        st.errors.append(line[7:].split("; please report this issue")[0])


def run_download(tools, url, quality, out_dir, temp_dir, on_update, cancel_event):
    """Download `url` as MP4 into out_dir. Partial files live in temp_dir so a
    cancelled or failed download leaves nothing behind in out_dir.

    on_update(**fields) receives stage/progress/speed/eta/title updates.
    Raises Cancelled, or RuntimeError with yt-dlp's error message."""
    cmd = [
        tools.ytdlp,
        "--newline", "--progress", "--no-simulate", "--color", "never",
        "--encoding", "utf-8", "--progress-delta", "0.5",
        "--no-playlist", "--windows-filenames",
        "-f", QUALITIES[quality],
        "--merge-output-format", "mp4",
        "--recode-video", "mp4",  # only re-encodes when the result isn't already MP4
        "-P", f"home:{out_dir}", "-P", f"temp:{temp_dir}",
        "-o", "%(title).150B [%(id)s].%(ext)s",
        "--progress-template", PROGRESS_TEMPLATE,
        "--progress-template", POSTPROCESS_TEMPLATE,
        "--print", "before_dl:[title] %(title)s",
        "--print", "after_move:[file] %(filepath)s",
    ]
    if tools.ffmpeg_dir:
        cmd += ["--ffmpeg-location", tools.ffmpeg_dir]
    cmd += ["--", url]

    st = _Progress(on_update)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        encoding="utf-8", errors="replace",
        creationflags=NO_WINDOW, start_new_session=not IS_WINDOWS,
    )

    def watch_cancel():
        # yt-dlp prints nothing while ffmpeg converts, so cancellation can't
        # wait for the next output line.
        while proc.poll() is None:
            if cancel_event.wait(0.5):
                kill_tree(proc)
                return

    threading.Thread(target=watch_cancel, daemon=True).start()
    try:
        for line in proc.stdout:
            _handle_line(line.rstrip("\r\n"), st)
    finally:
        proc.wait()
    if cancel_event.is_set():
        raise Cancelled()
    if proc.returncode != 0 or not st.path:
        raise RuntimeError(st.errors[-1] if st.errors else f"yt-dlp exited with code {proc.returncode}")
    return DownloadResult(path=st.path, title=st.title)


def version(tools):
    out = subprocess.run([tools.ytdlp, "--version"], capture_output=True, text=True,
                         creationflags=NO_WINDOW, timeout=60)
    return out.stdout.strip()


def self_update(tools):
    """Run `yt-dlp -U`. Only works for the standalone executable (pip installs
    refuse; those are updated with pip instead)."""
    out = subprocess.run([tools.ytdlp, "-U"], capture_output=True, text=True,
                         creationflags=NO_WINDOW, timeout=300)
    return out.returncode == 0, (out.stdout + out.stderr).strip()
