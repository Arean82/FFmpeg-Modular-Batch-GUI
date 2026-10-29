# FFmpeg Batch AV Converter (Linux Native)

A high-performance, native Linux multi-threaded batch audio and video converter ported from FFmpeg Batch AV Converter to PySide6 (Qt for Python) and native Linux FFmpeg/FFprobe.

---

## Highlights & Features

- **Strictly Decoupled UI:** All views, windows, and auxiliary dialogs are built as standard Qt `.ui` XML files fully editable in Qt Designer (`designer-qt6`). Zero hardcoded layout geometry in Python.
- **Pure Linux Ecosystem:** All Windows dependencies, paths (`C:\`), and executables (`.exe`) have been purged. Operates directly on native Linux paths and system binaries.
- **Multi-Threaded Queue:** Concurrent encoding powered by `QThreadPool` and `QRunnable` with customizable thread allocation, real-time per-file progress percentage, and speed estimation.
- **Dynamic Variable Tokens:** Supports parameter templating with variables including `%~n` (basename), `%~x` (extension), `<res>` (resolution), `<vcodec>`, `<acodec>`, and `<source_dir>`.
- **4 Dedicated Operational Tabs:**
  1. **Batch Processing:** Full queue encoding with multi-pass, hardware acceleration, watermarking, audio fades, and real-time size estimation.
  2. **Stream Multiplexing:** Multi-track muxing (video, audio, subtitles) with metadata and language tagging.
  3. **Batch Subtitles:** Subtitle hardcode burn-in (`-vf subtitles=...`) or soft-embed muxing.
  4. **Batch URLs / Streams:** Online media extraction and direct remuxing via `yt-dlp` and `ffmpeg`.

---

## Integrated Tools & Dialogs

Accessible via the application menus or shortcut keys:

- **Two-Pass Target Size Calculator (`Ctrl+Shift+T`):** Calculate the exact video bitrate required to fit a target file size (e.g., Discord 25MB, DVD, Email) and automatically configure 2-pass encoding.
- **Try Current Preset (10s):** Test the active encoding preset on a 10-second segment before committing to full queue conversion.
- **Terminal Command Preview:** View and copy the exact FFmpeg command string generated for selected queue items.
- **Trim / Cut Video:** Non-destructive stream cut or precision re-encode by timestamp or frame range.
- **Join / Concatenate Files:** Merge multiple media files with drag-and-drop reordering using either FFmpeg concat demuxer (stream copy) or concat filter.
- **Crop & Black Bars Detection:** Automated `cropdetect` filter integration with aspect ratio analysis and custom crop box configuration.
- **Watermark / Logo Overlay:** Interactive image watermark overlay with 9-point alignment (Top-Left, Center, Bottom-Right, etc.), offset padding, and opacity scaling.
- **Silence Detector & Remover:** Detects and trims audio silence using FFmpeg `silencedetect` and `silenceremove` filters.
- **Generate Video Teaser / Trailer:** Generates preview trailers by sampling sequential slices across media duration.
- **Create Video from Still Images:** Compiles still image sequences or slideshows into video with custom framerates and codecs.
- **Inspect Media Streams (MediaInfo) (`Ctrl+I`):** In-depth audio/video stream inspector with codec parameters, bitrates, sample rates, channels, and tags.
- **File Types Exclusion Filter:** Configure media and non-media extension exclusions so batch folder imports skip unwanted files.
- **Multiple Presets Batch Run:** Sequence multiple encoding presets against the queue simultaneously.

---

## Requirements & Dependencies

On Ubuntu / Debian-based distributions:

```bash
sudo apt update
sudo apt install -y python3-pyside6 ffmpeg yt-dlp qt6-tools-dev-tools
```

---

## Launching the Application

### From Terminal:

```bash
cd /home/arean/Downloads/Other/ffmpeg_batch-master
./run.sh
# or
python3 main.py
```

### From Desktop Menu:
The desktop entry is registered at `~/.local/share/applications/ffmpeg-batch-linux.desktop` and appears in your application launcher under **Sound & Video** / **AudioVideo**.

---

## Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Ctrl + O` | Add Files to Queue |
| `Ctrl + R` | Start Queue Processing |
| `Ctrl + I` | Inspect Media Streams (MediaInfo) |
| `Ctrl + Shift + T` | Two-Pass Target Size Calculator |
| `Ctrl + ,` | Application Settings |
| `F1` | Open Readme / Documentation Viewer |
| `Delete` | Remove Selected Items from Queue |
| `Ctrl + Q` | Exit Application |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
