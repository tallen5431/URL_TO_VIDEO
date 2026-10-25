"""URL to Video: paste a video page URL, get an MP4 back.

Downloads with yt-dlp (YouTube and ~1000 other sites) and uses ffmpeg to
merge/convert the result into MP4. Jobs run in a small background pool and the
web page polls for progress.
"""
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from flask import Flask, abort, jsonify, render_template, request, send_file
from yt_dlp.utils import DownloadCancelled

APP_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", APP_DIR / "downloads")).resolve()
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
# Finished files are deleted after this many hours so the disk doesn't fill up.
KEEP_HOURS = float(os.environ.get("KEEP_HOURS", "24"))

# Prefer native MP4/M4A streams so no re-encode is needed; otherwise take the
# best available and let ffmpeg merge/convert to MP4.
QUALITIES = {
    "best": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
    "1080": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b[height<=1080]/b",
    "720": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720]+ba/b[height<=720]/b",
    "480": "bv*[height<=480][ext=mp4]+ba[ext=m4a]/b[height<=480][ext=mp4]/bv*[height<=480]+ba/b[height<=480]/b",
}

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
jobs = {}
jobs_lock = threading.Lock()


def update_job(job_id, **fields):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(fields)


def public_job(job):
    return {k: v for k, v in job.items() if not k.startswith("_")}


def run_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None or job["_cancel"].is_set():
            return
        url, quality, cancel = job["url"], job["quality"], job["_cancel"]
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    update_job(job_id, status="downloading", stage="Starting")

    def progress_hook(d):
        if cancel.is_set():
            raise DownloadCancelled("Cancelled")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            update_job(
                job_id,
                stage="Downloading",
                progress=round(done / total * 100, 1) if total else None,
                speed=d.get("_speed_str", "").strip(),
                eta=d.get("_eta_str", "").strip(),
            )
        elif d["status"] == "finished":
            update_job(job_id, progress=100.0)

    def postprocessor_hook(d):
        if d["status"] == "started":
            update_job(job_id, stage="Converting to MP4", progress=None, speed="", eta="")

    opts = {
        "format": QUALITIES[quality],
        "merge_output_format": "mp4",
        # Only re-encodes when the downloaded file isn't already MP4.
        "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
        "outtmpl": str(job_dir / "%(title).150B [%(id)s].%(ext)s"),
        "restrictfilenames": False,
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if cancel.is_set():  # deleted while converting
            raise DownloadCancelled("Cancelled")
        update_job(job_id, title=info.get("title") or url)
        mp4s = sorted(job_dir.glob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
        if not mp4s:
            raise RuntimeError("No MP4 was produced (is ffmpeg installed?)")
        out = mp4s[0]
        update_job(
            job_id,
            status="done",
            stage="Done",
            progress=100.0,
            speed="",
            eta="",
            filename=out.name,
            size=out.stat().st_size,
            finished=time.time(),
            _path=str(out),
        )
    except DownloadCancelled:
        shutil.rmtree(job_dir, ignore_errors=True)
    except Exception as e:  # yt-dlp raises many types; surface the message to the UI
        if cancel.is_set():
            shutil.rmtree(job_dir, ignore_errors=True)
            return
        # Drop yt-dlp's "please report this issue..." boilerplate.
        msg = str(e).replace("ERROR: ", "", 1).split("; please report this issue")[0]
        update_job(job_id, status="error", stage="Failed", error=msg, finished=time.time())
        shutil.rmtree(job_dir, ignore_errors=True)


def cleanup_loop():
    while True:
        cutoff = time.time() - KEEP_HOURS * 3600
        with jobs_lock:
            expired = [j for j, job in jobs.items() if job.get("finished") and job["finished"] < cutoff]
            for j in expired:
                del jobs[j]
        for j in expired:
            shutil.rmtree(DOWNLOAD_DIR / j, ignore_errors=True)
        time.sleep(600)


@app.get("/")
def index():
    return render_template("index.html", keep_hours=KEEP_HOURS)


@app.post("/api/jobs")
def create_job():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    quality = data.get("quality") or "best"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify(error="Enter a full http(s):// video URL"), 400
    if quality not in QUALITIES:
        return jsonify(error="Unknown quality"), 400
    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id,
            "url": url,
            "quality": quality,
            "title": url,
            "status": "queued",
            "stage": "Queued",
            "progress": None,
            "speed": "",
            "eta": "",
            "error": None,
            "filename": None,
            "size": None,
            "created": time.time(),
            "finished": None,
            "_cancel": threading.Event(),
            "_path": None,
        }
    executor.submit(run_job, job_id)
    return jsonify(id=job_id), 201


@app.get("/api/jobs")
def list_jobs():
    with jobs_lock:
        items = sorted(jobs.values(), key=lambda j: j["created"], reverse=True)
        return jsonify([public_job(j) for j in items])


@app.get("/api/jobs/<job_id>")
def get_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            abort(404)
        return jsonify(public_job(job))


@app.get("/api/jobs/<job_id>/file")
def download_file(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        path = job and job["_path"]
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=job["filename"], mimetype="video/mp4")


@app.delete("/api/jobs/<job_id>")
def delete_job(job_id):
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if job is None:
        abort(404)
    # A running job sees the flag in its progress hook and cleans up after itself.
    job["_cancel"].set()
    if job["status"] in ("done", "error"):
        shutil.rmtree(DOWNLOAD_DIR / job_id, ignore_errors=True)
    return "", 204


if __name__ == "__main__":
    # Files from a previous run aren't tracked in memory any more, so clear them.
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=cleanup_loop, daemon=True).start()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8090"))
    app.run(host=host, port=port, threaded=True)
