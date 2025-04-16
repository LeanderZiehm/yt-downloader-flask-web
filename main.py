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

    templates_dir = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)

    index_html_path = os.path.join(templates_dir, "index.html")

    with open(index_html_path, "w") as f:
        f.write(
            """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Video Downloader</title>
 <style>
    :root {
        --bg-color: #0d1117;
        --container-bg: #161b22;
        --text-color: #c9d1d9;
        --accent-color: #238636;
        --error-color: #f85149;
        --border-color: #30363d;
        --button-hover: #2ea043;
    }

    body {
        background-color: var(--bg-color);
        color: var(--text-color);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        max-width: 800px;
        margin: 0 auto;
        padding: 20px;
    }

    .container {
        background-color: var(--container-bg);
        border-radius: 8px;
        padding: 20px;
        border: 1px solid var(--border-color);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.4);
    }

    .input-group {
        margin-bottom: 20px;
        display: flex;
        gap: 10px;
    }

    input[type="text"] {
        flex: 1;
        padding: 10px;
        background-color: #0d1117;
        border: 1px solid var(--border-color);
        color: var(--text-color);
        border-radius: 4px;
    }

    button {
        padding: 10px 15px;
        background-color: var(--accent-color);
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-weight: bold;
        transition: background-color 0.2s;
    }

    button:hover {
        background-color: var(--button-hover);
    }

    .progress-container {
        margin-top: 20px;
        display: none;
    }

    .progress-bar {
        height: 20px;
        background-color: var(--border-color);
        border-radius: 10px;
        margin-bottom: 10px;
        overflow: hidden;
    }

    .progress {
        height: 100%;
        background-color: var(--accent-color);
        width: 0%;
        transition: width 0.3s ease-in-out;
    }

    .progess-slider {
        height: 6px;
        background-color: var(--border-color);
        border-radius: 4px;
        margin-bottom: 10px;
        overflow: hidden;
        position: relative;
    }

    .progess-slider::after {
        content: '';
        position: absolute;
        height: 100%;
        width: 0%;
        background-color: var(--accent-color);
        transition: width 0.3s ease-in-out;
    }

    .thumbnail-container img {
        max-width: 100%;
        margin: 10px 0;
        border-radius: 4px;
    }

    .download-link {
        display: none;
        margin-top: 10px;
        padding: 10px;
        background-color: var(--accent-color);
        color: white;
        text-decoration: none;
        border-radius: 4px;
        display: inline-block;
    }

    .error {
        color: var(--error-color);
        margin-top: 10px;
        display: none;
    }

    .progess-slider {
    position: relative;
    height: 6px;
    background-color: var(--border-color);
    border-radius: 4px;
    margin-bottom: 10px;
    overflow: hidden;
}

.slider-fill {
    height: 100%;
    width: 0%;
    background-color: var(--accent-color);
    transition: width 0.3s ease-in-out;
}

</style>

</head>
<body>
    <div class="container">
        <h1>YouTube Video Downloader</h1>
        <div class="input-group">
            <input type="text" id="video-url" placeholder="Enter YouTube URL...">
            <button id="download-btn">Download</button>
        </div>
        
        <div class="progress-container" id="progress-container">
            <h3 id="video-title">Downloading...</h3>
            <div class="thumbnail-container"> <img style="display:none" id="thumbnail"></div>
            <div class="progress-bar">
                <div class="progress" id="progress-bar"></div>
            </div>
            <div class="progess-slider">
             <div class="slider-fill"></div>
            </div>
            <p id="progress-text">0%</p>
            <p id="file-size"></p>
            <a href="#" class="download-link" id="download-link">Download Video</a>
        </div>
        
        <div class="error" id="error-message"></div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const videoUrlInput = document.getElementById('video-url');
            const downloadBtn = document.getElementById('download-btn');
            const progressContainer = document.getElementById('progress-container');
            const progressBar = document.getElementById('progress-bar');
            const progressText = document.getElementById('progress-text');
            const videoTitle = document.getElementById('video-title');
            const fileSize = document.getElementById('file-size');
            const downloadLink = document.getElementById('download-link');
            const errorMessage = document.getElementById('error-message');

            const slider = document.querySelector('.progess-slider::after');
            const sliderWrapper = document.querySelector('.progess-slider');
            const progressSlider = sliderWrapper.querySelector('::after'); // won't work like this directly, so:
            const sliderBar = document.querySelector('.progess-slider');

    

            
            let downloadInterval;
            let currentDownloadId;
            
            downloadBtn.addEventListener('click', startDownload);
            
            function startDownload() {
                const url = videoUrlInput.value.trim();
                
                if (!url) {
                    showError('Please enter a YouTube URL');
                    return;
                }
                
                // Clear previous download if any
                if (downloadInterval) {
                    clearInterval(downloadInterval);
                }
                
                // Reset UI
                resetUI();
                
                // Show progress container
                progressContainer.style.display = 'block';
                
                // Start download
                fetch('/download', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ url: url }),
                })
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        showError(data.error);
                        return;
                    }
                    
                    currentDownloadId = data.download_id;
                    
                    // Start polling for progress
                    downloadInterval = setInterval(checkProgress, 1000);
                })
                .catch(error => {
                    showError('Error starting download: ' + error.message);
                });
            }
            
            function checkProgress() {
                if (!currentDownloadId) return;
                
                fetch(`/progress/${currentDownloadId}`)
                    .then(response => response.json())
                    .then(data => {

                    console.log(data);
                        if (data.error) {
                            showError(data.error);
                            clearInterval(downloadInterval);
                            return;
                        }
                        
                        // Update progress bar LOL
                        const percentage = data.percentage;
                        progressBar.style.width = `${percentage}%`;
                        progressText.textContent = `${percentage}%`;

                        const sliderFill = document.querySelector('.slider-fill');
                        if (sliderFill) {
                            sliderFill.style.width = `${percentage}%`;
                        }

                        
                        // Update video title if available
                        if (data.title) {
                            videoTitle.textContent = data.title;
                        }
                        const thumbnail_url = data.thumbnail_url;
                        console.log(thumbnail_url);
                        if (thumbnail_url) {
                            // videoTitle.innerHTML = `<img src="${thumbnail_url}" alt="Thumbnail" > ${data.title}`;
                            const thumbnail = document.getElementById('thumbnail');
                            thumbnail.src = thumbnail_url;
                            //unhide
                            thumbnail.style.display = 'block';



                        }
                        
                        // Update file size if available
                        if (data.total_size) {
                            const totalSizeMB = (data.total_size / (1024 * 1024)).toFixed(2);
                            const downloadedSizeMB = (data.bytes_downloaded / (1024 * 1024)).toFixed(2);
                            fileSize.textContent = `${downloadedSizeMB} MB / ${totalSizeMB} MB`;
                        }
                        
                        // Check if download is completed
                     if (data.status === 'completed') {

                     console.log('Download completed');
                            clearInterval(downloadInterval);

                            // Set the download link
                            downloadLink.href = `/get_file/${currentDownloadId}`;
                            downloadLink.download = ''; // This prompts the browser to download rather than navigate
                            downloadLink.style.display = 'inline-block';
                            progressText.textContent = 'Download completed!';

                            // Auto-trigger the download
                            downloadLink.click();
                        } else if (data.status === 'error') {
                            clearInterval(downloadInterval);
                            showError('Error downloading: ' + (data.error || 'Unknown error'));
                        }
                    })
                    .catch(error => {
                        showError('Error checking progress: ' + error.message);
                        clearInterval(downloadInterval);
                    });
            }
            
            function resetUI() {
                progressBar.style.width = '0%';
                progressText.textContent = '0%';
                videoTitle.textContent = 'Downloading...';
                fileSize.textContent = '';
                downloadLink.style.display = 'none';
                errorMessage.style.display = 'none';
            }
            
            function showError(message) {
                errorMessage.textContent = message;
                errorMessage.style.display = 'block';
                progressContainer.style.display = 'none';
            }
        });
    </script>
</body>
</html>
            """
        )

    app.run(debug=True)
