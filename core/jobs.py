"""Background download jobs, shared by the web app and the desktop app."""
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from . import ytdlp


class JobManager:
    """Queues downloads and tracks their progress in memory.

    out_dir_for(job_id) says where a finished file goes: a per-job folder for
    the web app, the user's chosen folder for the desktop app. Partial files
    always live under work_dir/tmp/<job_id> and are removed afterwards.
    keep_files_on_remove: removing a finished job from the list leaves its file
    alone (desktop: it's in the user's Downloads) instead of deleting it (web).
    """

    def __init__(self, tools, out_dir_for, work_dir, max_concurrent=2, keep_files_on_remove=False):
        self.tools = tools
        self.out_dir_for = out_dir_for
        self.tmp_root = Path(work_dir) / "tmp"
        self.keep_files_on_remove = keep_files_on_remove
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self.jobs = {}
        self.lock = threading.Lock()
        shutil.rmtree(self.tmp_root, ignore_errors=True)  # leftovers from a crash

    def _update(self, job_id, **fields):
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id].update(fields)

    @staticmethod
    def public(job):
        return {k: v for k, v in job.items() if not k.startswith("_")}

    def submit(self, url, quality="best"):
        """Queue a download. Returns the job id; raises ValueError on bad input."""
        url = (url or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Enter a full http(s):// video URL")
        if quality not in ytdlp.QUALITIES:
            raise ValueError("Unknown quality")
        job_id = uuid.uuid4().hex[:12]
        with self.lock:
            self.jobs[job_id] = {
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
        self.executor.submit(self._run, job_id)
        return job_id

    def _run(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["_cancel"].is_set():
                return
            url, quality, cancel = job["url"], job["quality"], job["_cancel"]
        out_dir = Path(self.out_dir_for(job_id))
        tmp_dir = self.tmp_root / job_id
        created_out_dir = not out_dir.exists()
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        self._update(job_id, status="downloading", stage="Starting")
        try:
            result = ytdlp.run_download(
                self.tools, url, quality, out_dir, tmp_dir,
                lambda **f: self._update(job_id, **f), cancel,
            )
            if cancel.is_set():  # removed just as it finished
                raise ytdlp.Cancelled()
            path = Path(result.path)
            created_out_dir = False
            self._update(
                job_id,
                status="done", stage="Done", progress=100.0, speed="", eta="",
                title=result.title or url, filename=path.name, size=path.stat().st_size,
                finished=time.time(), _path=str(path),
            )
        except ytdlp.Cancelled:
            pass
        except Exception as e:
            self._update(job_id, status="error", stage="Failed", error=str(e), finished=time.time())
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            if created_out_dir:  # the web app's per-job folder, left empty by a failure
                try:
                    out_dir.rmdir()
                except OSError:
                    pass

    def list(self):
        with self.lock:
            items = sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)
            return [self.public(j) for j in items]

    def get(self, job_id):
        """Returns (public job dict, finished file path) or (None, None)."""
        with self.lock:
            job = self.jobs.get(job_id)
            return (self.public(job), job["_path"]) if job else (None, None)

    def remove(self, job_id):
        """Cancel a running job, or forget a finished one. Returns False if unknown."""
        with self.lock:
            job = self.jobs.pop(job_id, None)
        if job is None:
            return False
        job["_cancel"].set()
        if not self.keep_files_on_remove and job["_path"]:
            try:
                os.remove(job["_path"])
                os.rmdir(os.path.dirname(job["_path"]))  # the web app's per-job folder, once empty
            except OSError:
                pass
        return True

    def expire(self, max_age_seconds):
        """Forget (and, unless keep_files_on_remove, delete) jobs finished longer ago than max_age."""
        cutoff = time.time() - max_age_seconds
        with self.lock:
            expired = [j for j, job in self.jobs.items() if job["finished"] and job["finished"] < cutoff]
        for job_id in expired:
            self.remove(job_id)

    def shutdown(self):
        """Cancel everything (the app is closing) and wait for workers to stop."""
        with self.lock:
            for job in self.jobs.values():
                job["_cancel"].set()
        self.executor.shutdown(wait=True, cancel_futures=True)
