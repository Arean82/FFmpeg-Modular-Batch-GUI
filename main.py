"""Main application entry point for native Linux FFmpeg Batch AV Converter."""
import json
import os
import re
import sys

# Suppress AT-SPI / dbind accessibility warnings when running under non-root / sudo environments
os.environ.setdefault("NO_AT_SPI", "1")
os.environ.setdefault("QT_ACCESSIBILITY", "0")
# Allow Chromium / QtWebEngine to initialize safely when executing as root or in elevated environments
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

import shlex
import subprocess

from PySide6.QtCore import QFile, QIODevice, QTime, QTimer, Qt, QThreadPool
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFontDialog,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSystemTrayIcon,
    QTableWidgetItem,
)

try:
    from PySide6.QtUiTools import QUiLoader
    HAS_UILOADER = True
except ImportError:
    HAS_UILOADER = False

from core.concat_engine import join_files, stitch_file_with_intro_outro
from core.config_manager import get_binary_path, get_config, save_config
from core.crop_engine import detect_black_bars
from core.engine import FFmpegTask
from core.estimations import estimate_size_mb
from core.mux_engine import MuxJobTask
from core.power_monitor import get_power_status
from core.presets import load_presets, save_presets
from core.probe import probe_file
from core.readme_viewer import ReadmeViewerDialog
from core.subs_engine import SubtitleTask
from core.theme_manager import ThemeManager
from core.tokens import substitute_tokens
from core.url_engine import UrlStreamTask


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
        self.is_paused = False
        self.current_font_size = 10
        self.sub_color_bgr_hex = "&H00FFFFFF"
        self.sub_jobs = []
        self.shutdown_seconds_left = 30
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.setInterval(1000)
        self.shutdown_timer.timeout.connect(self._on_shutdown_tick)

        # Delayed start schedule timer
        self.delay_seconds_left = 0
        self.delay_timer = QTimer(self)
        self.delay_timer.setInterval(1000)
        self.delay_timer.timeout.connect(self._on_delay_schedule_tick)

        # Linux Power & Battery monitor timer (checks every 5 seconds)
        self.power_timer = QTimer(self)
        self.power_timer.setInterval(5000)
        self.power_timer.timeout.connect(self._on_power_check_tick)
        self.power_timer.start()
        self.auto_paused_by_power = False

        self.load_ui()
        self.build_menu_bar()
        self.setup_queue_table()
        self.setup_system_tray()
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

        queue_menu.addSeparator()

        act_adv_filter = QAction("Advanced &Filter...", self)
        act_adv_filter.setShortcut("Ctrl+F")
        act_adv_filter.triggered.connect(self.open_queue_filter_dialog)
        queue_menu.addAction(act_adv_filter)

        act_conf_cols = QAction("Configure &Columns...", self)
        act_conf_cols.triggered.connect(self.open_custom_columns_dialog)
        queue_menu.addAction(act_conf_cols)

        queue_menu.addSeparator()

        act_delayed_start = QAction("Schedule &Delayed Start...", self)
        act_delayed_start.triggered.connect(self.open_delay_timer_dialog)
        queue_menu.addAction(act_delayed_start)

        # 3. Presets Menu
        preset_menu = menubar.addMenu("&Presets")
        act_manage_presets = QAction("&Presets Manager...", self)
        act_manage_presets.triggered.connect(self.open_presets_dialog)
        preset_menu.addAction(act_manage_presets)

        act_online_presets = QAction("&Online & Community Presets...", self)
        act_online_presets.triggered.connect(self.open_online_presets_dialog)
        preset_menu.addAction(act_online_presets)

        act_multi_presets = QAction("&Multiple Presets Batch Run...", self)
        act_multi_presets.triggered.connect(self.open_multi_presets_dialog)
        preset_menu.addAction(act_multi_presets)

        act_insert_var = QAction("&Insert Variable...", self)
        act_insert_var.triggered.connect(self.open_token_builder_dialog)
        preset_menu.addAction(act_insert_var)

        # 4. Tools Menu
        tools_menu = menubar.addMenu("&Tools")

        act_wizard = QAction("🧙 &Guided Task Wizard...", self)
        act_wizard.triggered.connect(self.open_task_wizard_dialog)
        tools_menu.addAction(act_wizard)

        tools_menu.addSeparator()

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

        act_batch_stitch = QAction("&Batch Intro / Outro Stitching...", self)
        act_batch_stitch.triggered.connect(self.open_batch_concat_dialog)
        tools_menu.addAction(act_batch_stitch)

        act_crop = QAction("&Crop & Black Bars Detection...", self)
        act_crop.triggered.connect(self.open_crop_dialog)
        tools_menu.addAction(act_crop)

        act_waveform = QAction("Audio &Waveform Visualizer...", self)
        act_waveform.triggered.connect(self.open_audio_waveform_dialog)
        tools_menu.addAction(act_waveform)

        act_screen_rec = QAction("Record Desktop &Screen (x11grab)...", self)
        act_screen_rec.triggered.connect(self.open_screen_record_dialog)
        tools_menu.addAction(act_screen_rec)

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

        act_stream_matrix = QAction("Interactive Stream &Routing Matrix...", self)
        act_stream_matrix.triggered.connect(self.open_stream_matrix_dialog)
        tools_menu.addAction(act_stream_matrix)

        act_renamer = QAction("Sequential &Batch File Renamer...", self)
        act_renamer.triggered.connect(self.open_batch_renamer_dialog)
        tools_menu.addAction(act_renamer)

        act_split = QAction("S&plit / Segment Media Files...", self)
        act_split.triggered.connect(self.open_split_video_dialog)
        tools_menu.addAction(act_split)

        act_chapters = QAction("&Chapter Markers Metadata Creator...", self)
        act_chapters.triggered.connect(self.open_chapters_dialog)
        tools_menu.addAction(act_chapters)

        act_log_viewer = QAction("View FFmpeg Full &Log File...", self)
        act_log_viewer.setShortcut("Ctrl+L")
        act_log_viewer.triggered.connect(self.open_log_viewer_dialog)
        tools_menu.addAction(act_log_viewer)

        tools_menu.addSeparator()

        act_hooks = QAction("Post-Processing &Hooks...", self)
        act_hooks.triggered.connect(self.open_post_process_dialog)
        tools_menu.addAction(act_hooks)

        act_power = QAction("&Battery & Power Management...", self)
        act_power.triggered.connect(self.open_battery_power_dialog)
        tools_menu.addAction(act_power)

        act_output_path = QAction("&Manual Output Path Hierarchy...", self)
        act_output_path.triggered.connect(self.open_output_path_dialog)
        tools_menu.addAction(act_output_path)

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

                for color, _variants in sorted(color_families.items()):
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

    def setup_queue_table(self):
        table = self.ui.tableQueue
        table.horizontalHeader().setStretchLastSection(True)
        table.cellDoubleClicked.connect(self.on_queue_cell_double_clicked)
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(self.show_queue_context_menu)
        self.apply_column_visibility()

    def on_queue_cell_double_clicked(self, row, col):
        if col == 1:
            self.open_frame_preview_dialog(row)
        else:
            self.open_media_info_dialog()

    def connect_signals(self):
        # Queue toolbar buttons
        self.ui.btnAddFiles.clicked.connect(self.on_add_files)
        self.ui.btnAddFolder.clicked.connect(self.on_add_folder)
        self.ui.btnRemoveSelected.clicked.connect(self.on_remove_selected)
        self.ui.btnClearQueue.clicked.connect(self.on_clear_queue)
        self.ui.btnCleanErrors.clicked.connect(self.on_clean_errors)
        self.ui.txtFilterQueue.textChanged.connect(self.on_filter_queue)
        if hasattr(self.ui, "btnAdvancedFilter"):
            self.ui.btnAdvancedFilter.clicked.connect(self.open_queue_filter_dialog)
        if hasattr(self.ui, "btnConfigureColumns"):
            self.ui.btnConfigureColumns.clicked.connect(self.open_custom_columns_dialog)

        # New Queue Toolbar actions
        self.ui.btnMoveUp.clicked.connect(self.on_move_up)
        self.ui.btnMoveDown.clicked.connect(self.on_move_down)
        self.ui.btnRequeue.clicked.connect(self.on_requeue_selected)
        self.ui.btnIncreaseFont.clicked.connect(self.on_increase_font)
        self.ui.btnDecreaseFont.clicked.connect(self.on_decrease_font)

        # Quick tools
        self.ui.btnTryPreset.clicked.connect(self.on_try_preset)
        self.ui.btnShowConsole.clicked.connect(self.on_show_console_cmd)
        self.ui.btnTrimTool.clicked.connect(self.open_trim_dialog)
        self.ui.btnJoinTool.clicked.connect(self.open_join_dialog)
        self.ui.btnCropTool.clicked.connect(self.open_crop_dialog)
        self.ui.btnAudioWaveform.clicked.connect(self.open_audio_waveform_dialog)
        self.ui.btnScreenCapture.clicked.connect(self.open_screen_record_dialog)
        self.ui.btnMultiPresetsBatch.clicked.connect(self.open_multi_presets_dialog)
        self.ui.btnOpenOutputDirQuick.clicked.connect(self.on_open_output_dir)
        self.ui.btnInsertVariable.clicked.connect(self.open_token_builder_dialog)

        # Execution controls
        self.ui.btnPause.clicked.connect(self.on_toggle_pause)
        self.ui.btnSkipCurrent.clicked.connect(self.on_skip_current_file)
        self.ui.btnAbortAll.clicked.connect(self.stop_processing)

        # Shutdown controls
        self.ui.chkAutoShutdown.toggled.connect(self.ui.comboShutdownAction.setEnabled)
        self.ui.btnCancelShutdown.clicked.connect(self.cancel_auto_shutdown)

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
        self.ui.btnRemoveUrl.clicked.connect(self.on_remove_url)
        self.ui.btnUrlMoveUp.clicked.connect(self.on_url_move_up)
        self.ui.btnUrlMoveDown.clicked.connect(self.on_url_move_down)
        self.ui.btnValidateUrls.clicked.connect(self.on_validate_urls)
        self.ui.btnRemoveUrlErrors.clicked.connect(self.on_remove_url_errors)
        self.ui.btnBrowseCookie.clicked.connect(self.on_browse_cookie_file)
        self.ui.btnBrowseUrlOutputDir.clicked.connect(self.on_browse_url_output_dir)
        self.ui.btnSkipActiveUrl.clicked.connect(self.on_skip_active_url)
        self.ui.btnStartUrlDownloads.clicked.connect(self.start_url_downloads)
        self.ui.tableUrls.horizontalHeader().setStretchLastSection(True)
        self.ui.tableUrls.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.tableUrls.customContextMenuRequested.connect(self.show_url_context_menu)
        self.active_url_tasks = []

        # Stream Multiplex (Tab 2) controls
        self.ui.btnAddMuxJob.clicked.connect(self.on_add_mux_job)
        self.ui.btnRemoveMuxJob.clicked.connect(self.on_remove_mux_job)
        self.ui.btnMuxClear.clicked.connect(self.on_clear_mux_jobs)
        self.ui.btnMuxMoveUp.clicked.connect(self.on_mux_move_up)
        self.ui.btnMuxMoveDown.clicked.connect(self.on_mux_move_down)
        self.ui.btnMuxSetDefault.clicked.connect(self.on_mux_toggle_default)
        self.ui.btnMuxExtractTrack.clicked.connect(self.on_mux_extract_track)
        self.ui.btnBrowseMuxOutputDir.clicked.connect(self.on_browse_mux_output_dir)
        self.ui.btnStartMux.clicked.connect(self.start_mux_jobs)
        self.ui.tableMux.horizontalHeader().setStretchLastSection(True)
        self.ui.tableMux.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.tableMux.customContextMenuRequested.connect(self.show_mux_context_menu)
        self.mux_jobs = []

        # Subtitles (Tab 3) controls
        self.ui.btnAddSubPair.clicked.connect(self.on_add_sub_pair)
        self.ui.btnAutoMatchSubs.clicked.connect(self.on_auto_match_subs)
        self.ui.btnRemoveSubPair.clicked.connect(self.on_remove_sub_pair)
        self.ui.btnClearSubs.clicked.connect(self.on_clear_subs)
        self.ui.btnSubMoveUp.clicked.connect(self.on_sub_move_up)
        self.ui.btnSubMoveDown.clicked.connect(self.on_sub_move_down)
        self.ui.btnChooseSubFont.clicked.connect(self.on_choose_sub_font)
        self.ui.btnChooseSubColor.clicked.connect(self.on_choose_sub_color)
        self.ui.btnSubSizeMinus.clicked.connect(lambda: self.ui.spinSubFontSize.setValue(max(8, self.ui.spinSubFontSize.value() - 2)))
        self.ui.btnSubSizePlus.clicked.connect(lambda: self.ui.spinSubFontSize.setValue(min(96, self.ui.spinSubFontSize.value() + 2)))
        self.ui.btnBrowseSubOutputDir.clicked.connect(self.on_browse_sub_output_dir)
        self.ui.btnPreviewSub.clicked.connect(self.on_preview_subtitles)
        self.ui.btnStartSubs.clicked.connect(self.start_subs_processing)
        self.ui.tableSubs.horizontalHeader().setStretchLastSection(True)
        self.ui.tableSubs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.tableSubs.customContextMenuRequested.connect(self.show_subs_context_menu)
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
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    u = line.strip()
                    if u and (u.startswith("http://") or u.startswith("https://") or u.startswith("rtsp://")):
                        self.add_url_to_table(u)

    def _renumber_urls(self):
        table = self.ui.tableUrls
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it:
                it.setText(str(r + 1))
        self.ui.lblUrlCount.setText(f"{table.rowCount()} URLs")

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
        self._renumber_urls()

    def on_remove_url(self):
        table = self.ui.tableUrls
        selected = table.selectedIndexes()
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        for r in rows:
            table.removeRow(r)
        self._renumber_urls()

    def on_clear_urls(self):
        self.ui.tableUrls.setRowCount(0)
        self._renumber_urls()

    def on_url_move_up(self):
        table = self.ui.tableUrls
        selected = table.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected))
        if rows[0] == 0:
            return
        for r in rows:
            for col in range(table.columnCount()):
                if col == 3:
                    w1 = table.cellWidget(r - 1, col)
                    w2 = table.cellWidget(r, col)
                    val1 = w1.value() if w1 else 0
                    val2 = w2.value() if w2 else 0
                    if w1: w1.setValue(val2)
                    if w2: w2.setValue(val1)
                else:
                    item1 = table.takeItem(r - 1, col)
                    item2 = table.takeItem(r, col)
                    table.setItem(r - 1, col, item2)
                    table.setItem(r, col, item1)
        self._renumber_urls()
        table.clearSelection()
        for r in rows:
            table.selectRow(r - 1)

    def on_url_move_down(self):
        table = self.ui.tableUrls
        selected = table.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        if rows[0] >= table.rowCount() - 1:
            return
        for r in rows:
            for col in range(table.columnCount()):
                if col == 3:
                    w1 = table.cellWidget(r + 1, col)
                    w2 = table.cellWidget(r, col)
                    val1 = w1.value() if w1 else 0
                    val2 = w2.value() if w2 else 0
                    if w1: w1.setValue(val2)
                    if w2: w2.setValue(val1)
                else:
                    item1 = table.takeItem(r + 1, col)
                    item2 = table.takeItem(r, col)
                    table.setItem(r + 1, col, item2)
                    table.setItem(r, col, item1)
        self._renumber_urls()
        table.clearSelection()
        for r in rows:
            table.selectRow(r + 1)

    def on_validate_urls(self):
        """Validates URL stream responsiveness using fast HEAD/probe requests."""
        table = self.ui.tableUrls
        if table.rowCount() == 0:
            QMessageBox.information(self, "No URLs", "Please add URLs to validate.")
            return

        import urllib.request
        valid_count = 0
        broken_count = 0
        self.ui.txtLog.appendPlainText(">>> Validating URLs in queue...")

        for r in range(table.rowCount()):
            url = table.item(r, 1).text().strip()
            st_item = table.item(r, 4)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
                with urllib.request.urlopen(req, timeout=5) as response:
                    code = response.getcode()
                    if 200 <= code < 400:
                        if st_item:
                            st_item.setText("Valid (HTTP 200)")
                        valid_count += 1
                    else:
                        if st_item:
                            st_item.setText(f"HTTP {code}")
                        broken_count += 1
            except Exception as e:
                # Fallback check for yt-dlp supported streams
                if st_item:
                    st_item.setText("Offline / Dead")
                broken_count += 1

        self.ui.txtLog.appendPlainText(f">>> Validation complete: {valid_count} valid, {broken_count} broken/offline.")
        QMessageBox.information(self, "Validation Complete", f"Validation finished:\n• Valid: {valid_count}\n• Broken / Offline: {broken_count}")

    def on_remove_url_errors(self):
        table = self.ui.tableUrls
        rows_to_remove = []
        for r in range(table.rowCount()):
            st = table.item(r, 4)
            if st and any(k in st.text().lower() for k in ["dead", "offline", "failed", "error", "404", "403"]):
                rows_to_remove.append(r)
        for r in sorted(rows_to_remove, reverse=True):
            table.removeRow(r)
        self._renumber_urls()
        QMessageBox.information(self, "Clean Complete", f"Removed {len(rows_to_remove)} dead / broken URL rows.")

    def on_browse_cookie_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Cookies File", "", "Text Files (*.txt);;All Files (*)")
        if f:
            self.ui.txtCookieFile.setText(f)

    def on_browse_url_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select URL Output Directory")
        if d:
            self.ui.txtUrlOutputDir.setText(d)

    def on_skip_active_url(self):
        if hasattr(self, "active_url_tasks"):
            for t in self.active_url_tasks:
                if not t.is_cancelled and t.process and t.process.poll() is None:
                    self.ui.txtLog.appendPlainText(f">>> Skipping active stream: {t.url}")
                    t.cancel()
                    break

    def show_url_context_menu(self, pos):
        table = self.ui.tableUrls
        menu = QMenu(self)

        act_add = menu.addAction("Add URL...")
        act_import = menu.addAction("Import URLs from File...")
        act_paste = menu.addAction("Paste URL from Clipboard")
        menu.addSeparator()

        selected_indexes = table.selectedIndexes()
        has_sel = len(selected_indexes) > 0

        act_copy = menu.addAction("Copy URL")
        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        menu.addSeparator()
        act_rem = menu.addAction("Remove Selected")
        act_clean = menu.addAction("Remove Broken URLs")
        act_clr = menu.addAction("Clear List")

        act_copy.setEnabled(has_sel)
        act_up.setEnabled(has_sel)
        act_down.setEnabled(has_sel)
        act_rem.setEnabled(has_sel)

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == act_add:
            self.on_add_url()
        elif action == act_import:
            self.on_import_urls()
        elif action == act_paste:
            cb_text = QApplication.clipboard().text().strip()
            if cb_text and any(cb_text.startswith(p) for p in ["http://", "https://", "rtsp://", "rtmp://"]):
                self.add_url_to_table(cb_text)
        elif action == act_copy and has_sel:
            row = table.selectedIndexes()[0].row()
            QApplication.clipboard().setText(table.item(row, 1).text())
        elif action == act_up:
            self.on_url_move_up()
        elif action == act_down:
            self.on_url_move_down()
        elif action == act_rem:
            self.on_remove_url()
        elif action == act_clean:
            self.on_remove_url_errors()
        elif action == act_clr:
            self.on_clear_urls()

    def start_url_downloads(self):
        table = self.ui.tableUrls
        if table.rowCount() == 0:
            QMessageBox.information(self, "No URLs", "Please add at least one stream URL first.")
            return

        dest_dir = self.ui.txtUrlOutputDir.text().strip()
        if not dest_dir or not os.path.isdir(dest_dir):
            dest_dir = os.path.expanduser("~/Downloads")

        custom_params = self.ui.txtUrlParams.text().strip()
        cookie_file = self.ui.txtCookieFile.text().strip()

        self.ui.btnStartUrlDownloads.setEnabled(False)
        self.ui.btnSkipActiveUrl.setEnabled(True)
        self.ui.txtLog.appendPlainText(">>> Starting Batch URL Stream Downloads...")

        self.active_url_tasks = []

        for r in range(table.rowCount()):
            url = table.item(r, 1).text()
            filename = table.item(r, 2).text()
            out_path = os.path.join(dest_dir, filename)

            task = UrlStreamTask(
                url,
                out_path,
                custom_params=custom_params,
                cookie_file=cookie_file
            )
            task.signals.progress.connect(self.on_url_progress)
            task.signals.finished.connect(self.on_url_finished)
            task.signals.log.connect(self.on_task_log)
            self.active_url_tasks.append(task)
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
            self.ui.btnSkipActiveUrl.setEnabled(False)
            self.ui.txtLog.appendPlainText(">>> Batch URL Downloads Finished.")
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

            # Global tab settings override if set
            tab_container = self.ui.comboMuxContainerFormat.currentText().strip()
            container = tab_container if tab_container else dialog.comboMuxContainer.currentText()
            stream_copy = self.ui.chkMuxStreamCopy.isChecked()

            custom_out_dir = self.ui.txtMuxOutputDir.text().strip()
            src_dir, src_filename = os.path.split(base_vid)
            base_name, _ = os.path.splitext(src_filename)
            target_folder = custom_out_dir if (custom_out_dir and os.path.isdir(custom_out_dir)) else src_dir
            out_file = os.path.join(target_folder, f"{base_name}_muxed.{container}")

            job = {
                "base_video": base_vid,
                "audio_track": audio_file,
                "audio_lang": audio_lang,
                "sub_track": sub_file,
                "sub_lang": sub_lang,
                "default_audio": True,
                "default_sub": False,
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
            table.setItem(row, 3, QTableWidgetItem(audio_lang if audio_file else "-"))
            table.setItem(row, 4, QTableWidgetItem(os.path.basename(sub_file) if sub_file else "None"))
            table.setItem(row, 5, QTableWidgetItem(sub_lang if sub_file else "-"))
            table.setItem(row, 6, QTableWidgetItem("Audio (Default)" if audio_file else "-"))
            table.setItem(row, 7, QTableWidgetItem(os.path.basename(out_file)))
            table.setItem(row, 8, QTableWidgetItem("Ready"))
            self.ui.lblMuxJobCount.setText(f"{len(self.mux_jobs)} jobs")
            dialog.accept()

        dialog.muxDialogButtonBox.accepted.connect(accept_job)
        dialog.muxDialogButtonBox.rejected.connect(dialog.reject)
        dialog.exec()

    def _renumber_mux_jobs(self):
        table = self.ui.tableMux
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it:
                it.setText(str(r + 1))
        self.ui.lblMuxJobCount.setText(f"{len(self.mux_jobs)} jobs")

    def on_remove_mux_job(self):
        table = self.ui.tableMux
        selected = table.selectedIndexes()
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        for r in rows:
            table.removeRow(r)
            if r < len(self.mux_jobs):
                del self.mux_jobs[r]
        self._renumber_mux_jobs()

    def on_clear_mux_jobs(self):
        self.ui.tableMux.setRowCount(0)
        self.mux_jobs.clear()
        self.ui.lblMuxJobCount.setText("0 jobs")

    def on_mux_move_up(self):
        table = self.ui.tableMux
        selected = table.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected))
        if rows[0] == 0:
            return
        for r in rows:
            self.mux_jobs[r - 1], self.mux_jobs[r] = self.mux_jobs[r], self.mux_jobs[r - 1]
            for col in range(table.columnCount()):
                item1 = table.takeItem(r - 1, col)
                item2 = table.takeItem(r, col)
                table.setItem(r - 1, col, item2)
                table.setItem(r, col, item1)
        self._renumber_mux_jobs()
        table.clearSelection()
        for r in rows:
            table.selectRow(r - 1)

    def on_mux_move_down(self):
        table = self.ui.tableMux
        selected = table.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        if rows[0] >= table.rowCount() - 1:
            return
        for r in rows:
            self.mux_jobs[r + 1], self.mux_jobs[r] = self.mux_jobs[r], self.mux_jobs[r + 1]
            for col in range(table.columnCount()):
                item1 = table.takeItem(r + 1, col)
                item2 = table.takeItem(r, col)
                table.setItem(r + 1, col, item2)
                table.setItem(r, col, item1)
        self._renumber_mux_jobs()
        table.clearSelection()
        for r in rows:
            table.selectRow(r + 1)

    def on_mux_toggle_default(self):
        table = self.ui.tableMux
        selected_rows = sorted(set(idx.row() for idx in table.selectedIndexes()))
        if not selected_rows:
            return
        for r in selected_rows:
            if r < len(self.mux_jobs):
                job = self.mux_jobs[r]
                # Toggle: Audio Default -> Sub Default -> Both -> None
                cur_audio = job.get("default_audio", True)
                cur_sub = job.get("default_sub", False)
                if cur_audio and not cur_sub:
                    job["default_audio"] = False
                    job["default_sub"] = True
                    desc = "Sub (Default)"
                elif not cur_audio and cur_sub:
                    job["default_audio"] = True
                    job["default_sub"] = True
                    desc = "Audio + Sub (Default)"
                elif cur_audio and cur_sub:
                    job["default_audio"] = False
                    job["default_sub"] = False
                    desc = "None"
                else:
                    job["default_audio"] = True
                    job["default_sub"] = False
                    desc = "Audio (Default)"
                table.setItem(r, 6, QTableWidgetItem(desc))

    def on_mux_extract_track(self):
        table = self.ui.tableMux
        selected_rows = sorted(set(idx.row() for idx in table.selectedIndexes()))
        if not selected_rows:
            QMessageBox.information(self, "No Job Selected", "Please select a multiplex job first.")
            return
        row = selected_rows[0]
        if row >= len(self.mux_jobs):
            return
        job = self.mux_jobs[row]

        # Options dialog: extract audio or sub or video
        menu = QMenu(self)
        act_extract_audio = menu.addAction(f"Extract Audio Track ({os.path.basename(job['audio_track']) if job['audio_track'] else 'embedded'})")
        act_extract_sub = menu.addAction(f"Extract Subtitle Track ({os.path.basename(job['sub_track']) if job['sub_track'] else 'embedded'})")
        act_extract_audio.setEnabled(bool(job['audio_track'] or job['base_video']))
        act_extract_sub.setEnabled(bool(job['sub_track'] or job['base_video']))

        action = menu.exec(self.cursor().pos())
        if not action:
            return

        ffmpeg_bin = get_binary_path("ffmpeg")
        if action == act_extract_audio:
            src = job['audio_track'] or job['base_video']
            src_dir, src_file = os.path.split(src)
            base, _ = os.path.splitext(src_file)
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Audio Track", os.path.join(src_dir, f"{base}_track.aac"), "Audio (*.aac *.mp3 *.flac *.m4a *.wav)")
            if save_path:
                cmd = [ffmpeg_bin, "-y", "-i", src, "-vn", "-c:a", "copy", save_path]
                self.ui.txtLog.appendPlainText(f">>> Extracting Audio Track: {' '.join(cmd)}")
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                self.ui.txtLog.appendPlainText(res.stdout)
                if res.returncode == 0:
                    QMessageBox.information(self, "Extraction Complete", f"Audio track saved to:\n{save_path}")
                else:
                    QMessageBox.warning(self, "Extraction Failed", f"Failed to extract audio track.\n{res.stdout[-300:]}")
        elif action == act_extract_sub:
            src = job['sub_track'] or job['base_video']
            src_dir, src_file = os.path.split(src)
            base, _ = os.path.splitext(src_file)
            save_path, _ = QFileDialog.getSaveFileName(self, "Save Subtitle Track", os.path.join(src_dir, f"{base}_track.srt"), "Subtitles (*.srt *.ass *.vtt)")
            if save_path:
                cmd = [ffmpeg_bin, "-y", "-i", src, "-an", "-vn", "-c:s", "copy", save_path]
                self.ui.txtLog.appendPlainText(f">>> Extracting Subtitle Track: {' '.join(cmd)}")
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                self.ui.txtLog.appendPlainText(res.stdout)
                if res.returncode == 0:
                    QMessageBox.information(self, "Extraction Complete", f"Subtitle track saved to:\n{save_path}")
                else:
                    QMessageBox.warning(self, "Extraction Failed", f"Failed to extract subtitle track.\n{res.stdout[-300:]}")

    def show_mux_context_menu(self, pos):
        table = self.ui.tableMux
        menu = QMenu(self)

        act_add = menu.addAction("Add Mux Job...")
        menu.addSeparator()

        selected_indexes = table.selectedIndexes()
        has_sel = len(selected_indexes) > 0

        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        act_def = menu.addAction("Toggle Default Flag")
        act_ext = menu.addAction("Extract / Save Track...")
        menu.addSeparator()
        act_rem = menu.addAction("Remove Selected Job")
        act_clr = menu.addAction("Clear All Jobs")

        act_up.setEnabled(has_sel)
        act_down.setEnabled(has_sel)
        act_def.setEnabled(has_sel)
        act_ext.setEnabled(has_sel)
        act_rem.setEnabled(has_sel)

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == act_add:
            self.on_add_mux_job()
        elif action == act_up:
            self.on_mux_move_up()
        elif action == act_down:
            self.on_mux_move_down()
        elif action == act_def:
            self.on_mux_toggle_default()
        elif action == act_ext:
            self.on_mux_extract_track()
        elif action == act_rem:
            self.on_remove_mux_job()
        elif action == act_clr:
            self.on_clear_mux_jobs()

    def on_browse_mux_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Mux Output Directory")
        if d:
            self.ui.txtMuxOutputDir.setText(d)

    def start_mux_jobs(self):
        if not self.mux_jobs:
            QMessageBox.information(self, "No Jobs", "Please add at least one multiplex job first.")
            return

        self.ui.btnStartMux.setEnabled(False)
        self.ui.txtLog.appendPlainText(">>> Starting Multiplex Jobs...")

        # Global overrides from tab controls
        stream_copy_flag = self.ui.chkMuxStreamCopy.isChecked()
        custom_params = self.ui.txtMuxCustomParam.text().strip()
        custom_out_dir = self.ui.txtMuxOutputDir.text().strip()
        container_fmt = self.ui.comboMuxContainerFormat.currentText().strip() or "mkv"

        for idx, job in enumerate(self.mux_jobs):
            # Recalculate output path if custom directory or format is specified
            base_vid = job["base_video"]
            src_dir, src_filename = os.path.split(base_vid)
            base_name, _ = os.path.splitext(src_filename)
            target_dir = custom_out_dir if (custom_out_dir and os.path.isdir(custom_out_dir)) else src_dir
            final_out_path = os.path.join(target_dir, f"{base_name}_muxed.{container_fmt}")
            job["out_path"] = final_out_path

            table_item_out = self.ui.tableMux.item(idx, 7)
            if table_item_out:
                table_item_out.setText(os.path.basename(final_out_path))

            table_item_status = self.ui.tableMux.item(idx, 8)
            if table_item_status:
                table_item_status.setText("Muxing...")

            task = MuxJobTask(
                job["base_video"],
                job["audio_track"],
                job["audio_lang"],
                job["sub_track"],
                job["sub_lang"],
                job["out_path"],
                stream_copy=stream_copy_flag,
                default_audio=job.get("default_audio", True),
                default_sub=job.get("default_sub", False),
                custom_params=custom_params
            )
            task.signals.finished.connect(self.on_mux_finished)
            task.signals.log.connect(self.on_task_log)
            self.threadpool.start(task)

    def on_mux_finished(self, base_video: str, success: bool, msg: str):
        table = self.ui.tableMux
        for r in range(table.rowCount()):
            if r < len(self.mux_jobs) and self.mux_jobs[r]["base_video"] == base_video:
                item = table.item(r, 8)
                if item:
                    item.setText("Completed" if success else f"Failed: {msg}")
                break

        # Check if all mux jobs finished
        all_done = True
        for r in range(table.rowCount()):
            st = table.item(r, 8)
            if st and st.text() in ["Ready", "Muxing..."]:
                all_done = False
                break
        if all_done:
            self.ui.btnStartMux.setEnabled(True)
            self.ui.txtLog.appendPlainText(">>> All Multiplex Jobs Finished.")
    # Subtitle Processing (Tab 3)
    def on_choose_sub_font(self):
        cur_font_name = self.ui.txtSubFont.text().strip() or "Sans"
        cur_size = self.ui.spinSubFontSize.value()
        from PySide6.QtGui import QFont
        initial_font = QFont(cur_font_name, cur_size)
        ok, font = QFontDialog.getFont(initial_font, self, "Choose Subtitle Font")
        if ok:
            self.ui.txtSubFont.setText(font.family())
            self.ui.spinSubFontSize.setValue(font.pointSize())

    def on_choose_sub_color(self):
        from PySide6.QtGui import QColor
        color = QColorDialog.getColor(QColor(255, 255, 255), self, "Choose Subtitle Font Color")
        if color.isValid():
            # In ASS subtitles, PrimaryColour is in format &HAABBGGRR (Alpha, Blue, Green, Red)
            # Default Alpha = 00
            b = color.blue()
            g = color.green()
            r = color.red()
            self.sub_color_bgr_hex = f"&H00{b:02X}{g:02X}{r:02X}"
            hex_name = color.name()
            self.ui.btnChooseSubColor.setText(f"Color: {hex_name}")
            self.ui.btnChooseSubColor.setStyleSheet(f"background-color: {hex_name}; color: {'black' if color.lightness() > 128 else 'white'}; font-weight: bold;")

    def on_browse_sub_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Subtitle Output Directory")
        if d:
            self.ui.txtSubOutputDir.setText(d)

    def on_preview_subtitles(self):
        """Generates a fast 10-second sample with current subtitle style and launches player."""
        if not self.sub_jobs:
            QMessageBox.information(self, "No File", "Please add at least one video to preview subtitles.")
            return
        job = self.sub_jobs[0]
        src_path = job["video_path"]
        sub_path = job.get("sub_path", "")
        src_dir, src_file = os.path.split(src_path)
        base, _ = os.path.splitext(src_file)
        preview_out = os.path.join(src_dir, f"{base}_sub_preview_10s.mp4")

        ffmpeg_bin = get_binary_path("ffmpeg")
        font_name = self.ui.txtSubFont.text().strip() or "Sans"
        font_size = self.ui.spinSubFontSize.value()
        color_hex = getattr(self, "sub_color_bgr_hex", "&H00FFFFFF")
        use_embedded = self.ui.chkUseEmbeddedSub.isChecked()

        if use_embedded or not sub_path:
            escaped_vid = src_path.replace(":", r"\:").replace(chr(39), r"'")
            sub_filter = f"subtitles='{escaped_vid}':force_style='FontName={font_name},FontSize={font_size},PrimaryColour={color_hex}'"
        else:
            escaped_sub = sub_path.replace(":", r"\:").replace(chr(39), r"'")
            sub_filter = f"subtitles='{escaped_sub}':force_style='FontName={font_name},FontSize={font_size},PrimaryColour={color_hex}'"

        cmd = [
            ffmpeg_bin, "-y",
            "-ss", "00:00:30",
            "-i", src_path,
            "-t", "10",
            "-vf", sub_filter,
            "-c:a", "aac",
            preview_out
        ]
        self.ui.txtLog.appendPlainText(f">>> Generating 10s Subtitle Preview: {' '.join(cmd)}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.ui.txtLog.appendPlainText(res.stdout)
        if res.returncode == 0:
            self.ui.txtLog.appendPlainText(f">>> Subtitle preview generated: {preview_out}")
            # Attempt to launch with default player or mpv/vlc
            subprocess.Popen(["xdg-open", preview_out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            QMessageBox.information(self, "Preview Ready", f"10-second subtitle preview generated successfully:\n{preview_out}")
        else:
            QMessageBox.warning(self, "Preview Failed", f"Failed to generate preview:\n{res.stdout[-300:]}")

    def on_add_sub_pair(self):
        vid, _ = QFileDialog.getOpenFileName(self, "Select Video File", "", "Videos (*.mp4 *.mkv *.avi *.mov *.ts)")
        if not vid:
            return
        use_embedded = self.ui.chkUseEmbeddedSub.isChecked()
        sub = ""
        if not use_embedded:
            sub, _ = QFileDialog.getOpenFileName(self, "Select Matching Subtitle File", os.path.dirname(vid), "Subtitles (*.srt *.ass *.vtt *.sub)")
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

    def _renumber_sub_jobs(self):
        table = self.ui.tableSubs
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it:
                it.setText(str(r + 1))
        self.ui.lblSubCount.setText(f"{len(self.sub_jobs)} items")

    def on_remove_sub_pair(self):
        table = self.ui.tableSubs
        selected = table.selectedIndexes()
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        for r in rows:
            table.removeRow(r)
            if r < len(self.sub_jobs):
                del self.sub_jobs[r]
        self._renumber_sub_jobs()

    def on_sub_move_up(self):
        table = self.ui.tableSubs
        selected = table.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected))
        if rows[0] == 0:
            return
        for r in rows:
            self.sub_jobs[r - 1], self.sub_jobs[r] = self.sub_jobs[r], self.sub_jobs[r - 1]
            for col in range(table.columnCount()):
                item1 = table.takeItem(r - 1, col)
                item2 = table.takeItem(r, col)
                table.setItem(r - 1, col, item2)
                table.setItem(r, col, item1)
        self._renumber_sub_jobs()
        table.clearSelection()
        for r in rows:
            table.selectRow(r - 1)

    def on_sub_move_down(self):
        table = self.ui.tableSubs
        selected = table.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        if rows[0] >= table.rowCount() - 1:
            return
        for r in rows:
            self.sub_jobs[r + 1], self.sub_jobs[r] = self.sub_jobs[r], self.sub_jobs[r + 1]
            for col in range(table.columnCount()):
                item1 = table.takeItem(r + 1, col)
                item2 = table.takeItem(r, col)
                table.setItem(r + 1, col, item2)
                table.setItem(r, col, item1)
        self._renumber_sub_jobs()
        table.clearSelection()
        for r in rows:
            table.selectRow(r + 1)

    def show_subs_context_menu(self, pos):
        table = self.ui.tableSubs
        menu = QMenu(self)

        act_add = menu.addAction("Pair Video & Subtitle...")
        act_auto = menu.addAction("Auto-Match from Folder...")
        act_prev = menu.addAction("Preview Subtitles (10s)")
        menu.addSeparator()

        selected_indexes = table.selectedIndexes()
        has_sel = len(selected_indexes) > 0

        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        menu.addSeparator()
        act_rem = menu.addAction("Remove Selected")
        act_clr = menu.addAction("Clear List")

        act_prev.setEnabled(has_sel)
        act_up.setEnabled(has_sel)
        act_down.setEnabled(has_sel)
        act_rem.setEnabled(has_sel)

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == act_add:
            self.on_add_sub_pair()
        elif action == act_auto:
            self.on_auto_match_subs()
        elif action == act_prev:
            self.on_preview_subtitles()
        elif action == act_up:
            self.on_sub_move_up()
        elif action == act_down:
            self.on_sub_move_down()
        elif action == act_rem:
            self.on_remove_sub_pair()
        elif action == act_clr:
            self.on_clear_subs()

    def add_sub_job_to_table(self, vid_path: str, sub_path: str):
        is_burn = self.ui.radBurnSubs.isChecked()
        mode_str = "Burn-in (Hardcode)" if is_burn else "Embed Soft"
        lang = self.ui.comboSubLanguage.currentText()
        if "(" in lang and ")" in lang:
            lang_code = lang[lang.find("(") + 1 : lang.rfind(")")]
        else:
            lang_code = "eng"

        font_name = self.ui.txtSubFont.text().strip() or "Sans"
        font_size = self.ui.spinSubFontSize.value()
        use_embedded = self.ui.chkUseEmbeddedSub.isChecked()

        job = {
            "video_path": vid_path,
            "sub_path": sub_path,
            "mode": "burn" if is_burn else "embed",
            "lang": lang_code,
            "font_name": font_name,
            "font_size": font_size,
            "use_embedded": use_embedded
        }
        self.sub_jobs.append(job)

        table = self.ui.tableSubs
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        table.setItem(row, 1, QTableWidgetItem(os.path.basename(vid_path)))
        sub_desc = "[Embedded Stream]" if (use_embedded or not sub_path) else os.path.basename(sub_path)
        table.setItem(row, 2, QTableWidgetItem(sub_desc))
        table.setItem(row, 3, QTableWidgetItem(mode_str))
        table.setItem(row, 4, QTableWidgetItem(f"{font_name} ({font_size}pt)"))
        table.setItem(row, 5, QTableWidgetItem(lang_code))
        table.setItem(row, 6, QTableWidgetItem("Ready"))
        self.ui.lblSubCount.setText(f"{len(self.sub_jobs)} items")

    def on_clear_subs(self):
        self.ui.tableSubs.setRowCount(0)
        self.sub_jobs.clear()
        self.ui.lblSubCount.setText("0 items")

    def start_subs_processing(self):
        if not self.sub_jobs:
            QMessageBox.information(self, "No Jobs", "Please add at least one subtitle pair first.")
            return

        self.ui.btnStartSubs.setEnabled(False)
        self.ui.txtLog.appendPlainText(">>> Starting Subtitle Processing Jobs...")

        dest_dir = self.ui.txtSubOutputDir.text().strip()
        fmt_choice = self.ui.comboSubContainerFormat.currentText().strip()

        for _idx, job in enumerate(self.sub_jobs):
            src_path = job["video_path"]
            src_dir, src_file = os.path.split(src_path)
            base_name, ext = os.path.splitext(src_file)

            if dest_dir and os.path.isdir(dest_dir):
                target_folder = dest_dir
            else:
                target_folder = src_dir

            if fmt_choice and fmt_choice != "Same as source":
                target_ext = f".{fmt_choice}"
            elif job["mode"] == "embed":
                target_ext = ".mkv"
            else:
                target_ext = ext

            out_path = os.path.join(target_folder, f"{base_name}_subbed{target_ext}")

            color_hex = getattr(self, "sub_color_bgr_hex", "&H00FFFFFF")
            task = SubtitleTask(
                job["video_path"],
                job["sub_path"],
                job["mode"],
                job["font_name"],
                job["font_size"],
                job["lang"],
                out_path,
                font_color_hex=color_hex,
                use_embedded=job.get("use_embedded", False)
            )
            task.signals.finished.connect(self.on_subs_finished)
            task.signals.log.connect(self.on_task_log)
            self.threadpool.start(task)

    def on_subs_finished(self, video_path: str, success: bool, msg: str):
        table = self.ui.tableSubs
        for r in range(table.rowCount()):
            if r < len(self.sub_jobs) and self.sub_jobs[r]["video_path"] == video_path:
                item = table.item(r, 6)
                if item:
                    item.setText("Completed" if success else f"Failed: {msg}")
                break

        all_done = True
        for r in range(table.rowCount()):
            st = table.item(r, 6)
            if st and st.text() in ["Ready", "Processing..."]:
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
        self._renumber_queue()

    def _renumber_queue(self):
        table = self.ui.tableQueue
        for r in range(table.rowCount()):
            it = table.item(r, 0)
            if it:
                it.setText(str(r + 1))
            if r < len(self.queue_items):
                self.queue_items[r]["row"] = r

    def on_move_up(self):
        table = self.ui.tableQueue
        selected = table.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected))
        if rows[0] == 0:
            return  # Already at top
        for r in rows:
            # Swap items in self.queue_items
            self.queue_items[r - 1], self.queue_items[r] = self.queue_items[r], self.queue_items[r - 1]
            # Swap table row contents
            for col in range(table.columnCount()):
                if col == 7:
                    # Progress bar widget
                    w1 = table.cellWidget(r - 1, col)
                    w2 = table.cellWidget(r, col)
                    val1 = w1.value() if w1 else 0
                    val2 = w2.value() if w2 else 0
                    if w1: w1.setValue(val2)
                    if w2: w2.setValue(val1)
                else:
                    item1 = table.takeItem(r - 1, col)
                    item2 = table.takeItem(r, col)
                    table.setItem(r - 1, col, item2)
                    table.setItem(r, col, item1)
        self._renumber_queue()
        table.clearSelection()
        for r in rows:
            table.selectRow(r - 1)

    def on_move_down(self):
        table = self.ui.tableQueue
        selected = table.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        if rows[0] >= table.rowCount() - 1:
            return  # Already at bottom
        for r in rows:
            self.queue_items[r + 1], self.queue_items[r] = self.queue_items[r], self.queue_items[r + 1]
            for col in range(table.columnCount()):
                if col == 7:
                    w1 = table.cellWidget(r + 1, col)
                    w2 = table.cellWidget(r, col)
                    val1 = w1.value() if w1 else 0
                    val2 = w2.value() if w2 else 0
                    if w1: w1.setValue(val2)
                    if w2: w2.setValue(val1)
                else:
                    item1 = table.takeItem(r + 1, col)
                    item2 = table.takeItem(r, col)
                    table.setItem(r + 1, col, item2)
                    table.setItem(r, col, item1)
        self._renumber_queue()
        table.clearSelection()
        for r in rows:
            table.selectRow(r + 1)

    def on_requeue_selected(self):
        table = self.ui.tableQueue
        selected_rows = set(idx.row() for idx in table.selectedIndexes())
        if not selected_rows:
            # Requeue all completed or failed items if none selected
            selected_rows = set(range(table.rowCount()))
        for r in selected_rows:
            if r < len(self.queue_items):
                self.queue_items[r]["status"] = "Pending"
            st = table.item(r, 8)
            if st:
                st.setText("Pending")
            bar = table.cellWidget(r, 7)
            if bar:
                bar.setValue(0)
        self.ui.overallProgress.setValue(0)
        self.ui.txtLog.appendPlainText(f">>> Requeued {len(selected_rows)} items back to Pending status.")

    def on_increase_font(self):
        if self.current_font_size < 20:
            self.current_font_size += 1
            font = self.ui.tableQueue.font()
            font.setPointSize(self.current_font_size)
            self.ui.tableQueue.setFont(font)

    def on_decrease_font(self):
        if self.current_font_size > 7:
            self.current_font_size -= 1
            font = self.ui.tableQueue.font()
            font.setPointSize(self.current_font_size)
            self.ui.tableQueue.setFont(font)

    def show_queue_context_menu(self, pos):
        table = self.ui.tableQueue
        menu = QMenu(self)

        act_add_files = menu.addAction("Add Files...")
        act_add_folder = menu.addAction("Add Folder...")
        act_paste_path = menu.addAction("Paste Path from Clipboard")
        menu.addSeparator()

        selected_indexes = table.selectedIndexes()
        has_sel = len(selected_indexes) > 0

        act_open_dir = menu.addAction("Open Source Directory")
        act_open_dest = menu.addAction("Open Output Directory")
        act_preview_frame = menu.addAction("Preview Frame (Thumbnail)")
        act_preview_cmd = menu.addAction("Copy FFmpeg Command")
        act_mediainfo = menu.addAction("Show Media Info (Ctrl+I)")
        menu.addSeparator()

        act_filter = menu.addAction("Filter Queue...")
        act_cols = menu.addAction("Configure Columns...")
        menu.addSeparator()

        act_up = menu.addAction("Move Up")
        act_down = menu.addAction("Move Down")
        act_requeue = menu.addAction("Requeue Item(s)")
        act_remove = menu.addAction("Remove Selected")
        act_clear = menu.addAction("Clear List")

        act_open_dir.setEnabled(has_sel)
        act_preview_frame.setEnabled(has_sel)
        act_preview_cmd.setEnabled(has_sel)
        act_mediainfo.setEnabled(has_sel)
        act_up.setEnabled(has_sel)
        act_down.setEnabled(has_sel)
        act_requeue.setEnabled(has_sel)
        act_remove.setEnabled(has_sel)

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if action == act_add_files:
            self.on_add_files()
        elif action == act_add_folder:
            self.on_add_folder()
        elif action == act_paste_path:
            clipboard_text = QApplication.clipboard().text().strip()
            if clipboard_text and os.path.exists(clipboard_text):
                if os.path.isdir(clipboard_text):
                    for root, _, files in os.walk(clipboard_text):
                        for f in sorted(files):
                            self.add_file_to_queue(os.path.join(root, f))
                else:
                    self.add_file_to_queue(clipboard_text)
        elif action == act_open_dir and has_sel:
            row = table.selectedIndexes()[0].row()
            if row < len(self.queue_items):
                p = os.path.dirname(self.queue_items[row]["path"])
                subprocess.Popen(["xdg-open", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif action == act_open_dest:
            self.on_open_output_dir()
        elif action == act_preview_frame and has_sel:
            row = table.selectedIndexes()[0].row()
            self.open_frame_preview_dialog(row)
        elif action == act_preview_cmd and has_sel:
            self.on_show_console_cmd()
        elif action == act_mediainfo and has_sel:
            self.open_media_info_dialog()
        elif action == act_filter:
            self.open_queue_filter_dialog()
        elif action == act_cols:
            self.open_custom_columns_dialog()
        elif action == act_up:
            self.on_move_up()
        elif action == act_down:
            self.on_move_down()
        elif action == act_requeue:
            self.on_requeue_selected()
        elif action == act_remove:
            self.on_remove_selected()
        elif action == act_clear:
            self.on_clear_queue()

    def on_open_output_dir(self):
        custom_dest = self.ui.radCustomFolder.isChecked()
        dest_dir = self.ui.txtOutputDir.text().strip()
        target_dir = None
        if custom_dest and dest_dir and os.path.isdir(dest_dir):
            target_dir = dest_dir
        elif self.queue_items:
            target_dir = os.path.dirname(self.queue_items[0]["path"])
        else:
            target_dir = os.path.expanduser("~")
        if target_dir and os.path.exists(target_dir):
            subprocess.Popen(["xdg-open", target_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
            QMessageBox.critical(self, "Test Failed", "FFmpeg returned an error. Check log console.")

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
        preset_keys = list(self.presets.keys())
        table.setRowCount(len(preset_keys))

        from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

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
            for _chk, name, pdata in selected:
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
                os.path.join(img_path, "%*.jpg")
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
            res = subprocess.run(cmd, capture_output=True, text=True)
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

        self.is_paused = False
        self.ui.btnStart.setEnabled(False)
        self.ui.btnPause.setEnabled(True)
        self.ui.btnPause.setText("Pause")
        self.ui.btnStop.setEnabled(True)
        self.ui.btnSkipCurrent.setEnabled(True)
        self.ui.btnAbortAll.setEnabled(True)
        self.ui.txtLog.appendPlainText(">>> Batch Processing Started...")

        self.active_tasks.clear()

        pre_input_val = self.ui.txtPreInput.text().strip() if hasattr(self.ui, "txtPreInput") else ""
        overwrite_val = self.ui.chkOverwrite.isChecked() if hasattr(self.ui, "chkOverwrite") else True
        cpu_prio_val = self.ui.comboCpuPriority.currentText() if hasattr(self.ui, "comboCpuPriority") else "Normal"

        for _idx, item in enumerate(self.queue_items):
            src_path = item["path"]
            src_dir, src_file = os.path.split(src_path)
            base_name, _ = os.path.splitext(src_file)

            if custom_dest and dest_dir and os.path.isdir(dest_dir):
                target_folder = dest_dir
            else:
                target_folder = src_dir

            out_filename = f"{base_name}_converted.{out_ext}"
            out_path = os.path.join(target_folder, out_filename)
            item["output_path"] = out_path

            combined_params = f"{params_template}{fade_extra}{wm_extra}".strip()
            final_params = substitute_tokens(combined_params, src_path, out_path, item["meta"])

            is_two_pass = hasattr(self.ui, "chkTwoPass") and self.ui.chkTwoPass.isChecked()
            task = FFmpegTask(
                src_path,
                out_path,
                final_params,
                item["meta"].get("duration", 0),
                two_pass=is_two_pass,
                pre_input=pre_input_val,
                overwrite=overwrite_val,
                cpu_priority=cpu_prio_val
            )
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
        out_path = ""
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
                out_path = item.get("output_path", "")
                break

        # Check Per-File Hook (Form13/Form14 Parity)
        cfg = get_config()
        if success and cfg.get("hook_per_file_enabled") and cfg.get("hook_per_file_cmd"):
            cmd_tmpl = cfg["hook_per_file_cmd"]
            cmd_exec = cmd_tmpl.replace("{input}", file_path).replace("{output}", out_path).replace("{status}", "Completed")
            try:
                subprocess.Popen(cmd_exec, shell=True)
            except Exception as e:
                self.ui.txtLog.appendPlainText(f"⚠ Per-file hook error: {e}")

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
            self.ui.btnPause.setEnabled(False)
            self.ui.btnPause.setText("Pause")
            self.ui.btnStop.setEnabled(False)
            self.ui.btnSkipCurrent.setEnabled(False)
            self.ui.btnAbortAll.setEnabled(False)
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
            if cfg.get("hook_on_complete_enabled") and cfg.get("hook_on_complete_cmd"):
                cmd_complete = cfg["hook_on_complete_cmd"]
                self.ui.txtLog.appendPlainText(f">>> Executing queue completion hook: {cmd_complete}")
                try:
                    subprocess.Popen(cmd_complete, shell=True)
                except Exception as e:
                    self.ui.txtLog.appendPlainText(f"⚠ Completion hook error: {e}")

            if cfg.get("run_script_enabled") and cfg.get("run_script_path"):
                scr = cfg["run_script_path"]
                if os.path.isfile(scr) and os.access(scr, os.X_OK):
                    self.ui.txtLog.appendPlainText(f">>> Executing completion script: {scr}")
                    try:
                        subprocess.Popen([scr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception as e:
                        self.ui.txtLog.appendPlainText(f"⚠ Script execution error: {e}")

            # Check UI auto-shutdown selection
            if hasattr(self.ui, "chkAutoShutdown") and self.ui.chkAutoShutdown.isChecked():
                self.start_auto_shutdown_countdown()
            else:
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

    def on_toggle_pause(self):
        if not self.is_paused:
            self.is_paused = True
            self.ui.btnPause.setText("Resume")
            for task in self.active_tasks:
                task.pause()
            self.ui.txtLog.appendPlainText(">>> Batch processing PAUSED.")
        else:
            self.is_paused = False
            self.ui.btnPause.setText("Pause")
            for task in self.active_tasks:
                task.resume()
            self.ui.txtLog.appendPlainText(">>> Batch processing RESUMED.")

    def on_skip_current_file(self):
        """Skips the first currently active encoding worker."""
        for task in self.active_tasks:
            if not task.is_cancelled and task.process and task.process.poll() is None:
                self.ui.txtLog.appendPlainText(f">>> Skipping current file: {os.path.basename(task.file_path)}")
                task.cancel()
                break

    def stop_processing(self):
        self.is_paused = False
        for task in self.active_tasks:
            task.cancel()
        self.ui.btnStart.setEnabled(True)
        self.ui.btnPause.setEnabled(False)
        self.ui.btnPause.setText("Pause")
        self.ui.btnStop.setEnabled(False)
        self.ui.btnSkipCurrent.setEnabled(False)
        self.ui.btnAbortAll.setEnabled(False)
        self.setWindowTitle("FFmpeg Batch AV Converter (Linux Native)")
        self.ui.txtLog.appendPlainText(">>> Batch Processing Stopped / Aborted by User.")

    def start_auto_shutdown_countdown(self):
        self.shutdown_seconds_left = 30
        self.ui.btnCancelShutdown.setVisible(True)
        action_name = self.ui.comboShutdownAction.currentText()
        self.ui.btnCancelShutdown.setText(f"Cancel {action_name} ({self.shutdown_seconds_left}s)")
        self.ui.txtLog.appendPlainText(f">>> Action scheduled: {action_name} in 30 seconds. Press cancel button to abort.")
        self.shutdown_timer.start()

    def _on_shutdown_tick(self):
        self.shutdown_seconds_left -= 1
        action_name = self.ui.comboShutdownAction.currentText()
        if self.shutdown_seconds_left > 0:
            self.ui.btnCancelShutdown.setText(f"Cancel {action_name} ({self.shutdown_seconds_left}s)")
        else:
            self.shutdown_timer.stop()
            self.ui.btnCancelShutdown.setVisible(False)
            self._execute_shutdown_action(action_name)

    def cancel_auto_shutdown(self):
        self.shutdown_timer.stop()
        self.ui.btnCancelShutdown.setVisible(False)
        self.ui.chkAutoShutdown.setChecked(False)
        self.ui.txtLog.appendPlainText(">>> Scheduled completion action CANCELLED by user.")

    def _execute_shutdown_action(self, action_name: str):
        self.ui.txtLog.appendPlainText(f">>> Executing action: {action_name}...")
        if "Shutdown" in action_name:
            subprocess.Popen(["systemctl", "poweroff"])
        elif "Suspend" in action_name or "Sleep" in action_name:
            subprocess.Popen(["systemctl", "suspend"])
        elif "Hibernate" in action_name:
            subprocess.Popen(["systemctl", "hibernate"])
        elif "Close" in action_name:
            self.close()

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

    # Item 7: System Tray Integration (matching Windows Settings.to_tray)
    def setup_system_tray(self):
        icon_path = os.path.join(os.path.dirname(__file__), "assets", "app_icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else self.windowIcon()
        self.tray_icon = QSystemTrayIcon(icon, self)

        tray_menu = QMenu(self)
        act_show = tray_menu.addAction("Show / Restore")
        act_show.triggered.connect(self.showNormal)
        act_pause = tray_menu.addAction("Pause / Resume Queue")
        act_pause.triggered.connect(self.on_toggle_pause)
        tray_menu.addSeparator()
        act_quit = tray_menu.addAction("Quit Application")
        act_quit.triggered.connect(QApplication.instance().quit)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick or reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.activateWindow()

    # Item 6: Audio Waveform Visualizer (button22)
    def open_audio_waveform_dialog(self):
        if not self.queue_items:
            QMessageBox.information(self, "No Media", "Please add a media file with audio to the queue first.")
            return

        selected_row = self.ui.tableQueue.currentRow()
        if selected_row < 0 or selected_row >= len(self.queue_items):
            selected_row = 0

        target_path = self.queue_items[selected_row]["path"]
        dlg = load_ui_widget("ui/waveform_dialog.ui", self)
        dlg.lblFile.setText(f"Media File: {os.path.basename(target_path)}")

        from PySide6.QtGui import QPixmap

        def render_waveform():
            dlg.lblWaveformImage.setText("Generating waveform with FFmpeg...")
            dlg.lblWaveformImage.setPixmap(QPixmap())
            QApplication.processEvents()

            color_choice = dlg.comboWaveColor.currentText()
            hex_color = color_choice[color_choice.find("(") + 1 : color_choice.rfind(")")]

            tmp_png = os.path.join(os.path.expanduser("~"), ".cache", "ffbatch_waveform.png")
            os.makedirs(os.path.dirname(tmp_png), exist_ok=True)

            ffmpeg_bin = get_binary_path("ffmpeg")
            cmd = [
                ffmpeg_bin, "-y",
                "-i", target_path,
                "-filter_complex", f"aformat=channel_layouts=mono,showwavespic=s=800x240:colors={hex_color}",
                "-frames:v", "1",
                tmp_png
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if res.returncode == 0 and os.path.exists(tmp_png):
                pix = QPixmap(tmp_png)
                dlg.lblWaveformImage.setPixmap(pix)
            else:
                dlg.lblWaveformImage.setText(f"Waveform generation failed (no audio stream found)")

        render_waveform()
        dlg.btnRegenerate.clicked.connect(render_waveform)

        def save_image():
            tmp_png = os.path.join(os.path.expanduser("~"), ".cache", "ffbatch_waveform.png")
            if not os.path.exists(tmp_png):
                return
            dest, _ = QFileDialog.getSaveFileName(dlg, "Save Waveform Image", "waveform.png", "PNG Images (*.png)")
            if dest:
                import shutil
                shutil.copyfile(tmp_png, dest)
                QMessageBox.information(dlg, "Saved", f"Waveform saved to:\n{dest}")

        dlg.btnSaveWaveform.clicked.connect(save_image)
        dlg.waveformButtonBox.rejected.connect(dlg.reject)
        dlg.exec()

    # Item 5: Linux Screen Recording Tool (btn_capture using x11grab)
    def open_screen_record_dialog(self):
        dlg = load_ui_widget("ui/screen_record_dialog.ui", self)
        display_var = os.environ.get("DISPLAY", ":0.0")
        dlg.txtDisplayServer.setText(display_var)

        default_out = os.path.join(os.path.expanduser("~/Videos"), "screen_recording.mp4")
        dlg.txtRecordPath.setText(default_out)

        def browse_path():
            f, _ = QFileDialog.getSaveFileName(dlg, "Save Screen Recording", default_out, "Videos (*.mp4 *.mkv)")
            if f:
                dlg.txtRecordPath.setText(f)

        dlg.btnBrowseRecordPath.clicked.connect(browse_path)

        rec_process = {"proc": None, "timer": None, "seconds": 0}

        def on_tick():
            rec_process["seconds"] += 1
            sec = rec_process["seconds"]
            dlg.lblRecordStatus.setText(f"Recording active: {sec // 60:02d}:{sec % 60:02d}")

        rec_timer = QTimer(dlg)
        rec_timer.setInterval(1000)
        rec_timer.timeout.connect(on_tick)
        rec_process["timer"] = rec_timer

        def toggle_record():
            if rec_process["proc"] is None:
                # Start recording
                out_file = dlg.txtRecordPath.text().strip() or default_out
                os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)
                disp = dlg.txtDisplayServer.text().strip() or ":0.0"
                fps = dlg.spinFramerate.value()
                audio_choice = dlg.comboAudioDevice.currentText()

                ffmpeg_bin = get_binary_path("ffmpeg")
                cmd = [
                    ffmpeg_bin, "-y",
                    "-video_size", "1920x1080",
                    "-framerate", str(fps),
                    "-f", "x11grab",
                    "-i", disp
                ]
                if "PulseAudio" in audio_choice or "default" in audio_choice:
                    cmd.extend(["-f", "pulse", "-i", "default"])
                cmd.extend(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", out_file])

                self.ui.txtLog.appendPlainText(f">>> Launching screen recording: {' '.join(cmd)}")
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    rec_process["proc"] = p
                    rec_process["seconds"] = 0
                    rec_timer.start()
                    dlg.btnToggleRecord.setText("⏹ Stop Recording")
                    dlg.btnToggleRecord.setStyleSheet("font-weight: bold; color: white; background-color: #27ae60;")
                    dlg.lblRecordStatus.setText("Recording active: 00:00")
                except Exception as e:
                    QMessageBox.warning(dlg, "Recording Error", f"Failed to start screen recording:\n{e}")
            else:
                # Stop recording
                p = rec_process["proc"]
                rec_timer.stop()
                try:
                    # Send 'q' to ffmpeg stdin for graceful termination
                    p.communicate(input=b"q", timeout=3)
                except Exception:
                    p.terminate()
                rec_process["proc"] = None
                dlg.btnToggleRecord.setText("⏺ Start Recording")
                dlg.btnToggleRecord.setStyleSheet("font-weight: bold; color: white; background-color: #e74c3c;")
                out_file = dlg.txtRecordPath.text().strip() or default_out
                dlg.lblRecordStatus.setText(f"Saved: {os.path.basename(out_file)}")
                # Ask to add to queue
                reply = QMessageBox.question(
                    dlg,
                    "Add to Batch Queue?",
                    f"Recording completed successfully!\nFile: {out_file}\n\nAdd this recording to the batch processing queue?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.add_file_to_queue(out_file)

        dlg.btnToggleRecord.clicked.connect(toggle_record)

        def on_close():
            if rec_process["proc"] is not None:
                toggle_record()
            dlg.reject()

        dlg.recordButtonBox.rejected.connect(on_close)
        dlg.exec()

    # Form16: Full Log File Viewer Dialog
    def open_log_viewer_dialog(self):
        dlg = load_ui_widget("ui/log_viewer_dialog.ui", self)
        full_text = self.ui.txtLog.toPlainText()
        dlg.txtFullLog.setPlainText(full_text)

        def on_filter_log(keyword):
            if not keyword.strip():
                dlg.txtFullLog.setPlainText(full_text)
                return
            lines = [l for l in full_text.splitlines() if keyword.lower() in l.lower()]
            dlg.txtFullLog.setPlainText("\n".join(lines))

        dlg.txtLogSearch.textChanged.connect(on_filter_log)
        dlg.btnClearLog.clicked.connect(lambda: dlg.txtFullLog.clear())
        dlg.btnCopyLog.clicked.connect(lambda: QApplication.clipboard().setText(dlg.txtFullLog.toPlainText()))
        dlg.logButtonBox.rejected.connect(dlg.reject)
        dlg.exec()

    # Form20: Sequential Batch File Renamer
    def open_batch_renamer_dialog(self):
        if not self.queue_items:
            QMessageBox.information(self, "Queue Empty", "Please add files to the queue before renaming.")
            return

        dlg = load_ui_widget("ui/batch_renamer_dialog.ui", self)
        table = dlg.tableRenamePreview
        table.horizontalHeader().setStretchLastSection(True)

        def update_preview():
            table.setRowCount(0)
            prefix = dlg.txtBasePrefix.text().strip()
            suffix = dlg.txtSuffix.text().strip()
            start_num = dlg.spinStartNumber.value()
            digits = dlg.spinDigits.value()

            for idx, item in enumerate(self.queue_items):
                orig_file = os.path.basename(item["path"])
                _, ext = os.path.splitext(orig_file)
                num_str = str(start_num + idx).zfill(digits)
                new_file = f"{prefix}{num_str}{suffix}{ext}" if prefix or suffix else orig_file

                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(orig_file))
                table.setItem(r, 1, QTableWidgetItem(new_file))

        dlg.txtBasePrefix.textChanged.connect(update_preview)
        dlg.txtSuffix.textChanged.connect(update_preview)
        dlg.spinStartNumber.valueChanged.connect(update_preview)
        dlg.spinDigits.valueChanged.connect(update_preview)
        update_preview()

        def apply_renaming():
            renamed_count = 0
            for r in range(table.rowCount()):
                new_name = table.item(r, 1).text()
                if r < len(self.queue_items):
                    old_path = self.queue_items[r]["path"]
                    d, _ = os.path.split(old_path)
                    new_path = os.path.join(d, new_name)
                    if old_path != new_path:
                        try:
                            os.rename(old_path, new_path)
                            self.queue_items[r]["path"] = new_path
                            self.ui.tableQueue.item(r, 1).setText(new_name)
                            renamed_count += 1
                        except Exception as e:
                            self.ui.txtLog.appendPlainText(f"⚠ Rename failed for {old_path}: {e}")
            QMessageBox.information(dlg, "Rename Complete", f"Successfully renamed {renamed_count} files.")
            dlg.accept()

        dlg.renameButtonBox.button(QDialogButtonBox.Apply).clicked.connect(apply_renaming)
        dlg.renameButtonBox.rejected.connect(dlg.reject)
        dlg.exec()

    # AeroWizard2: Split / Segment Media Files
    def open_split_video_dialog(self):
        if not self.queue_items:
            QMessageBox.information(self, "Queue Empty", "Please add a media file to the queue first.")
            return

        dlg = load_ui_widget("ui/split_video_dialog.ui", self)
        target_item = self.queue_items[0]
        src_path = target_item["path"]
        total_duration = target_item["meta"].get("duration", 0.0)
        dlg.lblTargetFile.setText(f"Target File: {os.path.basename(src_path)} ({int(total_duration)}s)")

        def on_mode_change():
            by_dur = dlg.radSplitDuration.isChecked()
            dlg.spinSegmentSeconds.setEnabled(by_dur)
            dlg.spinPartCount.setEnabled(not by_dur)

        dlg.radSplitDuration.toggled.connect(on_mode_change)
        dlg.radSplitCount.toggled.connect(on_mode_change)

        def on_sec_change(val):
            mins = val / 60.0
            dlg.lblMinutesHelper.setText(f"({mins:.1f} minutes)")

        dlg.spinSegmentSeconds.valueChanged.connect(on_sec_change)

        def run_split():
            ffmpeg_bin = get_binary_path("ffmpeg")
            src_dir, src_file = os.path.split(src_path)
            base, ext = os.path.splitext(src_file)
            out_pattern = os.path.join(src_dir, f"{base}_part%03d{ext}")

            if dlg.radSplitDuration.isChecked():
                seg_time = dlg.spinSegmentSeconds.value()
            else:
                parts = max(2, dlg.spinPartCount.value())
                seg_time = max(5, int(total_duration / parts)) if total_duration > 0 else 60

            cmd = [
                ffmpeg_bin, "-y",
                "-i", src_path,
                "-c", "copy",
                "-map", "0",
                "-segment_time", str(seg_time),
                "-f", "segment",
                "-reset_timestamps", "1",
                out_pattern
            ]
            self.ui.txtLog.appendPlainText(f">>> Running Video Split: {' '.join(cmd)}")
            dlg.progSplit.setValue(30)
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.ui.txtLog.appendPlainText(res.stdout)
            dlg.progSplit.setValue(100)
            if res.returncode == 0:
                QMessageBox.information(dlg, "Split Complete", f"Media split successfully into segments:\n{out_pattern}")
                dlg.accept()
            else:
                QMessageBox.warning(dlg, "Split Failed", f"Splitting failed:\n{res.stdout[-300:]}")

        dlg.splitButtonBox.button(QDialogButtonBox.Apply).clicked.connect(run_split)
        dlg.splitButtonBox.rejected.connect(dlg.reject)
        dlg.exec()

    # AeroWizard6: Chapters Metadata Creator
    def open_chapters_dialog(self):
        dlg = load_ui_widget("ui/chapters_dialog.ui", self)
        table = dlg.tableChapters
        table.horizontalHeader().setStretchLastSection(True)

        def add_ch():
            t = dlg.txtChapterTime.text().strip()
            title = dlg.txtChapterTitle.text().strip() or "Chapter"
            if not t:
                return
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(str(r + 1)))
            table.setItem(r, 1, QTableWidgetItem(t))
            table.setItem(r, 2, QTableWidgetItem(title))
            dlg.txtChapterTime.clear()
            dlg.txtChapterTitle.clear()

        dlg.btnAddChapter.clicked.connect(add_ch)
        dlg.btnRemoveChapter.clicked.connect(lambda: [table.removeRow(idx.row()) for idx in sorted(table.selectedIndexes(), reverse=True)])
        dlg.btnClearChapters.clicked.connect(lambda: table.setRowCount(0))

        def export_txt():
            f, _ = QFileDialog.getSaveFileName(dlg, "Export FFMETADATA File", "metadata.txt", "Text Files (*.txt)")
            if f:
                with open(f, "w", encoding="utf-8") as fp:
                    fp.write(";FFMETADATA1\n")
                    for r in range(table.rowCount()):
                        time_str = table.item(r, 1).text()
                        title = table.item(r, 2).text()
                        parts = [int(p) for p in time_str.split(":")]
                        if len(parts) == 3:
                            sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
                        elif len(parts) == 2:
                            sec = parts[0] * 60 + parts[1]
                        else:
                            sec = parts[0]
                        start_ms = sec * 1000
                        fp.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start_ms}\nEND={start_ms + 60000}\ntitle={title}\n\n")
                QMessageBox.information(dlg, "Exported", f"FFMETADATA file exported to:\n{f}")

        dlg.btnExportChaptersTxt.clicked.connect(export_txt)

        def inject_chapters():
            if not self.queue_items:
                QMessageBox.warning(dlg, "No Target", "Please select a video file in the queue.")
                return
            target_path = self.queue_items[0]["path"]
            src_dir, src_file = os.path.split(target_path)
            base, ext = os.path.splitext(src_file)
            out_file = os.path.join(src_dir, f"{base}_with_chapters{ext}")

            tmp_meta = os.path.join(src_dir, "tmp_meta.txt")
            with open(tmp_meta, "w", encoding="utf-8") as fp:
                fp.write(";FFMETADATA1\n")
                for r in range(table.rowCount()):
                    time_str = table.item(r, 1).text()
                    title = table.item(r, 2).text()
                    parts = [int(p) for p in time_str.split(":")]
                    if len(parts) == 3:
                        sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
                    elif len(parts) == 2:
                        sec = parts[0] * 60 + parts[1]
                    else:
                        sec = parts[0]
                    start_ms = sec * 1000
                    fp.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start_ms}\nEND={start_ms + 60000}\ntitle={title}\n\n")

            ffmpeg_bin = get_binary_path("ffmpeg")
            cmd = [
                ffmpeg_bin, "-y",
                "-i", target_path,
                "-i", tmp_meta,
                "-map_metadata", "1",
                "-c", "copy",
                out_file
            ]
            self.ui.txtLog.appendPlainText(f">>> Injecting Chapters: {' '.join(cmd)}")
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if os.path.exists(tmp_meta):
                os.remove(tmp_meta)
            if res.returncode == 0:
                QMessageBox.information(dlg, "Injection Complete", f"Chapters injected successfully:\n{out_file}")
                dlg.accept()
            else:
                QMessageBox.warning(dlg, "Injection Failed", f"Failed to inject chapters:\n{res.stdout[-300:]}")

        dlg.btnInjectChapters.clicked.connect(inject_chapters)
        dlg.chaptersButtonBox.rejected.connect(dlg.reject)
        dlg.exec()

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

    # Phase 1: Queue Inspection, Filtering & Customization
    def apply_column_visibility(self):
        """Applies saved column visibility preferences to tableQueue."""
        cfg = get_config()
        # Default: 0:#, 1:File Name, 2:Duration, 3:Video Codec, 4:Audio Codec, 5:Size, 6:Est. Size, 7:Progress, 8:Status
        # All columns visible by default
        visible_cols = cfg.get("queue_visible_columns", list(range(9)))
        table = self.ui.tableQueue
        for c in range(table.columnCount()):
            table.setColumnHidden(c, c not in visible_cols)

    def open_custom_columns_dialog(self):
        """Allows configuring which queue table columns are visible."""
        dlg = load_ui_widget("ui/custom_columns_dialog.ui", self)
        table = self.ui.tableQueue

        col_names = []
        for c in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(c)
            col_names.append(header_item.text() if header_item else f"Column {c}")

        cfg = get_config()
        visible_cols = set(cfg.get("queue_visible_columns", list(range(table.columnCount()))))

        for idx, name in enumerate(col_names):
            item = QListWidgetItem(name, dlg.listColumns)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # Column 1 (File Name) and 8 (Status) are mandatory for UX, others optional
            is_checked = idx in visible_cols or idx in (1, 8)
            item.setCheckState(Qt.Checked if is_checked else Qt.Unchecked)

        def on_select_all():
            for r in range(dlg.listColumns.count()):
                dlg.listColumns.item(r).setCheckState(Qt.Checked)

        def on_reset():
            for r in range(dlg.listColumns.count()):
                dlg.listColumns.item(r).setCheckState(Qt.Checked)

        def on_apply():
            selected = []
            for r in range(dlg.listColumns.count()):
                if dlg.listColumns.item(r).checkState() == Qt.Checked:
                    selected.append(r)
            if 1 not in selected:
                selected.append(1)  # Ensure File Name is always visible
            selected.sort()
            cfg["queue_visible_columns"] = selected
            save_config(cfg)
            self.apply_column_visibility()
            dlg.accept()

        dlg.btnSelectAll.clicked.connect(on_select_all)
        dlg.btnResetDefault.clicked.connect(on_reset)
        dlg.btnSaveColumns.clicked.connect(on_apply)
        dlg.btnCancel.clicked.connect(dlg.reject)
        dlg.exec()

    def open_queue_filter_dialog(self):
        """Advanced queue filtering and batch cleanup dialog."""
        dlg = load_ui_widget("ui/queue_filter_dialog.ui", self)
        table = self.ui.tableQueue

        criteria = [
            "File Name",
            "Status",
            "Video Codec",
            "Audio Codec",
            "Duration (seconds >)",
            "Duration (seconds <)",
            "Size (MB >)",
            "Size (MB <)",
            "Total Bitrate (kbps >)",
            "Total Bitrate (kbps <)",
            "Resolution"
        ]
        dlg.comboFilterBy.addItems(criteria)

        def on_apply():
            attr = dlg.comboFilterBy.currentText()
            val = dlg.txtFilterValue.text().strip().lower()
            action_keep = dlg.comboAction.currentIndex() == 0  # 0: Keep matching, 1: Remove matching
            rem_invalid = dlg.chkRemoveInvalid.isChecked()
            rem_novideo = dlg.chkRemoveNonVideo.isChecked()
            rem_zerosize = dlg.chkRemoveZeroSize.isChecked()

            rows_to_remove = []
            for row in range(len(self.queue_items)):
                item_data = self.queue_items[row]
                meta = item_data.get("meta", {})
                dur = meta.get("duration", 0.0)
                size_mb = meta.get("size", 0) / (1024 * 1024)
                vcodec = meta.get("video_codec", "").lower()
                acodec = meta.get("audio_codec", "").lower()
                res = meta.get("resolution", "").lower()
                status = item_data.get("status", "").lower()
                fname = os.path.basename(item_data.get("path", "")).lower()
                bitrate_kbps = meta.get("bitrate", 0) / 1000

                # Check quick cleanup flags
                if rem_invalid and (dur <= 0 or not meta):
                    rows_to_remove.append(row)
                    continue
                if rem_novideo and (not vcodec or vcodec in ("n/a", "none")):
                    rows_to_remove.append(row)
                    continue
                if rem_zerosize and size_mb <= 0:
                    rows_to_remove.append(row)
                    continue

                # Check attribute criteria if value provided
                if val:
                    matches = False
                    if attr == "File Name":
                        matches = val in fname
                    elif attr == "Status":
                        matches = val in status
                    elif attr == "Video Codec":
                        matches = val in vcodec
                    elif attr == "Audio Codec":
                        matches = val in acodec
                    elif attr == "Resolution":
                        matches = val in res
                    elif "Duration" in attr:
                        try:
                            thresh = float(val)
                            matches = dur > thresh if ">" in attr else dur < thresh
                        except ValueError:
                            pass
                    elif "Size" in attr:
                        try:
                            thresh = float(val)
                            matches = size_mb > thresh if ">" in attr else size_mb < thresh
                        except ValueError:
                            pass
                    elif "Bitrate" in attr:
                        try:
                            thresh = float(val)
                            matches = bitrate_kbps > thresh if ">" in attr else bitrate_kbps < thresh
                        except ValueError:
                            pass

                    # Keep vs remove action
                    if action_keep and not matches:
                        rows_to_remove.append(row)
                    elif not action_keep and matches:
                        rows_to_remove.append(row)

            # Perform removals in reverse order
            for r in sorted(set(rows_to_remove), reverse=True):
                table.removeRow(r)
                if r < len(self.queue_items):
                    del self.queue_items[r]

            self._renumber_queue()
            self.ui.lblItemCount.setText(f"{len(self.queue_items)} items")
            dlg.accept()

        dlg.btnApplyFilter.clicked.connect(on_apply)
        dlg.btnCancel.clicked.connect(dlg.reject)
        dlg.exec()

    def open_frame_preview_dialog(self, row_idx: int = -1):
        """Extracts and inspects a high-resolution preview frame/thumbnail from the selected file."""
        if row_idx < 0:
            row_idx = self.ui.tableQueue.currentRow()
        if row_idx < 0 or row_idx >= len(self.queue_items):
            if self.queue_items:
                row_idx = 0
            else:
                QMessageBox.information(self, "No Item", "Please select a media file from the queue.")
                return

        item = self.queue_items[row_idx]
        file_path = item["path"]
        meta = item.get("meta", {})
        dur = meta.get("duration", 0.0)

        # Seek to 15% of duration or 2s in for representative thumbnail
        seek_time = max(1.0, min(10.0, dur * 0.15)) if dur > 2.0 else 0.5
        ffmpeg_bin = get_binary_path("ffmpeg")
        tmp_img = os.path.join("/tmp", f"ffbatch_preview_{os.getpid()}.jpg")

        cmd = [
            ffmpeg_bin, "-y",
            "-ss", str(seek_time),
            "-i", file_path,
            "-frames:v", "1",
            "-q:v", "2",
            tmp_img
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except Exception:
            pass

        dlg = load_ui_widget("ui/frame_preview_dialog.ui", self)
        dlg.lblFrameInfo.setText(f"File: {os.path.basename(file_path)} | Timestamp: {seek_time:.2f}s | Resolution: {meta.get('resolution', 'N/A')}")

        pixmap = QPixmap(tmp_img) if os.path.exists(tmp_img) else QPixmap()
        if not pixmap.isNull():
            # Scale preview cleanly maintaining aspect ratio
            scaled = pixmap.scaled(680, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dlg.lblImageDisplay.setPixmap(scaled)
        else:
            dlg.lblImageDisplay.setText("Could not extract video frame preview (Audio-only or invalid stream).")

        def on_copy():
            if not pixmap.isNull():
                QApplication.clipboard().setPixmap(pixmap)
                QMessageBox.information(dlg, "Copied", "Frame copied to clipboard.")

        def on_save():
            if pixmap.isNull():
                return
            save_path, _ = QFileDialog.getSaveFileName(dlg, "Save Preview Frame", f"{os.path.splitext(os.path.basename(file_path))[0]}_frame.png", "Images (*.png *.jpg)")
            if save_path:
                pixmap.save(save_path)
                QMessageBox.information(dlg, "Saved", f"Preview frame saved to:\n{save_path}")

        dlg.btnCopyClipboard.clicked.connect(on_copy)
        dlg.btnSaveImage.clicked.connect(on_save)
        dlg.btnClose.clicked.connect(dlg.accept)
        dlg.exec()

        if os.path.exists(tmp_img):
            try:
                os.remove(tmp_img)
            except Exception:
                pass

    # Phase 2: Batch Execution Hooks, Automation & Scheduling
    def open_delay_timer_dialog(self):
        """Allows scheduling batch queue execution for a future time or countdown."""
        dlg = load_ui_widget("ui/delay_timer_dialog.ui", self)
        dlg.timeTarget.setTime(QTime.currentTime().addSecs(1800))

        def on_arm():
            if dlg.radCountdown.isChecked():
                h = dlg.spinHours.value()
                m = dlg.spinMinutes.value()
                total_secs = (h * 3600) + (m * 60)
                if total_secs <= 0:
                    QMessageBox.warning(dlg, "Invalid Time", "Please specify a delay greater than 0.")
                    return
                self.delay_seconds_left = total_secs
            else:
                target_time = dlg.timeTarget.time()
                cur_time = QTime.currentTime()
                diff_secs = cur_time.secsTo(target_time)
                if diff_secs <= 0:
                    diff_secs += 24 * 3600  # Scheduled for next day
                self.delay_seconds_left = diff_secs

            self.delay_timer.start()
            self.ui.txtLog.appendPlainText(f">>> Delayed start scheduled: Queue starts in {self.delay_seconds_left} seconds ({self.delay_seconds_left // 60} mins).")
            self.statusBar().showMessage(f"Scheduled delayed start in {self.delay_seconds_left}s", 5000)
            dlg.accept()

        dlg.btnStartSchedule.clicked.connect(on_arm)
        dlg.btnCancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _on_delay_schedule_tick(self):
        if self.delay_seconds_left > 0:
            self.delay_seconds_left -= 1
            if self.delay_seconds_left % 60 == 0 or self.delay_seconds_left <= 10:
                self.statusBar().showMessage(f"Queue starting in {self.delay_seconds_left} seconds...", 2000)
        else:
            self.delay_timer.stop()
            self.statusBar().showMessage("Delayed start triggering now!", 3000)
            self.ui.txtLog.appendPlainText(">>> Schedule timer elapsed. Starting queue execution now...")
            self.start_processing()

    def open_post_process_dialog(self):
        """Configure per-file and queue completion shell command hooks."""
        dlg = load_ui_widget("ui/post_process_dialog.ui", self)
        cfg = get_config()

        dlg.chkRunPerFile.setChecked(cfg.get("hook_per_file_enabled", False))
        dlg.txtPerFileCmd.setText(cfg.get("hook_per_file_cmd", ""))
        dlg.chkRunOnComplete.setChecked(cfg.get("hook_on_complete_enabled", False))
        dlg.txtOnCompleteCmd.setText(cfg.get("hook_on_complete_cmd", ""))

        def on_save():
            cfg["hook_per_file_enabled"] = dlg.chkRunPerFile.isChecked()
            cfg["hook_per_file_cmd"] = dlg.txtPerFileCmd.text().strip()
            cfg["hook_on_complete_enabled"] = dlg.chkRunOnComplete.isChecked()
            cfg["hook_on_complete_cmd"] = dlg.txtOnCompleteCmd.text().strip()
            save_config(cfg)
            QMessageBox.information(dlg, "Saved", "Post-processing hook configuration saved.")
            dlg.accept()

        dlg.btnSaveHooks.clicked.connect(on_save)
        dlg.btnCancel.clicked.connect(dlg.reject)
        dlg.exec()

    def open_battery_power_dialog(self):
        """Configure Linux power/battery protection rules."""
        dlg = load_ui_widget("ui/battery_power_dialog.ui", self)
        cfg = get_config()

        on_ac, batt_pct = get_power_status()
        state_str = "AC Mains" if on_ac else "Battery"
        dlg.lblCurrentState.setText(f"Power Source: {state_str} | Battery: {batt_pct}%")

        dlg.chkPauseOnBattery.setChecked(cfg.get("power_pause_battery", False))
        dlg.chkThreshold.setChecked(cfg.get("power_threshold_enabled", False))
        dlg.spinBatteryThreshold.setValue(cfg.get("power_threshold_pct", 25))
        dlg.chkResumeOnAC.setChecked(cfg.get("power_resume_ac", True))

        def on_save():
            cfg["power_pause_battery"] = dlg.chkPauseOnBattery.isChecked()
            cfg["power_threshold_enabled"] = dlg.chkThreshold.isChecked()
            cfg["power_threshold_pct"] = dlg.spinBatteryThreshold.value()
            cfg["power_resume_ac"] = dlg.chkResumeOnAC.isChecked()
            save_config(cfg)
            QMessageBox.information(dlg, "Saved", "Power management settings saved.")
            dlg.accept()

        dlg.btnSavePower.clicked.connect(on_save)
        dlg.btnCancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _on_power_check_tick(self):
        """Monitors system power status periodically during active queue processing."""
        if not self.active_tasks:
            return

        cfg = get_config()
        pause_on_batt = cfg.get("power_pause_battery", False)
        if not pause_on_batt:
            return

        on_ac, batt_pct = get_power_status()
        thresh_enabled = cfg.get("power_threshold_enabled", False)
        thresh_pct = cfg.get("power_threshold_pct", 25)
        resume_on_ac = cfg.get("power_resume_ac", True)

        should_pause = False
        if not on_ac:
            if thresh_enabled:
                if batt_pct < thresh_pct:
                    should_pause = True
            else:
                should_pause = True

        if should_pause and not self.is_paused:
            self.ui.txtLog.appendPlainText(f"⚠ Power Alert: Running on battery ({batt_pct}%). Pausing active queue...")
            self.on_toggle_pause()
            self.auto_paused_by_power = True
        elif on_ac and self.is_paused and self.auto_paused_by_power and resume_on_ac:
            self.ui.txtLog.appendPlainText(f">>> AC Power Restored (Battery: {batt_pct}%). Auto-resuming queue...")
            self.on_toggle_pause()
            self.auto_paused_by_power = False

    # Phase 3: Advanced Batch Muxing & Intro/Outro Stitching
    def open_batch_concat_dialog(self):
        """Batch prepend intro and append outro to all files in queue."""
        if not self.queue_items:
            QMessageBox.information(self, "Queue Empty", "Please add files to the batch queue first.")
            return

        dlg = load_ui_widget("ui/batch_concat_dialog.ui", self)
        dlg.progStitch.setValue(0)

        def on_browse_intro():
            path, _ = QFileDialog.getOpenFileName(dlg, "Select Intro Video File", "", "Videos (*.mp4 *.mkv *.avi *.mov *.webm);;All Files (*)")
            if path:
                dlg.txtIntroFile.setText(path)

        def on_browse_outro():
            path, _ = QFileDialog.getOpenFileName(dlg, "Select Outro Video File", "", "Videos (*.mp4 *.mkv *.avi *.mov *.webm);;All Files (*)")
            if path:
                dlg.txtOutroFile.setText(path)

        def on_start():
            intro = dlg.txtIntroFile.text().strip()
            outro = dlg.txtOutroFile.text().strip()
            if not intro and not outro:
                QMessageBox.warning(dlg, "Missing Clips", "Please specify at least an Intro or an Outro file.")
                return

            stream_copy = dlg.chkStreamCopy.isChecked()
            dlg.btnStartStitch.setEnabled(False)
            total = len(self.queue_items)

            success_cnt = 0
            for i, item in enumerate(self.queue_items):
                src = item["path"]
                dir_name, base_name = os.path.split(src)
                root, ext = os.path.splitext(base_name)
                out_stitched = os.path.join(dir_name, f"{root}_stitched{ext}")

                ok, msg = stitch_file_with_intro_outro(src, intro, outro, out_stitched, stream_copy=stream_copy)
                if ok:
                    success_cnt += 1
                    self.ui.txtLog.appendPlainText(f">>> Stitched: {base_name} -> {os.path.basename(out_stitched)}")
                else:
                    self.ui.txtLog.appendPlainText(f"⚠ Stitch error on {base_name}: {msg}")

                pct = int(((i + 1) / total) * 100)
                dlg.progStitch.setValue(pct)
                QApplication.processEvents()

            dlg.btnStartStitch.setEnabled(True)
            QMessageBox.information(dlg, "Batch Stitching Complete", f"Processed {total} items ({success_cnt} succeeded).")
            dlg.accept()

        dlg.btnBrowseIntro.clicked.connect(on_browse_intro)
        dlg.btnBrowseOutro.clicked.connect(on_browse_outro)
        dlg.btnStartStitch.clicked.connect(on_start)
        dlg.btnClose.clicked.connect(dlg.reject)
        dlg.exec()

    def open_stream_matrix_dialog(self):
        """Interactive stream routing matrix with per-track default/forced flags and lang tagging."""
        selected_row = self.ui.tableQueue.currentRow()
        if selected_row < 0 or selected_row >= len(self.queue_items):
            if self.queue_items:
                selected_row = 0
            else:
                QMessageBox.information(self, "No Item", "Please select a media file from the queue.")
                return

        item = self.queue_items[selected_row]
        file_path = item["path"]

        ffprobe_bin = get_binary_path("ffprobe")
        cmd = [
            ffprobe_bin, "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            file_path
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            streams_data = json.loads(res.stdout).get("streams", [])
        except Exception as e:
            QMessageBox.warning(self, "Probe Error", f"Could not inspect streams:\n{e}")
            return

        dlg = load_ui_widget("ui/stream_matrix_dialog.ui", self)
        table = dlg.tableStreams
        table.setRowCount(0)

        for s in streams_data:
            idx = s.get("index", 0)
            st_type = s.get("codec_type", "unknown")
            codec = s.get("codec_name", "")
            tags = s.get("tags", {})
            lang = tags.get("language", "und")
            disposition = s.get("disposition", {})
            is_def = disposition.get("default", 0) == 1
            is_forced = disposition.get("forced", 0) == 1

            details = ""
            if st_type == "video":
                w, h = s.get("width"), s.get("height")
                details = f"{w}x{h}" if w and h else ""
            elif st_type == "audio":
                ch = s.get("channels", 2)
                sr = s.get("sample_rate", "")
                details = f"{ch}ch, {sr}Hz"
            elif st_type == "subtitle":
                details = tags.get("title", "Subtitle Track")

            row = table.rowCount()
            table.insertRow(row)

            # Map Checkbox
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked)
            table.setItem(row, 0, chk)

            table.setItem(row, 1, QTableWidgetItem(str(idx)))
            table.setItem(row, 2, QTableWidgetItem(st_type))
            table.setItem(row, 3, QTableWidgetItem(codec))
            table.setItem(row, 4, QTableWidgetItem(details))
            table.setItem(row, 5, QTableWidgetItem(lang))

            # Default flag
            chk_d = QTableWidgetItem()
            chk_d.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_d.setCheckState(Qt.Checked if is_def else Qt.Unchecked)
            table.setItem(row, 6, chk_d)

            # Forced flag
            chk_f = QTableWidgetItem()
            chk_f.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_f.setCheckState(Qt.Checked if is_forced else Qt.Unchecked)
            table.setItem(row, 7, chk_f)

        def update_preview_args():
            args = []
            for r in range(table.rowCount()):
                if table.item(r, 0).checkState() == Qt.Checked:
                    st_idx = table.item(r, 1).text()
                    args.append(f"-map 0:{st_idx}")
                    lang = table.item(r, 5).text().strip()
                    if lang and lang != "und":
                        args.append(f"-metadata:s:{st_idx} language={lang}")
                    if table.item(r, 6).checkState() == Qt.Checked:
                        args.append(f"-disposition:{st_idx} default")
                    if table.item(r, 7).checkState() == Qt.Checked:
                        args.append(f"-disposition:{st_idx} forced")
            dlg.txtGeneratedArgs.setText(" ".join(args))

        update_preview_args()
        table.itemChanged.connect(lambda item: update_preview_args())

        def on_map_all():
            for r in range(table.rowCount()):
                table.item(r, 0).setCheckState(Qt.Checked)
            update_preview_args()

        def on_reset():
            for r in range(table.rowCount()):
                table.item(r, 0).setCheckState(Qt.Checked)
                table.item(r, 6).setCheckState(Qt.Unchecked)
                table.item(r, 7).setCheckState(Qt.Unchecked)
            update_preview_args()

        def on_apply():
            gen_args = dlg.txtGeneratedArgs.text().strip()
            if gen_args:
                cur = self.ui.txtParameters.text().strip()
                if cur:
                    self.ui.txtParameters.setText(f"{cur} {gen_args}")
                else:
                    self.ui.txtParameters.setText(gen_args)
                QMessageBox.information(dlg, "Applied", f"Stream routing arguments added to Parameters:\n{gen_args}")
            dlg.accept()

        dlg.btnMapAll.clicked.connect(on_map_all)
        dlg.btnReset.clicked.connect(on_reset)
        dlg.btnApplyArgs.clicked.connect(on_apply)
        dlg.btnCancel.clicked.connect(dlg.reject)
        dlg.exec()

    def open_output_path_dialog(self):
        """Configure directory hierarchy replication and dynamic file naming."""
        dlg = load_ui_widget("ui/output_path_dialog.ui", self)
        cfg = get_config()

        dlg.chkReplicateTree.setChecked(cfg.get("replicate_tree", False))
        dlg.txtNamingPattern.setText(cfg.get("output_naming_pattern", "{name}_converted.{ext}"))
        if self.ui.radCustomFolder.isChecked():
            dlg.radCustomFolder.setChecked(True)
        else:
            dlg.radSameAsSource.setChecked(True)
        dlg.txtBaseOutputDir.setText(self.ui.txtOutputDir.text().strip())

        def on_browse():
            d = QFileDialog.getExistingDirectory(dlg, "Select Output Directory")
            if d:
                dlg.txtBaseOutputDir.setText(d)
                update_live_preview()

        def update_live_preview():
            pattern = dlg.txtNamingPattern.text().strip() or "{name}_converted.{ext}"
            preview_filename = pattern.replace("{name}", "sample_video").replace("{ext}", "mp4")
            if dlg.radCustomFolder.isChecked() and dlg.txtBaseOutputDir.text().strip():
                base = dlg.txtBaseOutputDir.text().strip()
                if dlg.chkReplicateTree.isChecked():
                    dlg.lblLivePreview.setText(f"Preview: {os.path.join(base, 'Season 1', preview_filename)}")
                else:
                    dlg.lblLivePreview.setText(f"Preview: {os.path.join(base, preview_filename)}")
            else:
                dlg.lblLivePreview.setText(f"Preview: /source/dir/{preview_filename}")

        dlg.radSameAsSource.toggled.connect(lambda: update_live_preview())
        dlg.radCustomFolder.toggled.connect(lambda: update_live_preview())
        dlg.chkReplicateTree.toggled.connect(lambda: update_live_preview())
        dlg.txtNamingPattern.textChanged.connect(lambda _: update_live_preview())
        dlg.btnBrowseDir.clicked.connect(on_browse)
        update_live_preview()

        def on_apply():
            cfg["replicate_tree"] = dlg.chkReplicateTree.isChecked()
            cfg["output_naming_pattern"] = dlg.txtNamingPattern.text().strip()
            save_config(cfg)
            if dlg.radCustomFolder.isChecked():
                self.ui.radCustomFolder.setChecked(True)
                self.ui.txtOutputDir.setText(dlg.txtBaseOutputDir.text().strip())
            else:
                self.ui.radSameFolder.setChecked(True)
            QMessageBox.information(dlg, "Saved", "Output path hierarchy configuration applied.")
            dlg.accept()

        dlg.btnApplyPath.clicked.connect(on_apply)
        dlg.btnCancel.clicked.connect(dlg.reject)
        dlg.exec()

    # Phase 4: Remote Presets & Interactive Task Wizard
    def open_online_presets_dialog(self):
        """Browse, search, and import remote/community presets."""
        dlg = load_ui_widget("ui/online_presets_dialog.ui", self)
        table = dlg.tableOnlinePresets
        table.horizontalHeader().setStretchLastSection(True)

        # Extended community repository presets
        online_presets_repo = [
            {"name": "AV1 10-bit High Quality", "cat": "Next-Gen", "ext": "mkv", "args": "-c:v libsvtav1 -preset 5 -crf 26 -pix_fmt yuv420p10le -c:a libopus -b:a 128k"},
            {"name": "AV1 Ultra Fast Archival", "cat": "Next-Gen", "ext": "mp4", "args": "-c:v libsvtav1 -preset 8 -crf 30 -c:a aac -b:a 128k"},
            {"name": "HEVC NVENC GPU Acceleration", "cat": "Hardware", "ext": "mp4", "args": "-c:v hevc_nvenc -preset p5 -rc vbr -cq 24 -c:a aac -b:a 160k"},
            {"name": "H264 VAAPI Intel/AMD GPU", "cat": "Hardware", "ext": "mp4", "args": "-vaapi_device /dev/dri/renderD128 -vf format=nv12,hwupload -c:v h264_vaapi -qp 23 -c:a aac"},
            {"name": "Discord 25MB Shrink", "cat": "Web & Social", "ext": "mp4", "args": "-c:v libx264 -crf 28 -preset fast -vf scale=-2:720 -c:a aac -b:a 96k"},
            {"name": "YouTube 4K Ultra", "cat": "Web & Social", "ext": "mp4", "args": "-c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -c:a aac -b:a 320k"},
            {"name": "ProRes 422 HQ Master", "cat": "Professional", "ext": "mov", "args": "-c:v prores_ks -profile:v 3 -vendor apl0 -pix_fmt yuv422p10le -c:a pcm_s24le"},
            {"name": "DNxHD Broadcast 1080p", "cat": "Professional", "ext": "mov", "args": "-c:v dnxhd -profile:v dnxhr_hq -pix_fmt yuv422p -c:a pcm_s16le"},
            {"name": "Audiobook M4B / AAC 64k", "cat": "Audio", "ext": "m4b", "args": "-vn -c:a aac -b:a 64k"},
            {"name": "FLAC Lossless Audio Extract", "cat": "Audio", "ext": "flac", "args": "-vn -c:a flac"}
        ]

        cats = sorted(set(p["cat"] for p in online_presets_repo))
        for c in cats:
            dlg.comboCategoryFilter.addItem(c)

        def populate_table(filter_text="", cat_filter="All Categories"):
            table.setRowCount(0)
            flt = filter_text.strip().lower()
            for p in online_presets_repo:
                if cat_filter != "All Categories" and p["cat"] != cat_filter:
                    continue
                if flt and (flt not in p["name"].lower() and flt not in p["args"].lower() and flt not in p["cat"].lower()):
                    continue
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(p["name"]))
                table.setItem(r, 1, QTableWidgetItem(p["cat"]))
                table.setItem(r, 2, QTableWidgetItem(p["ext"]))
                table.setItem(r, 3, QTableWidgetItem(p["args"]))

        populate_table()

        def on_selection_changed():
            sel = table.selectedIndexes()
            if sel:
                row = sel[0].row()
                dlg.txtPresetArgsPreview.setText(table.item(row, 3).text())

        table.itemSelectionChanged.connect(on_selection_changed)
        dlg.txtSearchPreset.textChanged.connect(lambda txt: populate_table(txt, dlg.comboCategoryFilter.currentText()))
        dlg.comboCategoryFilter.currentIndexChanged.connect(lambda _: populate_table(dlg.txtSearchPreset.text(), dlg.comboCategoryFilter.currentText()))
        dlg.btnRefreshOnline.clicked.connect(lambda: populate_table(dlg.txtSearchPreset.text(), dlg.comboCategoryFilter.currentText()))

        def on_import_local():
            sel = table.selectedIndexes()
            if not sel:
                QMessageBox.information(dlg, "No Selection", "Please select a preset from the table.")
                return
            row = sel[0].row()
            name = table.item(row, 0).text()
            cat = table.item(row, 1).text()
            ext = table.item(row, 2).text()
            args = table.item(row, 3).text()

            self.presets[name] = {"category": cat, "ext": ext, "args": args}
            save_presets(self.presets)
            self.refresh_presets_combo()
            QMessageBox.information(dlg, "Imported", f"Preset '{name}' added to local presets library.")

        def on_load_to_active():
            sel = table.selectedIndexes()
            if not sel:
                QMessageBox.information(dlg, "No Selection", "Please select a preset from the table.")
                return
            row = sel[0].row()
            args = table.item(row, 3).text()
            ext = table.item(row, 2).text()
            self.ui.txtParameters.setText(args)
            idx = self.ui.comboOutputFormat.findText(ext, Qt.MatchFixedString)
            if idx >= 0:
                self.ui.comboOutputFormat.setCurrentIndex(idx)
            QMessageBox.information(dlg, "Loaded", f"Loaded preset parameters into main window.")
            dlg.accept()

        dlg.btnImportLocal.clicked.connect(on_import_local)
        dlg.btnLoadToActive.clicked.connect(on_load_to_active)
        dlg.btnClose.clicked.connect(dlg.reject)
        dlg.exec()

    def open_task_wizard_dialog(self):
        """Unified 3-step native task wizard (replacing AeroWizard suite)."""
        dlg = load_ui_widget("ui/task_wizard_dialog.ui", self)
        stack = dlg.stackedPages
        stack.setCurrentIndex(0)

        def update_wizard_preview():
            # Derive parameters from choices
            crf_val = dlg.sliderCrf.value()
            dlg.lblCrfValue.setText(f"{crf_val} ({'High Quality' if crf_val < 20 else 'Balanced' if crf_val <= 26 else 'Compressed'})")
            preset_spd = dlg.comboWizardPreset.currentText().split()[0]
            abitrate = dlg.comboAudioBitrate.currentText().split()[0]

            if dlg.radStandardVideo.isChecked():
                args = f"-c:v libx264 -preset {preset_spd} -crf {crf_val} -c:a aac -b:a {abitrate}"
            elif dlg.radHighEfficiency.isChecked():
                args = f"-c:v libx265 -preset {preset_spd} -crf {crf_val} -c:a aac -b:a {abitrate}"
            elif dlg.radAudioExtraction.isChecked():
                args = f"-vn -c:a libmp3lame -q:a 2"
            elif dlg.radWebmStreaming.isChecked():
                args = f"-c:v libvpx-vp9 -crf {crf_val} -b:v 0 -c:a libopus -b:a {abitrate}"
            elif dlg.radSilenceRemoval.isChecked():
                args = f"-af silenceremove=stop_periods=-1:stop_duration=1:stop_threshold=-50dB"
            else:
                args = f"-c:v libx264 -preset {preset_spd} -crf {crf_val} -c:a aac -b:a {abitrate}"

            dlg.txtWizardFinalArgs.setText(args)

        update_wizard_preview()
        dlg.sliderCrf.valueChanged.connect(lambda _: update_wizard_preview())
        dlg.comboWizardPreset.currentIndexChanged.connect(lambda _: update_wizard_preview())
        dlg.comboAudioBitrate.currentIndexChanged.connect(lambda _: update_wizard_preview())

        def on_next():
            idx = stack.currentIndex()
            if idx < stack.count() - 1:
                stack.setCurrentIndex(idx + 1)
                update_wizard_preview()
                dlg.btnWizardBack.setEnabled(True)
                if stack.currentIndex() == stack.count() - 1:
                    dlg.btnWizardNext.setEnabled(False)
                    dlg.btnWizardFinish.setEnabled(True)

        def on_back():
            idx = stack.currentIndex()
            if idx > 0:
                stack.setCurrentIndex(idx - 1)
                dlg.btnWizardNext.setEnabled(True)
                dlg.btnWizardFinish.setEnabled(False)
                if stack.currentIndex() == 0:
                    dlg.btnWizardBack.setEnabled(False)

        def on_finish():
            final_args = dlg.txtWizardFinalArgs.text().strip()
            self.ui.txtParameters.setText(final_args)
            if dlg.radAudioExtraction.isChecked():
                i = self.ui.comboOutputFormat.findText("mp3", Qt.MatchFixedString)
                if i >= 0: self.ui.comboOutputFormat.setCurrentIndex(i)
            elif dlg.radHighEfficiency.isChecked():
                i = self.ui.comboOutputFormat.findText("mkv", Qt.MatchFixedString)
                if i >= 0: self.ui.comboOutputFormat.setCurrentIndex(i)
            elif dlg.radWebmStreaming.isChecked():
                i = self.ui.comboOutputFormat.findText("webm", Qt.MatchFixedString)
                if i >= 0: self.ui.comboOutputFormat.setCurrentIndex(i)
            else:
                i = self.ui.comboOutputFormat.findText("mp4", Qt.MatchFixedString)
                if i >= 0: self.ui.comboOutputFormat.setCurrentIndex(i)

            dlg.accept()
            if dlg.chkWizardAutoStart.isChecked() and self.queue_items:
                self.start_processing()

        dlg.btnWizardNext.clicked.connect(on_next)
        dlg.btnWizardBack.clicked.connect(on_back)
        dlg.btnWizardFinish.clicked.connect(on_finish)
        dlg.btnWizardCancel.clicked.connect(dlg.reject)
        dlg.exec()

    def show_about(self):
        QMessageBox.about(
            self,
            "About FFmpeg Batch Native Linux",
            "<b>FFmpeg Batch AV Converter (Linux Native)</b><br><br>"
            "Modern, multi-threaded PySide6 batch converter powered by native Linux FFmpeg.<br>"
            "Decoupled UI architecture with Qt Designer support.<br><br>"
            "<b>Author:</b> Arean<br>"
            "<b>Contact:</b> <a href='mailto:arean@synorastudio.in'>arean@synorastudio.in</a>"
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    theme_mgr = ThemeManager()
    theme_mgr.apply_current_theme(app)
    window = FFBatchApp()
    window.showMaximized()
    sys.exit(app.exec())
