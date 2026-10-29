"""README / Documentation Viewer Dialog.
Uses Qt WebEngine (QWebEngineView) to render standard GitHub-Flavored Markdown,
including HTML tags (<div align="center">, <img>), SVG badges, tables, Mermaid
diagrams, and custom styling with full zoom controls and smooth fade animations.
Zero modifications to README.md.
"""

import json
import os

from PySide6.QtCore import QPropertyAnimation, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class CustomWebPage(QWebEnginePage):
    """Intercepts external links to open in default system web browser."""
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            if url.scheme() in ("http", "https", "mailto"):
                QDesktopServices.openUrl(url)
                return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class ReadmeViewerDialog(QDialog):
    """Renders README.md with full fidelity using Chromium-based QWebEngineView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Documentation - FFmpeg Modular Batch GUI")
        self.resize(980, 720)
        self.setModal(True)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(10)

        # Top Header Bar
        self.header_layout = QHBoxLayout()
        self.title_label = QLabel("📘 Documentation (README.md)")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 15px;")
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch()

        # Zoom Controls
        self.zoom_factor = 1.0

        self.zoom_out_btn = QPushButton("🔍 −")
        self.zoom_out_btn.setFixedSize(36, 28)
        self.zoom_out_btn.setToolTip("Zoom Out")
        self.zoom_out_btn.clicked.connect(self._zoom_out)

        self.zoom_in_btn = QPushButton("🔍 +")
        self.zoom_in_btn.setFixedSize(36, 28)
        self.zoom_in_btn.setToolTip("Zoom In")
        self.zoom_in_btn.clicked.connect(self._zoom_in)

        self.zoom_reset_btn = QPushButton("Reset Zoom")
        self.zoom_reset_btn.setFixedHeight(28)
        self.zoom_reset_btn.clicked.connect(self._zoom_reset)

        self.header_layout.addWidget(self.zoom_out_btn)
        self.header_layout.addWidget(self.zoom_in_btn)
        self.header_layout.addWidget(self.zoom_reset_btn)
        self.layout.addLayout(self.header_layout)

        # WebEngine View for Markdown & HTML rendering
        self.web_view = QWebEngineView(self)
        self.web_page = CustomWebPage(self)
        self.web_view.setPage(self.web_page)
        self.layout.addWidget(self.web_view)

        # Bottom Bar with Close Button
        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.setMinimumWidth(110)
        self.close_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 20px;
                font-weight: 500;
            }
        """)
        self.close_btn.clicked.connect(self.accept)
        self.bottom_layout.addWidget(self.close_btn)
        self.layout.addLayout(self.bottom_layout)

        # Load content
        self.load_readme()

    def _zoom_in(self):
        self.zoom_factor = min(2.5, self.zoom_factor + 0.1)
        self.web_view.setZoomFactor(self.zoom_factor)

    def _zoom_out(self):
        self.zoom_factor = max(0.5, self.zoom_factor - 0.1)
        self.web_view.setZoomFactor(self.zoom_factor)

    def _zoom_reset(self):
        self.zoom_factor = 1.0
        self.web_view.setZoomFactor(self.zoom_factor)

    def showEvent(self, event):
        """Smooth fade-in animation on open."""
        self.setWindowOpacity(0)
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(200)
        self.fade_anim.setStartValue(0)
        self.fade_anim.setEndValue(1)
        self.fade_anim.start()
        super().showEvent(event)

    def _fade_out_and_close(self, result_code):
        self.exit_anim = QPropertyAnimation(self, b"windowOpacity")
        self.exit_anim.setDuration(160)
        self.exit_anim.setStartValue(1)
        self.exit_anim.setEndValue(0)
        self.exit_anim.finished.connect(lambda: self.done(result_code))
        self.exit_anim.start()

    def accept(self):
        self._fade_out_and_close(QDialog.Accepted)

    def reject(self):
        self._fade_out_and_close(QDialog.Rejected)

    def load_readme(self):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        possible_names = ["README.md", "README", "Readme.md", "readme.md"]
        raw_md = ""

        for name in possible_names:
            path = os.path.join(base_dir, name)
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        raw_md = f.read()
                    break
                except Exception:
                    pass

        if not raw_md:
            raw_md = "# README not found\n\nCould not find a valid README.md in the application directory."

        # Map remote shield badge URLs to local SVG files in assets/badges/ for offline rendering
        badge_map = {
            "https://img.shields.io/badge/Platform-Linux%20Native-FCC624?logo=linux&logoColor=black": "assets/badges/platform.svg",
            "https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white": "assets/badges/python.svg",
            "https://img.shields.io/badge/Framework-PySide6%20%2F%20Qt6-41CD52?logo=qt&logoColor=white": "assets/badges/qt.svg",
            "https://img.shields.io/badge/FFmpeg-6.x%20%2F%207.x-007808?logo=ffmpeg&logoColor=white": "assets/badges/ffmpeg.svg",
            "https://img.shields.io/badge/License-MIT-blue.svg": "assets/badges/license.svg",
        }
        rendered_md = raw_md
        for remote_url, local_svg in badge_map.items():
            if os.path.exists(os.path.join(base_dir, local_svg)):
                rendered_md = rendered_md.replace(remote_url, local_svg)

        # Detect Dark Mode preference
        is_dark = False
        try:
            parent_window = self.parent()
            if parent_window and hasattr(parent_window, "theme_manager"):
                is_dark = (parent_window.theme_manager.current_mode == "dark")
        except Exception:
            pass

        theme_bg = "#1e1e1e" if is_dark else "#ffffff"
        theme_fg = "#d4d4d4" if is_dark else "#24292f"
        theme_border = "#3e3e3e" if is_dark else "#d0d7de"
        theme_code_bg = "#2d2d2d" if is_dark else "#f6f8fa"
        theme_table_header = "#252525" if is_dark else "#f6f8fa"
        theme_table_stripe = "#181818" if is_dark else "#fbfcfd"
        theme_link = "#58a6ff" if is_dark else "#0969da"

        escaped_md = json.dumps(rendered_md)

        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  body {{
    background-color: {theme_bg};
    color: {theme_fg};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    margin: 0;
    padding: 24px 32px;
  }}
  a {{ color: {theme_link}; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  h1, h2, h3, h4 {{
    border-bottom: 1px solid {theme_border};
    padding-bottom: 8px;
    margin-top: 24px;
    margin-bottom: 16px;
    font-weight: 600;
  }}
  h1 {{ font-size: 2em; }}
  h2 {{ font-size: 1.5em; }}
  h3 {{ font-size: 1.25em; border-bottom: none; }}
  p {{ margin-top: 0; margin-bottom: 16px; }}
  hr {{
    height: 1px;
    background-color: {theme_border};
    border: none;
    margin: 24px 0;
  }}
  code {{
    background-color: {theme_code_bg};
    border-radius: 4px;
    padding: 2px 6px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 85%;
  }}
  pre {{
    background-color: {theme_code_bg};
    border-radius: 6px;
    padding: 16px;
    overflow: auto;
    font-size: 85%;
    line-height: 1.45;
  }}
  pre code {{ background: none; padding: 0; }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin-top: 16px;
    margin-bottom: 16px;
    display: table;
  }}
  table th, table td {{
    padding: 8px 12px;
    border: 1px solid {theme_border};
    text-align: left;
  }}
  table th {{
    background-color: {theme_table_header};
    font-weight: 600;
  }}
  table tr:nth-child(even) {{
    background-color: {theme_table_stripe};
  }}
  blockquote {{
    border-left: 4px solid {theme_border};
    padding: 0 16px;
    color: #8b949e;
    margin: 0 0 16px 0;
  }}
  ul, ol {{ padding-left: 2em; margin-bottom: 16px; }}
  li {{ margin-top: 4px; }}
  img {{ max-width: 100%; height: auto; }}
  div[align="center"] {{ text-align: center; }}
  .mermaid {{ margin: 20px 0; text-align: center; }}
</style>
<script src="assets/vendor/marked.min.js"></script>
<script src="assets/vendor/mermaid.min.js"></script>
</head>
<body>
<div id="content"></div>
<script>
  if (typeof mermaid !== 'undefined') {{
    try {{
      mermaid.initialize({{ startOnLoad: false, theme: '{"dark" if is_dark else "default"}' }});
    }} catch(e) {{
      console.warn("Mermaid init:", e);
    }}
  }}

  const rawMarkdown = {escaped_md};

  if (typeof marked !== 'undefined') {{
    marked.use({{
      renderer: {{
        code(token) {{
          if (token.lang === 'mermaid') {{
            return '<div class="mermaid">' + token.text + '</div>';
          }}
          return false;
        }}
      }}
    }});
    document.getElementById('content').innerHTML = marked.parse(rawMarkdown);
  }} else {{
    document.getElementById('content').innerText = rawMarkdown;
  }}

  // Trigger Mermaid diagrams rendering safely
  if (typeof mermaid !== 'undefined') {{
    try {{
      mermaid.run();
    }} catch(e) {{
      console.warn("Mermaid run:", e);
    }}
  }}
</script>
</body>
</html>"""

        base_url = QUrl.fromLocalFile(base_dir + os.sep)
        self.web_view.setHtml(html_template, base_url)
