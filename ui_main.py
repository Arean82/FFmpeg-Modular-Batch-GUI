import signal
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading, os

from presets import load_presets
from file_manager import scan_folder, get_resolution, get_duration
from ffmpeg_runner import run_ffmpeg
from ui_preset_editor import PresetEditor
from estimations import estimate_size_mb   # ✅ USE CENTRAL MODULE ONLY


class FFmpegGUI:
    def __init__(self, root):

        self.root = root
        self.presets = load_presets()
        self.files = []
        self.current_folder = None
        self.output_dir = None
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.active_processes = []

        # ---------- TOP BAR ----------
        top = ttk.Frame(root)
        top.pack(fill="x")

        ttk.Button(top, text="Select Folder", command=self.select_folder).pack(side="left")
        ttk.Button(top, text="Add Preset", command=self.open_preset_editor).pack(side="left", padx=5)
        ttk.Button(top, text="Select All", command=self.select_all).pack(side="left", padx=5)
        ttk.Button(top, text="Uncheck All", command=self.uncheck_all).pack(side="left", padx=5)

        # ---------- FILTER + OUTPUT FOLDER ----------
        filt = ttk.Frame(root)
        filt.pack(fill="x", pady=2)

        ttk.Label(filt, text="Show only:").pack(side="left")
        self.ext_filter = ttk.Combobox(
            filt, values=["all", "ts", "mp4", "mkv", "avi", "mov"],
            width=8, state="readonly"
        )
        self.ext_filter.current(0)
        self.ext_filter.pack(side="left", padx=5)
        self.ext_filter.bind("<<ComboboxSelected>>", self.apply_filter)

        ttk.Label(filt, text="Output folder:").pack(side="left", padx=(20, 5))
        self.out_var = tk.StringVar()
        self.out_entry = ttk.Entry(filt, textvariable=self.out_var, width=45)
        self.out_entry.pack(side="left")
        ttk.Button(filt, text="Browse", command=self.browse_output).pack(side="left", padx=5)

        self.auto_subfolder_var = tk.BooleanVar(value=False)
        self.estimate_size_var = tk.BooleanVar(value=False)

        opts = ttk.Frame(root)
        opts.pack(fill="x", padx=8, pady=2)

        ttk.Checkbutton(
            opts, text="Auto-create /converted subfolder",
            variable=self.auto_subfolder_var
        ).pack(side="left", padx=5)

        ttk.Checkbutton(
            opts, text="Estimate output size",
            variable=self.estimate_size_var
        ).pack(side="left", padx=15)

        # ---------- FILE TABLE ----------
        self.tree = ttk.Treeview(
            root,
            columns=("use", "in", "out", "ext", "res", "op_res", "op_fmt", "cur_size", "est_size"),
            show="headings",
            selectmode="none"
        )

        for col, text, width in [
            ("use", "Use", 50),
            ("in", "Input File", 320),
            ("cur_size", "Current Size (MB)", 120),
            ("ext", "Ext", 70),
            ("out", "Output File Name", 320),
            ("res", "Resolution", 110),
            ("op_res", "Output Resolution", 140),
            ("op_fmt", "Output Format", 90),
            ("est_size", "Est. Output (MB)", 130)
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="center")

        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<Button-1>", self.toggle_checkbox)
        #self.tree.bind("<Double-1>", self.edit_output_name)
        #self.tree.bind("<Double-1>", self.edit_output_resolution, add="+")
        #self.tree.bind("<Double-1>", self.edit_output_format, add="+")

        # ---------- PRESETS ----------
        sorted_presets = sorted(
            self.presets.items(),
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
        self.preset_box.bind("<<ComboboxSelected>>", self.update_active_args)

        # ---------- ACTIVE PRESET ARGS ----------
        args_frame = ttk.Frame(self.root)
        args_frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(args_frame, text="Active FFmpeg Args:").pack(side="left")

        self.active_args_var = tk.StringVar()
        self.active_args_entry = ttk.Entry(
            args_frame,
            textvariable=self.active_args_var,
            state="readonly"
        )
        self.active_args_entry.pack(side="left", fill="x", expand=True, padx=5)

        # ---------- START BUTTON ----------
        #ttk.Button(root, text="Start Conversion", command=self.start).pack(pady=6)
        ttk.Button(root, text="Start Conversion", command=self.toggle_start).pack(pady=6)

        # ---------- PROGRESS BAR ----------
        self.progress = ttk.Progressbar(root, length=500)
        self.progress.pack(pady=4)
        self.progress.configure(maximum=100)

        # ---------- GUI CONSOLE ----------
        log_frame = ttk.LabelFrame(self.root, text="FFmpeg Console")
        log_frame.pack(fill="both", expand=True, padx=8, pady=6)

        self.log = tk.Text(log_frame, height=10, wrap="word")
        self.log.pack(fill="both", expand=True)

        # ---------- INITIAL DISPLAY ----------
        self.update_active_args()

    # ---------------- Presets ----------------
    def refresh_presets(self):
        self.presets = load_presets()
        sorted_presets = sorted(
            self.presets.items(),
            key=lambda x: (x[1].get("category", ""), x[0])
        )

        self.preset_box["values"] = [
            f"{v.get('category','Other')} :: {k}" for k, v in sorted_presets
        ]

        if sorted_presets:
            self.preset_box.current(0)

        self.update_active_args()

    def open_preset_editor(self):
        PresetEditor(self.root, self.presets, self.refresh_presets)

    # ---------------- Output Folder ----------------
    def browse_output(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir = folder
            self.out_var.set(folder)

    # ---------------- File Loading ----------------
    def select_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return

        self.current_folder = folder

        if not self.output_dir:
            self.output_dir = folder
            self.out_var.set(folder)

        self.load_files("all")

    def load_files(self, ext_filter):
        self.tree.delete(*self.tree.get_children())
        self.files.clear()

        paths = scan_folder(self.current_folder)

        for p in paths:
            if not p or not os.path.exists(p):
                continue

            name = os.path.basename(p).strip()
            if not name:
                continue

            base, ext = os.path.splitext(name)
            ext_clean = ext.lstrip(".").lower()

            if ext_filter != "all" and ext_clean != ext_filter:
                continue

            try:
                res = get_resolution(p)
            except:
                res = "unknown"

            try:
                cur_size = round(os.path.getsize(p) / (1024 * 1024), 2)
            except:
                cur_size = "?"

            item = {
                "path": p,
                "use": True,
                "out": base,
                "op_res": "Same",
                "op_fmt": ext_clean
            }

            self.files.append(item)

            row = (
                "✔", base, base, f".{ext_clean}",
                res, "Same", ext_clean,
                cur_size, ""
            )

            if len(row) == 9:
                self.tree.insert("", "end", values=row)

    def apply_filter(self, event=None):
        if not self.current_folder:
            return
        ext = self.ext_filter.get()
        self.load_files(ext)

    # ---------------- Checkboxes ----------------
    def select_all(self):
        for i, f in enumerate(self.files):
            f["use"] = True
            row = self.tree.get_children()[i]
            vals = list(self.tree.item(row, "values"))
            vals[0] = "✔"
            self.tree.item(row, values=vals)

    def uncheck_all(self):
        for i, f in enumerate(self.files):
            f["use"] = False
            row = self.tree.get_children()[i]
            vals = list(self.tree.item(row, "values"))
            vals[0] = ""
            self.tree.item(row, values=vals)

    def toggle_checkbox(self, event):
        region = self.tree.identify("region", event.x, event.y)
        col = self.tree.identify_column(event.x)
        if region != "cell" or col != "#1":
            return
        row = self.tree.identify_row(event.y)
        idx = self.tree.index(row)
        self.files[idx]["use"] = not self.files[idx]["use"]
        vals = list(self.tree.item(row, "values"))
        vals[0] = "✔" if self.files[idx]["use"] else ""
        self.tree.item(row, values=vals)

    # ---------------- ACTIVE PRESET + ESTIMATE ----------------
    def update_active_args(self, event=None):
        display_name = self.preset_box.get()
        if not display_name:
            return

        preset_key = display_name.split("::", 1)[1].strip()
        if preset_key not in self.presets:
            return

        args = self.presets[preset_key]["args"]
        self.active_args_var.set(args)

        if not self.estimate_size_var.get():
            return

        for i, f in enumerate(self.files):
            try:
                duration = get_duration(f["path"])
                est = estimate_size_mb(duration, args)

                row_id = self.tree.get_children()[i]
                vals = list(self.tree.item(row_id, "values"))
                vals[8] = est if est else ""
                self.tree.item(row_id, values=vals)
            except:
                pass

    def on_close(self):
        running = [p for p in self.active_processes if p.poll() is None]

        if running:
            if not messagebox.askyesno(
                "FFmpeg Still Running",
                "Video conversion is still running.\n\n"
                "If you close now, all FFmpeg processes will be TERMINATED.\n\n"
                "Do you want to continue?"
            ):
                return

            for p in running:
                try:
                    os.kill(p.pid, signal.SIGTERM)
                except:
                    pass

        self.root.destroy()

    def toggle_start(self):
        if not getattr(self, "is_running", False):
            self.start_conversion()
        else:
            self.stop_conversion()

    def start_conversion(self):
        self.is_running = True
        self.start_btn.configure(text="Stop Conversion")
        self.start()  # calls your existing start() worker

    def stop_conversion(self):
        self.is_running = False
        self.start_btn.configure(text="Start Conversion")

        for p in self.active_processes:
            try:
                os.kill(p.pid, signal.CTRL_BREAK_EVENT)
            except:
                try:
                    os.kill(p.pid, signal.SIGTERM)
                except:
                    pass

        self.active_processes.clear()
        self.log_line("⛔ Conversion stopped by user")
