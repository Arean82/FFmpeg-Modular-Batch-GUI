#!/bin/bash
set -e
export QT_QPA_PLATFORMTHEME="${QT_QPA_PLATFORMTHEME:-qt6ct}"
export QTWEBENGINE_DISABLE_SANDBOX=1
cd /app/share/ffmpeg-batch-gui
exec python3 main.py "$@"
