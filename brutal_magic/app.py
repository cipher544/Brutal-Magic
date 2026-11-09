"""Application entry point."""

import sys
import tkinter as tk
from .ui.window import EditorWindow


def main():
    root = tk.Tk()
    window = EditorWindow(root)
    if len(sys.argv) > 1:
        window.load(sys.argv[1])
    root.mainloop()
