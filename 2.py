import sys

# from pytube import YouTube
from pytubefix import YouTube
import os


def on_progress(stream, chunk, bytes_remaining):
    total_size = stream.filesize
    bytes_downloaded = total_size - bytes_remaining
    percentage = (bytes_downloaded / total_size) * 100
    print(f"\rDownloading... {percentage:.2f}%", end="")


def download_video(url):
    try:
        yt = YouTube(url, on_progress_callback=on_progress)
        stream = yt.streams.filter(progressive=True).get_highest_resolution()
        print(f"Downloading: {yt.title}")
        stream.download(output_path=os.getcwd())
        print("\nDownload completed!")
    except Exception as e:
        print(f"\nError: {e}")


if __name__ == "__main__":
    # if len(sys.argv) != 2:
    # print("Usage: python youtube_downloader.py <YouTube-URL>")
    # sys.exit(1)

    video_url = "https://www.youtube.com/watch?v=79e6KBYcVmQ"  # sys.argv[1]
    download_video(video_url)
