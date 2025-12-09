Perfect — here’s a **polished, icon-rich, badge-style README** you can directly paste into your repo to make it look modern and attractive. I’ve kept it clean, professional, and “GitHub-worthy” with emojis, badges, and visual structure:

---

```markdown
<p align="center">
  <img src="https://raw.githubusercontent.com/Arean82/FFmpeg-Modular-Batch-GUI/main/assets/logo.png" width="140" alt="FFmpeg Modular Batch GUI Logo">
</p>

<h1 align="center">FFmpeg Modular Batch GUI</h1>

<p align="center">
  <b>A powerful, modular, preset-based FFmpeg batch conversion GUI built with Python & Tkinter</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue.svg">
  <img src="https://img.shields.io/badge/Platform-Windows-blue.svg">
  <img src="https://img.shields.io/badge/License-MIT-green.svg">
  <img src="https://img.shields.io/badge/FFmpeg-Required-red.svg">
</p>

---

## 🧾 Overview

**FFmpeg Modular Batch GUI** is a desktop application that simplifies complex FFmpeg batch operations using a clean graphical interface.  
It is designed for **bulk video processing, stream copy, GPU encoding (Intel QSV), audio extraction, and resolution scaling** — all without touching the command line.

---

## ✨ Key Features

✅ Folder-based batch processing  
✅ Checkbox-based file selection  
✅ Preset-driven FFmpeg commands  
✅ **Intel QSV GPU Acceleration** ⚡  
✅ Stream copy / rewrap (ultra-fast)  
✅ Audio-only extraction (AAC / MP3, etc.)  
✅ Per-file output resolution & format  
✅ Real-time FFmpeg console logs  
✅ Live progress tracking  
✅ Output file renaming  
✅ Safe exit with running-process protection  
✅ Modular, expandable architecture  

---

## 🎯 Use Cases

- 🎬 Bulk video conversion  
- 📦 Rewrapping `.ts` → `.mp4` without re-encoding  
- 🔊 Audio extraction from videos  
- ⚡ GPU-accelerated encoding  
- 🧪 Fixing corrupted or problem media  
- 📺 Batch resolution downscaling  

---

## 🗂️ Project Structure

```

FFmpeg-Modular-Batch-GUI/
│
├── main.py                 # Application entry point
├── config.py               # FFmpeg configuration
├── presets.py              # Preset definitions
├── file_manager.py         # File scanning & selection
├── ffmpeg_runner.py        # FFmpeg command executor
├── ui_main.py              # Main GUI window
├── ui_tree.py              # File tree view
├── ui_presets.py           # Preset manager UI
├── ui_preset_editor.py    # Preset editor
└── ffmpeg_presets.json    # Default + custom presets

````

---

## ⚙️ Requirements

- 🐍 Python **3.9 or newer**
- 🎥 FFmpeg (QSV-enabled build for GPU encoding)
- 🪟 Windows 10 / 11

---

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Arean82/FFmpeg-Modular-Batch-GUI.git
   cd FFmpeg-Modular-Batch-GUI
````

2. **Install Python dependencies (if any later added)**
   *(Currently uses only standard libraries)*

3. **Download FFmpeg**

4. **Set FFmpeg path in `config.py`**

   ```python
   FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"
   ```

5. **Launch the app**

   ```bash
   python main.py
   ```

---

## ▶️ How to Use

1. 📁 Select input folder
2. ✅ Select files using checkboxes
3. 📐 Choose preset
4. 📝 Modify output name, format, or resolution (optional)
5. 📤 Select output folder
6. ▶️ Click **Start Conversion**
7. 📊 Monitor progress and logs in real-time
8. ✅ Completion popup when finished

⚠️ If you attempt to close while encoding is running, the app will warn you and safely terminate FFmpeg if forced.

---

## 🚧 Known Limitations

* Only **Intel QSV** GPU encoding supported
* No job resume after app restart
* No NVENC / AMD support (yet)

---

## 🛣️ Roadmap

* ⏳ ETA for each file
* 📝 Export logs to file
* 🧩 Plugin system for presets
* 🖼️ Frame preview before conversion
* 🔁 Resume failed jobs
* 🎨 Possible Qt-based UI upgrade

---

## 📜 License

Licensed under the **MIT License**.
See `LICENSE` file for details.

---

## 🙏 Acknowledgements

* 🎞️ **FFmpeg Team** — backend video engine
* 🐍 **Python & Tkinter** — GUI framework
* ❤️ Open-source contributors & testers

---

## 📬 Support & Contributions

* 🐞 Open an **Issue** for bugs or feature requests
* 🔧 **Pull Requests** are welcome
* 📄 Include FFmpeg logs for faster debugging

---

<p align="center">
  ⭐ If you find this project useful, please consider giving it a star!
</p>
```

---

### ✅ What You Can Add for Extra Polish (Optional)

If you want, I can also:

* Add **automatic GitHub Actions status badge**
* Add **screenshots section (with markdown gallery)**
* Create a **professional SVG logo**
* Add **Contributing.md + Issue templates**

---

If you want, I can now:

* ✅ **Match this exactly to your existing folder names**
* ✅ Add a **Screenshots section** (if you upload 1–2 GUI images)
* ✅ Add a **short “Quick Start” version for beginners**

Tell me what style you prefer — **minimal / professional / flashy dev-tool look**.
