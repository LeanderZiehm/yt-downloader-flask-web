from flask import Flask, request, jsonify, render_template, send_file
from pytubefix import YouTube
import threading
import uuid
import os
import time
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

download_tasks = {}


def get_download_path():
    """Get the download directory path"""
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    return download_dir


@app.route("/")
def index():
    """Serve the main page"""
    return render_template("index.html")


def download_video(url, download_id):
    """Function to download YouTube video in a separate thread"""
    try:

        download_tasks[download_id]["status"] = "downloading"

        yt = YouTube(url)

        def progress_callback(stream, chunk, bytes_remaining):
            file_size = stream.filesize
            bytes_downloaded = file_size - bytes_remaining
            download_tasks[download_id]["total_size"] = file_size
            download_tasks[download_id]["bytes_downloaded"] = bytes_downloaded
            download_tasks[download_id]["percentage"] = int(
                (bytes_downloaded / file_size) * 100
            )

        yt.register_on_progress_callback(progress_callback)

        video = yt.streams.filter(progressive=True).get_highest_resolution()

        download_tasks[download_id]["total_size"] = video.filesize
        download_tasks[download_id]["title"] = yt.title
        url = yt.thumbnail_url
        print(url)
        download_tasks[download_id]["thumbnail_url"] = url

        output_path = get_download_path()
        filename = video.download(output_path=output_path)

        download_tasks[download_id]["status"] = "completed"
        download_tasks[download_id]["percentage"] = 100
        download_tasks[download_id]["file_path"] = filename

    except Exception as e:

        download_tasks[download_id]["status"] = "error"
        download_tasks[download_id]["error"] = str(e)
        print(f"Error downloading video: {e}")


@app.route("/download", methods=["POST"])
def start_download():
    """Endpoint to start a download"""
    data = request.get_json()
    url = data.get("url")

    if not url:
        return jsonify({"error": "URL is required"}), 400

    download_id = str(uuid.uuid4())

    download_tasks[download_id] = {
        "url": url,
        "total_size": 0,
        "bytes_downloaded": 0,
        "percentage": 0,
        "status": "initializing",
        "started_at": time.time(),
    }

    thread = threading.Thread(target=download_video, args=(url, download_id))
    thread.daemon = True
    thread.start()

    return jsonify({"download_id": download_id})


@app.route("/progress/<download_id>", methods=["GET"])
def check_progress(download_id):
    """Endpoint to check download progress"""
    if download_id not in download_tasks:
        return jsonify({"error": "Download ID not found"}), 404

    download_info = download_tasks[download_id]

    return jsonify(download_info)


@app.route("/get_file/<download_id>", methods=["GET"])
def get_file(download_id):
    """Endpoint to download the file once it's ready"""
    if download_id not in download_tasks:
        return jsonify({"error": "Download ID not found"}), 404

    download_info = download_tasks[download_id]

    if download_info["status"] != "completed":
        return jsonify({"error": "Download not completed yet"}), 400

    file_path = download_info["file_path"]
    return send_file(file_path, as_attachment=True)


@app.route("/cleanup_old_tasks", methods=["POST"])
def cleanup_old_tasks():
    """Endpoint to clean up old completed tasks"""
    current_time = time.time()
    tasks_to_remove = []

    for task_id, task_info in download_tasks.items():

        if current_time - task_info.get("started_at", current_time) > 3600:
            tasks_to_remove.append(task_id)

    for task_id in tasks_to_remove:
        download_tasks.pop(task_id, None)

    return jsonify({"removed_tasks": len(tasks_to_remove)})


if __name__ == "__main__":

    app.run(debug=True)
