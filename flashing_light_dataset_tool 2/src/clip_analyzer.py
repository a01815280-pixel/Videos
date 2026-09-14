from pathlib import Path
import subprocess

import cv2

from auto_sort import analyze_video

ROOT = Path(__file__).resolve().parents[1]
CLIPS = ROOT / "data" / "clips"


def make_clips(video_path, clip_seconds=2.0, overlap_seconds=0.5):
    """Create H.264 mini clips without changing the source video."""
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    if clip_seconds <= 0:
        raise ValueError("clip_seconds must be greater than 0")
    if not 0 <= overlap_seconds < clip_seconds:
        raise ValueError("overlap_seconds must be >= 0 and smaller than clip_seconds")

    output_dir = CLIPS / video_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {video_path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    finally:
        cap.release()

    if fps <= 0 or total <= 0:
        raise RuntimeError("Could not determine video duration.")

    duration = total / fps
    step = clip_seconds - overlap_seconds
    starts = []
    start = 0.0
    while start < duration:
        length = min(clip_seconds, duration - start)
        if length >= 0.25:
            starts.append((start, length))
        start += step

    clips = []
    for index, (start, length) in enumerate(starts, 1):
        output = output_dir / f"{video_path.stem}_clip_{index:04d}_{start:.2f}s.mp4"
        if not output.is_file() or output.stat().st_size == 0:
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start:.3f}",
                "-i", str(video_path),
                "-t", f"{length:.3f}",
                "-an",
                "-vf", "scale=300:-2",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-y", str(output),
            ]
            subprocess.run(command, check=True)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg failed to create {output}")

        clips.append({
            "path": output,
            "start": start,
            "duration": length,
            "index": index,
        })

    return clips


def analyze_clips(video_path, clip_seconds=2.0, overlap_seconds=0.5):
    """Create and analyze every mini clip from a video."""
    results = []
    for clip in make_clips(video_path, clip_seconds, overlap_seconds):
        result = analyze_video(clip["path"], sample_fps=10, max_frames=300)
        results.append({**clip, **result})
    return results
