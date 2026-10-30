"""URL / Stream downloader task using native yt-dlp and FFmpeg."""
import os
import shlex
import subprocess

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from core.config_manager import get_binary_path


class UrlTaskSignals(QObject):
    started = Signal(str)                  # url
    progress = Signal(str, float)          # url, percent
    finished = Signal(str, bool, str)      # url, success, message
    log = Signal(str)                      # log line

class UrlStreamTask(QRunnable):
    def __init__(self, url: str, output_path: str, custom_params: str = "",
                 cookie_file: str = "", speed_limit_kb: int = 0):
        super().__init__()
        self.url = url
        self.output_path = output_path
        self.custom_params = custom_params.strip() if custom_params else "-bsf:a aac_adtstoasc -c copy"
        self.cookie_file = cookie_file.strip() if cookie_file else ""
        self.speed_limit_kb = speed_limit_kb
        self.signals = UrlTaskSignals()
        self.is_cancelled = False
        self.process = None

    @Slot()
    def run(self):
        self.signals.started.emit(self.url)
        self.signals.log.emit(f">>> Fetching stream for: {self.url}")

        is_direct_stream = any(self.url.lower().endswith(ext) for ext in [".m3u8", ".mp4", ".mkv", ".ts", ".webm"]) or "m3u8" in self.url.lower()

        ytdlp_bin = get_binary_path("yt-dlp")
        ffmpeg_bin = get_binary_path("ffmpeg")

        if is_direct_stream:
            media_url = self.url
        else:
            try:
                cmd = [ytdlp_bin, "-g", "--no-warnings"]
                if self.cookie_file and os.path.exists(self.cookie_file):
                    cmd.extend(["--cookies", self.cookie_file])
                cmd.append(self.url)
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if res.returncode == 0 and res.stdout.strip():
                    media_url = res.stdout.strip().splitlines()[0]
                else:
                    self.signals.finished.emit(self.url, False, "Failed to resolve stream link")
                    return
            except Exception as e:
                self.signals.finished.emit(self.url, False, str(e))
                return

        cmd = [ffmpeg_bin, "-y"]
        if self.cookie_file and os.path.exists(self.cookie_file):
            cmd.extend(["-headers", f"Cookie: {self._read_cookie_header()}"])
        cmd.extend(["-i", media_url])

        if self.custom_params:
            cmd.extend(shlex.split(self.custom_params))

        cmd.extend(["-progress", "pipe:1", self.output_path])
        self.signals.log.emit(f">>> Running URL stream capture: {' '.join(cmd)}")

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

    def _read_cookie_header(self):
        try:
            with open(self.cookie_file, encoding="utf-8", errors="ignore") as f:
                cookies = []
                for line in f:
                    if line.strip() and not line.startswith("#"):
                        parts = line.strip().split("\t")
                        if len(parts) >= 7:
                            cookies.append(f"{parts[5]}={parts[6]}")
                return "; ".join(cookies)
        except Exception:
            return ""

    def cancel(self):
        self.is_cancelled = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
