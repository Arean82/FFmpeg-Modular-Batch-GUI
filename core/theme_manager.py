"""Theme Manager for FFmpeg Batch AV Converter.

Supports 3 100% free, open-source modular theming engines under a unified Light/Dark master switch:
1. Google Material Design (`qt_material`) - 20+ accent color families.
2. PyQtDarkTheme (`qdarktheme`) - Modern flat, subtle, VS Code-like style.
3. Native Clean QSS - Built-in distraction-free light.qss / dark.qss.
"""
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.config_manager import get_config, save_config


class ThemeManager:
    def __init__(self):
        self.themes_dir = Path(__file__).parent.parent / "assets" / "themes"

    def get_theme_mode(self) -> str:
        """Returns 'light', 'dark', or 'system' (default: 'system')."""
        cfg = get_config()
        return cfg.get("theme_mode", "system")

    def save_theme_mode(self, mode: str):
        """Saves theme mode: 'light', 'dark', or 'system'."""
        cfg = get_config()
        cfg["theme_mode"] = mode
        save_config(cfg)

    def get_theme_engine(self) -> str:
        """Returns active engine: 'material', 'pyqtdarktheme', or 'qss' (default: 'qss')."""
        cfg = get_config()
        return cfg.get("theme_engine", "qss")

    def save_theme_engine(self, engine: str):
        """Saves active theme engine: 'material', 'pyqtdarktheme', or 'qss'."""
        cfg = get_config()
        cfg["theme_engine"] = engine
        save_config(cfg)

    def get_material_theme(self) -> str:
        """Returns material theme identifier (e.g. 'teal', 'dark_teal.xml', or 'default')."""
        cfg = get_config()
        return cfg.get("material_theme", "teal")

    def save_material_theme(self, theme_name: str):
        """Saves selected material theme."""
        cfg = get_config()
        cfg["material_theme"] = theme_name
        save_config(cfg)

    def is_system_dark(self, app=None) -> bool:
        """Detects if system OS is currently in dark mode."""
        app_inst = app or QApplication.instance()
        if app_inst:
            palette = app_inst.palette()
            return palette.window().color().lightness() < 128
        return True

    def get_effective_brightness(self, app=None) -> str:
        """Resolves whether effective theme is 'dark' or 'light' considering 'system' setting."""
        mode = self.get_theme_mode()
        if mode == "system":
            return "dark" if self.is_system_dark(app) else "light"
        elif mode == "light":
            return "light"
        return "dark"

    def get_all_material_themes(self) -> list[str]:
        """Returns list of all available Material theme files from qt_material."""
        try:
            import qt_material
            return qt_material.list_themes()
        except ImportError:
            return []

    def apply_current_theme(self, app=None, window=None):
        """Applies theme based on saved theme_engine and theme_mode."""
        app = app or QApplication.instance()
        if not app:
            return

        engine = self.get_theme_engine()
        brightness = self.get_effective_brightness(app)

        if engine == "pyqtdarktheme":
            try:
                import qdarktheme
                style = qdarktheme.load_stylesheet(brightness)
                app.setStyleSheet(style)
                if window:
                    window.setStyleSheet(style)
                return
            except Exception as e:
                print(f"Error loading qdarktheme: {e}")

        elif engine == "qss":
            qss_file = self.themes_dir / f"{brightness}.qss"
            if qss_file.exists():
                with open(qss_file, encoding="utf-8") as f:
                    qss_content = f.read()
                    app.setStyleSheet(qss_content)
                    if window:
                        window.setStyleSheet(qss_content)
            else:
                app.setStyleSheet("")
                if window:
                    window.setStyleSheet("")
            return

        # Default fallback or explicit Material Theme
        material = self.get_material_theme()
        if material == "default":
            qss_file = self.themes_dir / f"{brightness}.qss"
            if qss_file.exists():
                with open(qss_file, encoding="utf-8") as f:
                    qss_content = f.read()
                    app.setStyleSheet(qss_content)
                    if window:
                        window.setStyleSheet(qss_content)
            else:
                app.setStyleSheet("")
                if window:
                    window.setStyleSheet("")
        else:
            available = self.get_all_material_themes()
            color_name = material.replace(".xml", "").replace("dark_", "").replace("light_", "")
            target_xml = f"{brightness}_{color_name}.xml"
            if target_xml not in available:
                matching = [t for t in available if f"_{color_name}.xml" in t or t == material]
                if matching:
                    target_xml = matching[0]
                elif material in available:
                    target_xml = material
                elif available:
                    target_xml = available[0]

            try:
                from qt_material import apply_stylesheet
                # Density scale -1 locks compact desktop sizing
                apply_stylesheet(app, theme=target_xml, extra={'density_scale': '-1'})
                if window:
                    window.setStyleSheet(app.styleSheet())
            except Exception:
                qss_file = self.themes_dir / f"{brightness}.qss"
                if qss_file.exists():
                    with open(qss_file, encoding="utf-8") as f:
                        qss_content = f.read()
                        app.setStyleSheet(qss_content)
                        if window:
                            window.setStyleSheet(qss_content)

    def set_theme_mode(self, app, mode: str, window=None):
        """Sets brightness mode ('light', 'dark', 'system') and reapplies theme."""
        self.save_theme_mode(mode)
        self.apply_current_theme(app, window=window)

    def set_engine_and_material(self, app, material_name: str, window=None):
        """Switches engine to 'material' and sets specific material accent."""
        self.save_theme_engine("material")
        self.save_material_theme(material_name)
        self.apply_current_theme(app, window=window)

    def set_engine_pyqtdarktheme(self, app, window=None):
        """Switches active engine to PyQtDarkTheme."""
        self.save_theme_engine("pyqtdarktheme")
        self.apply_current_theme(app, window=window)

    def set_engine_qss(self, app, window=None):
        """Switches active engine to Native Clean QSS."""
        self.save_theme_engine("qss")
        self.apply_current_theme(app, window=window)

    def toggle_theme(self, app=None, window=None):
        """Toggles brightness mode between dark and light."""
        app = app or QApplication.instance()
        eff = self.get_effective_brightness(app)
        new_mode = "light" if eff == "dark" else "dark"
        self.set_theme_mode(app, new_mode, window=window)
        return new_mode
