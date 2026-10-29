"""Multi-track audio, video, and subtitle multiplexing engine."""
import subprocess
from PySide6.QtCore import QObject, Signal, QRunnable, Slot
from core.config_manager import get_binary_path

class MuxTaskSignals(QObject):
    started = Signal(str)                  # base_video
    finished = Signal(str, bool, str)      # base_video, success, message
    log = Signal(str)

class MuxJobTask(QRunnable):
    def __init__(self, base_video: str, audio_track: str, audio_lang: str,
                 sub_track: str, sub_lang: str, out_path: str, stream_copy: bool = True):
        super().__init__()
        self.base_video = base_video
        self.audio_track = audio_track
        self.audio_lang = audio_lang
        self.sub_track = sub_track
        self.sub_lang = sub_lang
        self.out_path = out_path
        self.stream_copy = stream_copy
        self.signals = MuxTaskSignals()
        self.is_cancelled = False
        self.process = None

    @Slot()
    def run(self):
        self.signals.started.emit(self.base_video)
        ffmpeg_bin = get_binary_path("ffmpeg")

        cmd = [ffmpeg_bin, "-y", "-i", self.base_video]
        input_count = 1

        if self.audio_track:
            cmd.extend(["-i", self.audio_track])
            audio_input_idx = input_count
            input_count += 1
        else:
            audio_input_idx = None

        if self.sub_track:
            cmd.extend(["-i", self.sub_track])
            sub_input_idx = input_count
            input_count += 1
        else:
            sub_input_idx = None

        # Maps
        cmd.extend(["-map", "0:v"])
        if audio_input_idx is not None:
            cmd.extend(["-map", f"{audio_input_idx}:a"])
        else:
            cmd.extend(["-map", "0:a?"])

        if sub_input_idx is not None:
            cmd.extend(["-map", f"{sub_input_idx}:s"])
        else:
            cmd.extend(["-map", "0:s?"])

        # Codecs
        if self.stream_copy:
            cmd.extend(["-c", "copy"])

        # Metadata language tagging
        if self.audio_lang:
            cmd.extend(["-metadata:s:a:0", f"language={self.audio_lang}"])
        if self.sub_lang and (sub_input_idx is not None):
            cmd.extend(["-metadata:s:s:0", f"language={self.sub_lang}"])

        cmd.append(self.out_path)
        self.signals.log.emit(f">>> Running Mux: {' '.join(cmd)}")

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
                    self.signals.finished.emit(self.base_video, False, "Cancelled")
                    return

            self.process.wait()
            if self.process.returncode == 0:
                self.signals.finished.emit(self.base_video, True, "Muxed Successfully")
            else:
                self.signals.finished.emit(self.base_video, False, f"Exit code {self.process.returncode}")
        except Exception as e:
            self.signals.finished.emit(self.base_video, False, str(e))

    def cancel(self):
        self.is_cancelled = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
