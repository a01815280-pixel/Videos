from pathlib import Path
import subprocess
import sys

from yt_dlp import YoutubeDL

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FOLDER = ROOT / "data" / "inbox"
OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)


def make_mac_playable(input_file, video_id):
    """Convert a downloaded video to a complete, widely compatible H.264 MP4 with no audio."""
    input_file = Path(input_file)
    output_file = OUTPUT_FOLDER / f"{video_id}.mp4"
    temp_file = OUTPUT_FOLDER / f".{video_id}_converting.mp4"

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(input_file),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        "-movflags", "+faststart",
        "-y", str(temp_file),
    ]

    try:
        subprocess.run(command, check=True)
        if not temp_file.is_file() or temp_file.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not create a valid converted video.")
        if output_file.exists() and output_file != input_file:
            output_file.unlink()
        temp_file.replace(output_file)
    finally:
        if temp_file.exists():
            temp_file.unlink()
        if input_file.exists() and input_file != output_file:
            input_file.unlink()

    return output_file


def _find_downloaded_file(video_id, prepared_name):
    """Find the actual source file produced by yt-dlp."""
    prepared = Path(prepared_name)
    if prepared.is_file():
        return prepared

    mp4 = OUTPUT_FOLDER / f"{video_id}.mp4"
    if mp4.is_file():
        return mp4

    candidates = [
        p for p in OUTPUT_FOLDER.glob(f"{video_id}.*")
        if p.is_file() and not p.name.startswith(f".{video_id}_")
    ]
    if not candidates:
        raise FileNotFoundError(f"Could not find downloaded file for {video_id}.")
    return candidates[0]


def download_single_video(video_url):
    """Download one YouTube video and convert it to a Mac-friendly MP4."""
    ydl_opts = {
        "format": "bestvideo[height<=360]/bestvideo/best[height<=360]/best",
        "outtmpl": str(OUTPUT_FOLDER / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "merge_output_format": "mp4",
        "js_runtimes": {"node": {}},
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        video_id = info.get("id")
        if not video_id:
            raise RuntimeError("yt-dlp did not return a video ID.")
        downloaded_file = _find_downloaded_file(
            video_id, ydl.prepare_filename(info)
        )

    print(f"Downloaded source: {downloaded_file}", flush=True)
    print("Converting to Mac-compatible H.264 MP4...", flush=True)
    final_file = make_mac_playable(downloaded_file, video_id)
    print(f"Ready to view: {final_file}", flush=True)
    return final_file


def _playlist_entries(playlist_url):
    """Return video URLs from a YouTube playlist without downloading them yet."""
    opts = {
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": False,
        "quiet": True,
        "ignoreerrors": True,
    }

    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    if info.get("_type") != "playlist":
        return [playlist_url]

    entries = []
    for entry in info.get("entries") or []:
        if not entry:
            continue
        url = entry.get("webpage_url") or entry.get("original_url")
        if not url:
            video_id = entry.get("id")
            if video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
        if url:
            entries.append(url)

    return entries


def download_url(url):
    """Download either one YouTube video or every video in a playlist."""
    url = url.strip()
    if not url:
        raise ValueError("YouTube URL cannot be empty.")

    entries = _playlist_entries(url)
    if len(entries) == 1 and entries[0] == url:
        return [download_single_video(url)]

    print(f"Playlist detected: {len(entries)} video(s)", flush=True)
    results = []
    for number, video_url in enumerate(entries, 1):
        print(f"\nPlaylist video {number}/{len(entries)}", flush=True)
        try:
            results.append(download_single_video(video_url))
        except Exception as exc:
            print(f"FAILED playlist item {number}: {exc}", flush=True)
    return results


def download_video(video_url):
    """Backward-compatible name used by the project."""
    return download_url(video_url)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python src/download_video.py <youtube_video_or_playlist_url>")
        raise SystemExit(2)

    files = download_url(sys.argv[1])
    print(f"\nFinished: {len(files)} video(s) ready in data/inbox/", flush=True)
