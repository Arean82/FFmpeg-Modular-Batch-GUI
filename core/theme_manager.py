"""Theme Manager for FFmpeg Batch AV Converter.

Replicates the complete theme architecture from Video-Analyse---Rename:
- Modes: 'light', 'dark', 'system' (with OS dark detection)
- Material themes via `qt_material`
- Built-in generic QSS themes (dark.qss / light.qss)
- Configuration persistence via config_manager
"""
import os
from pathlib import Path
from PySide6.QtWidgets import QApplication
from core.config_manager import get_config, save_config


class ThemeManager:
    def __init__(self):
        self.themes_dir = Path(__file__).parent.parent / "assets" / "themes"

    def get_theme_mode(self) -> str:
        """Returns 'light', 'dark', or 'system' (default: 'dark')."""
        cfg = get_config()
        return cfg.get("theme_mode", "dark")

    def save_theme_mode(self, mode: str):
        """Saves theme mode: 'light', 'dark', or 'system'."""
        cfg = get_config()
        cfg["theme_mode"] = mode
        save_config(cfg)

    def get_material_theme(self) -> str:
        """Returns 'default' (Generic built-in) or a material theme file name (e.g. 'dark_teal.xml')."""
        cfg = get_config()
        return cfg.get("material_theme", "default")

    def save_material_theme(self, theme_name: str):
        """Saves selected material theme (e.g., 'default', 'blue', 'dark_teal.xml')."""
        cfg = get_config()
        cfg["material_theme"] = theme_name
        save_config(cfg)

    def is_system_dark(self, app=None) -> bool:
        """Detects if system OS is currently dark mode."""
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

    def get_all_material_themes(self) -> list:
        """Returns list of all available Material theme files from qt_material."""
        try:
            import qt_material
            return qt_material.list_themes()
        except ImportError:
            return []

    def apply_current_theme(self, app=None):
        """Applies theme based on saved theme_mode and material_theme."""
        app = app or QApplication.instance()
        if not app:
            return

        mode = self.get_theme_mode()
        material = self.get_material_theme()
        effective_brightness = self.get_effective_brightness(app)

        if material == "default":
            # Apply built-in generic QSS theme (dark.qss or light.qss)
            app.setStyleSheet("")
            qss_file = self.themes_dir / f"{effective_brightness}.qss"
            if qss_file.exists():
                with open(qss_file, "r", encoding="utf-8") as f:
                    app.setStyleSheet(f.read())
        else:
            # Material Theme selected: resolve dark/light variant matching current mode
            available = self.get_all_material_themes()
            color_name = material.replace(".xml", "").replace("dark_", "").replace("light_", "")
            
            # Primary choice: matching current brightness (e.g., 'dark_blue.xml' or 'light_blue.xml')
            target_xml = f"{effective_brightness}_{color_name}.xml"
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
                app.setStyleSheet("")
                apply_stylesheet(app, theme=target_xml)
            except Exception:
                # Fallback to generic theme if qt_material fails
                qss_file = self.themes_dir / f"{effective_brightness}.qss"
                if qss_file.exists():
                    with open(qss_file, "r", encoding="utf-8") as f:
                        app.setStyleSheet(f.read())

    def set_theme_mode(self, app, mode: str):
        """Sets brightness mode ('light', 'dark', 'system') and reapplies theme."""
        self.save_theme_mode(mode)
        self.apply_current_theme(app)

    def set_material_theme(self, app, material_name: str):
        """Sets material theme ('default' or specific color/xml) and reapplies theme."""
        self.save_material_theme(material_name)
        self.apply_current_theme(app)

    def toggle_theme(self, app=None):
        """Toggles brightness mode between dark and light."""
        app = app or QApplication.instance()
        eff = self.get_effective_brightness(app)
        new_mode = "light" if eff == "dark" else "dark"
        self.set_theme_mode(app, new_mode)
        return new_mode
