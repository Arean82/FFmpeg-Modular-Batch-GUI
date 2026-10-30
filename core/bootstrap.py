"""Early environment bootstrap for Linux desktop integration.

Configures environment flags and site-package fallback paths prior to PySide6 / Qt initialization.
"""
from __future__ import annotations

import os
import sys

# Suppress AT-SPI / dbind accessibility warnings when running under non-root / sudo environments
os.environ.setdefault("NO_AT_SPI", "1")
os.environ.setdefault("QT_ACCESSIBILITY", "0")

# Allow Chromium / QtWebEngine to initialize safely when executing as root or in elevated environments
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

# Avoid portal session registration collisions under non-flatpak environments
os.environ.setdefault("QT_NO_XDG_DESKTOP_PORTAL", "1")

# Ensure user site-packages are accessible even when launched with sudo / root
for user_site in [
    os.path.expanduser("~/.local/lib/python3.14/site-packages"),
    "/home/arean/.local/lib/python3.14/site-packages",
    "/home/arean/.local/lib/python3.12/site-packages",
    "/home/arean/.local/lib/python3.11/site-packages",
    "/home/arean/.local/lib/python3.10/site-packages",
]:
    if os.path.exists(user_site) and user_site not in sys.path:
        sys.path.insert(0, user_site)
