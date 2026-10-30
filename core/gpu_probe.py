"""Automated GPU hardware-accelerated encoder probing for FFmpeg.

Probes which hardware transcode APIs are available on the current system:
  - NVIDIA NVENC  (h264_nvenc, hevc_nvenc, av1_nvenc)
  - AMD/Intel VAAPI  (h264_vaapi, hevc_vaapi, av1_vaapi)
  - Intel QSV  (h264_qsv, hevc_qsv, av1_qsv)

Each probe runs a very-short null-sink FFmpeg encode so it completes
in milliseconds regardless of whether GPU is present.
"""

import subprocess

from core.config_manager import get_binary_path

# Encoders to probe grouped by vendor
_PROBE_PLAN: dict[str, list[dict]] = {
    "NVIDIA NVENC": [
        {"enc": "h264_nvenc",  "label": "H.264 NVENC",  "preset": "p1"},
        {"enc": "hevc_nvenc",  "label": "H.265 NVENC",  "preset": "p1"},
        {"enc": "av1_nvenc",   "label": "AV1 NVENC",    "preset": "p1"},
    ],
    "AMD/Intel VAAPI": [
        {"enc": "h264_vaapi",  "label": "H.264 VAAPI",  "preset": None},
        {"enc": "hevc_vaapi",  "label": "H.265 VAAPI",  "preset": None},
        {"enc": "av1_vaapi",   "label": "AV1 VAAPI",    "preset": None},
    ],
    "Intel QSV": [
        {"enc": "h264_qsv",    "label": "H.264 QSV",    "preset": None},
        {"enc": "hevc_qsv",    "label": "H.265 QSV",    "preset": None},
        {"enc": "av1_qsv",     "label": "AV1 QSV",      "preset": None},
    ],
}

# Safe minimal FFmpeg command to test hardware encoder availability
_NULL_SINK_TEMPLATE = [
    "{ffmpeg}", "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", "color=c=black:s=32x32:r=1",
    "-frames:v", "2",
    "-c:v", "{encoder}",
]


def _build_probe_cmd(ffmpeg_bin: str, enc: str, preset: str | None) -> list[str]:
    cmd = []
    for tok in _NULL_SINK_TEMPLATE:
        cmd.append(tok.replace("{ffmpeg}", ffmpeg_bin).replace("{encoder}", enc))

    if enc.endswith("_vaapi"):
        # VAAPI requires hwupload + pixel format
        cmd = [
            ffmpeg_bin, "-hide_banner", "-loglevel", "error",
            "-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128",
            "-f", "lavfi", "-i", "color=c=black:s=32x32:r=1",
            "-vf", "format=nv12,hwupload",
            "-frames:v", "2",
            "-c:v", enc,
        ]
    elif enc.endswith("_qsv"):
        cmd = [
            ffmpeg_bin, "-hide_banner", "-loglevel", "error",
            "-hwaccel", "qsv",
            "-f", "lavfi", "-i", "color=c=black:s=32x32:r=1",
            "-vf", "format=nv12",
            "-frames:v", "2",
            "-c:v", enc,
        ]

    if preset and enc.endswith("_nvenc"):
        cmd.extend(["-preset", preset])

    cmd.extend(["-f", "null", "-"])
    return cmd


def probe_gpu_encoders(timeout: float = 5.0) -> dict[str, list[dict]]:
    """
    Probe available hardware encoders.

    Returns a dict mapping vendor_name -> list of {enc, label, available, error}.
    """
    ffmpeg_bin = get_binary_path("ffmpeg")
    results: dict[str, list[dict]] = {}

    for vendor, encoders in _PROBE_PLAN.items():
        vendor_results = []
        for spec in encoders:
            enc = spec["enc"]
            preset = spec.get("preset")
            cmd = _build_probe_cmd(ffmpeg_bin, enc, preset)
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    text=True
                )
                ok = proc.returncode == 0
                err = "" if ok else proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "Unknown error"
            except FileNotFoundError:
                ok = False
                err = "ffmpeg not found"
            except subprocess.TimeoutExpired:
                ok = False
                err = "Probe timed out"
            except Exception as e:
                ok = False
                err = str(e)

            vendor_results.append({
                "enc": enc,
                "label": spec["label"],
                "available": ok,
                "error": err,
            })
        results[vendor] = vendor_results

    return results


def build_hwaccel_args(enc: str) -> str:
    """Returns ready-to-use FFmpeg parameter snippet for the given hardware encoder."""
    if enc.endswith("_nvenc"):
        if "h264" in enc:
            return f"-c:v {enc} -preset p4 -rc vbr -cq 23 -c:a aac -b:a 160k"
        elif "hevc" in enc:
            return f"-c:v {enc} -preset p4 -rc vbr -cq 24 -c:a aac -b:a 160k"
        elif "av1" in enc:
            return f"-c:v {enc} -preset p4 -cq 28 -c:a libopus -b:a 128k"
    elif enc.endswith("_vaapi"):
        base = f"-vaapi_device /dev/dri/renderD128 -vf 'format=nv12,hwupload' -c:v {enc} -qp 23 -c:a aac"
        return base
    elif enc.endswith("_qsv"):
        return f"-c:v {enc} -global_quality 23 -c:a aac -b:a 160k"
    return f"-c:v {enc}"


def get_available_encoder_args() -> list[dict]:
    """Returns a flat list of available GPU encoders with their FFmpeg args."""
    results = probe_gpu_encoders()
    available = []
    for vendor, encoders in results.items():
        for e in encoders:
            if e["available"]:
                available.append({
                    "label": f"{e['label']} ({vendor})",
                    "enc": e["enc"],
                    "args": build_hwaccel_args(e["enc"]),
                })
    return available
