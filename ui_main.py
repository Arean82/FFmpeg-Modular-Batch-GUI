import signal
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading, os

from presets import load_presets
from file_manager import scan_folder, get_resolution, get_duration
from ffmpeg_runner import run_ffmpeg
from ui_preset_editor import PresetEditor


class FFmpegGUI:
    def __init__(self, root):

        # ---------- ACTIVE ARGS DISPLAY VAR ----------
        self.active_args_var = tk.StringVar()

        self.root = root
        self.presets = load_presets()
        self.files = []   # {path, use, out_name}
        self.current_folder = None
        self.output_dir = None  # common for the session
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
        self.ext_filter = ttk.Combobox(filt, values=["all", "ts", "mp4", "mkv", "avi", "mov"], width=8, state="readonly")
        self.ext_filter.current(0)
        self.ext_filter.pack(side="left", padx=5)
        self.ext_filter.bind("<<ComboboxSelected>>", self.apply_filter)

        ttk.Label(filt, text="Output folder:").pack(side="left", padx=(20, 5))
        self.out_var = tk.StringVar()
        self.out_entry = ttk.Entry(filt, textvariable=self.out_var, width=45)
        self.out_entry.pack(side="left")
        ttk.Button(filt, text="Browse", command=self.browse_output).pack(side="left", padx=5)

        # ---------- FILE TABLE (SIDE-BY-SIDE IO) ----------
        self.tree = ttk.Treeview(root, columns=("use", "in", "out", "ext", "res", "op_res", "op_fmt"), show="headings", selectmode="none")
        self.tree.heading("use", text="Use")
        self.tree.heading("in", text="Input File")
        self.tree.heading("out", text="Output File Name")
        self.tree.heading("ext", text="Ext")
        self.tree.heading("res", text="Resolution")
        self.tree.heading("op_res", text="Output Resolution")
        self.tree.heading("op_fmt", text="Output Format")

        self.tree.column("use", width=50, anchor="center")
        self.tree.column("in", width=320)
        self.tree.column("out", width=320)
        self.tree.column("ext", width=70, anchor="center")
        self.tree.column("res", width=110, anchor="center")
        self.tree.column("op_res", width=140, anchor="center")
        self.tree.column("op_fmt", width=90, anchor="center")
        self.tree.pack(fill="both", expand=True)

        self.tree.bind("<Button-1>", self.toggle_checkbox)
        self.tree.bind("<Double-1>", self.edit_output_name)
        self.tree.bind("<Double-1>", self.edit_output_resolution, add="+")
        self.tree.bind("<Double-1>", self.edit_output_format, add="+")

        # ---------- ACTIVE PRESET ARGS DISPLAY ----------
        args_frame = ttk.Frame(self.root)
        args_frame.pack(fill="x", padx=8)

        ttk.Label(args_frame, text="Active FFmpeg Args:").pack(side="left")

        self.active_args_var = tk.StringVar()
        self.active_args_entry = ttk.Entry(
            args_frame, textvariable=self.active_args_var, state="readonly"
        )
        self.active_args_entry.pack(side="left", fill="x", expand=True, padx=5)

        # ---------- PRESETS ----------
        sorted_presets = sorted(
            self.presets.items(),
            key=lambda x: (x[1].get("category", ""), x[0])
        )

        # ✅ VARIABLE-BACKED COMBOBOX (NO EVENT RELIANCE)
        self.preset_var = tk.StringVar()

        self.preset_box = ttk.Combobox(
            root,
            textvariable=self.preset_var,
            values=[f"{v.get('category','Other')} :: {k}" for k, v in sorted_presets],
            state="readonly"
        )

        if sorted_presets:
            self.preset_box.current(0)

        self.preset_box.pack(fill="x", pady=4)

        # ✅ FORCE UPDATE WHENEVER VALUE CHANGES
        self.preset_var.trace_add("write", lambda *a: self.update_active_args())

        # ✅ INITIAL DISPLAY
        self.update_active_args()


        # initialize display
        if self.preset_box.get():
            preset_key = self.preset_box.get().split("::", 1)[1].strip()
            self.active_args_var.set(
                self.presets[preset_key]["args"]
            )

        # update when preset changes
        self.preset_box.bind("<<ComboboxSelected>>", self.update_active_args)

        # ---------- GUI CONSOLE ----------
        log_frame = ttk.LabelFrame(self.root, text="FFmpeg Console")
        log_frame.pack(fill="both", expand=False, padx=8, pady=6)

        self.log = tk.Text(log_frame, height=10, wrap="word")
        self.log.pack(fill="both", expand=True)


    # ---------------- Presets ----------------
    def refresh_presets(self):
        self.presets = load_presets()
        self.preset_box["values"] = list(self.presets.keys())
        if self.presets:
            self.preset_box.current(0)

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
        self.load_files("all")

    def load_files(self, ext_filter):
        paths = scan_folder(self.current_folder)
        self.files = []
        self.tree.delete(*self.tree.get_children())

        for p in paths:
            name = os.path.basename(p)
            base, ext = os.path.splitext(name)
            if not base.strip():
                base = name       # fallback safety       
            ext_clean = ext.lstrip(".").lower()
            if ext_filter != "all" and ext_clean != ext_filter:
                continue

            res = get_resolution(p)
            item = {
                "path": p,
                "use": True,
                "out": base,
                "op_res": "Same",
                "op_fmt": ext_clean   # default = same as input format
            }


            self.files.append(item)
            self.tree.insert(
                "", "end",
                values=("✔", base, base, ext, res, "Same", ext_clean)
            )

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

    # ---------------- Rename Output (Side-by-Side) ----------------
    def edit_output_name(self, event):
        col = self.tree.identify_column(event.x)
        if col != "#3":  # Output column
            return
        row = self.tree.identify_row(event.y)
        idx = self.tree.index(row)
        x, y, w, h = self.tree.bbox(row, col)

        entry = ttk.Entry(self.root)
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, self.files[idx]["out"])
        entry.focus()

        def save_edit(event=None):
            new = entry.get().strip()
            if new:
                self.files[idx]["out"] = new
                vals = list(self.tree.item(row, "values"))
                vals[2] = new
                self.tree.item(row, values=vals)
            entry.destroy()

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)

    # ---------------- Start Conversion (FIXED) ----------------

    def start(self):
        selected = [f for f in self.files if f["use"]]
        if not selected:
            messagebox.showerror("Error", "No files selected")
            return

        preset_name = self.preset_box.get()
        if not preset_name:
            messagebox.showerror("Error", "No preset selected")
            return

        preset_key = preset_name.split("::", 1)[1].strip()
        base_args = self.presets[preset_key]["args"]

        out_dir = self.output_dir or self.current_folder

        self.progress.configure(value=0, maximum=100)
        self.active_processes = []

        def worker():
            for f in selected:
                in_path = f["path"]

                # --------- OUTPUT FORMAT ----------
                in_ext = os.path.splitext(in_path)[1].lstrip(".").lower()
                out_ext = f.get("op_fmt", "mp4")

                # --------- CONTAINER CONFLICT ----------
                if "-c copy" in base_args and out_ext != in_ext:
                    self.log_line("⚠ Copy preset forces original container")
                    out_ext = in_ext

                out_path = os.path.join(out_dir, f["out"] + "." + out_ext)

                # --------- OUTPUT RESOLUTION ----------
                args = base_args
                if f.get("op_res", "Same") != "Same" and "-vf" not in base_args:
                    args = f'-vf scale={f["op_res"]} ' + args
                elif f.get("op_res", "Same") != "Same":
                    self.log_line("⚠ Preset already contains scaling; per-file op_res ignored")

                # --------- GET DURATION ----------
                try:
                    duration = get_duration(in_path)
                except:
                    duration = 0

                # --------- RUN FFMPEG ----------
                proc = run_ffmpeg(
                    in_path,
                    out_path,
                    args,
                    on_log=self.log_line,
                    on_progress=lambda sec, d=duration: self.root.after(
                        0,
                        lambda: self.progress.configure(
                            value=min(100, (sec / d) * 100) if d else 0
                        )
                    )
                )

                self.active_processes.append(proc)
                proc.wait()

            # --------- COMPLETION POPUP ----------
            self.root.after(0, lambda: messagebox.showinfo(
                "Completed",
                "All selected video conversions are completed."
            ))

        threading.Thread(target=worker, daemon=True).start()



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

    def log_line(self, text):
        def append():
            self.log.insert("end", text + "\n")
            self.log.see("end")
        self.root.after(0, append)


    def edit_output_resolution(self, event):
        col = self.tree.identify_column(event.x)
        if col != "#6":   # op_res column
            return

        row = self.tree.identify_row(event.y)
        idx = self.tree.index(row)
        x, y, w, h = self.tree.bbox(row, col)

        combo = ttk.Combobox(
            self.root,
            values=[
                "Same",
                "426x240",
                "640x360",
                "854x480",
                "1280x720",
                "1920x1080"
            ],
            state="readonly"
        )
        combo.place(x=x, y=y, width=w, height=h)
        combo.set(self.files[idx]["op_res"])
        combo.focus()

        def save(_=None):
            val = combo.get()
            self.files[idx]["op_res"] = val

            vals = list(self.tree.item(row, "values"))
            vals[5] = val
            self.tree.item(row, values=vals)
            combo.destroy()

        combo.bind("<<ComboboxSelected>>", save)
        combo.bind("<FocusOut>", save)

    def edit_output_format(self, event):
        col = self.tree.identify_column(event.x)
        if col != "#7":   # Output format column
            return

        row = self.tree.identify_row(event.y)
        idx = self.tree.index(row)
        x, y, w, h = self.tree.bbox(row, col)

        combo = ttk.Combobox(
            self.root,
            values=["mp4", "mkv", "ts", "avi", "mov"],
            state="readonly"
        )
        combo.place(x=x, y=y, width=w, height=h)
        combo.set(self.files[idx]["op_fmt"])
        combo.focus()

        def save(_=None):
            val = combo.get()
            self.files[idx]["op_fmt"] = val
            vals = list(self.tree.item(row, "values"))
            vals[6] = val
            self.tree.item(row, values=vals)
            combo.destroy()

        combo.bind("<<ComboboxSelected>>", save)
        combo.bind("<FocusOut>", save)

    def update_active_args(self, event=None):
        display_name = self.preset_var.get()
        if not display_name:
            return  

        preset_key = display_name.split("::", 1)[1].strip()
        args = self.presets[preset_key]["args"] 

        print("Selected preset key:", preset_key)
        print("Selected preset args:", args)    

        self.active_args_var.set(args)  


