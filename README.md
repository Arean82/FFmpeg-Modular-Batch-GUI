


# 🎬 FFmpeg Modular Batch GUI (Python + Tkinter)

A **modular, preset-driven, batch FFmpeg GUI** built with **Python & Tkinter** for fast, reliable, and user-friendly media processing.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![FFmpeg](https://img.shields.io/badge/FFmpeg-Required-red)



## 🧾 Overview

**FFmpeg Modular Batch GUI** is designed to simplify complex FFmpeg batch workflows using a clean graphical interface.  
It supports **bulk conversion, stream copy, GPU acceleration, audio extraction, resolution scaling**, and more — without needing to type FFmpeg commands manually.

The application is built with a **modular architecture**, making it easy to extend with new presets and features in future updates.

---

## ✅ Key Features

🧩 Modular, extendable architecture  
📁 Folder-based batch processing  
✅ Checkbox file selection  
🎛 Preset-based FFmpeg commands  
⚡ Intel QSV GPU encoding support  
🔁 Direct stream copy & rewrap (no re-encode)  
🎧 Audio-only extraction  
📏 Per-file output resolution selection  
📦 Per-file output format selection  
📝 Live FFmpeg console logs in GUI  
📊 Progress bar with real-time updates  
✏️ Editable output file names  
📂 Single output folder per session  
⚠️ Warns on close if encoding is running  
🛑 Kills FFmpeg process on forced exit  
🗂 Preset categorization (Copy / GPU / CPU / Audio / Fix / LowBW)

---

## 🎯 Use Cases

🎬 Bulk video conversion  
📦 Rewrapping `.ts` → `.mp4` without quality loss  
🔊 Extracting audio from video files  
⚡ GPU-accelerated video encoding  
🧪 Fixing corrupted or problematic media  
📺 Batch resolution downscaling  
📉 Creating low-bandwidth media versions

---

## 🗂 Project Structure

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

🐍 Python **3.9+**  
🎥 FFmpeg (**QSV-enabled build** for GPU encoding)  
🪟 Windows **10 / 11**

---

## 🛠 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/Arean82/FFmpeg-Modular-Batch-GUI.git
   cd FFmpeg-Modular-Batch-GUI
   ```

2. **Download FFmpeg** and ensure it works from command line

3. **Set FFmpeg path in `config.py`**

   ```python
   FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"
   ```

4. **Run the application**

   ```bash
   python main.py
   ```

---

## ▶️ Usage

1. 📁 Select an **input folder**
2. ✅ Choose files using **checkboxes**
3. 🎛 Select a **preset**
4. 📏 Adjust **resolution / format / output name** (optional)
5. 📂 Select **output folder**
6. ▶️ Click **Start Conversion**
7. 📝 Monitor **logs & progress**
8. ✅ Completion notification when finished

⚠️ Closing the app while encoding will trigger a **warning** and safely terminate FFmpeg if forced.

---

## 🚧 Known Limitations

* Only **Intel QSV** GPU encoding is supported
* No job persistence after restart
* No NVENC or AMD GPU support yet

---

## 🛣 Roadmap

⏳ Estimated time remaining per file
📝 Export FFmpeg logs to files
🧩 Plugin-based preset system
🖼 Frame preview before encoding
🔁 Resume failed jobs
🎨 Possible Qt-based UI upgrade

---

## 📜 License

This project is licensed under the **MIT License**.
See the `LICENSE` file for details.

---

## 🙏 Acknowledgements

🎞 **FFmpeg Team** — Media processing engine
🐍 **Python & Tkinter** — GUI framework
❤️ Open-source contributors & testers

---

## 📬 Support & Contributions

🐞 Report bugs via **GitHub Issues**
🔧 **Pull requests are welcome**
📄 Attach FFmpeg logs for faster debugging



