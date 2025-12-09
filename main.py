# main.py
# Entry point for FFmpeg Modular GUI Application

import tkinter as tk
from ui_main import FFmpegGUI

if __name__ == "__main__":
    root = tk.Tk()
    root.title("FFmpeg Modular GUI")

    # ✅ Fullscreen modes — choose ONE:
    root.state("zoomed")              # Windowed fullscreen (recommended)
    # root.attributes("-fullscreen", True)  # True borderless fullscreen

    FFmpegGUI(root)
    root.mainloop()
