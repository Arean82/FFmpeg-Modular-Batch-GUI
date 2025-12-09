# ffmpeg_runner.py
# Module to run FFmpeg commands and track progress

import subprocess, re, os, signal

TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

def run_ffmpeg(infile, outfile, args, on_progress=None, on_log=None):
    cmd = f'"{infile}"'

    full_cmd = f'ffmpeg -y -i "{infile}" {args} "{outfile}"'

    proc = subprocess.Popen(
        full_cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )

    for line in proc.stderr:
        if on_log:
            on_log(line.strip())

        m = TIME_RE.search(line)
        if m and on_progress:
            h, m_, s = m.groups()
            sec = int(h) * 3600 + int(m_) * 60 + float(s)
            on_progress(sec)

    return proc
