#!/usr/bin/env python3
import os
import sys
import re
import time
from urllib.parse import parse_qs, urlparse

from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    send_from_directory,
    session,
)
from pytubefix import YouTube as yt
from pytubefix.exceptions import PytubeFixError
import googleapiclient.discovery as dis
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv()
YOUTUBE_DEVELOPER_KEY = os.getenv("YOUTUBE_DEVELOPER_KEY")
if not YOUTUBE_DEVELOPER_KEY:
    print("Error: YOUTUBE_DEVELOPER_KEY not found in .env file.", file=sys.stderr)
    # sys.exit(1) # Don't exit immediately, API might only be needed for playlists

# Flask App Setup
app = Flask(__name__)
# IMPORTANT: Change this to a random secret key for production!
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, "downloads")
ERROR_LOG_FILE = os.path.join(BASE_DIR, "download_errors.log")

# Create download folder if it doesn't exist
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Global list to keep track of downloaded files in the current session (simple approach)
# A more robust solution would use a database or better session management
# For simplicity, we'll store them directly on the server and list them.
# We'll store filenames in the session to display them.
# Note: This means filenames are only tracked per-user-session

# Target resolution (default)
DEFAULT_TARGET_RESOLUTION = "360p"

# --- YouTube API Client (Optional but needed for playlists) ---
youtube = None
try:
    if YOUTUBE_DEVELOPER_KEY:
        youtube = dis.build("youtube", "v3", developerKey=YOUTUBE_DEVELOPER_KEY)
    else:
        print(
            "Warning: YOUTUBE_DEVELOPER_KEY not set. Playlist downloading might fail.",
            file=sys.stderr,
        )
except Exception as e:
    print(f"Error initializing YouTube API client: {e}", file=sys.stderr)
    youtube = None  # Ensure it's None if initialization fails

# --- Helper Functions (Adapted from original script) ---


def remove_illegal_path_characters(name):
    """Removes characters illegal in Windows/Linux filenames and replaces spaces."""
    # Remove characters illegal in Windows/Linux filenames
    illegal_characters = r'[<>:"/\\|?*\x00-\x1F\x7F!]'
    cleaned_name = re.sub(illegal_characters, "", name)
    # Replace spaces with underscores for better compatibility
    cleaned_name = cleaned_name.replace(" ", "_")
    # Ensure the name is not empty after cleaning
    if not cleaned_name:
        cleaned_name = "downloaded_file"
    return cleaned_name


def log_error(url, error_message):
    """Logs download errors to a file."""
    try:
        with open(ERROR_LOG_FILE, "a") as f:
            f.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} - ERROR: {url} - {error_message}\n"
            )
    except Exception as e:
        print(f"Failed to write to error log: {e}", file=sys.stderr)


def get_playlist_id(play_url):
    """Extracts playlist ID from a YouTube URL."""
    try:
        query = parse_qs(urlparse(play_url).query, keep_blank_values=True)
        if "list" in query and query["list"]:
            return query["list"][0]
    except Exception:
        pass  # Ignore parsing errors, return None
    return None


def get_playlist_name(playlist_id):
    """Gets playlist name using YouTube API."""
    if not youtube:
        # flash("YouTube API client not available. Cannot fetch playlist name.", "warning")
        print(
            "YouTube API client not available. Cannot fetch playlist name.",
            file=sys.stderr,
        )
        return f"playlist_{playlist_id}"  # Return a generic name

    try:
        playlist_response = (
            youtube.playlists().list(part="snippet", id=playlist_id).execute()
        )
        if playlist_response.get("items"):
            return playlist_response["items"][0]["snippet"]["title"]
        else:
            return f"playlist_{playlist_id}_notfound"
    except HttpError as e:
        log_error(f"Playlist ID: {playlist_id}", f"API Error getting name: {e}")
        # flash(f"API Error getting playlist name: {e.reason}", "warning")
        print(f"API Error getting playlist name: {e}", file=sys.stderr)
        return f"playlist_{playlist_id}_apierror"
    except Exception as e:
        log_error(f"Playlist ID: {playlist_id}", f"Error getting name: {e}")
        # flash(f"Error getting playlist name: {e}", "warning")
        print(f"Error getting playlist name: {e}", file=sys.stderr)
        return f"playlist_{playlist_id}_error"


def get_all_links_from_playlist(playlist_id):
    """Gets all video links from a playlist using YouTube API."""
    if not youtube:
        # flash("YouTube API client not available. Cannot fetch playlist videos.", "danger")
        print(
            "YouTube API client not available. Cannot fetch playlist videos.",
            file=sys.stderr,
        )
        return []

    links = []
    try:
        request = youtube.playlistItems().list(
            part="snippet", playlistId=playlist_id, maxResults=50  # API max per page
        )

        while request:
            response = request.execute()
            for item in response.get("items", []):
                video_id = item.get("snippet", {}).get("resourceId", {}).get("videoId")
                if video_id:
                    # Construct a simple video URL
                    links.append(f"https://www.youtube.com/watch?v={video_id}")

            # Get the next page token
            request = youtube.playlistItems().list_next(request, response)

    except HttpError as e:
        log_error(f"Playlist ID: {playlist_id}", f"API Error getting videos: {e}")
        flash(f"API Error getting playlist videos: {e.reason}", "danger")
        print(f"API Error getting playlist videos: {e}", file=sys.stderr)
        return []  # Return empty on error
    except Exception as e:
        log_error(f"Playlist ID: {playlist_id}", f"Error getting videos: {e}")
        flash(f"Error getting playlist videos: {e}", "danger")
        print(f"Error getting playlist videos: {e}", file=sys.stderr)
        return []  # Return empty on error

    return links


def download_single_video(
    url,
    download_path,
    download_type="video",
    target_resolution=DEFAULT_TARGET_RESOLUTION,
    max_res=False,
):
    """Downloads a single YouTube video or audio."""
    try:
        # Note: Removed OAuth, might fail on age-restricted/private videos
        yt_obj = yt(url)
        streams = yt_obj.streams

        file_to_download = None
        extension = ".mp4"  # Default

        if download_type == "audio":
            file_to_download = streams.get_audio_only()  # Get best audio-only
            extension = ".mp3"  # We save as mp3
            if not file_to_download:
                flash(
                    f"No audio-only stream found for {url}. Trying adaptive.", "warning"
                )
                # Fallback might be needed (e.g., adaptive audio)
                file_to_download = (
                    streams.filter(only_audio=True).order_by("abr").desc().first()
                )
                if not file_to_download:
                    flash(f"Could not find any audio stream for {url}", "danger")
                    log_error(url, "No audio stream found")
                    return None

        elif download_type == "video":
            if max_res:
                # Get highest resolution progressive stream (video+audio combined)
                file_to_download = (
                    streams.filter(progressive=True, file_extension="mp4")
                    .order_by("resolution")
                    .desc()
                    .first()
                )
                if not file_to_download:
                    flash(
                        f"No progressive MP4 stream found for {url}. Trying any progressive.",
                        "warning",
                    )
                    file_to_download = (
                        streams.filter(progressive=True)
                        .order_by("resolution")
                        .desc()
                        .first()
                    )  # Try any extension
            else:
                # Get specific resolution (or nearest lower if not available)
                file_to_download = streams.filter(
                    res=target_resolution, progressive=True, file_extension="mp4"
                ).first()
                # If exact resolution not found, try finding the highest progressive <= target
                if not file_to_download:
                    flash(
                        f"{target_resolution} progressive MP4 not found for {url}. Trying best available progressive.",
                        "warning",
                    )
                    available_streams = (
                        streams.filter(progressive=True, file_extension="mp4")
                        .order_by("resolution")
                        .desc()
                    )
                    # Simple fallback: get the highest available progressive stream
                    file_to_download = available_streams.first()

        if not file_to_download:
            flash(f"Could not find a suitable video stream for {url}", "danger")
            log_error(url, "No suitable video stream found")
            return None
        extension = f".{file_to_download.subtype}"  # Use actual extension

        # --- Filename Handling ---
        base_filename = remove_illegal_path_characters(yt_obj.title)
        # Ensure extension is correct, especially for audio
        final_filename = f"{base_filename}{extension}"
        output_filepath = os.path.join(download_path, final_filename)

        # --- Download ---
        print(f"Attempting to download: {yt_obj.title} as {final_filename}")
        # Use stream's download method
        downloaded_filepath = file_to_download.download(
            output_path=download_path, filename=final_filename
        )
        print(f"Successfully downloaded to: {downloaded_filepath}")

        # Check if the returned path matches expected (it usually does, but good practice)
        if os.path.exists(output_filepath):
            # Add filename to session for display
            if "recent_downloads" not in session:
                session["recent_downloads"] = []
            # Add to beginning and keep unique list
            if final_filename not in session["recent_downloads"]:
                session["recent_downloads"].insert(0, final_filename)
                session.modified = (
                    True  # Important when modifying mutable types in session
                )
            return final_filename
        else:
            # This case should ideally not happen if .download() succeeds without error
            flash(
                f"Download completed but file not found at expected location: {output_filepath}",
                "warning",
            )
            log_error(
                url, f"File not found after pytubefix download: {output_filepath}"
            )
            return None

    except PytubeFixError as e:
        error_msg = f"PytubeFix Error: {e}"
        flash(f"Error downloading {url}: {error_msg}", "danger")
        log_error(url, error_msg)
        print(f"Error downloading {url}: {error_msg}", file=sys.stderr)
        return None
    except Exception as e:
        # Catch potential network errors, filesystem errors, etc.
        error_msg = f"Unexpected Error: {e}"
        flash(f"An unexpected error occurred for {url}: {e}", "danger")
        log_error(url, error_msg)
        print(f"Unexpected error downloading {url}: {error_msg}", file=sys.stderr)
        return None


# --- Flask Routes ---


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        url = request.form.get("url")
        download_type = request.form.get("download_type", "video")  # Default to video

        if not url:
            flash("Please enter a YouTube URL.", "warning")
            return redirect(url_for("index"))

        # Basic URL validation
        if "yout" not in url:
            flash(
                "Invalid URL. Please enter a valid YouTube video or playlist URL.",
                "warning",
            )
            return redirect(url_for("index"))

        is_playlist = "playlist" in url and get_playlist_id(url) is not None
        max_res = download_type == "video_max"
        # Adjust download_type if max_res was selected
        if max_res:
            download_type = "video"

        flash(f"Processing URL: {url}", "info")

        if is_playlist:
            playlist_id = get_playlist_id(url)
            if not playlist_id:
                flash("Could not extract Playlist ID from URL.", "danger")
                return redirect(url_for("index"))

            if not youtube:
                flash(
                    "YouTube API key not configured or invalid. Cannot download playlists.",
                    "danger",
                )
                return redirect(url_for("index"))

            playlist_name = get_playlist_name(playlist_id)
            clean_playlist_name = remove_illegal_path_characters(playlist_name)
            playlist_download_path = os.path.join(DOWNLOAD_FOLDER, clean_playlist_name)
            os.makedirs(playlist_download_path, exist_ok=True)

            flash(f"Fetching videos for playlist: {playlist_name}", "info")
            video_urls = get_all_links_from_playlist(playlist_id)

            if not video_urls:
                flash(
                    f"No videos found in playlist '{playlist_name}' or error fetching them.",
                    "warning",
                )
                return redirect(url_for("index"))

            flash(
                f"Starting download for {len(video_urls)} videos from playlist '{playlist_name}'...",
                "info",
            )
            # Note: Downloading multiple files sequentially in a web request can be slow.
            # For large playlists, a background task queue (Celery, RQ) would be better.
            # This simple version downloads them one by one.
            success_count = 0
            fail_count = 0
            downloaded_files_playlist = []
            for video_url in video_urls:
                # Ensure files from playlist are downloaded into the specific playlist folder
                # download_single_video needs the *parent* directory
                filename = download_single_video(
                    video_url,
                    playlist_download_path,
                    download_type,
                    DEFAULT_TARGET_RESOLUTION,
                    max_res,
                )
                if filename:
                    success_count += 1
                    # We need the path relative to DOWNLOAD_FOLDER for the download link
                    relative_filename = os.path.join(clean_playlist_name, filename)
                    downloaded_files_playlist.append(relative_filename)
                else:
                    fail_count += 1
                time.sleep(0.1)  # Small delay between downloads

            # Update session with playlist files (overwrite single video tracking for this request)
            session["recent_downloads"] = downloaded_files_playlist
            session.modified = True

            if success_count > 0:
                flash(
                    f"Playlist '{playlist_name}': Downloaded {success_count} files.",
                    "success",
                )
            if fail_count > 0:
                flash(
                    f"Playlist '{playlist_name}': Failed to download {fail_count} files. Check logs.",
                    "warning",
                )

        else:  # Single video download
            # Download directly into the main DOWNLOAD_FOLDER
            filename = download_single_video(
                url, DOWNLOAD_FOLDER, download_type, DEFAULT_TARGET_RESOLUTION, max_res
            )
            if filename:
                flash(f"Successfully downloaded: {filename}", "success")
                # filename is already relative to DOWNLOAD_FOLDER here
                if "recent_downloads" not in session:
                    session["recent_downloads"] = []
                if filename not in session["recent_downloads"]:
                    session["recent_downloads"].insert(0, filename)
                    session.modified = True
            # Error flashing is handled within download_single_video

        return redirect(
            url_for("index")
        )  # Redirect to show flashed messages and updated list

    # GET request: Render the main page
    # Get recent downloads from session for display
    recent_downloads = session.get("recent_downloads", [])
    return render_template("index.html", recent_downloads=recent_downloads)


@app.route("/downloads/<path:filename>")
def get_file(filename):
    """Serves files from the download folder."""
    # Security: Ensure filename is safe and doesn't allow path traversal outside DOWNLOAD_FOLDER
    # send_from_directory handles basic security like preventing ../
    print(f"Attempting to send file: {filename} from {DOWNLOAD_FOLDER}")
    try:
        return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)
    except FileNotFoundError:
        flash(f"File not found: {filename}. It might have been cleared.", "danger")
        # Remove broken link from session if it exists
        if "recent_downloads" in session and filename in session["recent_downloads"]:
            session["recent_downloads"].remove(filename)
            session.modified = True
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Error serving file {filename}: {e}", "danger")
        log_error(f"Serving file: {filename}", f"Error: {e}")
        return redirect(url_for("index"))


@app.route("/clear_downloads", methods=["POST"])
def clear_downloads():
    """Clears downloaded files from the server folder and session."""
    cleared_count = 0
    failed_clear = []
    for filename in os.listdir(DOWNLOAD_FOLDER):
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
                cleared_count += 1
            elif os.path.isdir(file_path):
                # Optionally remove subdirectories (like playlist folders)
                import shutil

                shutil.rmtree(file_path)
                cleared_count += 1  # Count the directory as one item cleared
        except Exception as e:
            failed_clear.append(filename)
            print(f"Failed to delete {file_path}. Reason: {e}", file=sys.stderr)
            log_error(f"Clearing file: {filename}", f"Error: {e}")

    # Clear the session list
    session.pop("recent_downloads", None)

    if not failed_clear:
        flash(f"Cleared {cleared_count} items from server download folder.", "success")
    else:
        flash(
            f"Cleared {cleared_count} items, but failed to clear: {', '.join(failed_clear)}",
            "warning",
        )

    return redirect(url_for("index"))


if __name__ == "__main__":
    print(f"Download folder: {DOWNLOAD_FOLDER}")
    # Use host='0.0.0.0' to make it accessible on your network
    app.run(host="0.0.0.0", port=5003)
