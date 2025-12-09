import tkinter as tk
from tkinter import ttk, messagebox
from presets import save_presets

class PresetEditor(tk.Toplevel):
    def __init__(self, parent, presets, refresh_cb):
        super().__init__(parent)
        self.presets = presets
        self.refresh_cb = refresh_cb

        self.title("Preset Editor")
        self.geometry("700x450")
        self.transient(parent)   # ✅ Stay on top of main window
        self.grab_set()          # ✅ MODAL: block main window until closed

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        # ---------------- Left: Preset List ----------------
        left = ttk.Frame(main)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="Existing Presets").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=30)
        self.listbox.pack(fill="y", expand=True,
                           pady=(5, 0))

        for name in self.presets.keys():
            self.listbox.insert("end", name)

        self.listbox.bind("<<ListboxSelect>>", self.load_selected)

        # ---------------- Right: Editor ----------------
        right = ttk.Frame(main)
        right.pack(side="left", fill="both", expand=True, padx=12)

        ttk.Label(right, text="Name").pack(anchor="w")
        self.name = ttk.Entry(right)
        self.name.pack(fill="x")

        ttk.Label(right, text="FFmpeg Args").pack(anchor="w", pady=(10, 0))
        self.args = ttk.Entry(right)
        self.args.pack(fill="x")

        ttk.Label(right, text="Description").pack(anchor="w", pady=(10, 0))
        self.desc = tk.Text(right, height=6)
        self.desc.pack(fill="both", expand=True)

        # ---------------- Buttons ----------------
        btns = ttk.Frame(right)
        btns.pack(pady=10, anchor="e")

        ttk.Button(btns, text="Save / Update", command=self.save).pack(side="left", padx=5)
        ttk.Button(btns, text="Delete", command=self.delete).pack(side="left", padx=5)
        ttk.Button(btns, text="Close", command=self.close).pack(side="left", padx=5)

    # -------- Load selected preset into editor --------
    def load_selected(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        p = self.presets[name]

        self.name.delete(0, "end")
        self.name.insert(0, name)

        self.args.delete(0, "end")
        self.args.insert(0, p.get("args", ""))

        self.desc.delete("1.0", "end")
        self.desc.insert("1.0", p.get("desc", ""))

    # -------- Save / Update --------
    def save(self):
        name = self.name.get().strip()
        args = self.args.get().strip()
        desc = self.desc.get("1.0", "end").strip()

        if not name or not args:
            messagebox.showerror("Error", "Name and FFmpeg args are required")
            return

        self.presets[name] = {"args": args, "desc": desc}
        save_presets(self.presets)
        self.refresh_cb()
        self.close()

    # -------- Delete --------
    def delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showerror("Error", "Select a preset to delete")
            return

        name = self.listbox.get(sel[0])
        if messagebox.askyesno("Confirm", f"Delete preset '{name}'?"):
            del self.presets[name]
            save_presets(self.presets)
            self.refresh_cb()
            self.close()

    # -------- Close Properly --------
    def close(self):
        self.grab_release()
        self.destroy()