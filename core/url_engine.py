"""URL / Stream downloader task using native yt-dlp and FFmpeg."""
import subprocess

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from core.config_manager import get_binary_path


class UrlTaskSignals(QObject):
    started = Signal(str)                  # url
    progress = Signal(str, float)          # url, percent
    finished = Signal(str, bool, str)      # url, success, message
    log = Signal(str)                      # log line

class UrlStreamTask(QRunnable):
    def __init__(self, url: str, output_path: str):
        super().__init__()
        self.url = url
        self.output_path = output_path
        self.signals = UrlTaskSignals()
        self.is_cancelled = False
        self.process = None

    @Slot()
    def run(self):
        self.signals.started.emit(self.url)
        self.signals.log.emit(f">>> Fetching stream for: {self.url}")

        # Check if URL is a direct M3U8/MP4 or needs yt-dlp extraction
        is_direct_stream = any(self.url.lower().endswith(ext) for ext in [".m3u8", ".mp4", ".mkv", ".ts", ".webm"]) or "m3u8" in self.url.lower()

        ytdlp_bin = get_binary_path("yt-dlp")
        ffmpeg_bin = get_binary_path("ffmpeg")

        if is_direct_stream:
            media_url = self.url
        else:
            # Use yt-dlp to extract direct media link
            try:
                cmd = [ytdlp_bin, "-g", "--no-warnings", self.url]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
                if res.returncode == 0 and res.stdout.strip():
                    media_url = res.stdout.strip().splitlines()[0]
                else:
                    self.signals.finished.emit(self.url, False, "Failed to resolve stream link")
                    return
            except Exception as e:
                self.signals.finished.emit(self.url, False, str(e))
                return

        # Download and remux with configured FFmpeg
        cmd = [
            ffmpeg_bin, "-y",
            "-i", media_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-progress", "pipe:1",
            self.output_path
        ]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            for line in self.process.stdout:
                if self.is_cancelled:
                    self.process.terminate()
                    self.signals.finished.emit(self.url, False, "Cancelled")
                    return

                line = line.strip()
                if "out_time_ms=" in line:
                    # Generic progress indicator pulse
                    self.signals.progress.emit(self.url, 50.0)
                elif "progress=end" in line:
                    self.signals.progress.emit(self.url, 100.0)

            self.process.wait()
            if self.process.returncode == 0:
                self.signals.finished.emit(self.url, True, "Downloaded")
            else:
                self.signals.finished.emit(self.url, False, f"Error (code {self.process.returncode})")
        except Exception as e:
            self.signals.finished.emit(self.url, False, str(e))

    def cancel(self):
        self.is_cancelled = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
