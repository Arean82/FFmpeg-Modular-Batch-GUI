import subprocess, re, threading
from config import FFMPEG_PATH

TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

# on_progress(seconds)
# on_log(line)
def run_ffmpeg(infile, outfile, args, on_progress=None, on_log=None):
    cmd = f'"{FFMPEG_PATH}" -y -i "{infile}" {args} "{outfile}"'

    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )

    def read_stderr():
        for line in proc.stderr:
            line = line.strip()

            if on_log:
                on_log(line)

            m = TIME_RE.search(line)
            if m and on_progress:
                h, m_, s = m.groups()
                sec = int(h) * 3600 + int(m_) * 60 + float(s)
                on_progress(sec)

    threading.Thread(target=read_stderr, daemon=True).start()

    return proc
