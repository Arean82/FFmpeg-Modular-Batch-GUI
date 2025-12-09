# ui_console.py
# FFmpeg log console display UI component

import tkinter as tk
from tkinter import ttk

class ConsoleUI:
    def __init__(self, root):
        self.frame = ttk.LabelFrame(root, text="FFmpeg Console")
        self.frame.pack(fill="both", expand=True, padx=8, pady=6)

        self.log = tk.Text(self.frame, height=10, wrap="word")
        self.log.pack(fill="both", expand=True)

    def log_line(self, text):
        def append():
            self.log.insert("end", text + "\n")
            self.log.see("end")
        self.log.after(0, append)
