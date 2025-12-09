import os, subprocess
from config import VIDEO_EXTS, FFPROBE_PATH

def scan_folder(folder):
    return [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(VIDEO_EXTS)
    ]


def build_output_name(infile, out_dir=None, rename=True):
    base = os.path.splitext(os.path.basename(infile))[0]
    if rename:
        base += "_converted"
    if not out_dir:
        out_dir = os.path.dirname(infile)
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, base + ".mp4")


def get_resolution(path):
    try:
        out = subprocess.check_output([
            FFPROBE_PATH,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            path
        ])
        return out.decode().strip()
    except Exception:
        return "unknown"
    
def get_duration(path):
    try:
        out = subprocess.check_output([
            FFPROBE_PATH, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", path
        ])
        return float(out.decode().strip())
    except:
        return 0
    