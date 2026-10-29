"""Subtitle burning and embedding engine."""
import os
import subprocess
from PySide6.QtCore import QObject, Signal, QRunnable, Slot
from core.config_manager import get_binary_path

class SubTaskSignals(QObject):
    started = Signal(str)                  # video_path
    finished = Signal(str, bool, str)      # video_path, success, message
    log = Signal(str)

class SubtitleTask(QRunnable):
    def __init__(self, video_path: str, sub_path: str, mode: str, font_name: str,
                 font_size: int, lang: str, out_path: str):
        super().__init__()
        self.video_path = video_path
        self.sub_path = sub_path
        self.mode = mode.lower()  # "burn" or "embed"
        self.font_name = font_name
        self.font_size = font_size
        self.lang = lang
        self.out_path = out_path
        self.signals = SubTaskSignals()
        self.is_cancelled = False
        self.process = None

    @Slot()
    def run(self):
        self.signals.started.emit(self.video_path)
        ffmpeg_bin = get_binary_path("ffmpeg")

        if "burn" in self.mode:
            # Hardcode subtitle into video frame
            escaped_sub = self.sub_path.replace(":", "\\:").replace("'", "\\'")
            sub_filter = f"subtitles='{escaped_sub}':force_style='FontName={self.font_name},FontSize={self.font_size}'"
            cmd = [
                ffmpeg_bin, "-y",
                "-i", self.video_path,
                "-vf", sub_filter,
                "-c:a", "copy",
                self.out_path
            ]
        else:
            # Soft-embed into container
            cmd = [
                ffmpeg_bin, "-y",
                "-i", self.video_path,
                "-i", self.sub_path,
                "-map", "0:v", "-map", "0:a?", "-map", "1:s",
                "-c", "copy",
                "-metadata:s:s:0", f"language={self.lang}",
                self.out_path
            ]

        self.signals.log.emit(f">>> Processing Subtitles: {' '.join(cmd)}")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True
            )

            for line in self.process.stdout:
                if self.is_cancelled:
                    self.process.terminate()
                    self.signals.finished.emit(self.video_path, False, "Cancelled")
                    return

            self.process.wait()
            if self.process.returncode == 0:
                self.signals.finished.emit(self.video_path, True, "Complete")
            else:
                self.signals.finished.emit(self.video_path, False, f"Exit code {self.process.returncode}")
        except Exception as e:
            self.signals.finished.emit(self.video_path, False, str(e))

    def cancel(self):
        self.is_cancelled = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
