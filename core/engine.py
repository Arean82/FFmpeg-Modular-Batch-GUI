"""Queue execution engine for launching parallel FFmpeg processes."""
import os
import re
import shlex
import signal
import subprocess
import time

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from core.config_manager import get_binary_path


class WorkerSignals(QObject):
    started = Signal(str)                  # file_path
    progress = Signal(str, float)          # file_path, percent (0-100)
    log = Signal(str)                      # log line
    finished = Signal(str, bool, str)      # file_path, success, error_msg

class FFmpegTask(QRunnable):
    def __init__(
        self,
        file_path: str,
        output_path: str,
        params: str,
        total_duration: float,
        two_pass: bool = False,
        pre_input: str = "",
        overwrite: bool = True,
        cpu_priority: str = "Normal"
    ):
        super().__init__()
        self.file_path = file_path
        self.output_path = output_path
        self.params = params
        self.total_duration = total_duration
        self.two_pass = two_pass
        self.pre_input = pre_input.strip() if pre_input else ""
        self.overwrite = overwrite
        self.cpu_priority = cpu_priority
        self.signals = WorkerSignals()
        self.is_cancelled = False
        self.is_paused = False
        self.process = None

    def _apply_priority(self):
        """Sets Linux nice level on the subprocess if possible."""
        if not self.process:
            return
        try:
            nice_levels = {
                "High": -5,
                "Normal": 0,
                "Below Normal": 5,
                "Idle (Low)": 15
            }
            target_nice = nice_levels.get(self.cpu_priority, 0)
            if target_nice != 0:
                os.setpriority(os.PRIO_PROCESS, self.process.pid, target_nice)
        except Exception:
            pass

    def pause(self):
        """Pause worker process with SIGSTOP."""
        self.is_paused = True
        if self.process and self.process.poll() is None:
            try:
                os.kill(self.process.pid, signal.SIGSTOP)
            except Exception:
                pass

    def resume(self):
        """Resume worker process with SIGCONT."""
        self.is_paused = False
        if self.process and self.process.poll() is None:
            try:
                os.kill(self.process.pid, signal.SIGCONT)
            except Exception:
                pass

    @Slot()
    def run(self):
        self.signals.started.emit(self.file_path)
        ffmpeg_bin = get_binary_path("ffmpeg")
        parsed_params = shlex.split(self.params) if self.params else []
        parsed_pre = shlex.split(self.pre_input) if self.pre_input else []
        overwrite_flag = "-y" if self.overwrite else "-n"
        time_pattern = re.compile(r"out_time_ms=(\d+)")

        try:
            # Check if two-pass is active
            if self.two_pass:
                self.signals.log.emit("[Two-Pass] Starting Pass 1 analysis...")
                pass1_cmd = [ffmpeg_bin, overwrite_flag]
                if parsed_pre:
                    pass1_cmd.extend(parsed_pre)
                pass1_cmd.extend(["-i", self.file_path])
                pass1_cmd.extend(parsed_params)
                pass1_cmd.extend(["-pass", "1", "-an", "-f", "null", "-progress", "pipe:1", "/dev/null"])

                self.process = subprocess.Popen(
                    pass1_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                self._apply_priority()

                for line in self.process.stdout:
                    while self.is_paused and not self.is_cancelled:
                        time.sleep(0.2)
                    if self.is_cancelled:
                        self.process.terminate()
                        self.signals.finished.emit(self.file_path, False, "Cancelled")
                        self._clean_pass_logs()
                        return
                    line = line.strip()
                    if not line:
                        continue
                    m = time_pattern.search(line)
                    if m and self.total_duration > 0:
                        out_sec = int(m.group(1)) / 1000000.0
                        percent = min(50.0, (out_sec / self.total_duration) * 50.0)
                        self.signals.progress.emit(self.file_path, percent)
                    elif not line.startswith("out_time") and not line.startswith("frame="):
                        self.signals.log.emit(f"[Pass 1] {line}")

                self.process.wait()
                if self.process.returncode != 0:
                    self._clean_pass_logs()
                    self.signals.finished.emit(self.file_path, False, f"Pass 1 failed (exit code {self.process.returncode})")
                    return

                # Pass 2: encode to output
                self.signals.log.emit("[Two-Pass] Pass 1 complete. Starting Pass 2 encoding...")
                pass2_cmd = [ffmpeg_bin, overwrite_flag]
                if parsed_pre:
                    pass2_cmd.extend(parsed_pre)
                pass2_cmd.extend(["-i", self.file_path])
                pass2_cmd.extend(parsed_params)
                pass2_cmd.extend(["-pass", "2", "-progress", "pipe:1", self.output_path])

                self.process = subprocess.Popen(
                    pass2_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                self._apply_priority()

                for line in self.process.stdout:
                    while self.is_paused and not self.is_cancelled:
                        time.sleep(0.2)
                    if self.is_cancelled:
                        self.process.terminate()
                        self.signals.finished.emit(self.file_path, False, "Cancelled")
                        self._clean_pass_logs()
                        return
                    line = line.strip()
                    if not line:
                        continue
                    m = time_pattern.search(line)
                    if m and self.total_duration > 0:
                        out_sec = int(m.group(1)) / 1000000.0
                        percent = min(100.0, 50.0 + ((out_sec / self.total_duration) * 50.0))
                        self.signals.progress.emit(self.file_path, percent)
                    elif "progress=end" in line:
                        self.signals.progress.emit(self.file_path, 100.0)
                    elif not line.startswith("out_time") and not line.startswith("frame="):
                        self.signals.log.emit(f"[Pass 2] {line}")

                self.process.wait()
                self._clean_pass_logs()
                if self.process.returncode == 0:
                    self.signals.finished.emit(self.file_path, True, "")
                else:
                    self.signals.finished.emit(self.file_path, False, f"Pass 2 failed (exit code {self.process.returncode})")
                return

            # Single pass mode
            cmd = [ffmpeg_bin, overwrite_flag]
            if parsed_pre:
                cmd.extend(parsed_pre)
            cmd.extend(["-i", self.file_path])
            cmd.extend(parsed_params)
            cmd.extend(["-progress", "pipe:1", self.output_path])

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            self._apply_priority()

            for line in self.process.stdout:
                while self.is_paused and not self.is_cancelled:
                    time.sleep(0.2)
                if self.is_cancelled:
                    self.process.terminate()
                    self.signals.finished.emit(self.file_path, False, "Cancelled")
                    return

                line = line.strip()
                if not line:
                    continue

                match = time_pattern.search(line)
                if match and self.total_duration > 0:
                    out_micro = int(match.group(1))
                    out_sec = out_micro / 1000000.0
                    percent = min(100.0, (out_sec / self.total_duration) * 100.0)
                    self.signals.progress.emit(self.file_path, percent)
                elif "progress=end" in line:
                    self.signals.progress.emit(self.file_path, 100.0)
                elif not line.startswith("out_time") and not line.startswith("frame="):
                    self.signals.log.emit(line)

            self.process.wait()
            if self.process.returncode == 0:
                self.signals.finished.emit(self.file_path, True, "")
            else:
                self.signals.finished.emit(self.file_path, False, f"Exit code {self.process.returncode}")
        except Exception as e:
            self._clean_pass_logs()
            self.signals.finished.emit(self.file_path, False, str(e))

    def _clean_pass_logs(self):
        """Remove any ffmpeg2pass-*.log files created during two-pass encoding."""
        try:
            for fname in os.listdir("."):
                if fname.startswith("ffmpeg2pass") and fname.endswith(".log"):
                    os.remove(fname)
        except Exception:
            pass

    def cancel(self):
        self.is_cancelled = True
        self.is_paused = False
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass
