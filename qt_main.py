# qt_main.py
# Main GUI application using PySide6 for FFmpeg Modular Batch GUI

import sys, os, signal, threading
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTableWidget, QTableWidgetItem,
    QComboBox, QLabel, QLineEdit, QProgressBar, QTextEdit, QMessageBox,
    QMenuBar, QMenu
)
from PySide6.QtCore import Qt, QTimer

from presets import load_presets
from file_manager import scan_folder, get_resolution, get_duration
from ffmpeg_runner import run_ffmpeg
from estimations import estimate_size_mb


class FFmpegQt(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FFmpeg Modular Batch GUI (Qt6)")
        self.resize(1200, 700)

        self.presets = load_presets()
        self.files = []
        self.current_folder = None
        self.output_dir = None
        self.active_processes = []
        self.is_running = False

        self._build_menu()
        self._build_ui()

    # ---------------- MENU ----------------

    def _build_menu(self):
        menubar = QMenuBar(self)
        file_menu = QMenu("File", self)
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)
        menubar.addMenu(file_menu)
        self.setMenuBar(menubar)

    # ---------------- UI ----------------

    def _build_ui(self):
        central = QWidget()
        main_layout = QVBoxLayout()

        # ---- Top buttons ----
        top = QHBoxLayout()
        self.btn_select = QPushButton("Select Folder")
        self.btn_refresh = QPushButton("Refresh")
        self.btn_start = QPushButton("Start Conversion")

        self.btn_select.clicked.connect(self.select_folder)
        self.btn_refresh.clicked.connect(self.refresh_files)
        self.btn_start.clicked.connect(self.toggle_start)

        top.addWidget(self.btn_select)
        top.addWidget(self.btn_refresh)
        top.addStretch()
        top.addWidget(self.btn_start)

        main_layout.addLayout(top)

        # ---- Filter + Output ----
        filt = QHBoxLayout()
        filt.addWidget(QLabel("Show only:"))

        self.ext_filter = QComboBox()
        self.ext_filter.addItems(["all", "ts", "mp4", "mkv", "avi", "mov"])
        self.ext_filter.currentTextChanged.connect(self.apply_filter)

        self.out_entry = QLineEdit()
        self.btn_browse = QPushButton("Browse")
        self.btn_browse.clicked.connect(self.browse_output)

        filt.addWidget(self.ext_filter)
        filt.addSpacing(20)
        filt.addWidget(QLabel("Output folder:"))
        filt.addWidget(self.out_entry)
        filt.addWidget(self.btn_browse)

        main_layout.addLayout(filt)

        # ---- Table ----
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Use", "Input", "Output", "Ext", "Resolution",
            "Out Res", "Out Fmt", "Cur Size MB", "Est Size MB"
        ])
        self.table.setSelectionMode(QTableWidget.NoSelection)
        main_layout.addWidget(self.table)

        # ---- Presets ----
        self.preset_box = QComboBox()
        for k, v in self.presets.items():
            self.preset_box.addItem(f"{v.get('category','Other')} :: {k}")
        self.preset_box.currentIndexChanged.connect(self.update_active_args)
        main_layout.addWidget(self.preset_box)

        # ---- Active args ----
        args_row = QHBoxLayout()
        args_row.addWidget(QLabel("Active FFmpeg Args:"))
        self.active_args = QLineEdit()
        self.active_args.setReadOnly(True)
        args_row.addWidget(self.active_args)
        main_layout.addLayout(args_row)

        # ---- Progress ----
        self.progress = QProgressBar()
        main_layout.addWidget(self.progress)

        # ---- Log ----
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        main_layout.addWidget(self.log)

        central.setLayout(main_layout)
        self.setCentralWidget(central)

        self.update_active_args()

    # ---------------- FILE LOADING ----------------

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if not folder:
            return

        self.current_folder = folder
        if not self.output_dir:
            self.output_dir = folder
            self.out_entry.setText(folder)

        self.load_files("all")

    def load_files(self, ext_filter):
        self.table.setRowCount(0)
        self.files.clear()

        paths = scan_folder(self.current_folder)
        for p in paths:
            base, ext = os.path.splitext(os.path.basename(p))
            ext_clean = ext.lstrip(".").lower()

            if ext_filter != "all" and ext_clean != ext_filter:
                continue

            try:
                res = get_resolution(p)
            except:
                res = "unknown"

            try:
                size = round(os.path.getsize(p)/(1024*1024), 2)
            except:
                size = "?"

            row = self.table.rowCount()
            self.table.insertRow(row)

            chk = QPushButton("✔")
            chk.clicked.connect(lambda _, r=row: self.toggle_row(r))

            values = [
                chk, base, base, ext, res,
                "Same", ext_clean, str(size), ""
            ]

            for col, v in enumerate(values):
                if isinstance(v, QPushButton):
                    self.table.setCellWidget(row, col, v)
                else:
                    self.table.setItem(row, col, QTableWidgetItem(str(v)))

            self.files.append({"path": p, "use": True})

    def apply_filter(self, ext):
        if self.current_folder:
            self.load_files(ext)

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_dir = folder
            self.out_entry.setText(folder)

    def refresh_files(self):
        if self.current_folder:
            self.load_files(self.ext_filter.currentText())
            self.log_line("🔄 File list refreshed")

    # ---------------- PRESET ----------------

    def update_active_args(self):
        text = self.preset_box.currentText()
        if not text:
            return

        key = text.split("::", 1)[1].strip()
        args = self.presets[key]["args"]
        self.active_args.setText(args)

        for i, f in enumerate(self.files):
            try:
                dur = get_duration(f["path"])
                est = estimate_size_mb(dur, args)
                self.table.setItem(i, 8, QTableWidgetItem(str(est)))
            except:
                pass

    # ---------------- START / STOP ----------------

    def toggle_start(self):
        if not self.is_running:
            self.start_conversion()
        else:
            self.stop_conversion()

    def start_conversion(self):
        self.is_running = True
        self.btn_start.setText("Stop Conversion")
        threading.Thread(target=self.start_worker, daemon=True).start()

    def stop_conversion(self):
        self.is_running = False
        self.btn_start.setText("Start Conversion")

        for p in self.active_processes:
            try:
                os.kill(p.pid, signal.SIGINT)
            except:
                pass

        self.active_processes.clear()
        self.log_line("⛔ Conversion stopped")

    def start_worker(self):
        self.active_processes.clear()
        selected = [f for f in self.files if f["use"]]

        total = len(selected)
        done = 0

        for f in selected:
            if not self.is_running:
                break

            p = run_ffmpeg(f["path"], self.output_dir, self.active_args.text())
            self.active_processes.append(p)
            p.wait()

            done += 1
            pct = int((done/total)*100)
            QTimer.singleShot(0, lambda v=pct: self.progress.setValue(v))

        self.is_running = False
        QTimer.singleShot(0, lambda: self.btn_start.setText("Start Conversion"))
        QTimer.singleShot(300, self.refresh_files)
        self.log_line("✅ Conversion finished")

    # ---------------- UTIL ----------------

    def toggle_row(self, row):
        self.files[row]["use"] = not self.files[row]["use"]

    def log_line(self, txt):
        self.log.append(txt)

    def closeEvent(self, event):
        running = [p for p in self.active_processes if p.poll() is None]
        if running:
            reply = QMessageBox.question(
                self, "FFmpeg Running",
                "Conversion still running. Kill and exit?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return

            for p in running:
                try:
                    os.kill(p.pid, signal.SIGINT)
                except:
                    pass

        event.accept()


# ---------------- APP ENTRY ----------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = FFmpegQt()
    win.show()
    sys.exit(app.exec())
