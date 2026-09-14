from pathlib import Path
import argparse
import shutil

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "raw"
VALID = {"flashing", "no_flashing"}


def move_video(video, label):
    """Move one video into its final manual-label folder."""
    if label not in VALID:
        raise ValueError(f"Invalid label: {label}")

    source = Path(video).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    target_dir = DEST / label
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists():
        raise FileExistsError(f"A file with this name already exists: {target}")

    shutil.move(str(source), str(target))
    return target


def main():
    parser = argparse.ArgumentParser(description="Move one video into its final label folder.")
    parser.add_argument("video")
    parser.add_argument("label", choices=sorted(VALID))
    args = parser.parse_args()
    print(f"Moved: {move_video(args.video, args.label)}")


if __name__ == "__main__":
    main()
