# main.py
# Qt6 Entry Point for FFmpeg Modular GUI Application

import sys
from PySide6.QtWidgets import QApplication
from qt_main import FFmpegQt   # this is the Qt window I gave you earlier


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = FFmpegQt()
    window.showMaximized()     # Qt equivalent of fullscreen windowed

    sys.exit(app.exec())
