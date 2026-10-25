"""Server version, as run by Start.sh / HTTP Server Manager: python -m web"""
import os
import shutil
import threading
import time
from pathlib import Path

from core import ytdlp
from core.jobs import JobManager
from web.app import create_app

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", ROOT / "downloads")).resolve()
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
# Finished files are deleted after this many hours so the disk doesn't fill up.
KEEP_HOURS = float(os.environ.get("KEEP_HOURS", "24"))


def cleanup_loop(manager):
    while True:
        manager.expire(KEEP_HOURS * 3600)
        time.sleep(600)


def main():
    # Jobs are only tracked in memory, so files from a previous run are orphans.
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    manager = JobManager(
        ytdlp.Tools(ytdlp=ytdlp.find_ytdlp()),
        out_dir_for=lambda job_id: DOWNLOAD_DIR / job_id,
        work_dir=DOWNLOAD_DIR,
        max_concurrent=MAX_CONCURRENT,
    )
    threading.Thread(target=cleanup_loop, args=(manager,), daemon=True).start()
    app = create_app(manager, keep_hours=KEEP_HOURS)
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8090")), threaded=True)


if __name__ == "__main__":
    main()
