from pathlib import Path
import argparse
import csv

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "inbox"
REVIEW = ROOT / "data" / "auto_review"
EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def _incident_value(incidents, name):
    return int(getattr(incidents, name, 0) or 0)


def _enum_name(value):
    return getattr(value, "name", str(value).split(".")[-1])


def _build_confidence(overall_name, total_frames, failed_frames, warning_frames, red_failed, pattern_failed):
    """Return a UI confidence estimate, not a medical/safety probability."""
    if total_frames <= 0:
        return 0.0
    failed_ratio = min(1.0, failed_frames / max(1.0, total_frames * 0.02))
    evidence = failed_ratio
    if red_failed:
        evidence = max(evidence, 0.8)
    if pattern_failed:
        evidence = max(evidence, 0.8)
    if overall_name == "Pass":
        # A pass is still not proof of safety; this only describes how clearly IRIS passed.
        return 0.85
    if overall_name == "PassWithWarning":
        return 0.55 + min(0.25, warning_frames / max(1.0, total_frames * 0.02) * 0.25)
    return 0.70 + 0.29 * evidence


def analyze_video(path, sample_fps=10, max_frames=1800, resize_width=300):
    """Analyze a video with IRIS-PSE-Detection 1.1.2.

    IRIS is the primary detector. It analyzes luminance flashes, saturated-red
    flashes, 1-second transition windows, extended failures, and optional
    spatial-pattern failures. The old custom >=3 Hz detector is no longer used
    to decide the automatic label.

    The legacy GUI fields are retained so the rest of the application keeps
    working, while IRIS-specific fields expose the actual result and evidence.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    try:
        from iris_pse_detection import VideoAnalyser, Configuration, AnalysisResult
    except ImportError as exc:
        raise RuntimeError(
            "IRIS-PSE-Detection 1.1.2 is not installed. Run ./setup_mac.command again."
        ) from exc

    config = Configuration()
    # These are the documented defaults, made explicit so the project behavior
    # is reproducible. Pattern detection is enabled because it is relevant to
    # the project's photosensitivity screening goal.
    config.luminance_flash_threshold = 0.10
    config.red_flash_threshold = 20.0
    config.area_proportion = 0.25
    config.max_transitions = 4
    config.extended_fail_seconds = 4
    config.pattern_detection_enabled = True

    analyser = VideoAnalyser(config)
    result = analyser.analyse_video(str(path))

    overall = _enum_name(result.overall_result)
    total_frames = int(getattr(result, "total_frames", 0) or 0)
    duration = float(getattr(result, "video_len", 0.0) or 0.0)

    lum_incidents = getattr(result, "total_luminance_incidents", None)
    red_incidents = getattr(result, "total_red_incidents", None)
    lum_flash = _incident_value(lum_incidents, "flash_fail_frames")
    lum_extended = _incident_value(lum_incidents, "extended_fail_frames")
    lum_warning = _incident_value(lum_incidents, "pass_with_warning_frames")
    red_flash = _incident_value(red_incidents, "flash_fail_frames")
    red_extended = _incident_value(red_incidents, "extended_fail_frames")
    red_warning = _incident_value(red_incidents, "pass_with_warning_frames")
    pattern_failed = int(getattr(result, "pattern_fail_frames", 0) or 0)

    total_failed = lum_flash + lum_extended + red_flash + red_extended
    total_warnings = lum_warning + red_warning

    # IRIS's documented overall results are the source of truth for the
    # automatic suggestion. Any actual failure becomes FLASHING; warnings are
    # surfaced separately rather than silently calling them "safe".
    label = "flashing" if overall in {
        "Fail",
        "LuminanceFlashFailure",
        "LuminanceExtendedFlashFailure",
        "RedFlashFailure",
        "RedExtendedFlashFailure",
        "PatternFailure",
    } else "no_flashing"

    confidence = _build_confidence(
        overall,
        total_frames,
        total_failed,
        total_warnings,
        red_flash + red_extended,
        pattern_failed,
    )

    # Retain a few simple compatibility metrics for the existing UI.
    fps = total_frames / duration if duration > 0 else 0.0
    failed_rate = total_failed / total_frames if total_frames else 0.0
    warning_rate = total_warnings / total_frames if total_frames else 0.0

    # Read enough frames to provide a visual-change summary for the existing
    # diagnostic panel. This is NOT used to determine the IRIS label.
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {path}")
    luminance = []
    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS) or fps or 30.0
        stride = max(1, round(native_fps / max(1, sample_fps)))
        frame_index = 0
        while len(luminance) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % stride:
                frame_index += 1
                continue
            if resize_width and frame.shape[1] > resize_width:
                h = max(2, round(frame.shape[0] * resize_width / frame.shape[1]))
                frame = cv2.resize(frame, (resize_width, h), interpolation=cv2.INTER_AREA)
            # Normalized average brightness only for the legacy diagnostic fields.
            luminance.append(float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean() / 255.0))
            frame_index += 1
    finally:
        cap.release()

    means = np.asarray(luminance, dtype=np.float32)
    changes = np.diff(means) if len(means) > 1 else np.asarray([], dtype=np.float32)
    abs_changes = np.abs(changes)
    median_change = float(np.median(abs_changes)) if len(abs_changes) else 0.0
    max_increase = float(np.max(changes)) if len(changes) else 0.0
    max_decrease = float(np.min(changes)) if len(changes) else 0.0
    threshold = max(median_change * 4.0, 0.02)
    spikes = int(np.sum(abs_changes >= threshold)) if len(abs_changes) else 0
    spike_rate = float(spikes / len(abs_changes)) if len(abs_changes) else 0.0
    signs = np.sign(means - np.median(means)) if len(means) else np.asarray([])
    signs = signs[signs != 0]
    alternations = float(np.mean(signs[1:] != signs[:-1])) if len(signs) > 1 else 0.0

    return {
        "label": label,
        "score": confidence,
        "confidence": confidence,
        "fps": float(fps),
        "duration": duration,
        "total_frames": total_frames,
        "samples": int(len(means)),
        "sample_fps": float(sample_fps),
        "mean_luminance": float(np.mean(means)) if len(means) else 0.0,
        "luminance_std": float(np.std(means)) if len(means) else 0.0,
        "median_change": median_change,
        "change_threshold": threshold,
        "spike_rate": spike_rate,
        "spikes": spikes,
        "max_pixel_increase": max_increase,
        "max_pixel_decrease": max_decrease,
        "largest_abs_pixel_change": max(abs(max_increase), abs(max_decrease)),
        "strong_increases": spikes,
        "strong_decreases": spikes,
        "alternations": alternations,
        "strongest_events": [],
        "flashes": [],
        "zigzags": [],
        "cycles": [],
        "riskcycles": [],
        "risk_segments": [],
        "max_frequency_hz": 0.0,
        "iris_result": overall,
        "iris_luminance_flash_frames": lum_flash,
        "iris_luminance_extended_frames": lum_extended,
        "iris_luminance_warning_frames": lum_warning,
        "iris_red_flash_frames": red_flash,
        "iris_red_extended_frames": red_extended,
        "iris_red_warning_frames": red_warning,
        "iris_pattern_fail_frames": pattern_failed,
        "iris_total_failed_frames": total_failed,
        "iris_total_warning_frames": total_warnings,
    }


def main():
    parser = argparse.ArgumentParser(description="Photosensitivity analysis using IRIS-PSE-Detection 1.1.2.")
    parser.add_argument("--sample-fps", type=int, default=10)
    parser.add_argument("--max-frames", type=int, default=1800)
    args = parser.parse_args()

    videos = sorted(p for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() in EXTS)
    if not videos:
        print("No videos found in data/inbox/")
        return

    REVIEW.mkdir(parents=True, exist_ok=True)
    print("\nIRIS photosensitivity analysis")
    print("==============================")
    print("Automatic labels are suggestions; manual labeling remains final.\n")

    for path in videos:
        try:
            result = analyze_video(path, sample_fps=args.sample_fps, max_frames=args.max_frames)
            print(f"{path.name}: {result['iris_result']} -> {result['label']} ({result['confidence']:.0%})")
            print(
                f"  luminance failures={result['iris_luminance_flash_frames']}, "
                f"extended={result['iris_luminance_extended_frames']}; "
                f"red failures={result['iris_red_flash_frames']}, "
                f"pattern failures={result['iris_pattern_fail_frames']}"
            )
        except Exception as exc:
            print(f"ERROR: {path.name}: {exc}")


if __name__ == "__main__":
    main()
