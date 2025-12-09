# ui_presets.py
# UI component for managing FFmpeg presets --- Preset combobox + active args display

import tkinter as tk
from tkinter import ttk

class PresetUI:
    def __init__(self, root, presets, on_change):
        self.presets = presets
        self.on_change = on_change

        sorted_presets = sorted(
            presets.items(),
            key=lambda x: (x[1].get("category", ""), x[0])
        )

        self.preset_box = ttk.Combobox(
            root,
            values=[f"{v.get('category','Other')} :: {k}" for k, v in sorted_presets],
            state="readonly"
        )
        if sorted_presets:
            self.preset_box.current(0)

        self.preset_box.pack(fill="x", pady=4)
        self.preset_box.bind("<<ComboboxSelected>>", self._changed)

        # ---- Active args display ----
        args_frame = ttk.Frame(root)
        args_frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(args_frame, text="Active FFmpeg Args:").pack(side="left")

        self.active_args_var = tk.StringVar()
        self.active_args_entry = ttk.Entry(
            args_frame,
            textvariable=self.active_args_var,
            state="readonly"
        )
        self.active_args_entry.pack(side="left", fill="x", expand=True, padx=5)

        self.update_active_args()

    def _changed(self, event=None):
        self.update_active_args()
        self.on_change()

    def update_active_args(self):
        display_name = self.preset_box.get()
        if not display_name:
            return

        if "::" in display_name:
            preset_key = display_name.split("::", 1)[1].strip()
        else:
            preset_key = display_name.strip()

        if preset_key not in self.presets:
            return

        args = self.presets[preset_key]["args"]
        self.active_args_var.set(args)

    def get_active_preset_key(self):
        display_name = self.preset_box.get()
        return display_name.split("::", 1)[1].strip()

    def get_active_args(self):
        return self.active_args_var.get()

    def refresh(self, presets):
        self.presets = presets
        sorted_presets = sorted(
            presets.items(),
            key=lambda x: (x[1].get("category", ""), x[0])
        )
        self.preset_box["values"] = [
            f"{v.get('category','Other')} :: {k}" for k, v in sorted_presets
        ]
        if sorted_presets:
            self.preset_box.current(0)
        self.update_active_args()
