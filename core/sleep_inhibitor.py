"""Linux sleep and screen blanking inhibitor.

Prevents the operating system from suspending, sleeping, or blanking
the screen while heavy batch media encoding is actively running.
Utilizes standard freedesktop D-Bus APIs (PowerManagement, ScreenSaver, GNOME SessionManager)
with graceful systemd-inhibit fallback.
"""
import subprocess
from typing import Optional, List, Tuple


class SleepInhibitor:
    """Manages an active power inhibitor lock on Linux across diverse desktop environments."""

    def __init__(self, app_name: str = "FFmpeg Modular Batch GUI"):
        self.app_name = app_name
        self.reason = "Encoding media batch queue"
        self._active_dbus_cookies: List[Tuple[str, str, int]] = []  # (dest, path, cookie)
        self._proc: Optional[subprocess.Popen] = None
        self.is_active = False

    def inhibit(self) -> bool:
        """Acquires sleep, idle, and screen blanking inhibition locks."""
        if self.is_active:
            return True

        acquired_any = False

        # Tier 1: org.freedesktop.PowerManagement.Inhibit (KDE, XFCE, FreeDesktop standard)
        # Flag 1 = suspend inhibition
        try:
            cmd = [
                "dbus-send",
                "--print-reply",
                "--dest=org.freedesktop.PowerManagement.Inhibit",
                "/org/freedesktop/PowerManagement/Inhibit",
                "org.freedesktop.PowerManagement.Inhibit.Inhibit",
                f"string:{self.app_name}",
                f"string:{self.reason}",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "uint32" in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            cookie = int(parts[1])
                            self._active_dbus_cookies.append(
                                ("org.freedesktop.PowerManagement.Inhibit", "/org/freedesktop/PowerManagement/Inhibit", cookie)
                            )
                            acquired_any = True
                            break
        except Exception:
            pass

        # Tier 2: org.gnome.SessionManager.Inhibit (GNOME 3/40+, Cinnamon, Budgie)
        # Flag 8 = Suspend/Sleep Inhibit, Flag 4 = Idle Inhibit (Combined = 12)
        try:
            cmd = [
                "dbus-send",
                "--print-reply",
                "--dest=org.gnome.SessionManager",
                "/org/gnome/SessionManager",
                "org.gnome.SessionManager.Inhibit",
                f"string:{self.app_name}",
                "uint32:0",
                f"string:{self.reason}",
                "uint32:12",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "uint32" in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            cookie = int(parts[1])
                            self._active_dbus_cookies.append(
                                ("org.gnome.SessionManager", "/org/gnome/SessionManager", cookie)
                            )
                            acquired_any = True
                            break
        except Exception:
            pass

        # Tier 3: org.freedesktop.ScreenSaver (Screen blanking prevention)
        try:
            cmd = [
                "dbus-send",
                "--print-reply",
                "--dest=org.freedesktop.ScreenSaver",
                "/org/freedesktop/ScreenSaver",
                "org.freedesktop.ScreenSaver.Inhibit",
                f"string:{self.app_name}",
                f"string:{self.reason}",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "uint32" in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            cookie = int(parts[1])
                            self._active_dbus_cookies.append(
                                ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", cookie)
                            )
                            acquired_any = True
                            break
        except Exception:
            pass

        # Tier 4: Fallback to systemd-inhibit process holding idle:sleep lock
        if not acquired_any:
            try:
                cmd = [
                    "systemd-inhibit",
                    "--what=idle:sleep",
                    f"--who={self.app_name}",
                    f"--why={self.reason}",
                    "sleep", "infinity"
                ]
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.is_active = True
                return True
            except Exception:
                pass

        if acquired_any:
            self.is_active = True
            return True

        return False

    def uninhibit(self):
        """Releases all active sleep and screen blanking inhibition locks."""
        if not self.is_active:
            return

        # Release all D-Bus cookies held across tiers
        for dest, path, cookie in self._active_dbus_cookies:
            try:
                unInhibitMethod = f"{dest}.UnInhibit"
                cmd = [
                    "dbus-send",
                    f"--dest={dest}",
                    path,
                    unInhibitMethod,
                    f"uint32:{cookie}",
                ]
                subprocess.run(cmd, capture_output=True, timeout=2)
            except Exception:
                pass
        self._active_dbus_cookies.clear()

        # Terminate systemd-inhibit process if running
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        self.is_active = False
