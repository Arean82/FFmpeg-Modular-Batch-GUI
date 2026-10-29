"""Main application entry point for native Linux FFmpeg Batch AV Converter."""
import sys
import os

# Suppress AT-SPI / dbind accessibility warnings when running under non-root / sudo environments
os.environ.setdefault("NO_AT_SPI", "1")
os.environ.setdefault("QT_ACCESSIBILITY", "0")

import subprocess
import shlex
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QTableWidgetItem,
    QProgressBar, QMessageBox, QMenu, QDialog, QDialogButtonBox
)
from PySide6.QtGui import QAction, QKeySequence, QIcon, QShortcut
from PySide6.QtCore import QFile, QIODevice, Qt, QThreadPool

try:
    from PySide6.QtUiTools import QUiLoader
    HAS_UILOADER = True
except ImportError:
    HAS_UILOADER = False

from core.probe import probe_file
from core.engine import FFmpegTask
from core.tokens import substitute_tokens
from core.readme_viewer import ReadmeViewerDialog
from core.presets import load_presets, save_presets
from core.estimations import estimate_size_mb
from core.url_engine import UrlStreamTask
from core.mux_engine import MuxJobTask
from core.subs_engine import SubtitleTask
from core.concat_engine import join_files
from core.crop_engine import detect_black_bars
from core.config_manager import get_config, save_config, get_binary_path
from core.theme_manager import ThemeManager

def load_ui_widget(ui_relative_path: str, parent=None):
    """Loads a .ui file using QUiLoader."""
    full_path = os.path.join(os.path.dirname(__file__), ui_relative_path)
    ui_file = QFile(full_path)
    if not ui_file.open(QIODevice.ReadOnly):
        raise RuntimeError(f"Cannot open {full_path}: {ui_file.errorString()}")
    loader = QUiLoader()
    widget = loader.load(ui_file, parent)
    ui_file.close()
    return widget

class FFBatchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.theme_manager = ThemeManager()
        self.threadpool = QThreadPool()
        self.queue_items = []
        self.active_tasks = []

        self.load_ui()
        self.build_menu_bar()
        self.setup_queue_table()
        self.connect_signals()

    def load_ui(self):
        """Loads front-end layout strictly from the .ui file."""
        self.ui = load_ui_widget("ui/main_window.ui")
        title = self.ui.windowTitle()
        sz = self.ui.size()
        self.setCentralWidget(self.ui.takeCentralWidget())
        self.setWindowTitle(title)
        self.resize(sz)

        # Set Window Icon from ported assets
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "app_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Populate formats
        self.ui.comboOutputFormat.addItems(["mp4", "mkv", "avi", "mov", "webm", "mp3", "m4a", "flac", "wav"])
        
        # Default sample watermark path
        default_wm = os.path.join(os.path.dirname(__file__), "assets", "sample_watermark.png")
        if os.path.exists(default_wm):
            self.ui.txtWatermarkFile.setText(default_wm)
        
        # Load presets
        self.presets = load_presets()
        self.refresh_presets_combo()

    def refresh_presets_combo(self):
        """Populate preset dropdown from presets dictionary."""
        self.ui.comboPresets.blockSignals(True)
        self.ui.comboPresets.clear()
        for name, data in self.presets.items():
            cat = data.get("category", "General")
            self.ui.comboPresets.addItem(f"[{cat}] {name}", userData=name)
        self.ui.comboPresets.blockSignals(False)
        if self.ui.comboPresets.count() > 0:
            self.on_preset_selected(0)

    def build_menu_bar(self):
        """Builds menu bar strictly programmatically in Python."""
        menubar = self.menuBar()

        # 1. File Menu
        file_menu = menubar.addMenu("&File")
        
        # Readme / Help (F1) at the top of File menu (matching Video-Analyse---Rename pattern)
        readme_action = QAction("📄 Readme / &Help", self)
        readme_action.setShortcut(QKeySequence("F1"))
        readme_action.triggered.connect(self.open_readme)
        file_menu.addAction(readme_action)

        file_menu.addSeparator()

        act_add_files = QAction("&Add Files...", self)
        act_add_files.setShortcut(QKeySequence.Open)
        act_add_files.triggered.connect(self.on_add_files)
        file_menu.addAction(act_add_files)

        act_add_folder = QAction("Add &Folder...", self)
        act_add_folder.triggered.connect(self.on_add_folder)
        file_menu.addAction(act_add_folder)

        file_menu.addSeparator()

        act_exit = QAction("E&xit", self)
        act_exit.setShortcut(QKeySequence.Quit)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # 2. Queue Menu
        queue_menu = menubar.addMenu("&Queue")
        
        act_start = QAction("&Start Processing", self)
        act_start.setShortcut("Ctrl+R")
        act_start.triggered.connect(self.start_processing)
        queue_menu.addAction(act_start)

        act_stop = QAction("S&top Processing", self)
        act_stop.triggered.connect(self.stop_processing)
        queue_menu.addAction(act_stop)

        queue_menu.addSeparator()

        act_remove = QAction("&Remove Selected", self)
        act_remove.setShortcut(QKeySequence.Delete)
        act_remove.triggered.connect(self.on_remove_selected)
        queue_menu.addAction(act_remove)

        act_clear = QAction("&Clear All", self)
        act_clear.triggered.connect(self.on_clear_queue)
        queue_menu.addAction(act_clear)

        act_clean_err = QAction("Remove &Error Rows", self)
        act_clean_err.triggered.connect(self.on_clean_errors)
        queue_menu.addAction(act_clean_err)

        # 3. Presets Menu
        preset_menu = menubar.addMenu("&Presets")
        act_manage_presets = QAction("&Presets Manager...", self)
        act_manage_presets.triggered.connect(self.open_presets_dialog)
        preset_menu.addAction(act_manage_presets)

        act_multi_presets = QAction("&Multiple Presets Batch Run...", self)
        act_multi_presets.triggered.connect(self.open_multi_presets_dialog)
        preset_menu.addAction(act_multi_presets)

        act_insert_var = QAction("&Insert Variable...", self)
        act_insert_var.triggered.connect(self.open_token_builder_dialog)
        preset_menu.addAction(act_insert_var)

        # 4. Tools Menu
        tools_menu = menubar.addMenu("&Tools")
        
        act_try_preset = QAction("▶ &Try Current Preset (10s)", self)
        act_try_preset.triggered.connect(self.on_try_preset)
        tools_menu.addAction(act_try_preset)

        act_show_cmd = QAction("&Terminal Command Preview", self)
        act_show_cmd.triggered.connect(self.on_show_console_cmd)
        tools_menu.addAction(act_show_cmd)

        tools_menu.addSeparator()

        act_trim = QAction("&Trim / Cut Video...", self)
        act_trim.triggered.connect(self.open_trim_dialog)
        tools_menu.addAction(act_trim)

        act_join = QAction("&Join / Concatenate Files...", self)
        act_join.triggered.connect(self.open_join_dialog)
        tools_menu.addAction(act_join)

        act_crop = QAction("&Crop & Black Bars Detection...", self)
        act_crop.triggered.connect(self.open_crop_dialog)
        tools_menu.addAction(act_crop)

        act_watermark = QAction("&Watermark / Logo Overlay...", self)
        act_watermark.triggered.connect(self.open_watermark_dialog)
        tools_menu.addAction(act_watermark)

        act_silence = QAction("&Silence Detector & Remover...", self)
        act_silence.triggered.connect(self.open_silence_dialog)
        tools_menu.addAction(act_silence)

        act_trailer = QAction("&Generate Video Teaser / Trailer...", self)
        act_trailer.triggered.connect(self.open_trailer_dialog)
        tools_menu.addAction(act_trailer)

        act_img_video = QAction("&Create Video from Still Images...", self)
        act_img_video.triggered.connect(self.open_image_to_video_dialog)
        tools_menu.addAction(act_img_video)

        act_media_info = QAction("&Inspect Media Streams (MediaInfo)...", self)
        act_media_info.setShortcut("Ctrl+I")
        act_media_info.triggered.connect(self.open_media_info_dialog)
        tools_menu.addAction(act_media_info)

        act_exclusions = QAction("&File Types Exclusion Filter...", self)
        act_exclusions.triggered.connect(self.open_exclusions_dialog)
        tools_menu.addAction(act_exclusions)

        act_target_size = QAction("&Two-Pass Target Size Calculator...", self)
        act_target_size.setShortcut("Ctrl+Shift+Z")
        act_target_size.triggered.connect(self.open_target_size_dialog)
        tools_menu.addAction(act_target_size)

        act_stream_mapping = QAction("&Stream Mapping / Muxing...", self)
        act_stream_mapping.triggered.connect(self.open_stream_mapping_dialog)
        tools_menu.addAction(act_stream_mapping)

        tools_menu.addSeparator()

        act_settings = QAction("&Settings...", self)
        act_settings.setShortcut("Ctrl+,")
        act_settings.triggered.connect(self.open_settings_dialog)
        tools_menu.addAction(act_settings)

        # 5. Theme Menu (Replicated from Video-Analyse---Rename)
        theme_menu = menubar.addMenu("&Theme 🎨")
        self.mode_actions = {}
        self.material_actions = {}

        # 1. Brightness Mode Actions
        self.light_mode_action = QAction("☀️ Light", self)
        self.light_mode_action.setCheckable(True)
        self.light_mode_action.triggered.connect(lambda: self.set_selected_mode("light"))
        theme_menu.addAction(self.light_mode_action)
        self.mode_actions["light"] = self.light_mode_action

        self.dark_mode_action = QAction("🌙 Dark", self)
        self.dark_mode_action.setCheckable(True)
        self.dark_mode_action.triggered.connect(lambda: self.set_selected_mode("dark"))
        theme_menu.addAction(self.dark_mode_action)
        self.mode_actions["dark"] = self.dark_mode_action

        self.system_mode_action = QAction("💻 System Default", self)
        self.system_mode_action.setCheckable(True)
        self.system_mode_action.triggered.connect(lambda: self.set_selected_mode("system"))
        theme_menu.addAction(self.system_mode_action)
        self.mode_actions["system"] = self.system_mode_action

        theme_menu.addSeparator()

        # 2. Material Themes Submenu
        material_menu = theme_menu.addMenu("🎨 Material Themes")

        default_action = QAction("Generic / Default (Built-in QSS)", self)
        default_action.setCheckable(True)
        default_action.triggered.connect(lambda: self.set_selected_material("default"))
        material_menu.addAction(default_action)
        self.material_actions["default"] = default_action
        material_menu.addSeparator()

        if hasattr(self, 'theme_manager'):
            material_themes = self.theme_manager.get_all_material_themes()
            if material_themes:
                color_families = {}
                for t in material_themes:
                    clean = t.replace('.xml', '')
                    parts = clean.split('_', 1)
                    var = parts[0]
                    color = parts[1] if len(parts) > 1 else clean
                    if color not in color_families:
                        color_families[color] = []
                    color_families[color].append((var, t))

                for color, variants in sorted(color_families.items()):
                    disp_name = color.replace('_', ' ').title()
                    action = QAction(f"Material {disp_name}", self)
                    action.setCheckable(True)
                    action.setData(color)
                    action.triggered.connect(lambda checked=False, col=color: self.set_selected_material(col))
                    material_menu.addAction(action)
                    self.material_actions[color] = action
            else:
                info_action = QAction("(qt-material not installed - using Default)", self)
                info_action.setEnabled(False)
                material_menu.addAction(info_action)

        theme_menu.addSeparator()

        info_toggle_label = QAction("🔄 Toggle Light/Dark (Ctrl+Shift+T)", self)
        info_toggle_label.setEnabled(False)
        theme_menu.addAction(info_toggle_label)

        self.toggle_shortcut = QShortcut(QKeySequence("Ctrl+Shift+T"), self)
        self.toggle_shortcut.activated.connect(self.toggle_theme)

        self._update_theme_menu_checks()

    def _update_theme_menu_checks(self):
        """Update the checkmarks in theme menu for both mode and material selection."""
        if hasattr(self, 'theme_manager'):
            current_mode = self.theme_manager.get_theme_mode()
            for mode, action in self.mode_actions.items():
                action.setChecked(mode == current_mode)

            current_mat = self.theme_manager.get_material_theme()
            cur_color = current_mat.replace(".xml", "").replace("dark_", "").replace("light_", "")
            for mat_key, action in self.material_actions.items():
                if current_mat == "default":
                    action.setChecked(mat_key == "default")
                else:
                    action.setChecked(mat_key == cur_color or mat_key == current_mat)

    def set_selected_mode(self, mode: str):
        if hasattr(self, 'theme_manager'):
            self.theme_manager.set_theme_mode(QApplication.instance(), mode)
            self._update_theme_menu_checks()

    def set_selected_material(self, material_name: str):
        if hasattr(self, 'theme_manager'):
            self.theme_manager.set_material_theme(QApplication.instance(), material_name)
            self._update_theme_menu_checks()

    def toggle_theme(self):
        if hasattr(self, 'theme_manager'):
            self.theme_manager.toggle_theme(QApplication.instance())
            self._update_theme_menu_checks()

        # 6. Help Menu
        help_menu = menubar.addMenu("&Help")
        
        act_help_readme = QAction("Documentation (README)", self)
        act_help_readme.setShortcut(QKeySequence.HelpContents)
        act_help_readme.triggered.connect(self.open_readme)
        help_menu.addAction(act_help_readme)

        help_menu.addSeparator()

        act_about = QAction("&About", self)
        act_about.triggered.connect(self.show_about)
        help_menu.addAction(act_about)

    def setup_queue_table(self):
        table = self.ui.tableQueue
        table.horizontalHeader().setStretchLastSection(True)
        table.cellDoubleClicked.connect(lambda row, col: self.open_media_info_dialog())

    def connect_signals(self):
        # Queue toolbar buttons
        self.ui.btnAddFiles.clicked.connect(self.on_add_files)
        self.ui.btnAddFolder.clicked.connect(self.on_add_folder)
        self.ui.btnRemoveSelected.clicked.connect(self.on_remove_selected)
        self.ui.btnClearQueue.clicked.connect(self.on_clear_queue)
        self.ui.btnCleanErrors.clicked.connect(self.on_clean_errors)
        self.ui.txtFilterQueue.textChanged.connect(self.on_filter_queue)

        # Quick tools
        self.ui.btnTryPreset.clicked.connect(self.on_try_preset)
        self.ui.btnShowConsole.clicked.connect(self.on_show_console_cmd)
        self.ui.btnTrimTool.clicked.connect(self.open_trim_dialog)
        self.ui.btnJoinTool.clicked.connect(self.open_join_dialog)
        self.ui.btnCropTool.clicked.connect(self.open_crop_dialog)
        self.ui.btnInsertVariable.clicked.connect(self.open_token_builder_dialog)

        # Parameters text change updates size estimations
        self.ui.txtParameters.textChanged.connect(self.update_estimated_sizes)

        # Output folder options
        self.ui.radSourceFolder.toggled.connect(self.on_dest_toggle)
        self.ui.radCustomFolder.toggled.connect(self.on_dest_toggle)
        self.ui.btnBrowseOutputDir.clicked.connect(self.on_browse_output)
        
        # Presets combo
        self.ui.comboPresets.currentIndexChanged.connect(self.on_preset_selected)
        self.ui.btnSavePreset.clicked.connect(self.open_presets_dialog)

        # Watermark UI controls
        self.ui.chkEnableWatermark.toggled.connect(self.on_watermark_toggle)
        self.ui.btnBrowseWatermark.clicked.connect(self.on_browse_watermark)
        
        # URL / Streams (Tab 4) controls
        self.ui.btnAddUrl.clicked.connect(self.on_add_url)
        self.ui.btnImportUrls.clicked.connect(self.on_import_urls)
        self.ui.btnClearUrls.clicked.connect(self.on_clear_urls)
        self.ui.btnStartUrlDownloads.clicked.connect(self.start_url_downloads)
        self.ui.tableUrls.horizontalHeader().setStretchLastSection(True)

        # Stream Multiplex (Tab 2) controls
        self.ui.btnAddMuxJob.clicked.connect(self.on_add_mux_job)
        self.ui.btnRemoveMuxJob.clicked.connect(self.on_remove_mux_job)
        self.ui.btnStartMux.clicked.connect(self.start_mux_jobs)
        self.ui.tableMux.horizontalHeader().setStretchLastSection(True)
        self.mux_jobs = []

        # Subtitles (Tab 3) controls
        self.ui.btnAddSubPair.clicked.connect(self.on_add_sub_pair)
        self.ui.btnAutoMatchSubs.clicked.connect(self.on_auto_match_subs)
        self.ui.btnClearSubs.clicked.connect(self.on_clear_subs)
        self.ui.btnStartSubs.clicked.connect(self.start_subs_processing)
        self.ui.tableSubs.horizontalHeader().setStretchLastSection(True)
        self.sub_jobs = []

        # Start / Stop
        self.ui.btnStart.clicked.connect(self.start_processing)
        self.ui.btnStop.clicked.connect(self.stop_processing)

    def on_watermark_toggle(self, enabled: bool):
        self.ui.comboWatermarkPos.setEnabled(enabled)
        self.ui.txtWatermarkFile.setEnabled(enabled)
        self.ui.btnBrowseWatermark.setEnabled(enabled)
        self.ui.spinWatermarkMargin.setEnabled(enabled)

    def on_browse_watermark(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Logo/Watermark Image", "", "Images (*.png *.jpg *.jpeg *.svg)"
        )
        if path:
            self.ui.txtWatermarkFile.setText(path)

    # URL / Stream Downloading (Tab 4)
    def on_add_url(self):
        url = self.ui.txtStreamUrl.text().strip()
        if not url:
            return
        self.add_url_to_table(url)
        self.ui.txtStreamUrl.clear()

    def on_import_urls(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import URLs from File", "", "Text Files (*.txt *.m3u *.m3u8);;All Files (*)")
        if file_path:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    u = line.strip()
                    if u and (u.startswith("http://") or u.startswith("https://") or u.startswith("rtsp://")):
                        self.add_url_to_table(u)

    def add_url_to_table(self, url: str):
        table = self.ui.tableUrls
        row = table.rowCount()
        table.insertRow(row)

        table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        table.setItem(row, 1, QTableWidgetItem(url))
        
        # Derive output filename
        clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', url.split('?')[0].split('/')[-1]) or f"stream_{row+1}"
        if not clean_name.endswith(".mp4"):
            clean_name += ".mp4"
        table.setItem(row, 2, QTableWidgetItem(clean_name))

        bar = QProgressBar()
        bar.setValue(0)
        table.setCellWidget(row, 3, bar)

        table.setItem(row, 4, QTableWidgetItem("Queued"))

    def on_clear_urls(self):
        self.ui.tableUrls.setRowCount(0)

    def start_url_downloads(self):
        table = self.ui.tableUrls
        if table.rowCount() == 0:
            QMessageBox.information(self, "No URLs", "Please add at least one stream URL first.")
            return

        dest_dir = self.ui.txtOutputDir.text().strip()
        if not dest_dir or not os.path.isdir(dest_dir):
            dest_dir = os.path.expanduser("~/Downloads")

        self.ui.btnStartUrlDownloads.setEnabled(False)
        self.ui.txtLog.appendPlainText(">>> Starting Batch URL Stream Downloads...")

        for r in range(table.rowCount()):
            url = table.item(r, 1).text()
            filename = table.item(r, 2).text()
            out_path = os.path.join(dest_dir, filename)

            task = UrlStreamTask(url, out_path)
            task.signals.progress.connect(self.on_url_progress)
            task.signals.finished.connect(self.on_url_finished)
            task.signals.log.connect(self.on_task_log)
            self.threadpool.start(task)

    def on_url_progress(self, url: str, percent: float):
        table = self.ui.tableUrls
        for r in range(table.rowCount()):
            if table.item(r, 1).text() == url:
                bar = table.cellWidget(r, 3)
                if bar:
                    bar.setValue(int(percent))
                st = table.item(r, 4)
                if st:
                    st.setText("Downloading...")
                break

    def on_url_finished(self, url: str, success: bool, msg: str):
        table = self.ui.tableUrls
        for r in range(table.rowCount()):
            if table.item(r, 1).text() == url:
                bar = table.cellWidget(r, 3)
                st = table.item(r, 4)
                if success:
                    if bar:
                        bar.setValue(100)
                    if st:
                        st.setText("Finished")
                else:
                    if st:
                        st.setText(f"Failed: {msg}")
                break

        # Check if all downloads finished
        all_done = True
        for r in range(table.rowCount()):
            st = table.item(r, 4)
            if st and ("downloading" in st.text().lower() or "queued" in st.text().lower()):
                all_done = False
                break
        if all_done:
            self.ui.btnStartUrlDownloads.setEnabled(True)
            self.ui.txtLog.appendPlainText(">>> Batch URL Downloads Finished.")

    # Stream Multiplexing (Tab 2)
    def on_add_mux_job(self):
        dialog = load_ui_widget("ui/add_mux_job_dialog.ui", self)

        def browse_file(target_line, title, filter_str):
            f, _ = QFileDialog.getOpenFileName(dialog, title, "", filter_str)
            if f:
                target_line.setText(f)

        dialog.btnBrowseBaseVideo.clicked.connect(lambda: browse_file(dialog.txtBaseVideo, "Select Base Video", "Videos (*.mp4 *.mkv *.avi *.mov *.ts)"))
        dialog.btnBrowseAudioTrack.clicked.connect(lambda: browse_file(dialog.txtAudioTrack, "Select Audio Track", "Audio Files (*.m4a *.aac *.ac3 *.mp3 *.flac *.wav)"))
        dialog.btnBrowseSubTrack.clicked.connect(lambda: browse_file(dialog.txtSubTrack, "Select Subtitle File", "Subtitles (*.srt *.ass *.vtt *.sub)"))

        def accept_job():
            base_vid = dialog.txtBaseVideo.text().strip()
            if not base_vid or not os.path.exists(base_vid):
                QMessageBox.warning(dialog, "Missing File", "Please select a valid base video file.")
                return

            audio_file = dialog.txtAudioTrack.text().strip()
            audio_lang = dialog.comboAudioLang.currentText()
            sub_file = dialog.txtSubTrack.text().strip()
            sub_lang = dialog.comboSubLang.currentText()
            container = dialog.comboMuxContainer.currentText()
            stream_copy = dialog.chkStreamCopy.isChecked()

            src_dir, src_filename = os.path.split(base_vid)
            base_name, _ = os.path.splitext(src_filename)
            out_file = os.path.join(src_dir, f"{base_name}_muxed.{container}")

            job = {
                "base_video": base_vid,
                "audio_track": audio_file,
                "audio_lang": audio_lang,
                "sub_track": sub_file,
                "sub_lang": sub_lang,
                "out_path": out_file,
                "stream_copy": stream_copy
            }
            self.mux_jobs.append(job)

            table = self.ui.tableMux
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            table.setItem(row, 1, QTableWidgetItem(os.path.basename(base_vid)))
            table.setItem(row, 2, QTableWidgetItem(os.path.basename(audio_file) if audio_file else "None"))
            table.setItem(row, 3, QTableWidgetItem(os.path.basename(sub_file) if sub_file else "None"))
            table.setItem(row, 4, QTableWidgetItem(audio_lang if audio_file else "-"))
            table.setItem(row, 5, QTableWidgetItem(sub_lang if sub_file else "-"))
            table.setItem(row, 6, QTableWidgetItem("Ready"))
            dialog.accept()

        dialog.muxDialogButtonBox.accepted.connect(accept_job)
        dialog.muxDialogButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def on_remove_mux_job(self):
        table = self.ui.tableMux
        selected = table.selectedIndexes()
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        for r in rows:
            table.removeRow(r)
            if r < len(self.mux_jobs):
                del self.mux_jobs[r]

    def start_mux_jobs(self):
        if not self.mux_jobs:
            QMessageBox.information(self, "No Jobs", "Please add at least one multiplex job first.")
            return

        self.ui.btnStartMux.setEnabled(False)
        self.ui.txtLog.appendPlainText(">>> Starting Multiplex Jobs...")

        for idx, job in enumerate(self.mux_jobs):
            task = MuxJobTask(
                job["base_video"],
                job["audio_track"],
                job["audio_lang"],
                job["sub_track"],
                job["sub_lang"],
                job["out_path"],
                job["stream_copy"]
            )
            task.signals.finished.connect(self.on_mux_finished)
            task.signals.log.connect(self.on_task_log)
            self.threadpool.start(task)

    def on_mux_finished(self, base_video: str, success: bool, msg: str):
        table = self.ui.tableMux
        for r in range(table.rowCount()):
            if r < len(self.mux_jobs) and self.mux_jobs[r]["base_video"] == base_video:
                item = table.item(r, 6)
                if item:
                    item.setText("Completed" if success else f"Failed: {msg}")
                break

        # Check if all mux jobs finished
        all_done = True
        for r in range(table.rowCount()):
            st = table.item(r, 6)
            if st and st.text() == "Ready":
                all_done = False
                break
        if all_done:
            self.ui.btnStartMux.setEnabled(True)
            self.ui.txtLog.appendPlainText(">>> All Multiplex Jobs Finished.")

    # Subtitle Processing (Tab 3)
    def on_add_sub_pair(self):
        vid, _ = QFileDialog.getOpenFileName(self, "Select Video File", "", "Videos (*.mp4 *.mkv *.avi *.mov *.ts)")
        if not vid:
            return
        sub, _ = QFileDialog.getOpenFileName(self, "Select Matching Subtitle File", os.path.dirname(vid), "Subtitles (*.srt *.ass *.vtt *.sub)")
        if not sub:
            return
        self.add_sub_job_to_table(vid, sub)

    def on_auto_match_subs(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder Containing Videos and Subtitles")
        if not folder:
            return
        found = 0
        for root, _, files in os.walk(folder):
            video_map = {}
            sub_map = {}
            for f in files:
                base, ext = os.path.splitext(f)
                ext_clean = ext.lower().lstrip(".")
                full = os.path.join(root, f)
                if ext_clean in ["mp4", "mkv", "avi", "mov", "ts"]:
                    video_map[base] = full
                elif ext_clean in ["srt", "ass", "vtt"]:
                    sub_map[base] = full
            
            for base, vid_path in video_map.items():
                if base in sub_map:
                    self.add_sub_job_to_table(vid_path, sub_map[base])
                    found += 1
        QMessageBox.information(self, "Auto-Match Results", f"Auto-matched {found} video and subtitle pairs.")

    def add_sub_job_to_table(self, vid_path: str, sub_path: str):
        is_burn = self.ui.radBurnSubs.isChecked()
        mode_str = "Burn-in (Hardcode)" if is_burn else "Embed Soft"
        lang = self.ui.comboSubLanguage.currentText()
        if "(" in lang and ")" in lang:
            lang_code = lang[lang.find("(") + 1 : lang.rfind(")")]
        else:
            lang_code = "eng"

        job = {
            "video_path": vid_path,
            "sub_path": sub_path,
            "mode": "burn" if is_burn else "embed",
            "lang": lang_code,
            "font_name": self.ui.txtSubFont.text().strip() or "Sans",
            "font_size": self.ui.spinSubFontSize.value()
        }
        self.sub_jobs.append(job)

        table = self.ui.tableSubs
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        table.setItem(row, 1, QTableWidgetItem(os.path.basename(vid_path)))
        table.setItem(row, 2, QTableWidgetItem(os.path.basename(sub_path)))
        table.setItem(row, 3, QTableWidgetItem(mode_str))
        table.setItem(row, 4, QTableWidgetItem(lang_code))
        table.setItem(row, 5, QTableWidgetItem("Ready"))

    def on_clear_subs(self):
        self.ui.tableSubs.setRowCount(0)
        self.sub_jobs.clear()

    def start_subs_processing(self):
        if not self.sub_jobs:
            QMessageBox.information(self, "No Jobs", "Please add at least one subtitle pair first.")
            return

        self.ui.btnStartSubs.setEnabled(False)
        self.ui.txtLog.appendPlainText(">>> Starting Subtitle Processing Jobs...")

        dest_dir = self.ui.txtOutputDir.text().strip()
        custom_dest = self.ui.radCustomFolder.isChecked()

        for idx, job in enumerate(self.sub_jobs):
            src_path = job["video_path"]
            src_dir, src_file = os.path.split(src_path)
            base_name, ext = os.path.splitext(src_file)

            if custom_dest and dest_dir and os.path.isdir(dest_dir):
                target_folder = dest_dir
            else:
                target_folder = src_dir

            target_ext = ".mkv" if job["mode"] == "embed" else ext
            out_path = os.path.join(target_folder, f"{base_name}_subbed{target_ext}")

            task = SubtitleTask(
                job["video_path"],
                job["sub_path"],
                job["mode"],
                job["font_name"],
                job["font_size"],
                job["lang"],
                out_path
            )
            task.signals.finished.connect(self.on_subs_finished)
            task.signals.log.connect(self.on_task_log)
            self.threadpool.start(task)

    def on_subs_finished(self, video_path: str, success: bool, msg: str):
        table = self.ui.tableSubs
        for r in range(table.rowCount()):
            if r < len(self.sub_jobs) and self.sub_jobs[r]["video_path"] == video_path:
                item = table.item(r, 5)
                if item:
                    item.setText("Completed" if success else f"Failed: {msg}")
                break

        all_done = True
        for r in range(table.rowCount()):
            st = table.item(r, 5)
            if st and st.text() == "Ready":
                all_done = False
                break
        if all_done:
            self.ui.btnStartSubs.setEnabled(True)
            self.ui.txtLog.appendPlainText(">>> Subtitle Batch Processing Finished.")

    def on_dest_toggle(self):
        custom = self.ui.radCustomFolder.isChecked()
        self.ui.txtOutputDir.setEnabled(custom)
        self.ui.btnBrowseOutputDir.setEnabled(custom)

    def on_preset_selected(self, index):
        preset_name = self.ui.comboPresets.currentData()
        if preset_name and preset_name in self.presets:
            p = self.presets[preset_name]
            self.ui.txtParameters.setText(p.get("args", ""))
            ext = p.get("ext")
            if ext:
                idx = self.ui.comboOutputFormat.findText(ext)
                if idx >= 0:
                    self.ui.comboOutputFormat.setCurrentIndex(idx)
        else:
            text = self.ui.comboPresets.currentText()
            if "(" in text and ")" in text:
                params = text[text.find("(") + 1 : text.rfind(")")]
                self.ui.txtParameters.setText(params)
        self.update_estimated_sizes()

    def update_estimated_sizes(self):
        """Update estimated file size column for all queue items based on current args."""
        args = self.ui.txtParameters.text()
        table = self.ui.tableQueue
        for row, item in enumerate(self.queue_items):
            duration = item.get("meta", {}).get("duration", 0)
            est = estimate_size_mb(duration, args)
            est_text = f"~{est:.1f} MB" if est else "-"
            table.setItem(row, 6, QTableWidgetItem(est_text))

    def on_filter_queue(self, query: str):
        query = query.strip().lower()
        table = self.ui.tableQueue
        for row in range(table.rowCount()):
            item = table.item(row, 1)  # File Name column
            if item:
                visible = query in item.text().lower()
                table.setRowHidden(row, not visible)

    def on_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Audio/Video Files", "", "Media Files (*.*)"
        )
        for f in files:
            self.add_file_to_queue(f)

    def on_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            cfg = get_config()
            filter_on = cfg.get("exclusions_enabled", True)
            exclusions = set(cfg.get("exclusions_list", []))

            for root, _, files in os.walk(folder):
                for f in sorted(files):
                    ext = os.path.splitext(f)[1].lower().lstrip(".")
                    if filter_on and ext in exclusions:
                        continue
                    full = os.path.join(root, f)
                    self.add_file_to_queue(full)

    def add_file_to_queue(self, path: str):
        if any(item["path"] == path for item in self.queue_items):
            return

        meta = probe_file(path)
        if not meta:
            return

        idx = len(self.queue_items)
        item_data = {
            "path": path,
            "meta": meta,
            "status": "Pending",
            "row": idx
        }
        self.queue_items.append(item_data)

        table = self.ui.tableQueue
        row = table.rowCount()
        table.insertRow(row)

        table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        table.setItem(row, 1, QTableWidgetItem(os.path.basename(path)))
        
        dur = meta.get("duration", 0)
        dur_str = f"{int(dur // 60):02d}:{int(dur % 60):02d}"
        table.setItem(row, 2, QTableWidgetItem(dur_str))
        
        table.setItem(row, 3, QTableWidgetItem(meta.get("video_codec", "")))
        table.setItem(row, 4, QTableWidgetItem(meta.get("audio_codec", "")))
        
        size_mb = meta.get("size", 0) / (1024 * 1024)
        table.setItem(row, 5, QTableWidgetItem(f"{size_mb:.2f} MB"))

        # Estimated Output Size
        args = self.ui.txtParameters.text()
        est = estimate_size_mb(dur, args)
        est_text = f"~{est:.1f} MB" if est else "-"
        table.setItem(row, 6, QTableWidgetItem(est_text))
        
        prog = QProgressBar()
        prog.setValue(0)
        prog.setTextVisible(True)
        table.setCellWidget(row, 7, prog)
        
        table.setItem(row, 8, QTableWidgetItem("Pending"))
        self.ui.lblItemCount.setText(f"{len(self.queue_items)} items")

    def on_remove_selected(self):
        table = self.ui.tableQueue
        selected = table.selectedIndexes()
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        for r in rows:
            table.removeRow(r)
            if r < len(self.queue_items):
                del self.queue_items[r]
        self.ui.lblItemCount.setText(f"{len(self.queue_items)} items")

    def on_clear_queue(self):
        self.ui.tableQueue.setRowCount(0)
        self.queue_items.clear()
        self.ui.lblItemCount.setText("0 items")

    def on_clean_errors(self):
        table = self.ui.tableQueue
        rows_to_remove = []
        for r in range(table.rowCount()):
            st = table.item(r, 8)
            if st and ("failed" in st.text().lower() or "error" in st.text().lower()):
                rows_to_remove.append(r)
        for r in sorted(rows_to_remove, reverse=True):
            table.removeRow(r)
            if r < len(self.queue_items):
                del self.queue_items[r]
        self.ui.lblItemCount.setText(f"{len(self.queue_items)} items")

    def on_browse_output(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.ui.txtOutputDir.setText(dir_path)

    # Documentation Viewer (Pure Python dialog exception matching Video-Analyse---Rename)
    def open_readme(self):
        ReadmeViewerDialog(self).exec()

    # Quick Action Tools
    def on_try_preset(self):
        """Encodes only first 10 seconds of the first file in the queue."""
        if not self.queue_items:
            QMessageBox.information(self, "Queue Empty", "Please add at least one file to test.")
            return

        item = self.queue_items[0]
        src_path = item["path"]
        src_dir, src_file = os.path.split(src_path)
        base, _ = os.path.splitext(src_file)
        out_ext = self.ui.comboOutputFormat.currentText().strip().lstrip(".") or "mp4"
        test_out = os.path.join(src_dir, f"{base}_preview_10s.{out_ext}")

        params = self.ui.txtParameters.text().strip()
        cmd = f"ffmpeg -y -i '{src_path}' -t 10 {params} '{test_out}'"
        
        self.ui.txtLog.appendPlainText(f">>> Running 10-second test encode:\n{cmd}")
        res = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.ui.txtLog.appendPlainText(res.stdout)
        if res.returncode == 0:
            QMessageBox.information(self, "Test Successful", f"Test preview generated successfully:\n{test_out}")
        else:
            QMessageBox.critical(self, "Test Failed", f"FFmpeg returned an error. Check log console.")

    def on_show_console_cmd(self):
        """Shows exact command line for the first item."""
        if not self.queue_items:
            QMessageBox.information(self, "Queue Empty", "Please add at least one file to view command.")
            return

        item = self.queue_items[0]
        src_path = item["path"]
        out_ext = self.ui.comboOutputFormat.currentText().strip().lstrip(".") or "mp4"
        out_path = f"/path/to/output.{out_ext}"
        params = self.ui.txtParameters.text().strip()
        final_params = substitute_tokens(params, src_path, out_path, item["meta"])
        full_cmd = f"ffmpeg -i '{src_path}' {final_params} '{out_path}'"

        QMessageBox.information(self, "FFmpeg Command Preview", full_cmd)

    # Secondary Dialog Launchers (Loaded dynamically from .ui files)
    def open_settings_dialog(self):
        dialog = load_ui_widget("ui/settings_dialog.ui", self)
        cfg = get_config()

        # Load current binary values
        dialog.chkCustomFfmpeg.setChecked(cfg.get("ffmpeg_custom", False))
        dialog.txtFfmpegPath.setText(cfg.get("ffmpeg_path", "/usr/bin/ffmpeg"))
        dialog.txtFfmpegPath.setEnabled(cfg.get("ffmpeg_custom", False))
        dialog.btnBrowseFfmpeg.setEnabled(cfg.get("ffmpeg_custom", False))

        dialog.chkCustomFfprobe.setChecked(cfg.get("ffprobe_custom", False))
        dialog.txtFfprobePath.setText(cfg.get("ffprobe_path", "/usr/bin/ffprobe"))
        dialog.txtFfprobePath.setEnabled(cfg.get("ffprobe_custom", False))
        dialog.btnBrowseFfprobe.setEnabled(cfg.get("ffprobe_custom", False))

        dialog.chkCustomYtdlp.setChecked(cfg.get("ytdlp_custom", False))
        dialog.txtYtdlpPath.setText(cfg.get("ytdlp_path", "/usr/bin/yt-dlp"))
        dialog.txtYtdlpPath.setEnabled(cfg.get("ytdlp_custom", False))
        dialog.btnBrowseYtdlp.setEnabled(cfg.get("ytdlp_custom", False))

        # Load Post-Task settings
        post_act = cfg.get("on_finish_action", "none")
        if post_act == "sleep":
            dialog.radActionSleep.setChecked(True)
        elif post_act == "shutdown":
            dialog.radActionShutdown.setChecked(True)
        else:
            dialog.radActionNone.setChecked(True)

        run_script_on = cfg.get("run_script_enabled", False)
        dialog.chkRunScript.setChecked(run_script_on)
        dialog.txtScriptPath.setText(cfg.get("run_script_path", ""))
        dialog.txtScriptPath.setEnabled(run_script_on)
        dialog.btnBrowseScript.setEnabled(run_script_on)

        dialog.chkRunScript.toggled.connect(lambda on: (
            dialog.txtScriptPath.setEnabled(on),
            dialog.btnBrowseScript.setEnabled(on)
        ))

        def browse_script():
            f, _ = QFileDialog.getOpenFileName(dialog, "Select Completion Script", "", "Shell Scripts (*.sh);;All Files (*)")
            if f:
                dialog.txtScriptPath.setText(f)

        dialog.btnBrowseScript.clicked.connect(browse_script)

        # Checkbox toggle listeners
        dialog.chkCustomFfmpeg.toggled.connect(lambda on: (
            dialog.txtFfmpegPath.setEnabled(on),
            dialog.btnBrowseFfmpeg.setEnabled(on)
        ))
        dialog.chkCustomFfprobe.toggled.connect(lambda on: (
            dialog.txtFfprobePath.setEnabled(on),
            dialog.btnBrowseFfprobe.setEnabled(on)
        ))
        dialog.chkCustomYtdlp.toggled.connect(lambda on: (
            dialog.txtYtdlpPath.setEnabled(on),
            dialog.btnBrowseYtdlp.setEnabled(on)
        ))

        # Browse buttons
        def browse_bin(target_line, title):
            f, _ = QFileDialog.getOpenFileName(dialog, title, "/usr/bin", "Executables (*)")
            if f:
                target_line.setText(f)

        dialog.btnBrowseFfmpeg.clicked.connect(lambda: browse_bin(dialog.txtFfmpegPath, "Select FFmpeg Binary"))
        dialog.btnBrowseFfprobe.clicked.connect(lambda: browse_bin(dialog.txtFfprobePath, "Select FFprobe Binary"))
        dialog.btnBrowseYtdlp.clicked.connect(lambda: browse_bin(dialog.txtYtdlpPath, "Select yt-dlp Binary"))

        # Test button
        def test_binaries():
            results = []
            for name, path in [("FFmpeg", dialog.txtFfmpegPath.text().strip()),
                               ("FFprobe", dialog.txtFfprobePath.text().strip()),
                               ("yt-dlp", dialog.txtYtdlpPath.text().strip())]:
                if os.path.exists(path) and os.access(path, os.X_OK):
                    try:
                        res = subprocess.run([path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
                        v_line = res.stdout.splitlines()[0] if res.stdout else "OK"
                        results.append(f"✓ {name}: {v_line[:40]}")
                    except Exception as e:
                        results.append(f"⚠ {name}: Error executing ({e})")
                else:
                    results.append(f"✗ {name}: File not found or not executable")
            dialog.lblBinariesStatus.setText("\n".join(results))

        dialog.btnTestBinaries.clicked.connect(test_binaries)

        def save_and_close():
            cfg["ffmpeg_custom"] = dialog.chkCustomFfmpeg.isChecked()
            cfg["ffmpeg_path"] = dialog.txtFfmpegPath.text().strip()
            cfg["ffprobe_custom"] = dialog.chkCustomFfprobe.isChecked()
            cfg["ffprobe_path"] = dialog.txtFfprobePath.text().strip()
            cfg["ytdlp_custom"] = dialog.chkCustomYtdlp.isChecked()
            cfg["ytdlp_path"] = dialog.txtYtdlpPath.text().strip()

            if dialog.radActionSleep.isChecked():
                cfg["on_finish_action"] = "sleep"
            elif dialog.radActionShutdown.isChecked():
                cfg["on_finish_action"] = "shutdown"
            else:
                cfg["on_finish_action"] = "none"

            cfg["run_script_enabled"] = dialog.chkRunScript.isChecked()
            cfg["run_script_path"] = dialog.txtScriptPath.text().strip()

            save_config(cfg)
            dialog.accept()

        dialog.dialogButtonBox.accepted.connect(save_and_close)
        dialog.dialogButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_presets_dialog(self):
        dialog = load_ui_widget("ui/presets_dialog.ui", self)
        
        def refresh_dialog_list():
            dialog.listPresets.clear()
            for name, data in self.presets.items():
                cat = data.get("category", "General")
                dialog.listPresets.addItem(f"[{cat}] {name}")

        def on_item_selected():
            cur = dialog.listPresets.currentItem()
            if not cur:
                return
            raw_text = cur.text()
            name = raw_text.split("] ", 1)[-1] if "] " in raw_text else raw_text
            if name in self.presets:
                p = self.presets[name]
                dialog.txtPresetTitle.setText(name)
                dialog.txtPresetExt.setText(p.get("ext", ""))
                dialog.txtPresetArgs.setPlainText(p.get("args", ""))
                cat_idx = dialog.comboPresetCategory.findText(p.get("category", ""))
                if cat_idx >= 0:
                    dialog.comboPresetCategory.setCurrentIndex(cat_idx)

        def on_save():
            name = dialog.txtPresetTitle.text().strip()
            if not name:
                return
            self.presets[name] = {
                "args": dialog.txtPresetArgs.toPlainText().strip(),
                "ext": dialog.txtPresetExt.text().strip(),
                "category": dialog.comboPresetCategory.currentText(),
                "desc": ""
            }
            save_presets(self.presets)
            self.refresh_presets_combo()
            refresh_dialog_list()

        def on_new():
            dialog.txtPresetTitle.setText("New Preset")
            dialog.txtPresetExt.setText("mp4")
            dialog.txtPresetArgs.setPlainText("-c:v libx264 -crf 23 -c:a aac -b:a 128k")

        def on_delete():
            cur = dialog.listPresets.currentItem()
            if not cur:
                return
            raw_text = cur.text()
            name = raw_text.split("] ", 1)[-1] if "] " in raw_text else raw_text
            if name in self.presets:
                del self.presets[name]
                save_presets(self.presets)
                self.refresh_presets_combo()
                refresh_dialog_list()

        def on_apply():
            on_save()
            name = dialog.txtPresetTitle.text().strip()
            idx = self.ui.comboPresets.findData(name)
            if idx >= 0:
                self.ui.comboPresets.setCurrentIndex(idx)
            dialog.accept()

        refresh_dialog_list()
        dialog.listPresets.itemSelectionChanged.connect(on_item_selected)
        dialog.btnSavePresetItem.clicked.connect(on_save)
        dialog.btnNewPreset.clicked.connect(on_new)
        dialog.btnDeletePreset.clicked.connect(on_delete)
        dialog.btnApplyToMain.clicked.connect(on_apply)
        dialog.presetButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_multi_presets_dialog(self):
        dialog = load_ui_widget("ui/multi_presets_dialog.ui", self)
        table = dialog.tableMultiPresets
        table.horizontalHeader().setStretchLastSection(True)
        table.setRowCount(0)

        # Populate with presets
        row = 0
        preset_keys = list(self.presets.keys())
        table.setRowCount(len(preset_keys))

        from PySide6.QtWidgets import QCheckBox, QWidget, QHBoxLayout

        checkboxes = {}
        for r, name in enumerate(preset_keys):
            data = self.presets[name]
            
            # Centered checkbox widget
            chk = QCheckBox()
            chk_widget = QWidget()
            layout = QHBoxLayout(chk_widget)
            layout.addWidget(chk)
            layout.setAlignment(Qt.AlignCenter)
            layout.setContentsMargins(0, 0, 0, 0)
            table.setCellWidget(r, 0, chk_widget)
            checkboxes[r] = (chk, name, data)

            table.setItem(r, 1, QTableWidgetItem(data.get("category", "General")))
            table.setItem(r, 2, QTableWidgetItem(name))
            table.setItem(r, 3, QTableWidgetItem(data.get("ext", "mp4")))
            table.setItem(r, 4, QTableWidgetItem(data.get("args", "")))

        def start_multi_batch():
            selected = [val for idx, val in checkboxes.items() if val[0].isChecked()]
            if not selected:
                QMessageBox.warning(dialog, "No Presets Selected", "Please enable at least one preset checkbox.")
                return

            if not self.queue_items:
                QMessageBox.warning(dialog, "Empty Queue", "Please add files to the main queue first.")
                return

            use_subfolders = dialog.chkSubfolderPerPreset.isChecked()
            custom_dest = self.ui.radCustomFolder.isChecked()
            dest_dir = self.ui.txtOutputDir.text().strip()

            self.ui.btnStart.setEnabled(False)
            self.ui.btnStop.setEnabled(True)
            self.ui.txtLog.appendPlainText(f">>> Starting Multiple Presets Batch ({len(selected)} presets chosen)...")

            dialog.accept()

            # Schedule jobs for every file x every selected preset
            for chk, name, pdata in selected:
                p_args = pdata.get("args", "")
                p_ext = pdata.get("ext", "mp4")
                p_folder_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name)

                for item in self.queue_items:
                    src_path = item["path"]
                    src_dir, src_file = os.path.split(src_path)
                    base, _ = os.path.splitext(src_file)

                    base_folder = dest_dir if (custom_dest and dest_dir and os.path.isdir(dest_dir)) else src_dir
                    target_folder = os.path.join(base_folder, p_folder_name) if use_subfolders else base_folder
                    os.makedirs(target_folder, exist_ok=True)

                    suffix = f"_{p_folder_name}" if not use_subfolders else ""
                    out_path = os.path.join(target_folder, f"{base}{suffix}.{p_ext}")

                    final_params = substitute_tokens(p_args, src_path, out_path, item["meta"])
                    is_two_pass = hasattr(self.ui, "chkTwoPass") and self.ui.chkTwoPass.isChecked()
                    task = FFmpegTask(src_path, out_path, final_params, item["meta"].get("duration", 0), two_pass=is_two_pass)
                    task.signals.progress.connect(self.on_task_progress)
                    task.signals.log.connect(self.on_task_log)
                    task.signals.finished.connect(self.on_task_finished)
                    self.active_tasks.append(task)
                    self.threadpool.start(task)

        dialog.multiButtonBox.accepted.connect(start_multi_batch)
        dialog.multiButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_stream_mapping_dialog(self):
        dialog = load_ui_widget("ui/stream_mapping_dialog.ui", self)
        dialog.streamButtonBox.accepted.connect(dialog.accept)
        dialog.streamButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_trim_dialog(self):
        dialog = load_ui_widget("ui/trim_dialog.ui", self)
        from PySide6.QtCore import QTime

        if not self.queue_items:
            dialog.lblTrimFileName.setText("File: No file selected in queue.")
            dialog.trimButtonBox.button(dialog.trimButtonBox.Apply).setEnabled(False)
        else:
            item = self.queue_items[0]
            src_path = item["path"]
            duration = int(item["meta"].get("duration", 0))
            dialog.lblTrimFileName.setText(f"File: {os.path.basename(src_path)}")

            dur_time = QTime(duration // 3600, (duration % 3600) // 60, duration % 60)
            dialog.lblTotalDuration.setText(f"Total: {dur_time.toString('HH:mm:ss')}")
            dialog.timeStart.setTime(QTime(0, 0, 0))
            dialog.timeEnd.setTime(dur_time)

            def update_calc_duration():
                s = dialog.timeStart.time()
                e = dialog.timeEnd.time()
                s_sec = s.hour() * 3600 + s.minute() * 60 + s.second()
                e_sec = e.hour() * 3600 + e.minute() * 60 + e.second()
                diff = max(0, e_sec - s_sec)
                calc_time = QTime(diff // 3600, (diff % 3600) // 60, diff % 60)
                dialog.lblCalculatedDuration.setText(calc_time.toString("HH:mm:ss"))

            dialog.timeStart.timeChanged.connect(update_calc_duration)
            dialog.timeEnd.timeChanged.connect(update_calc_duration)
            update_calc_duration()

            def apply_trim():
                s_str = dialog.timeStart.time().toString("HH:mm:ss")
                e_str = dialog.timeEnd.time().toString("HH:mm:ss")
                fast_seek = dialog.radFastSeek.isChecked()

                if fast_seek:
                    # Place -ss in pre-input
                    self.ui.txtPreInput.setText(f"-ss {s_str}")
                    cur_params = self.ui.txtParameters.text().strip()
                    # Append -to in parameters
                    self.ui.txtParameters.setText(f"-to {e_str} {cur_params}".strip())
                else:
                    cur_params = self.ui.txtParameters.text().strip()
                    self.ui.txtParameters.setText(f"-ss {s_str} -to {e_str} {cur_params}".strip())

                QMessageBox.information(dialog, "Trim Applied", f"Trim cut points applied:\nStart: {s_str}\nEnd: {e_str}")
                dialog.accept()

            dialog.trimButtonBox.button(dialog.trimButtonBox.Apply).clicked.connect(apply_trim)

        dialog.trimButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_join_dialog(self):
        dialog = load_ui_widget("ui/join_dialog.ui", self)
        
        # Populate with items from queue
        for item in self.queue_items:
            dialog.listJoinFiles.addItem(item["path"])

        # Auto-suggest output path
        if self.queue_items:
            first_dir = os.path.dirname(self.queue_items[0]["path"])
            default_out = os.path.join(first_dir, "joined_video.mp4")
            dialog.txtJoinOutput.setText(default_out)

        # Browse output
        def browse_out():
            f, _ = QFileDialog.getSaveFileName(dialog, "Select Joined Output File", dialog.txtJoinOutput.text(), "MP4 Video (*.mp4);;MKV Video (*.mkv);;All Files (*)")
            if f:
                dialog.txtJoinOutput.setText(f)

        dialog.btnBrowseJoinOutput.clicked.connect(browse_out)

        # List buttons
        def add_more():
            files, _ = QFileDialog.getOpenFileNames(dialog, "Add Files to Join", "", "Videos (*.mp4 *.mkv *.avi *.ts *.mov);;All Files (*)")
            for f in files:
                dialog.listJoinFiles.addItem(f)

        def remove_sel():
            for itm in dialog.listJoinFiles.selectedItems():
                dialog.listJoinFiles.takeItem(dialog.listJoinFiles.row(itm))

        def move_up():
            row = dialog.listJoinFiles.currentRow()
            if row > 0:
                item = dialog.listJoinFiles.takeItem(row)
                dialog.listJoinFiles.insertItem(row - 1, item)
                dialog.listJoinFiles.setCurrentRow(row - 1)

        def move_down():
            row = dialog.listJoinFiles.currentRow()
            if row < dialog.listJoinFiles.count() - 1:
                item = dialog.listJoinFiles.takeItem(row)
                dialog.listJoinFiles.insertItem(row + 1, item)
                dialog.listJoinFiles.setCurrentRow(row + 1)

        dialog.btnAddJoinFiles.clicked.connect(add_more)
        dialog.btnRemoveJoinFile.clicked.connect(remove_sel)
        dialog.btnMoveUpJoin.clicked.connect(move_up)
        dialog.btnMoveDownJoin.clicked.connect(move_down)
        dialog.btnClearJoinFiles.clicked.connect(dialog.listJoinFiles.clear)

        def do_join():
            file_list = [dialog.listJoinFiles.item(i).text() for i in range(dialog.listJoinFiles.count())]
            out_file = dialog.txtJoinOutput.text().strip()
            if not out_file:
                QMessageBox.warning(dialog, "Missing Output", "Please choose an output destination.")
                return

            stream_copy = dialog.radStreamCopy.isChecked()
            success, msg = join_files(file_list, out_file, stream_copy)
            if success:
                QMessageBox.information(dialog, "Join Complete", f"Files concatenated successfully:\n{out_file}")
                dialog.accept()
            else:
                QMessageBox.critical(dialog, "Join Error", msg)

        dialog.joinButtonBox.accepted.connect(do_join)
        dialog.joinButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_crop_dialog(self):
        dialog = load_ui_widget("ui/crop_dialog.ui", self)
        
        if not self.queue_items:
            dialog.lblFileNameVal.setText("No file selected in queue.")
            dialog.btnRunDetection.setEnabled(False)
        else:
            target_path = self.queue_items[0]["path"]
            dialog.lblFileNameVal.setText(os.path.basename(target_path))

            def run_crop():
                dialog.btnRunDetection.setEnabled(False)
                dialog.txtCropLog.setPlainText("Running cropdetect on 60 frames...")
                
                crop_arg, ratio_desc, log = detect_black_bars(target_path)
                dialog.txtCropLog.setPlainText(log)
                if crop_arg:
                    dialog.txtCropFilter.setText(crop_arg)
                    QMessageBox.information(dialog, "Detection Complete", f"Detected Aspect Ratio: {ratio_desc}\n\nRecommended: {crop_arg}")
                else:
                    QMessageBox.warning(dialog, "No Crop", ratio_desc)
                dialog.btnRunDetection.setEnabled(True)

            dialog.btnRunDetection.clicked.connect(run_crop)

            def apply_crop():
                filter_val = dialog.txtCropFilter.text().strip()
                if filter_val:
                    cur = self.ui.txtParameters.text().strip()
                    self.ui.txtParameters.setText(f"{cur} {filter_val}".strip())
                    dialog.accept()

            dialog.cropButtonBox.button(dialog.cropButtonBox.Apply).clicked.connect(apply_crop)

        dialog.cropButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_watermark_dialog(self):
        dialog = load_ui_widget("ui/watermark_dialog.ui", self)
        
        def browse_img():
            path, _ = QFileDialog.getOpenFileName(dialog, "Select Logo/Watermark Image", "", "Images (*.png *.jpg *.jpeg *.svg)")
            if path:
                dialog.txtWatermarkPath.setText(path)

        def apply_watermark():
            img_path = dialog.txtWatermarkPath.text().strip()
            if not img_path or not os.path.isfile(img_path):
                QMessageBox.warning(dialog, "Image Missing", "Please select a valid image file.")
                return

            pos = dialog.comboPosition.currentText()
            margin = dialog.spinMargin.value()

            if "Bottom-Right" in pos:
                coord = f"x=(main_w-overlay_w)-{margin}:y=(main_h-overlay_h)-{margin}"
            elif "Bottom-Left" in pos:
                coord = f"x={margin}:y=(main_h-overlay_h)-{margin}"
            elif "Top-Right" in pos:
                coord = f"x=(main_w-overlay_w)-{margin}:y={margin}"
            elif "Top-Left" in pos:
                coord = f"x={margin}:y={margin}"
            else:
                coord = "x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2"

            overlay_args = f"-i \"{img_path}\" -filter_complex \"overlay={coord}\""
            current_params = self.ui.txtParameters.text().strip()
            self.ui.txtParameters.setText(f"{current_params} {overlay_args}".strip())
            dialog.accept()

        dialog.btnBrowseWatermark.clicked.connect(browse_img)
        dialog.watermarkButtonBox.button(dialog.watermarkButtonBox.Apply).clicked.connect(apply_watermark)
        dialog.watermarkButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_silence_dialog(self):
        dialog = load_ui_widget("ui/silence_dialog.ui", self)
        table = dialog.tableSilences
        table.horizontalHeader().setStretchLastSection(True)

        if not self.queue_items:
            dialog.lblTargetFile.setText("No file selected in queue.")
            dialog.btnStartDetection.setEnabled(False)
        else:
            target_path = self.queue_items[0]["path"]
            dialog.lblTargetFile.setText(f"Analyzing: {os.path.basename(target_path)}")

            def run_detection():
                threshold = dialog.spinThreshold.value()
                duration = dialog.spinMinDuration.value()
                ffmpeg_bin = get_binary_path("ffmpeg")

                cmd = [
                    ffmpeg_bin, "-y", "-i", target_path,
                    "-af", f"silencedetect=noise={threshold}dB:d={duration}",
                    "-f", "null", "-"
                ]

                table.setRowCount(0)
                try:
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    start_pattern = re.compile(r"silence_start:\s+([\d\.]+)")
                    end_pattern = re.compile(r"silence_end:\s+([\d\.]+)\s+\|\s+silence_duration:\s+([\d\.]+)")
                    
                    current_start = None
                    silences = []

                    for line in res.stdout.splitlines():
                        m_start = start_pattern.search(line)
                        if m_start:
                            current_start = float(m_start.group(1))
                        m_end = end_pattern.search(line)
                        if m_end and current_start is not None:
                            end_val = float(m_end.group(1))
                            dur_val = float(m_end.group(2))
                            silences.append((current_start, end_val, dur_val))
                            current_start = None

                    table.setRowCount(len(silences))
                    for r, (s_start, s_end, s_dur) in enumerate(silences):
                        table.setItem(r, 0, QTableWidgetItem(str(r + 1)))
                        table.setItem(r, 1, QTableWidgetItem(f"{s_start:.2f}s"))
                        table.setItem(r, 2, QTableWidgetItem(f"{s_end:.2f}s"))
                        table.setItem(r, 3, QTableWidgetItem(f"{s_dur:.2f}s"))

                    if not silences:
                        QMessageBox.information(dialog, "Detection Result", "No silent sections detected matching threshold.")
                except Exception as e:
                    QMessageBox.critical(dialog, "Error", f"Failed running silence detection: {e}")

            dialog.btnStartDetection.clicked.connect(run_detection)

            def apply_filter():
                threshold = dialog.spinThreshold.value()
                duration = dialog.spinMinDuration.value()
                filter_str = f"-af silenceremove=stop_periods=-1:stop_duration={duration}:stop_threshold={threshold}dB"
                cur = self.ui.txtParameters.text().strip()
                self.ui.txtParameters.setText(f"{cur} {filter_str}".strip())
                dialog.accept()

            dialog.btnApplySilenceRemove.clicked.connect(apply_filter)

        dialog.btnCloseSilence.clicked.connect(dialog.reject)
        dialog.exec()

    def open_trailer_dialog(self):
        dialog = load_ui_widget("ui/trailer_dialog.ui", self)
        
        if not self.queue_items:
            dialog.lblSourceFileName.setText("No file selected in queue.")
            dialog.btnStartTrailer.setEnabled(False)
        else:
            item = self.queue_items[0]
            src_path = item["path"]
            duration = item["meta"].get("duration", 0)
            dialog.lblSourceFileName.setText(os.path.basename(src_path))
            
            src_dir, src_file = os.path.split(src_path)
            base, _ = os.path.splitext(src_file)
            default_out = os.path.join(src_dir, f"{base}_trailer.mp4")
            dialog.txtTrailerOutput.setText(default_out)

            def browse_out():
                f, _ = QFileDialog.getSaveFileName(dialog, "Select Trailer Output", default_out, "MP4 Video (*.mp4)")
                if f:
                    dialog.txtTrailerOutput.setText(f)

            dialog.btnBrowseTrailerOutput.clicked.connect(browse_out)

            def start_gen():
                clip_dur = dialog.spinClipDuration.value()
                interval = dialog.spinInterval.value()
                out_path = dialog.txtTrailerOutput.text().strip()
                if not out_path:
                    return

                ffmpeg_bin = get_binary_path("ffmpeg")
                dialog.btnStartTrailer.setEnabled(False)
                dialog.trailerProgress.setValue(20)

                # Generate sampling timestamps
                timestamps = []
                cur = 10.0  # start 10s in to avoid intro logos
                while cur + clip_dur < duration:
                    timestamps.append(cur)
                    cur += interval

                if not timestamps:
                    timestamps = [0.0]

                # Build filter_complex select expression
                # e.g.: between(t,10,13)+between(t,70,73)
                v_select = "+".join([f"between(t,{ts},{ts+clip_dur})" for ts in timestamps])
                filter_complex = f"[0:v]select='{v_select}',setpts=N/FRAME_RATE/TB[v];[0:a]aselect='{v_select}',asetpts=N/SR/TB[a]"

                cmd = [
                    ffmpeg_bin, "-y", "-i", src_path,
                    "-filter_complex", filter_complex,
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "22", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "128k",
                    out_path
                ]

                try:
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                    dialog.trailerProgress.setValue(100)
                    if res.returncode == 0:
                        QMessageBox.information(dialog, "Success", f"Teaser trailer created successfully:\n{out_path}")
                        dialog.accept()
                    else:
                        QMessageBox.critical(dialog, "Error", f"FFmpeg failed creating trailer:\n{res.stdout[-300:]}")
                except Exception as e:
                    QMessageBox.critical(dialog, "Error", str(e))
                finally:
                    dialog.btnStartTrailer.setEnabled(True)

            dialog.btnStartTrailer.clicked.connect(start_gen)

        dialog.btnCloseTrailer.clicked.connect(dialog.reject)
        dialog.exec()

    def open_image_to_video_dialog(self):
        dialog = load_ui_widget("ui/image_to_video_dialog.ui", self)

        def on_mode_change():
            is_single = dialog.radSingleImgAudio.isChecked()
            dialog.txtAudioPath.setEnabled(is_single)
            dialog.btnBrowseAudio.setEnabled(is_single)
            dialog.lblImageSource.setText("Image File:" if is_single else "Images Folder:")

        dialog.radSingleImgAudio.toggled.connect(on_mode_change)
        dialog.radImageSequence.toggled.connect(on_mode_change)

        def browse_img():
            if dialog.radSingleImgAudio.isChecked():
                f, _ = QFileDialog.getOpenFileName(dialog, "Select Image File", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
                if f:
                    dialog.txtImagePath.setText(f)
                    base, _ = os.path.splitext(f)
                    dialog.txtOutputVideo.setText(f"{base}_video.mp4")
            else:
                d = QFileDialog.getExistingDirectory(dialog, "Select Sequence Folder")
                if d:
                    dialog.txtImagePath.setText(d)
                    dialog.txtOutputVideo.setText(os.path.join(d, "timelapse_output.mp4"))

        def browse_aud():
            f, _ = QFileDialog.getOpenFileName(dialog, "Select Audio File", "", "Audio (*.mp3 *.m4a *.wav *.flac *.aac)")
            if f:
                dialog.txtAudioPath.setText(f)

        def browse_out():
            f, _ = QFileDialog.getSaveFileName(dialog, "Save Video", dialog.txtOutputVideo.text(), "MP4 Video (*.mp4)")
            if f:
                dialog.txtOutputVideo.setText(f)

        dialog.btnBrowseImage.clicked.connect(browse_img)
        dialog.btnBrowseAudio.clicked.connect(browse_aud)
        dialog.btnBrowseOutput.clicked.connect(browse_out)

        def create_video():
            img_path = dialog.txtImagePath.text().strip()
            out_path = dialog.txtOutputVideo.text().strip()
            if not img_path or not out_path:
                QMessageBox.warning(dialog, "Missing Path", "Please select input and output destinations.")
                return

            ffmpeg_bin = get_binary_path("ffmpeg")
            fps = dialog.spinFps.value()
            res_choice = dialog.comboResolution.currentText()

            scale_filter = ""
            if "1920x1080" in res_choice:
                scale_filter = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"
            elif "1280x720" in res_choice:
                scale_filter = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
            elif "3840x2160" in res_choice:
                scale_filter = "scale=3840:2160:force_original_aspect_ratio=decrease,pad=3840:2160:(ow-iw)/2:(oh-ih)/2"

            if dialog.radSingleImgAudio.isChecked():
                audio_path = dialog.txtAudioPath.text().strip()
                if not audio_path or not os.path.isfile(audio_path):
                    QMessageBox.warning(dialog, "Missing Audio", "Please select an audio file.")
                    return

                cmd = [
                    ffmpeg_bin, "-y",
                    "-loop", "1",
                    "-framerate", str(fps),
                    "-i", img_path,
                    "-i", audio_path,
                    "-c:v", "libx264",
                    "-tune", "stillimage",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-pix_fmt", "yuv420p",
                    "-shortest"
                ]
                if scale_filter:
                    cmd.extend(["-vf", scale_filter])
                cmd.append(out_path)
            else:
                # Sequence folder: e.g. %04d.jpg or *.jpg
                pattern = os.path.join(img_path, "%*.jpg")
                cmd = [
                    ffmpeg_bin, "-y",
                    "-framerate", str(fps),
                    "-pattern_type", "glob",
                    "-i", os.path.join(img_path, "*.*"),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p"
                ]
                if scale_filter:
                    cmd.extend(["-vf", scale_filter])
                cmd.append(out_path)

            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if res.returncode == 0:
                    QMessageBox.information(dialog, "Success", f"Video created successfully:\n{out_path}")
                    dialog.accept()
                else:
                    QMessageBox.critical(dialog, "Error", f"FFmpeg failed:\n{res.stdout[-400:]}")
            except Exception as e:
                QMessageBox.critical(dialog, "Error", str(e))

        dialog.imgDialogButtonBox.accepted.connect(create_video)
        dialog.imgDialogButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_media_info_dialog(self):
        dialog = load_ui_widget("ui/media_info_dialog.ui", self)
        table = dialog.tableMediaStreams
        table.horizontalHeader().setStretchLastSection(True)

        selected_row = self.ui.tableQueue.currentRow()
        if selected_row < 0 or selected_row >= len(self.queue_items):
            if self.queue_items:
                selected_row = 0
            else:
                QMessageBox.information(self, "No File", "Please add a file to the queue first.")
                return

        item = self.queue_items[selected_row]
        file_path = item["path"]
        dialog.lblFilePathVal.setText(file_path)

        ffprobe_bin = get_binary_path("ffprobe")
        cmd = [
            ffprobe_bin, "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            file_path
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            data = json.loads(res.stdout) if res.stdout else {}
            dialog.txtRawJson.setPlainText(json.dumps(data, indent=2))

            fmt = data.get("format", {})
            dialog.lblFormatVal.setText(f"{fmt.get('format_name', 'N/A')} (bitrate: {int(fmt.get('bit_rate', 0)) // 1000} kbps)")

            dur = float(fmt.get("duration", 0))
            size_mb = int(fmt.get("size", 0)) / (1024 * 1024)
            dur_str = f"{int(dur // 3600):02d}:{int((dur % 3600) // 60):02d}:{int(dur % 60):02d}"
            dialog.lblDurationSizeVal.setText(f"{dur_str}  |  {size_mb:.2f} MB")

            streams = data.get("streams", [])
            table.setRowCount(len(streams))
            for r, s in enumerate(streams):
                st_type = s.get("codec_type", "").upper()
                table.setItem(r, 0, QTableWidgetItem(str(s.get("index", r))))
                table.setItem(r, 1, QTableWidgetItem(st_type))
                table.setItem(r, 2, QTableWidgetItem(s.get("codec_name", "")))

                details = ""
                if st_type == "VIDEO":
                    details = f"{s.get('width', '')}x{s.get('height', '')} @ {s.get('r_frame_rate', '')} fps, {s.get('pix_fmt', '')}"
                elif st_type == "AUDIO":
                    details = f"{s.get('channels', '')} ch, {s.get('sample_rate', '')} Hz"
                elif st_type == "SUBTITLE":
                    details = f"Title: {s.get('tags', {}).get('title', 'N/A')}"
                table.setItem(r, 3, QTableWidgetItem(details))

                b_rate = int(s.get("bit_rate", 0)) // 1000 if s.get("bit_rate") else 0
                table.setItem(r, 4, QTableWidgetItem(f"{b_rate} kbps" if b_rate else "-"))

                lang = s.get("tags", {}).get("language", "und")
                table.setItem(r, 5, QTableWidgetItem(lang))

        except Exception as e:
            QMessageBox.critical(dialog, "Probe Error", str(e))

        def copy_to_clipboard():
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(dialog.txtRawJson.toPlainText())
            QMessageBox.information(dialog, "Copied", "Full stream JSON copied to clipboard.")

        dialog.btnCopyInfo.clicked.connect(copy_to_clipboard)
        dialog.btnCloseInfo.clicked.connect(dialog.accept)
        dialog.exec()

    def open_exclusions_dialog(self):
        dialog = load_ui_widget("ui/exclusions_dialog.ui", self)
        cfg = get_config()

        dialog.chkEnableFilter.setChecked(cfg.get("exclusions_enabled", True))
        current_exts = cfg.get("exclusions_list", [])

        def populate():
            dialog.listExclusions.clear()
            for ext in sorted(current_exts):
                dialog.listExclusions.addItem(ext)

        populate()

        def add_ext():
            val = dialog.txtNewExt.text().strip().lower().lstrip(".")
            if val and val not in current_exts:
                current_exts.append(val)
                populate()
                dialog.txtNewExt.clear()

        def remove_ext():
            for item in dialog.listExclusions.selectedItems():
                t = item.text()
                if t in current_exts:
                    current_exts.remove(t)
            populate()

        def reset_defaults():
            nonlocal current_exts
            current_exts = ["txt", "nfo", "srt", "ass", "vtt", "jpg", "png", "ini", "pdf", "url", "part", "zip", "rar", "7z", "torrent", "exe"]
            populate()

        dialog.btnAddExt.clicked.connect(add_ext)
        dialog.btnRemoveExt.clicked.connect(remove_ext)
        dialog.btnResetDefaults.clicked.connect(reset_defaults)

        def save_and_close():
            cfg["exclusions_enabled"] = dialog.chkEnableFilter.isChecked()
            cfg["exclusions_list"] = current_exts
            save_config(cfg)
            dialog.accept()

        dialog.exclusionButtonBox.accepted.connect(save_and_close)
        dialog.exclusionButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def open_token_builder_dialog(self):
        dialog = load_ui_widget("ui/token_builder_dialog.ui", self)
        table = dialog.tableTokens
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Token", "Description", "Example"])
        tokens = [
            ("%~n", "Filename without extension", "video_sample"),
            ("%~x", "Original extension with dot", ".mp4"),
            ("<res>", "Resolution width x height", "1920x1080"),
            ("<vcodec>", "Detected video codec", "h264"),
            ("<acodec>", "Detected audio codec", "aac"),
            ("<source_dir>", "Directory path of input file", "/home/user/Videos"),
            ("<filename>", "Filename without extension", "video_sample")
        ]
        table.setRowCount(len(tokens))
        for r, (tok, desc, ex) in enumerate(tokens):
            table.setItem(r, 0, QTableWidgetItem(tok))
            table.setItem(r, 1, QTableWidgetItem(desc))
            table.setItem(r, 2, QTableWidgetItem(ex))
        table.horizontalHeader().setStretchLastSection(True)

        def insert_selected():
            sel = table.selectedIndexes()
            if sel:
                row = sel[0].row()
                tok = table.item(row, 0).text()
                self.ui.txtParameters.insert(tok)
                dialog.accept()

        dialog.btnInsertToken.clicked.connect(insert_selected)
        dialog.btnCloseToken.clicked.connect(dialog.reject)
        dialog.exec()

    # Execution Engine
    def start_processing(self):
        if not self.queue_items:
            QMessageBox.information(self, "Queue Empty", "Please add files to the queue first.")
            return

        max_threads = self.ui.spinThreads.value()
        self.threadpool.setMaxThreadCount(max_threads)
        
        params_template = self.ui.txtParameters.text().strip()
        out_ext = self.ui.comboOutputFormat.currentText().strip().lstrip(".")
        if not out_ext:
            out_ext = "mp4"

        custom_dest = self.ui.radCustomFolder.isChecked()
        dest_dir = self.ui.txtOutputDir.text().strip()

        # Check fade parameters
        fade_v = self.ui.spinFadeVideoIn.value()
        fade_a = self.ui.spinFadeAudioIn.value()
        fade_extra = ""
        if fade_v > 0:
            fade_extra += f" -vf fade=t=in:st=0:d={fade_v}"
        if fade_a > 0:
            fade_extra += f" -af afade=t=in:st=0:d={fade_a}"

        # Check watermark parameters
        wm_extra = ""
        if self.ui.chkEnableWatermark.isChecked():
            wm_path = self.ui.txtWatermarkFile.text().strip()
            if wm_path and os.path.exists(wm_path):
                pos = self.ui.comboWatermarkPos.currentText()
                margin = self.ui.spinWatermarkMargin.value()
                if "Bottom-Right" in pos:
                    coord = f"x=(main_w-overlay_w)-{margin}:y=(main_h-overlay_h)-{margin}"
                elif "Bottom-Left" in pos:
                    coord = f"x={margin}:y=(main_h-overlay_h)-{margin}"
                elif "Top-Right" in pos:
                    coord = f"x=(main_w-overlay_w)-{margin}:y={margin}"
                elif "Top-Left" in pos:
                    coord = f"x={margin}:y={margin}"
                else:
                    coord = "x=(main_w-overlay_w)/2:y=(main_h-overlay_h)/2"
                wm_extra = f" -i \"{wm_path}\" -filter_complex \"overlay={coord}\""

        self.ui.btnStart.setEnabled(False)
        self.ui.btnStop.setEnabled(True)
        self.ui.txtLog.appendPlainText(">>> Batch Processing Started...")

        self.active_tasks.clear()

        for idx, item in enumerate(self.queue_items):
            src_path = item["path"]
            src_dir, src_file = os.path.split(src_path)
            base_name, _ = os.path.splitext(src_file)

            if custom_dest and dest_dir and os.path.isdir(dest_dir):
                target_folder = dest_dir
            else:
                target_folder = src_dir

            out_filename = f"{base_name}_converted.{out_ext}"
            out_path = os.path.join(target_folder, out_filename)

            combined_params = f"{params_template}{fade_extra}{wm_extra}".strip()
            final_params = substitute_tokens(combined_params, src_path, out_path, item["meta"])

            is_two_pass = hasattr(self.ui, "chkTwoPass") and self.ui.chkTwoPass.isChecked()
            task = FFmpegTask(src_path, out_path, final_params, item["meta"].get("duration", 0), two_pass=is_two_pass)
            task.signals.progress.connect(self.on_task_progress)
            task.signals.log.connect(self.on_task_log)
            task.signals.finished.connect(self.on_task_finished)
            
            self.active_tasks.append(task)
            self.threadpool.start(task)

    def on_task_progress(self, file_path: str, percent: float):
        total_percent = 0.0
        for idx, item in enumerate(self.queue_items):
            if item["path"] == file_path:
                bar = self.ui.tableQueue.cellWidget(idx, 7)
                if bar:
                    bar.setValue(int(percent))
                status_item = self.ui.tableQueue.item(idx, 8)
                if status_item:
                    status_item.setText(f"Encoding ({int(percent)}%)")
            
            # Tally aggregate progress
            bar = self.ui.tableQueue.cellWidget(idx, 7)
            if bar:
                total_percent += bar.value()

        # Update Overall Progress & Dynamic Window Title
        if self.queue_items:
            avg_percent = int(total_percent / len(self.queue_items))
            self.ui.overallProgress.setValue(avg_percent)
            self.setWindowTitle(f"[{avg_percent}%] FFmpeg Batch AV Converter (Linux Native)")

    def on_task_log(self, line: str):
        self.ui.txtLog.appendPlainText(line)

    def on_task_finished(self, file_path: str, success: bool, msg: str):
        for idx, item in enumerate(self.queue_items):
            if item["path"] == file_path:
                status_item = self.ui.tableQueue.item(idx, 8)
                bar = self.ui.tableQueue.cellWidget(idx, 7)
                if success:
                    if status_item:
                        status_item.setText("Completed")
                    if bar:
                        bar.setValue(100)
                else:
                    if status_item:
                        status_item.setText(f"Failed ({msg})")
                break

        # Check if entire queue has finished
        all_finished = True
        completed_count = 0
        for r in range(self.ui.tableQueue.rowCount()):
            st = self.ui.tableQueue.item(r, 8)
            if st:
                txt = st.text()
                if "encoding" in txt.lower() or "pending" in txt.lower():
                    all_finished = False
                    break
                elif "completed" in txt.lower():
                    completed_count += 1

        if all_finished and self.active_tasks:
            self.ui.btnStart.setEnabled(True)
            self.ui.btnStop.setEnabled(False)
            self.ui.overallProgress.setValue(100)
            self.setWindowTitle("FFmpeg Batch AV Converter (Linux Native)")
            self.ui.txtLog.appendPlainText(f">>> Batch Finished! {completed_count}/{len(self.queue_items)} files converted successfully.")

            # 1. Play Completion Audio Chime
            sound_path = os.path.join(os.path.dirname(__file__), "assets", "complete.wav")
            if os.path.exists(sound_path):
                try:
                    subprocess.Popen(["paplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    try:
                        subprocess.Popen(["aplay", "-q", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass

            # 2. Native Linux Desktop Notification
            try:
                icon_path = os.path.join(os.path.dirname(__file__), "assets", "app_icon.png")
                msg = f"Queue finished: {completed_count} of {len(self.queue_items)} files converted successfully."
                subprocess.Popen([
                    "notify-send",
                    "-i", icon_path,
                    "FFmpeg Batch AV Converter",
                    msg
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

            # 3. Post-Task Action (External script, Suspend, or Shutdown)
            cfg = get_config()
            if cfg.get("run_script_enabled") and cfg.get("run_script_path"):
                scr = cfg["run_script_path"]
                if os.path.isfile(scr) and os.access(scr, os.X_OK):
                    self.ui.txtLog.appendPlainText(f">>> Executing completion script: {scr}")
                    try:
                        subprocess.Popen([scr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception as e:
                        self.ui.txtLog.appendPlainText(f"⚠ Script execution error: {e}")

            action = cfg.get("on_finish_action", "none")
            if action == "sleep":
                self.ui.txtLog.appendPlainText(">>> Triggering computer sleep (systemctl suspend)...")
                try:
                    subprocess.Popen(["systemctl", "suspend"])
                except Exception:
                    pass
            elif action == "shutdown":
                self.ui.txtLog.appendPlainText(">>> Triggering computer shutdown (systemctl poweroff)...")
                try:
                    subprocess.Popen(["systemctl", "poweroff"])
                except Exception:
                    pass

    def stop_processing(self):
        for task in self.active_tasks:
            task.cancel()
        self.ui.btnStart.setEnabled(True)
        self.ui.btnStop.setEnabled(False)
        self.setWindowTitle("FFmpeg Batch AV Converter (Linux Native)")
        self.ui.txtLog.appendPlainText(">>> Batch Processing Stopped by User.")

    def closeEvent(self, event):
        """Warn user if active encoding tasks exist before closing."""
        running = any(not task.is_cancelled and task.process and task.process.poll() is None for task in self.active_tasks)
        if running:
            reply = QMessageBox.question(
                self,
                "Confirm Exit",
                "Encoding tasks are currently active. Do you really want to exit and stop all encodings?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.stop_processing()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def open_target_size_dialog(self):
        """Open Target File Size & Two-Pass Bitrate Calculator dialog."""
        dlg = load_ui_widget("ui/target_size_dialog.ui", self)

        # Detect duration from selected queue item
        selected_duration = 0.0
        selected_rows = self.ui.tableQueue.selectionModel().selectedRows()
        if selected_rows:
            row_idx = selected_rows[0].row()
            if 0 <= row_idx < len(self.queue_items):
                meta = self.queue_items[row_idx].get("meta", {})
                selected_duration = meta.get("duration", 0.0)

        if selected_duration > 0:
            mins = int(selected_duration // 60)
            secs = int(selected_duration % 60)
            dlg.lblDurationVal.setText(f"{mins}m {secs}s ({selected_duration:.1f} seconds)")
        else:
            dlg.lblDurationVal.setText("No video selected in queue (assuming 10 min / 600s)")
            selected_duration = 600.0

        def recalculate():
            target_mb = dlg.spinTargetMB.value()
            audio_text = dlg.comboAudioBitrate.currentText()
            try:
                audio_kbps = int(audio_text.split()[0])
            except Exception:
                audio_kbps = 128

            # Bitrate calc: total_bits = target_mb * 8192 kbits
            # total_kbps = total_bits / duration
            # video_kbps = total_kbps - audio_kbps
            total_kbits = target_mb * 8192.0
            total_kbps = total_kbits / max(1.0, selected_duration)
            video_kbps = max(50, int(total_kbps - audio_kbps))

            dlg.lblComputedBitrateVal.setText(f"{video_kbps} kbps (Video) + {audio_kbps} kbps (Audio)")
            dlg.txtGeneratedArgs.setText(f"-b:v {video_kbps}k -b:a {audio_kbps}k")

        dlg.spinTargetMB.valueChanged.connect(recalculate)
        dlg.comboAudioBitrate.currentIndexChanged.connect(recalculate)
        recalculate()

        def on_apply():
            args = dlg.txtGeneratedArgs.text().strip()
            if args:
                cur = self.ui.txtParameters.text().strip()
                if cur:
                    self.ui.txtParameters.setText(f"{cur} {args}")
                else:
                    self.ui.txtParameters.setText(args)
                if hasattr(self.ui, "chkTwoPass"):
                    self.ui.chkTwoPass.setChecked(True)
                QMessageBox.information(dlg, "Applied", f"Injected '{args}' and enabled Two-Pass Encoding.")
            dlg.accept()

        dlg.targetButtonBox.button(QDialogButtonBox.Apply).clicked.connect(on_apply)
        dlg.targetButtonBox.button(QDialogButtonBox.Close).clicked.connect(dlg.reject)
        dlg.exec()

    def show_about(self):
        QMessageBox.about(
            self,
            "About FFmpeg Batch Native Linux",
            "<b>FFmpeg Batch AV Converter (Linux Native)</b><br><br>"
            "Modern, multi-threaded PySide6 batch converter powered by native Linux FFmpeg.<br>"
            "Decoupled UI architecture with Qt Designer support."
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    theme_mgr = ThemeManager()
    theme_mgr.apply_current_theme(app)
    window = FFBatchApp()
    window.show()
    sys.exit(app.exec())
