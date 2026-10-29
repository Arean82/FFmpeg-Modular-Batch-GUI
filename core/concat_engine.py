"""Concatenation engine supporting stream-copy concat demuxer and re-encode concat filter."""
import os
import tempfile
import subprocess
from core.config_manager import get_binary_path

def join_files(files: list, output_path: str, stream_copy: bool = True) -> tuple[bool, str]:
    if not files or len(files) < 2:
        return False, "At least two files are required for concatenation."

    ffmpeg_bin = get_binary_path("ffmpeg")

    if stream_copy:
        # Fast Stream Copy using concat demuxer
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                list_file = f.name
                for file_path in files:
                    escaped = file_path.replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")

            cmd = [
                ffmpeg_bin, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                output_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if os.path.exists(list_file):
                os.remove(list_file)

            if res.returncode == 0:
                return True, "Files joined successfully via stream copy."
            else:
                return False, f"Stream copy failed:\n{res.stdout[-400:]}"
        except Exception as e:
            return False, str(e)
    else:
        # Re-encode mode using concat filter
        cmd = [ffmpeg_bin, "-y"]
        filter_ins = ""
        for i, file_path in enumerate(files):
            cmd.extend(["-i", file_path])
            filter_ins += f"[{i}:v][{i}:a]"

        filter_complex = f"{filter_ins}concat=n={len(files)}:v=1:a=1[outv][outa]"
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:v", "libx264",
            "-crf", "22",
            "-preset", "fast",
            "-c:a", "aac",
            "-b:a", "160k",
            output_path
        ])

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if res.returncode == 0:
                return True, "Files joined successfully via re-encode filter."
            else:
                return False, f"Re-encode join failed:\n{res.stdout[-400:]}"
        except Exception as e:
            return False, str(e)
