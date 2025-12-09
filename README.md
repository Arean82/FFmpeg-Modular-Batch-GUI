# FFmpeg-Modular-Batch-GUI



# 🎬 FFmpeg Modular Batch GUI (Python + Tkinter)

A **modular, preset-based FFmpeg batch video converter GUI** built with **Python + Tkinter**.  
Designed for fast **bulk conversion**, **stream copy**, **Intel QSV GPU encoding**, **audio extraction**, **error recovery**, and **resolution scaling** with a clean checkbox-based interface.



## ✅ Key Features

- 📁 **Folder-based batch processing**
- ✅ **Checkbox file selection**
- 🎛 **Preset-based FFmpeg commands**
- ⚡ **Intel QSV GPU encoding support**
- 🔁 **Direct stream copy & rewrap (no re-encode)**
- 🎧 **Audio-only extraction**
- 📏 **Per-file output resolution selection**
- 📦 **Per-file output format selection**
- 📝 **Live FFmpeg console logs in GUI**
- 📊 **Progress bar with real-time updates**
- ✏️ **Editable output file names**
- 📂 **Single output folder per session**
- ⚠️ **Warns on close if encoding is running**
- 🛑 **Kills FFmpeg process on forced exit**
- 🗂 **Preset categorization (Copy / GPU / CPU / Audio / Fix / LowBW)**
- **Modular Architecture**



## 📂 Supported Input Formats

```

.ts   .mp4   .mkv   .avi   .mov

```



## 🧠 Preset Categories

- **Copy**
  - Direct Copy (Fastest)
  - Copy with Error Recovery
  - Rewrap (TS → MP4)

- **GPU (Intel QSV)**
  - H.264 QSV Balanced / High Quality
  - HEVC QSV Small / Very Small
  - HEVC 720p Sharpen

- **CPU (x264 / x265)**
  - H.264 Standard / High Quality
  - HEVC Small / Very Small

- **Audio Only**
  - Extract AAC / MP3
  - Audio Copy Only

- **Fix / Filters**
  - Fix A/V Sync
  - Normalize Audio

- **Low Bandwidth**
  - 480p Mobile
  - Ultra Low Bandwidth

Presets are stored in:
```

ffmpeg_presets.json

```
and auto-merged with defaults.



## 🗂 Project Structure

```
ffmpeg_gui/
│
├── main.py
├── config.py
├── presets.py
├── file_manager.py
├── ffmpeg_runner.py
├── ui_main.py
├── ui_preset_editor.py
└── ffmpeg_presets.json
```


## ⚙️ Requirements

- Python **3.9+**
- FFmpeg **with Intel QSV support**
- Windows 10 / 11 (tested)



## 🔧 Setup Instructions

1. Install Python  
2. Download FFmpeg (QSV enabled)
3. Set FFmpeg path in:

```python
# config.py
FFMPEG_PATH = r"C:\path\to\ffmpeg.exe"
````

4. Run:

```bash
python main.py
```



## ▶️ How to Use

1. Click **Select Folder**
2. Choose a folder with video files
3. Select files using **checkboxes**
4. Choose a **preset**
5. (Optional) Change:

   * Output name
   * Output format
   * Output resolution
6. Choose **Output Folder**
7. Click **Start Conversion**
8. Monitor:

   * Live logs
   * Progress bar
9. Completion popup appears when done ✅



## 🚨 Safe Exit Handling

* If FFmpeg is running and you close the app:

  * You get a **warning**
  * If confirmed, all FFmpeg processes are **terminated safely**



## 🐞 Known Limitations

* NVENC not supported (Intel QSV only)
* No multi-GPU scheduling
* No job queue persistence (yet)



## 🛣 Roadmap

* ⏳ Estimated time remaining per file
* 📄 Export conversion logs
* 🧩 Plugin-based preset packs
* 🎞 Frame preview
* 🔄 Resume failed jobs
* Planned update to QT6


## 🛡 License

This project is released under the **MIT License**.



## 🙏 Credits

* FFmpeg Team for the backend engine
* Python + Tkinter for GUI framework



## 📬 Support

If you face issues:

* Open a GitHub issue
* Or attach console logs for debugging



### ✅ Built for power users who prefer **precision, speed, and control** over one-click bloated converters.

```



If you want, I can also:

- Add **badges** (Python, Windows, FFmpeg)
- Add **screenshots section**
- Add **download / release instructions**
- Add **contribution guidelines**

Just tell me what you want added.
```
