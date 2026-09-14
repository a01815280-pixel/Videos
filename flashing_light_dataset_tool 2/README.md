# Flashing-Light Video Dataset Tool

A Mac desktop tool for building a manually labeled flashing-light video dataset.

## Workflow

1. Paste YouTube URLs into the app. Videos are downloaded into `data/inbox/`.
2. Click **Choose Flashing / No Flashing**.
3. The full video is analyzed automatically using frame-to-frame luminance changes.
4. The app creates 2-second mini clips with 0.5-second overlap and analyzes every clip independently.
5. Watch the full video or a selected mini clip if needed.
6. Label individual clips, all clips, or the complete original video.
7. The complete labeled video is moved from `data/inbox/` into `data/raw/flashing/` or `data/raw/no_flashing/`.
8. Labeled mini clips are moved into `data/clips/flashing/` or `data/clips/no_flashing/`.

The automatic analysis is only evidence. Your manual label is the final label.

## Why mini clips are included

A long video can contain both flashing and non-flashing sections. The mini clips let the future LSTM learn from short labeled sections while the complete source video is still retained in the final dataset.

Mini clips are generated separately, so the original video is never replaced by the clips.

## Analysis

The analysis uses IRIS-PSE-Detection 1.1.2 as the primary detector. IRIS checks luminance flashes, saturated-red flashes, transitions in a 1-second sliding window, extended failures, and optional spatial-pattern failures. The GUI also keeps a simple brightness-change diagnostic for context.

The automatic suggestion is not a trained classifier and is not a guarantee that a video is safe for every viewer. The manual label remains final. IRIS itself documents that its results should not be treated as the sole method for ensuring video safety.

## LSTM

The old LSTM training system and TensorFlow dependencies are intentionally not included. The `lstm/` folder is reserved for connecting your existing LSTM later.

## Mac setup

Open Terminal, enter the project folder, and run:

```bash
chmod +x setup_mac.command run_app.command
./setup_mac.command
./run_app.command
```

The setup installs Homebrew Python 3.12, ffmpeg, Node, PySide6, OpenCV, NumPy, yt-dlp, and IRIS-PSE-Detection 1.1.2 inside the project's virtual environment.

After setup, normally you only need:

```bash
./run_app.command
```

## Video compatibility

YouTube can provide formats such as WebM, VP9, or AV1. The downloader converts the downloaded video to an H.264 MP4 with no audio so the dataset contains video only and remains broadly compatible with QuickTime and Finder.

The conversion keeps the complete video rather than creating a shortened preview. Both full videos and mini clips are H.264 MP4 files with no audio because the project only needs the visual signal.

## Project structure

```text
flashing_light_dataset_tool/
├── data/
│   ├── inbox/
│   ├── auto_review/
│   ├── raw/
│   │   ├── flashing/
│   │   └── no_flashing/
│   └── clips/
│       ├── <video-name>/
│       ├── flashing/
│       └── no_flashing/
├── lstm/
├── src/
│   ├── app.py
│   ├── auto_sort.py
│   ├── clip_analyzer.py
│   ├── download_video.py
│   └── manual_label.py
├── requirements.txt
├── setup_mac.command
└── run_app.command
```


## Supplied luminance algorithm integrated
This version keeps the project's Mac-friendly downloader and integrates the supplied luminance-event detector: 25% pixel threshold at +/-20, mutually exclusive bright/dark events, alternating zigzags, three-event cycles, frequency calculation, and >=3 Hz risk-segment grouping. The GUI and dataset workflow remain compatible with the existing project.


## Current YouTube workflow
The app accepts individual YouTube video URLs and playlist URLs. Playlist entries are processed one at a time; every completed download is converted to H.264 video with no audio and placed in `data/inbox/` before review.
