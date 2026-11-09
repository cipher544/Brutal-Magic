"""Sprite selection and ROM graphics preview."""
import tkinter as tk
from tkinter import ttk

from ..core.tiles import NAMES, WIDTH


def sprite_image(editor, sprite_id):
    """Return a 16×16 crop from an isolated placement using room graphics."""
    if editor.graphics is None or editor.current_map is None:
        return None
    state = editor.document.state(editor.current_map)
    cells = [0] * len(state["cells"])
    cells[12 * WIDTH + 15] = sprite_id
    result = editor.graphics.snapshot(editor.current_map, editor.current_level_index,
                                      cells=cells, header=state["header"], footer=state["footer"])
    pixels = result['rgb']
    image = bytearray()
    for y in range(192, 208):
        start = (y * 512 + 240) * 3
        image.extend(pixels[start:start + 16 * 3])
    return bytes(image)


class SpriteWindow:
    def __init__(self, editor):
        self.editor = editor
        self.window = tk.Toplevel(editor.root)
        self.window.title('Add Sprites')
        self.window.transient(editor.root)
        self.window.resizable(False, False)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        editor.bind_map_shortcuts(self.window)
        self.selector = ttk.Combobox(self.window, state='readonly', width=58,
            values=[f'${value:02X} — {NAMES.get(value,"Unknown")}' for value in range(1,64)])
        self.selector.pack(fill='x', padx=12, pady=12)
        self.selector.current(editor.selected_sprite - 1)
        self.selector.bind('<<ComboboxSelected>>', self.select)
        self.canvas = tk.Canvas(self.window, width=64, height=64,
                                background='#252831', highlightthickness=0)
        self.canvas.pack(padx=12, pady=(0,12))
        self.photo = None
        self.refresh()

    def select(self, event=None):
        self.editor.finish_stroke()
        self.editor.selected_sprite = self.selector.current() + 1
        self.refresh()

    def refresh(self):
        self.canvas.delete('all')
        self.photo = None
        try:
            pixels = sprite_image(self.editor, self.editor.selected_sprite)
        except (ValueError, IndexError):
            pixels = None
        if pixels is not None:
            self.photo = tk.PhotoImage(data=b'P6\n16 16\n255\n' + pixels, format='PPM').zoom(4)
            self.canvas.create_image(0, 0, anchor='nw', image=self.photo)

    def close(self):
        self.window.destroy()
        self.editor.sprite_window = None
        self.editor.edit_mode.set('draw')
