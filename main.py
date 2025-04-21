from flask import Flask, request, jsonify, render_template, send_file
from pytubefix import YouTube
import threading
import uuid
import os
import time
import json
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

download_tasks = {}


@app.route("/")
def index():
    """Serve the main page"""
    return render_template("index.html")


@app.route("/history.html")
def history():
    """Serve the download history page"""

    return render_template("history.html")


def get_download_path():
    """Get the download directory path"""
    download_dir = os.path.join(os.getcwd(), "downloads")
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    return download_dir


def get_history_file_path():
    """Get the path to the download history JSON file"""
    return os.path.join(os.getcwd(), "download_history.json")


def load_download_history():
    """Load the download history from the JSON file"""
    history_path = get_history_file_path()
    if os.path.exists(history_path):
        try:
            with open(history_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading download history: {e}")
            return []
    return []


def save_to_download_history(download_data):
    """Save download metadata to the history file"""
    history_path = get_history_file_path()
    history = load_download_history()

    # Add the new download to the history
    history.append(download_data)

    # Save back to the file
    try:
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving download history: {e}")


def download_video(url, download_id):
    """Function to download YouTube video in a separate thread"""
    try:
        # Record start time
        start_time = datetime.now().isoformat()
        download_tasks[download_id]["started_at"] = time.time()
        download_tasks[download_id]["start_time_iso"] = start_time
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
        thumbnail_url = yt.thumbnail_url
        print(thumbnail_url)
        download_tasks[download_id]["thumbnail_url"] = thumbnail_url

        output_path = get_download_path()
        filename = video.download(output_path=output_path)
        filename_only = os.path.basename(filename)

        # Record end time
        end_time = datetime.now().isoformat()

        download_tasks[download_id]["status"] = "completed"
        download_tasks[download_id]["percentage"] = 100
        download_tasks[download_id]["file_path"] = filename
        download_tasks[download_id]["filename"] = filename_only
        download_tasks[download_id]["end_time_iso"] = end_time

        # Get video length from YouTube metadata instead of using MoviePy
        length_seconds = yt.length  # This is provided by PyTubefix
        download_tasks[download_id]["duration_seconds"] = length_seconds

        # Save download metadata to history
        history_entry = {
            "download_id": download_id,
            "url": url,
            "title": yt.title,
            "thumbnail_url": thumbnail_url,
            "filename": filename_only,
            "file_path": filename,
            "filesize": video.filesize,
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": length_seconds,
            "video_id": yt.video_id,
        }

        save_to_download_history(history_entry)

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


@app.route("/get_file_by_name/<filename>", methods=["GET"])
def get_file_by_name(filename):
    """Endpoint to download a file by its filename"""
    download_dir = get_download_path()
    file_path = os.path.join(download_dir, filename)

    # Prevent directory traversal
    if not os.path.abspath(file_path).startswith(os.path.abspath(download_dir)):
        return jsonify({"error": "Invalid filename"}), 400

    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

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


@app.route("/history", methods=["GET"])
def download_history():
    """
    Return the download history from the JSON file
    """
    history = load_download_history()

    # Sort by end time (newest first)
    history.sort(key=lambda x: x.get("end_time", ""), reverse=True)

    return jsonify(history)


@app.route("/file_status", methods=["GET"])
def check_file_status():
    """
    Check if files in the history still exist in the filesystem
    """
    history = load_download_history()
    download_dir = get_download_path()

    for entry in history:
        filename = entry.get("filename")
        if filename:
            file_path = os.path.join(download_dir, filename)
            entry["file_exists"] = os.path.exists(file_path)
        else:
            entry["file_exists"] = False

    return jsonify(history)


@app.route("/delete_file", methods=["POST"])
def delete_file():
    """
    Delete a given file from the downloads folder and remove from history.
    JSON body: { "filename": "<name of file to delete>" }
    """
    data = request.get_json()
    fname = data.get("filename")
    if not fname:
        return jsonify({"error": "filename is required"}), 400

    download_dir = get_download_path()
    safe_path = os.path.abspath(os.path.join(download_dir, fname))
    # Prevent path traversal
    if not safe_path.startswith(os.path.abspath(download_dir) + os.sep):
        return jsonify({"error": "invalid filename"}), 400

    if not os.path.exists(safe_path):
        return jsonify({"error": "file not found"}), 404

    try:
        # Delete the file
        os.remove(safe_path)

        # Remove entry from history
        history = load_download_history()
        history = [entry for entry in history if entry.get("filename") != fname]

        # Save updated history
        with open(get_history_file_path(), "w") as f:
            json.dump(history, f, indent=2)

        return jsonify({"deleted": fname}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
