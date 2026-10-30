"""Automated Hot Folder watchdog service for FFmpeg Batch AV Converter.

Monitors an input directory via Linux kernel inotify (using QFileSystemWatcher),
detects when new media files finish copying, and automatically dispatches batch jobs.
"""
import os

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal


class HotFolderWatchdog(QObject):
    file_detected = Signal(str)

    def __init__(self, watch_dir: str = "", parent: QObject | None = None):
        super().__init__(parent)
        self.watch_dir = watch_dir
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._on_dir_changed)
        self.known_files = set()
        self.pending_files = {}  # path: last_size
        self.is_active = False

        self.stabilize_timer = QTimer(self)
        self.stabilize_timer.setInterval(2000)
        self.stabilize_timer.timeout.connect(self._check_file_stabilization)

    def start_watching(self, directory: str):
        """Starts monitoring the specified directory."""
        if not os.path.isdir(directory):
            return False

        self.stop_watching()
        self.watch_dir = os.path.abspath(directory)
        self.known_files = set(os.listdir(self.watch_dir))
        self.watcher.addPath(self.watch_dir)
        self.is_active = True
        self.stabilize_timer.start()
        return True

    def stop_watching(self):
        """Stops the active folder monitor."""
        if self.watch_dir and self.watch_dir in self.watcher.directories():
            self.watcher.removePath(self.watch_dir)
        self.stabilize_timer.stop()
        self.pending_files.clear()
        self.is_active = False

    def _on_dir_changed(self, path: str):
        if not os.path.isdir(path):
            return
        current_files = set(os.listdir(path))
        new_files = current_files - self.known_files
        for nf in new_files:
            full = os.path.join(path, nf)
            if os.path.isfile(full):
                try:
                    self.pending_files[full] = os.path.getsize(full)
                except Exception:
                    pass
        self.known_files = current_files

    def _check_file_stabilization(self):
        """Ensures incoming files are fully copied before emitting."""
        stable = []
        for fpath, last_sz in list(self.pending_files.items()):
            if not os.path.exists(fpath):
                self.pending_files.pop(fpath, None)
                continue
            try:
                curr_sz = os.path.getsize(fpath)
                if curr_sz == last_sz and curr_sz > 0:
                    stable.append(fpath)
                else:
                    self.pending_files[fpath] = curr_sz
            except Exception:
                pass

        for sf in stable:
            self.pending_files.pop(sf, None)
            self.file_detected.emit(sf)
