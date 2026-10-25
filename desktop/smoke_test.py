"""End-to-end check of a desktop build, run in CI as `URLtoVideo.exe --smoke-test`.

Makes a WebM clip with the bundled ffmpeg, serves it on localhost, converts it
through the app's own HTTP API, and checks an MP4 comes out. Exit code 0 = pass.
Output goes to app.log in the data dir (a windowed build has no console).
"""
import functools
import json
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import ytdlp
from desktop.main import BUNDLE_BIN, EXE, FROZEN, start_server

HEADERS = {"X-Requested-With": "url-to-video", "Content-Type": "application/json"}


def call(base, method, path, body=None, headers=HEADERS):
    req = urllib.request.Request(base + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            is_json = res.headers.get_content_type() == "application/json"
            return res.status, json.loads(res.read()) if is_json else None
    except urllib.error.HTTPError as e:
        return e.code, None


def run(data_dir):
    work = Path(tempfile.mkdtemp(prefix="urltovideo-smoke-"))
    try:
        check(data_dir, work)
    except Exception as e:
        print(f"SMOKE TEST FAILED: {e}")
        return 1
    print("SMOKE TEST PASSED")
    return 0


def check(data_dir, work):
    import webview  # noqa: F401  (the window can't open in CI, but it must be packaged)

    ffmpeg = BUNDLE_BIN / f"ffmpeg{EXE}"
    ffmpeg = str(ffmpeg) if ffmpeg.is_file() else "ffmpeg"
    clip_dir, out_dir = work / "src", work / "out"
    clip_dir.mkdir()
    out_dir.mkdir()
    subprocess.run(
        [ffmpeg, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25",
         "-f", "lavfi", "-i", "sine=duration=3", "-c:v", "libvpx-vp9", "-c:a", "libopus", str(clip_dir / "clip.webm")],
        check=True, creationflags=ytdlp.NO_WINDOW,
    )
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(clip_dir))
    clip_server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=clip_server.serve_forever, daemon=True).start()

    base, manager, server = start_server(data_dir)
    try:
        if FROZEN:
            assert (data_dir / "bin" / f"yt-dlp{EXE}").is_file(), "yt-dlp was not copied to the data dir"
        status, _ = call(base, "GET", "")
        assert status == 200, f"page returned {status}"
        status, _ = call(base, "POST", "api/jobs", {"url": "http://x/"}, headers={"Content-Type": "application/json"})
        assert status == 403, f"request without the app header returned {status}, expected 403"
        status, settings = call(base, "PUT", "api/settings", {"output_dir": str(out_dir)})
        assert status == 200 and Path(settings["output_dir"]) == out_dir, f"settings: {status} {settings}"

        status, created = call(base, "POST", "api/jobs", {"url": f"http://127.0.0.1:{clip_server.server_port}/clip.webm"})
        assert status == 201, f"create job returned {status}"
        deadline = time.time() + 180
        while time.time() < deadline:
            _, job = call(base, "GET", f"api/jobs/{created['id']}")
            if job["status"] in ("done", "error"):
                break
            time.sleep(0.5)
        print(f"job: {job}")
        assert job["status"] == "done", f"job ended as {job['status']}: {job['error']}"
        mp4 = out_dir / job["filename"]
        assert mp4.is_file() and mp4.suffix == ".mp4", f"missing output {mp4}"
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(mp4)], capture_output=True, text=True, creationflags=ytdlp.NO_WINDOW,
        ).stderr
        assert "h264" in probe and "aac" in probe, f"output is not H.264/AAC:\n{probe}"
    finally:
        manager.shutdown()
        server.shutdown()
        clip_server.shutdown()
