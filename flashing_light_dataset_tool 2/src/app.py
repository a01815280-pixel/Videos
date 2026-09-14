from pathlib import Path
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QThread, QUrl, QObject, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data" / "inbox"
REVIEW = ROOT / "data" / "auto_review"
RAW = ROOT / "data" / "raw"
CLIPS = ROOT / "data" / "clips"
EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

for folder in (INBOX, REVIEW, RAW / "flashing", RAW / "no_flashing", CLIPS):
    folder.mkdir(parents=True, exist_ok=True)


class DownloadWorker(QObject):
    log = Signal(str)
    finished = Signal()

    def __init__(self, urls):
        super().__init__()
        self.urls = urls

    @Slot()
    def run(self):
        try:
            for url in self.urls:
                self.log.emit(f"Downloading: {url}")
                command = [sys.executable, str(ROOT / "src" / "download_video.py"), url]
                try:
                    environment = os.environ.copy()
                    environment["PYTHONUNBUFFERED"] = "1"
                    process = subprocess.Popen(
                        command,
                        cwd=ROOT,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        env=environment,
                    )
                    if process.stdout:
                        for line in process.stdout:
                            self.log.emit(line.rstrip())
                    code = process.wait()
                    if code == 0:
                        self.log.emit(f"Download finished successfully: {url}")
                    else:
                        self.log.emit(f"Download failed with code {code}: {url}")
                except Exception as exc:
                    self.log.emit(f"ERROR downloading {url}: {exc}")
        finally:
            self.finished.emit()


class AnalysisWorker(QObject):
    finished = Signal(object, object)
    error = Signal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    @Slot()
    def run(self):
        try:
            from auto_sort import analyze_video
            from clip_analyzer import analyze_clips

            full_result = analyze_video(self.path, sample_fps=10, max_frames=1800)
            clip_results = analyze_clips(self.path, clip_seconds=2.0, overlap_seconds=0.5)
            self.finished.emit(full_result, clip_results)
        except Exception as exc:
            self.error.emit(str(exc))


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Flashing-Light Video Dataset Tool")
        self.resize(980, 760)
        self.download_thread = None
        self.download_worker = None
        self.review_window = None
        self.build_ui()
        self.refresh_counts()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)

        title = QLabel("Flashing-Light Video Dataset Tool")
        title.setStyleSheet("font-size: 25px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "Download videos → review the brightness information → choose a label → move the video."
        ))

        counts = QHBoxLayout()
        self.inbox_label = QLabel()
        self.flash_label = QLabel()
        self.noflash_label = QLabel()
        for widget in (self.inbox_label, self.flash_label, self.noflash_label):
            counts.addWidget(widget)
        counts.addStretch()
        layout.addLayout(counts)

        download_box = QGroupBox("1. Add videos")
        download_layout = QVBoxLayout(download_box)
        download_layout.addWidget(QLabel(
            "Paste one YouTube video URL or playlist URL per line. Playlist videos are downloaded individually and converted to Mac-compatible MP4 files in the Inbox."
        ))
        self.url_box = QPlainTextEdit()
        self.url_box.setPlaceholderText(
            "https://www.youtube.com/watch?v=...\nhttps://youtu.be/..."
        )
        self.url_box.setMaximumHeight(110)
        download_layout.addWidget(self.url_box)

        row = QHBoxLayout()
        self.download_btn = QPushButton("Download Videos")
        self.download_btn.clicked.connect(self.download_urls)
        self.clear_btn = QPushButton("Clear URLs")
        self.clear_btn.clicked.connect(self.url_box.clear)
        self.open_inbox_btn = QPushButton("Open Inbox")
        self.open_inbox_btn.clicked.connect(lambda: self.open_folder(INBOX))
        for button in (self.download_btn, self.clear_btn, self.open_inbox_btn):
            row.addWidget(button)
        row.addStretch()
        download_layout.addLayout(row)
        layout.addWidget(download_box)

        review_box = QGroupBox("2. Review and label")
        review_layout = QHBoxLayout(review_box)
        self.review_btn = QPushButton("Choose Flashing / No Flashing")
        self.review_btn.clicked.connect(self.open_manual_review)
        self.open_final_btn = QPushButton("Open Final Dataset")
        self.open_final_btn.clicked.connect(lambda: self.open_folder(RAW))
        review_layout.addWidget(self.review_btn)
        review_layout.addWidget(self.open_final_btn)
        layout.addWidget(review_box)

        explanation_box = QGroupBox("How the analysis works")
        explanation_layout = QVBoxLayout(explanation_box)
        explanation_layout.addWidget(QLabel(
            "The automatic analysis now uses IRIS-PSE-Detection 1.1.2. It checks luminance flashes, "
            "saturated-red flashes, 1-second transition windows, extended flashes, and spatial patterns. "
            "It does not make the final decision for you."
        ))
        explanation_layout.addWidget(QLabel(
            "The analysis provides evidence before you press FLASHING or NO FLASHING."
        ))
        layout.addWidget(explanation_box)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        log_box = QGroupBox("Activity log")
        log_layout = QVBoxLayout(log_box)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        log_layout.addWidget(self.output)
        layout.addWidget(log_box, 1)

        self.setStyleSheet("""
            QPushButton { padding: 9px 12px; }
            QGroupBox { font-weight: 600; }
        """)

    def log(self, text):
        self.output.append(text)

    def refresh_counts(self):
        def count(folder):
            if not folder.exists():
                return 0
            return sum(
                1 for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in EXTS
            )

        self.inbox_label.setText(f"Inbox: {count(INBOX)}")
        self.flash_label.setText(f"Flashing: {count(RAW / 'flashing')}")
        self.noflash_label.setText(f"No flashing: {count(RAW / 'no_flashing')}")

    def set_busy(self, busy):
        self.progress.setVisible(busy)
        self.download_btn.setEnabled(not busy)
        self.review_btn.setEnabled(not busy)

    def download_urls(self):
        urls = [url.strip() for url in self.url_box.toPlainText().splitlines() if url.strip()]
        if not urls:
            QMessageBox.information(self, "No URLs", "Paste one or more YouTube URLs first.")
            return

        self.set_busy(True)
        self.log(f"Starting {len(urls)} download(s)…")
        self.download_thread = QThread(self)
        self.download_worker = DownloadWorker(urls)
        self.download_worker.moveToThread(self.download_thread)
        self.download_thread.started.connect(self.download_worker.run)
        self.download_worker.log.connect(self.log)
        self.download_worker.finished.connect(self.download_thread.quit)
        self.download_worker.finished.connect(self.download_worker.deleteLater)
        self.download_thread.finished.connect(self._downloads_finished)
        self.download_thread.finished.connect(self.download_thread.deleteLater)
        self.download_thread.start()

    @Slot()
    def _downloads_finished(self):
        self.log("All requested downloads finished. You can continue using the app.")
        self.set_busy(False)
        self.refresh_counts()
        self.download_thread = None
        self.download_worker = None

    def open_folder(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def open_video(self, path):
        path = Path(path)
        if not path.is_file():
            QMessageBox.warning(self, "Video not found", f"Could not find:\n{path}")
            return

        try:
            subprocess.run(["open", "-a", "QuickTime Player", str(path)], check=True)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            if not opened:
                QMessageBox.warning(
                    self,
                    "Could not open video",
                    f"macOS could not open:\n{path}\n\n{exc}",
                )

    def open_manual_review(self):
        if self.review_window is None or not self.review_window.isVisible():
            self.review_window = ManualReviewWindow(self)
            self.review_window.show()
        self.review_window.raise_()
        self.review_window.activateWindow()


class ManualReviewWindow(QWidget):
    """Review full videos and automatically create and analyze mini clips."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Review Videos — Full Video + Mini Clips")
        self.resize(1120, 820)
        self.index = 0
        self.items = []
        self.analysis_token = 0
        self.analysis_thread = None
        self.analysis_worker = None
        self.clip_results = []
        self.current_clip_index = -1

        layout = QVBoxLayout(self)
        title = QLabel("Review Videos")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "The original video is kept intact. The app creates 2-second clips with 0.5-second overlap, "
            "analyzes each clip separately, and lets you label the full video and individual clips."
        ))

        self.info = QLabel()
        self.info.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.info)
        self.current = QLabel()
        self.current.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(self.current)

        analysis_box = QGroupBox("Full-video analysis")
        analysis_layout = QVBoxLayout(analysis_box)
        self.summary = QLabel("Select a video to analyze it.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size: 15px; padding: 8px;")
        analysis_layout.addWidget(self.summary)

        form = QFormLayout()
        self.values = {}
        fields = [
            ("Automatic suggestion", "suggestion"),
            ("Confidence", "confidence"),
            ("Brightness changes", "changes"),
            ("Bright ↔ dark alternation", "alternation"),
            ("Typical brightness change", "typical_change"),
            ("Strongest brightening", "increase"),
            ("Strongest darkening", "decrease"),
            ("Video", "video"),
        ]
        for label, key in fields:
            value = QLabel("—")
            value.setWordWrap(True)
            self.values[key] = value
            form.addRow(QLabel(f"{label}:"), value)
        analysis_layout.addLayout(form)
        layout.addWidget(analysis_box)

        clips_box = QGroupBox("Mini-clip analysis")
        clips_layout = QVBoxLayout(clips_box)
        clips_layout.addWidget(QLabel(
            "Each clip is checked independently. A video can therefore contain both flashing and non-flashing clips."
        ))
        self.clip_table = QTableWidget(0, 5)
        self.clip_table.setHorizontalHeaderLabels([
            "Clip", "Time", "Suggestion", "Confidence", "Brightness changes"
        ])
        self.clip_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.clip_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.clip_table.setSelectionMode(QTableWidget.SingleSelection)
        self.clip_table.itemSelectionChanged.connect(self.select_clip)
        clips_layout.addWidget(self.clip_table, 1)

        clip_row = QHBoxLayout()
        self.open_clip_btn = QPushButton("Open Selected Clip")
        self.open_clip_btn.clicked.connect(self.open_selected_clip)
        self.clip_flash_btn = QPushButton("FLASHING — Clip")
        self.clip_flash_btn.clicked.connect(lambda: self.label_clip("flashing"))
        self.clip_no_btn = QPushButton("NO FLASHING — Clip")
        self.clip_no_btn.clicked.connect(lambda: self.label_clip("no_flashing"))
        self.all_flash_btn = QPushButton("Label All Clips FLASHING")
        self.all_flash_btn.clicked.connect(lambda: self.label_all_clips("flashing"))
        self.all_no_btn = QPushButton("Label All Clips NO FLASHING")
        self.all_no_btn.clicked.connect(lambda: self.label_all_clips("no_flashing"))
        self.clip_buttons = (
            self.open_clip_btn,
            self.clip_flash_btn,
            self.clip_no_btn,
        )
        self.all_clip_buttons = (self.all_flash_btn, self.all_no_btn)
        for button in (*self.clip_buttons, *self.all_clip_buttons):
            clip_row.addWidget(button)
        clips_layout.addLayout(clip_row)
        layout.addWidget(clips_box, 1)

        meaning_box = QGroupBox("What the numbers mean")
        meaning_layout = QVBoxLayout(meaning_box)
        meaning = QLabel(
            "• Mini clip: a short section for the future LSTM. The original video is never replaced.\n"
            "• Brightness changes: detected frame-to-frame light events using the luminance-pixel threshold.\n"
            "• Bright ↔ dark alternation: repeated switching between brighter and darker states.\n"
            "• Confidence: how far the rule-based score is from its decision boundary; it is NOT model accuracy.\n"
            "• Strongest brightening/darkening: the biggest light increase/decrease found.\n"
            "• Important: cuts, camera movement, sunlight, explosions, and other normal effects can look like flashing."
        )
        meaning.setWordWrap(True)
        meaning_layout.addWidget(meaning)
        layout.addWidget(meaning_box)

        row = QHBoxLayout()
        buttons = [
            ("Open Full Video", self.open_current),
            ("← Previous", self.previous),
            ("SKIP", self.skip),
            ("FLASHING — MOVE ORIGINAL", lambda: self.label("flashing")),
            ("NO FLASHING — MOVE ORIGINAL", lambda: self.label("no_flashing")),
        ]
        for text, slot in buttons:
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)

        self.set_clip_buttons_enabled(False)
        self.populate()

    def set_clip_buttons_enabled(self, enabled):
        for button in self.clip_buttons:
            button.setEnabled(enabled)
        for button in self.all_clip_buttons:
            button.setEnabled(enabled)

    def populate(self):
        self.items = [
            path for path in sorted(INBOX.iterdir())
            if path.is_file() and path.suffix.lower() in EXTS
        ]
        if self.items:
            self.show_current()
        else:
            self.show_empty()

    def show_empty(self):
        self.info.setText("No videos waiting in Inbox.")
        self.current.setText("")
        self.summary.setText("There are no videos to review.")
        for value in self.values.values():
            value.setText("—")
        self.clip_table.setRowCount(0)
        self.clip_results = []
        self.current_clip_index = -1
        self.set_clip_buttons_enabled(False)

    def show_current(self):
        if not self.items:
            return

        path = self.items[self.index]
        self.info.setText(f"Video {self.index + 1} of {len(self.items)}")
        self.current.setText(path.name)
        self.summary.setText("Analyzing full video and creating/analyzing mini clips…")
        for value in self.values.values():
            value.setText("Analyzing…")
        self.clip_table.setRowCount(0)
        self.clip_results = []
        self.current_clip_index = -1
        self.set_clip_buttons_enabled(False)
        self.analysis_token += 1
        self.start_analysis(path, self.analysis_token)

    def start_analysis(self, path, token):
        if self.analysis_thread is not None and self.analysis_thread.isRunning():
            return

        self.analysis_thread = QThread(self)
        self.analysis_worker = AnalysisWorker(path)
        self.analysis_worker.moveToThread(self.analysis_thread)
        self.analysis_thread.started.connect(self.analysis_worker.run)
        self.analysis_worker.finished.connect(
            lambda result, clips: self.show_analysis(result, clips, token, path)
        )
        self.analysis_worker.error.connect(
            lambda error: self.show_analysis_error(error, token)
        )
        self.analysis_worker.finished.connect(self.analysis_thread.quit)
        self.analysis_worker.error.connect(self.analysis_thread.quit)
        self.analysis_worker.finished.connect(self.analysis_worker.deleteLater)
        self.analysis_worker.error.connect(self.analysis_worker.deleteLater)
        self.analysis_thread.finished.connect(self._analysis_thread_finished)
        self.analysis_thread.finished.connect(self.analysis_thread.deleteLater)
        self.analysis_thread.start()

    @Slot()
    def _analysis_thread_finished(self):
        self.analysis_thread = None
        self.analysis_worker = None

    def show_analysis(self, result, clips, token, path):
        if token != self.analysis_token or not self.items or not path.exists():
            return

        self.clip_results = [{**clip, "source_video": str(path)} for clip in clips]
        clips = self.clip_results
        label = result["label"]
        confidence = result["confidence"]
        confidence_text = "Low" if confidence < 0.25 else "Medium" if confidence < 0.65 else "Higher"
        self.values["suggestion"].setText("FLASHING" if label == "flashing" else "NO FLASHING")
        self.values["confidence"].setText(f"{confidence_text} ({confidence:.0%})")
        self.values["changes"].setText(
            f"{result['spikes']} unusual changes ({result['spike_rate'] * 100:.1f}%)"
        )
        self.values["alternation"].setText(f"{result['alternations'] * 100:.1f}%")
        self.values["typical_change"].setText(f"{result['median_change']:.2f}")
        self.values["increase"].setText(f"+{result['max_pixel_increase']:.2f}")
        self.values["decrease"].setText(f"{result['max_pixel_decrease']:.2f}")
        self.values["video"].setText(
            f"{result['duration']:.2f}s • {result['fps']:.2f} FPS • {result['total_frames']} frames"
        )

        flashing_clips = sum(clip["label"] == "flashing" for clip in clips)
        iris_result = result.get("iris_result", "Unavailable")
        self.summary.setText(
            f"IRIS result: {iris_result}. "
            f"Automatic suggestion: {'FLASHING' if label == 'flashing' else 'NO FLASHING'}. "
            f"The app found {len(clips)} mini clips; {flashing_clips} were suggested as flashing. "
            f"Luminance failures: {result.get('iris_luminance_flash_frames', 0)}; "
            f"red failures: {result.get('iris_red_flash_frames', 0)}; "
            f"pattern failures: {result.get('iris_pattern_fail_frames', 0)}. "
            "Review the clips because one video can contain both kinds of sections."
        )

        self.clip_table.setRowCount(len(clips))
        for row, clip in enumerate(clips):
            values = [
                str(clip["index"]),
                f"{clip['start']:.2f}s–{clip['start'] + clip['duration']:.2f}s",
                "FLASHING" if clip["label"] == "flashing" else "NO FLASHING",
                f"{clip['confidence']:.0%}",
                str(clip["spikes"]),
            ]
            for column, value in enumerate(values):
                self.clip_table.setItem(row, column, QTableWidgetItem(value))

        self.set_clip_buttons_enabled(bool(clips))
        if clips:
            self.clip_table.selectRow(0)
        self.app.log(
            f"Analyzed {path.name}: {len(clips)} mini clips in data/clips/{path.stem}/"
        )

    def show_analysis_error(self, error, token):
        if token != self.analysis_token:
            return
        self.summary.setText(
            f"Analysis failed: {error}\nYou can still watch and label the original video."
        )
        for value in self.values.values():
            value.setText("Unavailable")
        self.set_clip_buttons_enabled(False)

    def select_clip(self):
        rows = self.clip_table.selectionModel().selectedRows()
        self.current_clip_index = rows[0].row() if rows else -1

    def open_current(self):
        if self.items:
            self.app.open_video(self.items[self.index])

    def _resolve_clip_path(self, clip):
        """Find a clip even if it has already been moved or needs recreation."""
        path = Path(clip["path"])
        if path.is_file():
            return path

        matches = [p for p in CLIPS.rglob(path.name) if p.is_file()]
        if matches:
            clip["path"] = matches[0]
            return matches[0]

        source_video = Path(clip.get("source_video", ""))
        candidates = [source_video] if source_video.is_file() else []
        if not candidates:
            stem = path.name.split("_clip_")[0]
            for folder in (INBOX, RAW / "flashing", RAW / "no_flashing"):
                if folder.exists():
                    candidates.extend(
                        p for p in folder.iterdir()
                        if p.is_file() and p.stem == stem
                    )

        for original in candidates:
            try:
                from clip_analyzer import make_clips
                recreated = make_clips(original, clip_seconds=2.0, overlap_seconds=0.5)
                for item in recreated:
                    if item["path"].name == path.name and item["path"].is_file():
                        clip["path"] = item["path"]
                        return item["path"]
            except Exception:
                continue

        return None

    def open_selected_clip(self):
        if not 0 <= self.current_clip_index < len(self.clip_results):
            QMessageBox.information(self, "Select a clip", "Select a mini clip first.")
            return

        clip = self.clip_results[self.current_clip_index]
        path = self._resolve_clip_path(clip)

        if path is None:
            QMessageBox.warning(
                self,
                "Clip not found",
                "Could not find or recreate this mini clip.\n\n"
                f"Expected: {clip['path']}",
            )
            return

        self.app.open_video(path)

    def previous(self):
        if self.analysis_thread is not None and self.analysis_thread.isRunning():
            return
        if self.items:
            self.index = max(0, self.index - 1)
            self.show_current()

    def skip(self):
        if self.analysis_thread is not None and self.analysis_thread.isRunning():
            return
        if self.items:
            self.index = min(len(self.items) - 1, self.index + 1)
            self.show_current()

    def label_clip(self, label, advance=True):
        if not 0 <= self.current_clip_index < len(self.clip_results):
            QMessageBox.information(self, "Select a clip", "Select a mini clip first.")
            return

        clip = self.clip_results[self.current_clip_index]
        source = self._resolve_clip_path(clip)
        if source is None:
            QMessageBox.warning(self, "Clip not found", f"Could not find or recreate the mini clip:\n{clip['path']}")
            return

        target_dir = CLIPS / label
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name

        try:
            if target.exists():
                QMessageBox.warning(
                    self,
                    "Clip already exists",
                    f"A clip with this name already exists in {label}.",
                )
                return
            shutil.move(str(source), str(target))
            clip["path"] = target
            clip["label"] = label
            self.clip_table.item(self.current_clip_index, 2).setText(
                "FLASHING" if label == "flashing" else "NO FLASHING"
            )
            self.app.log(f"Clip labeled {target.name}: {label.upper()} — moved")
            self.app.refresh_counts()

            # After labeling a clip, automatically select the next clip so the
            # reviewer can work through the list without manually clicking each row.
            if advance:
                next_index = self.current_clip_index + 1
                if next_index < self.clip_table.rowCount():
                    self.clip_table.selectRow(next_index)
                else:
                    # This was the last clip. Leave it unselected rather than
                    # accidentally labeling the same clip again.
                    self.clip_table.clearSelection()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Could not label clip",
                f"The clip could not be moved:\n{exc}",
            )

    def label_all_clips(self, label):
        if not self.clip_results:
            return
        for index in range(len(self.clip_results)):
            self.current_clip_index = index
            self.label_clip(label, advance=False)
        self.current_clip_index = -1
        self.clip_table.clearSelection()

    def label(self, label):
        if self.analysis_thread is not None and self.analysis_thread.isRunning():
            QMessageBox.information(
                self,
                "Analysis in progress",
                "Wait for the analysis to finish before moving the original video.",
            )
            return
        if not self.items:
            return

        source = self.items[self.index]
        target_dir = RAW / label
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        if target.exists():
            QMessageBox.warning(
                self,
                "File already exists",
                f"A video named '{source.name}' already exists in {label}.",
            )
            return

        try:
            shutil.move(str(source), str(target))
        except Exception as exc:
            QMessageBox.critical(self, "Move failed", f"Could not move the video:\n{exc}")
            return

        self.app.log(
            f"Labeled ORIGINAL {source.name}: {label.upper()} — moved from Inbox. "
            "Mini clips remain available in data/clips/."
        )
        self.items.pop(self.index)
        self.analysis_token += 1
        if self.items:
            self.index = min(self.index, len(self.items) - 1)
            self.show_current()
        else:
            self.show_empty()
        self.app.refresh_counts()


if __name__ == "__main__":
    application = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(application.exec())
