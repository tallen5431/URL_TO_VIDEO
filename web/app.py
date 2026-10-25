"""Flask UI and JSON API. Used by the server version (python -m web) and, with
a `desktop` helper, by the desktop app's window."""
import os

from flask import Flask, abort, jsonify, render_template, request, send_file


def create_app(manager, desktop=None, keep_hours=None):
    """desktop: object with get_settings(), set_output_dir(path), open_file(path),
    reveal(path) and allowed_host — only in the desktop app."""
    app = Flask(__name__)

    if desktop:
        @app.before_request
        def local_only():
            # The desktop server listens on 127.0.0.1, but any web page in the
            # user's browser could still send it requests. Refuse other Host
            # names (DNS rebinding) and require a header a cross-site form or
            # simple fetch can't send.
            if request.host != desktop.allowed_host:
                abort(403)
            if request.method != "GET" and request.headers.get("X-Requested-With") != "url-to-video":
                abort(403)

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            desktop=bool(desktop),
            keep_hours=keep_hours,
        )

    @app.post("/api/jobs")
    def create_job():
        data = request.get_json(silent=True) or {}
        try:
            job_id = manager.submit(data.get("url"), data.get("quality") or "best")
        except ValueError as e:
            return jsonify(error=str(e)), 400
        return jsonify(id=job_id), 201

    @app.get("/api/jobs")
    def list_jobs():
        return jsonify(manager.list())

    @app.get("/api/jobs/<job_id>")
    def get_job(job_id):
        job, _ = manager.get(job_id)
        if job is None:
            abort(404)
        return jsonify(job)

    @app.get("/api/jobs/<job_id>/file")
    def download_file(job_id):
        job, path = manager.get(job_id)
        if not path or not os.path.exists(path):
            abort(404)
        return send_file(path, as_attachment=True, download_name=job["filename"], mimetype="video/mp4")

    @app.delete("/api/jobs/<job_id>")
    def delete_job(job_id):
        if not manager.remove(job_id):
            abort(404)
        return "", 204

    if desktop:
        @app.post("/api/jobs/<job_id>/<action>")
        def file_action(job_id, action):
            _, path = manager.get(job_id)
            if not path or not os.path.exists(path):
                return jsonify(error="The file was moved or deleted."), 404
            if action == "open":
                desktop.open_file(path)
            elif action == "reveal":
                desktop.reveal(path)
            else:
                abort(404)
            return "", 204

        @app.get("/api/settings")
        def get_settings():
            return jsonify(desktop.get_settings())

        @app.put("/api/settings")
        def put_settings():
            data = request.get_json(silent=True) or {}
            if "output_dir" in data:
                try:
                    desktop.set_output_dir(data["output_dir"])
                except ValueError as e:
                    return jsonify(error=str(e)), 400
            return jsonify(desktop.get_settings())

    return app
