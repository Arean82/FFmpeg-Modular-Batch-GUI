"""Hardware Thermal and Power Throttling Guard for FFmpeg Modular Batch GUI.

Monitors CPU package temperatures and GPU sensors (NVIDIA, AMD ROCm, Intel)
to automatically throttle encoding workers or pause processing when safe
thermal thresholds are exceeded, preventing hardware degradation and thermal shutdown.
"""
import os
import subprocess
from typing import Dict, Any, Optional


class ThermalGuard:
    """Monitors system hardware temperatures and advises throttling/pausing."""

    def __init__(self, max_temp_celsius: int = 85, resume_temp_celsius: int = 70):
        self.max_temp = max_temp_celsius
        self.resume_temp = resume_temp_celsius
        self.is_throttled = False

    def get_cpu_temp(self) -> Optional[float]:
        """Reads CPU package temperature in Celsius via sysfs or sensors."""
        # 1. Try Linux /sys/class/thermal/
        try:
            thermal_dir = "/sys/class/thermal"
            if os.path.exists(thermal_dir):
                temps = []
                for entry in os.listdir(thermal_dir):
                    if entry.startswith("thermal_zone"):
                        temp_file = os.path.join(thermal_dir, entry, "temp")
                        if os.path.exists(temp_file):
                            with open(temp_file, "r") as f:
                                val = float(f.read().strip())
                                # Usually in millidegrees C
                                if val > 1000:
                                    val /= 1000.0
                                temps.append(val)
                if temps:
                    return max(temps)
        except Exception:
            pass

        # 2. Try lm-sensors CLI
        try:
            res = subprocess.run(["sensors", "-u"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                temps = []
                for line in res.stdout.splitlines():
                    if "temp" in line and "_input:" in line:
                        parts = line.split(":")
                        if len(parts) == 2:
                            temps.append(float(parts[1].strip()))
                if temps:
                    return max(temps)
        except Exception:
            pass

        return None

    def get_gpu_temp(self) -> Optional[float]:
        """Reads GPU temperatures via nvidia-smi or rocm-smi."""
        # 1. NVIDIA
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=1
            )
            if res.returncode == 0:
                vals = [float(x.strip()) for x in res.stdout.strip().splitlines() if x.strip().isdigit()]
                if vals:
                    return max(vals)
        except Exception:
            pass

        # 2. AMD ROCm
        try:
            res = subprocess.run(["rocm-smi", "--showtemp"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                temps = []
                for line in res.stdout.splitlines():
                    if "c" in line.lower() and "edge" in line.lower():
                        for token in line.split():
                            if token.replace(".", "", 1).isdigit():
                                temps.append(float(token))
                if temps:
                    return max(temps)
        except Exception:
            pass

        return None

    def check_thermal_status(self) -> Dict[str, Any]:
        """Evaluates current system temperature against thresholds.

        Returns:
            Dict containing:
                cpu_temp: Optional[float]
                gpu_temp: Optional[float]
                max_observed: float
                should_pause: bool
                should_resume: bool
                status_text: str
        """
        cpu_t = self.get_cpu_temp()
        gpu_t = self.get_gpu_temp()

        valid_temps = [t for t in (cpu_t, gpu_t) if t is not None]
        max_obs = max(valid_temps) if valid_temps else 0.0

        should_pause = False
        should_resume = False

        if valid_temps:
            if max_obs >= self.max_temp:
                should_pause = True
                self.is_throttled = True
            elif self.is_throttled and max_obs <= self.resume_temp:
                should_resume = True
                self.is_throttled = False

        status_str = f"CPU: {cpu_t or 'N/A'}°C | GPU: {gpu_t or 'N/A'}°C"
        return {
            "cpu_temp": cpu_t,
            "gpu_temp": gpu_t,
            "max_observed": max_obs,
            "should_pause": should_pause,
            "should_resume": should_resume,
            "is_throttled": self.is_throttled,
            "status_text": status_str
        }
