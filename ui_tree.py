# ui_tree.py
# UI component for displaying and managing a tree view of files and their attributes.  
# Treeview + file list UI + editing

import os
from tkinter import ttk

class TreeUI:
    def __init__(self, root, file_loader):
        self.root = root
        self.file_loader = file_loader
        self.files = []

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

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.files.clear()

    def add_file(self, item, row):
        self.files.append(item)
        self.tree.insert("", "end", values=row)
