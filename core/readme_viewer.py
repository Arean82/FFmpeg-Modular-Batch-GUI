"""README / Documentation Viewer Dialog matching the pattern from Video-Analyse---Rename.
Pure Python dialog with zoom controls and smooth fade animation.
Uses QTextBrowser with native PySide6 markdown rendering (no external dependencies).
"""

import os

from PySide6.QtCore import QPropertyAnimation
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout


class ReadmeViewerDialog(QDialog):
    """Renders README.md with clean styling, zoom controls, and fade animation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("README - FFmpeg Batch AV Converter")
        self.resize(850, 600)
        self.setModal(True)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 12, 12, 12)
        self.layout.setSpacing(10)

        # Top Header Bar
        self.header_layout = QHBoxLayout()
        self.title_label = QLabel("📘 Documentation (README)")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch()

        # Zoom Controls
        self.zoom_in_btn = QPushButton("🔍 +")
        self.zoom_in_btn.setFixedSize(36, 26)
        self.zoom_in_btn.setToolTip("Zoom In")
        self.zoom_in_btn.clicked.connect(self._zoom_in)

        self.zoom_out_btn = QPushButton("🔍 −")
        self.zoom_out_btn.setFixedSize(36, 26)
        self.zoom_out_btn.setToolTip("Zoom Out")
        self.zoom_out_btn.clicked.connect(self._zoom_out)

        self.zoom_reset_btn = QPushButton("Reset Zoom")
        self.zoom_reset_btn.setFixedHeight(26)
        self.zoom_reset_btn.clicked.connect(self._zoom_reset)

        self.header_layout.addWidget(self.zoom_out_btn)
        self.header_layout.addWidget(self.zoom_in_btn)
        self.header_layout.addWidget(self.zoom_reset_btn)
        self.layout.addLayout(self.header_layout)

        # TextBrowser for Markdown rendering
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setStyleSheet("""
            QTextBrowser {
                padding: 12px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                font-size: 14px;
                line-height: 1.6;
            }
        """)
        self.layout.addWidget(self.text_browser)

        # Bottom Bar with Close Button
        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.setMinimumWidth(100)
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
        self.text_browser.zoomIn(1)

    def _zoom_out(self):
        self.text_browser.zoomOut(1)

    def _zoom_reset(self):
        # Reset zoom font size
        font = self.text_browser.font()
        font.setPointSize(11)
        self.text_browser.setFont(font)

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

        self.text_browser.setMarkdown(raw_md)
