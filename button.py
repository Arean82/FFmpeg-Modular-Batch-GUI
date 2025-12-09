# button.py
# A themed toggle button for starting/stopping a process using tkinter and ttk.
# It changes appearance based on its state (running or not running).

import tkinter as tk
from tkinter import ttk


class ThemedToggleButton:
    def __init__(self, parent, command):
        self.parent = parent
        self.command = command

        self.is_running = False

        # ttk style
        self.style = ttk.Style()
        self._create_styles()

        # actual button
        self.button = ttk.Button(
            parent,
            text="Start Conversion",
            style="Start.TButton",
            command=self._on_click
        )

        # mouse events
        self.button.bind("<Enter>", self._on_hover)
        self.button.bind("<Leave>", self._on_leave)
        self.button.bind("<ButtonPress-1>", self._on_press)

    def _create_styles(self):
        # START styles (Green)
        self.style.configure("Start.TButton",
            foreground="white",
            background="#2ecc71",
            font=("Segoe UI", 10, "bold"),
            padding=8
        )
        self.style.map("Start.TButton",
            background=[
                ("active", "#58d68d"),
                ("pressed", "#239b56")
            ]
        )

        # STOP styles (Red)
        self.style.configure("Stop.TButton",
            foreground="white",
            background="#e74c3c",
            font=("Segoe UI", 10, "bold"),
            padding=8
        )
        self.style.map("Stop.TButton",
            background=[
                ("active", "#ec7063"),
                ("pressed", "#b03a2e")
            ]
        )

    def _on_click(self):
        # Delegate real logic to GUI
        self.command()

    def _on_hover(self, event):
        pass  # ttk already handles hover via style.map

    def _on_leave(self, event):
        pass

    def _on_press(self, event):
        pass

    def pack(self, **kwargs):
        self.button.pack(**kwargs)

    def set_running(self, running: bool):
        """Call this from GUI to toggle Start/Stop appearance"""
        self.is_running = running

        if running:
            self.button.configure(
                text="Stop Conversion",
                style="Stop.TButton"
            )
        else:
            self.button.configure(
                text="Start Conversion",
                style="Start.TButton"
            )
