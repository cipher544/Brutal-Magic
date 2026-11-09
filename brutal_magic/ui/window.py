"""Main editor window."""

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core.rom import GauntletROM
from ..core.tiles import WIDTH
from ..core.exits import read_exits
from ..core.level_files import export_levels, level_filename, read_level_directory, read_level_file
from ..core.document import EditorDocument
from ..graphics.renderer import ROMGraphics
from ..graphics.preview import MapPreview
from .map_canvas import MapCanvasView
from .sprites import SpriteWindow
from .world_map import WorldMapWindow


ZOOM_LEVELS = ((16, "100%"), (24, "150%"), (32, "200%"))


class EditorWindow(MapCanvasView):
    def __init__(self, root):
        self.root = root
        root.title("Brutal Magic — Level Editor")
        self.cells = None
        self.rom = None
        self.current_header = None
        self.graphics = None
        self.graphics_snapshot = None
        self.photo = None
        self.document = None
        self.current_map = None
        self.current_label = ""
        self.current_level_index = None
        self.save_path = None
        self.preview = None
        self.stroke_before = None
        self.stroke_last = None
        self.render_job = None
        self.zoom = tk.IntVar(value=24)
        self.simple_mode = tk.BooleanVar(value=False)
        self.grid = tk.BooleanVar(value=False)
        self.room_exits = []
        self.ids = tk.BooleanVar(value=False)
        self.edit_mode = tk.StringVar(value='draw')
        self.selected_sprite = 0x2E
        self.sprite_window = None
        self.world_map_window = None
        self.create_menus()
        navigation = ttk.Frame(root, padding=(8, 0, 8, 4))
        navigation.pack(fill="x")
        self.level_selector = ttk.Combobox(navigation, state="readonly", width=34)
        self.level_selector.pack(side="left", padx=6)
        self.level_selector.bind("<<ComboboxSelected>>", self.select_level)
        ttk.Label(navigation, text="  Map:").pack(side="left")
        self.map_selector = ttk.Combobox(navigation, state="readonly", width=9)
        self.map_selector.pack(side="left", padx=6)
        self.map_selector.bind("<<ComboboxSelected>>", self.select_map)
        editing = ttk.Frame(root, padding=(8, 2, 8, 4))
        editing.pack(fill="x")
        ttk.Label(editing, text="Tileset:").pack(side="left")
        self.tileset_selector = ttk.Combobox(
            editing,
            state="readonly",
            width=10,
            values=[f"{i} (${i<<4:02X})" for i in range(10)],
        )
        self.tileset_selector.pack(side="left", padx=5)
        self.tileset_selector.bind("<<ComboboxSelected>>", self.change_appearance)
        ttk.Label(editing, text="Sprite Tileset:").pack(side="left")
        self.footer_selector = ttk.Combobox(editing, state="disabled", width=8)
        self.footer_selector.pack(side="left", padx=5)
        self.footer_selector.bind("<<ComboboxSelected>>", self.change_footer)
        ttk.Label(editing, text="Palette:").pack(side="left")
        self.palette_values = list(range(0x70))
        self.palette_selector = ttk.Combobox(
            editing,
            state="readonly",
            width=23,
            values=[
                f"${v:02X} — Floor {v>>4:X} / Wall {v&15:X}"
                for v in self.palette_values
            ],
        )
        self.palette_selector.pack(side="left", padx=5)
        self.palette_selector.bind("<<ComboboxSelected>>", self.change_appearance)
        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(frame, background="#252831", highlightthickness=0)
        horizontal = ttk.Scrollbar(
            frame, orient="horizontal", command=self.canvas.xview
        )
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(
            xscrollcommand=horizontal.set, yscrollcommand=vertical.set
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.status = ttk.Label(
            root,
            text="Open a ROM to view and edit its levels.",
            padding=8,
        )
        self.status.pack(fill="x")
        self.canvas.bind("<Motion>", self.hover)
        for button in (1, 3):
            self.canvas.bind(f"<Button-{button}>", lambda e, b=button: self.paint(e, b))
            self.canvas.bind(
                f"<B{button}-Motion>", lambda e, b=button: self.paint(e, b)
            )
            self.root.bind(f"<ButtonRelease-{button}>", lambda e: self.finish_stroke())
        root.geometry("900x820")
        root.bind("<Control-o>", lambda e: self.open_rom())
        root.bind("<Control-s>", lambda e: self.save_rom())
        root.bind("<Control-z>", lambda e: self.undo())
        root.bind("<Control-y>", lambda e: self.redo())
        root.bind("<Control-Shift-S>", lambda e: self.save_rom(True))
        root.bind("<Prior>", lambda e: self.step(-1))
        root.bind("<Next>", lambda e: self.step(1))
        self.bind_map_shortcuts(root)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def create_menus(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open ROM…", accelerator="Ctrl+O", command=self.open_rom)
        file_menu.add_command(label="Save ROM", accelerator="Ctrl+S", command=self.save_rom)
        file_menu.add_command(label="Save ROM as…", accelerator="Ctrl+Shift+S", command=lambda: self.save_rom(True))
        file_menu.add_separator()
        file_menu.add_command(label="Open Level from File…", command=self.open_level_file)
        file_menu.add_command(label="Save Level to File…", command=self.save_level_file)
        file_menu.add_separator()
        file_menu.add_command(label="Import Multiple Levels…", command=self.import_level_files)
        file_menu.add_command(label="Export Multiple Levels…", command=self.export_level_files)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close)
        menubar.add_cascade(label="File", menu=file_menu)
        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_radiobutton(label="Draw Mode", accelerator="1", variable=self.edit_mode, value="draw", command=self.change_mode)
        edit_menu.add_radiobutton(label="Add Sprites", accelerator="2", variable=self.edit_mode, value="sprites", command=self.change_mode)
        edit_menu.add_separator()
        edit_menu.add_command(label="World Map…", command=self.open_world_map)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        view_menu = tk.Menu(menubar, tearoff=False)
        zoom_menu = tk.Menu(view_menu, tearoff=False)
        for size, label in ZOOM_LEVELS:
            zoom_menu.add_radiobutton(label=label, variable=self.zoom, value=size, command=self.draw)
        view_menu.add_cascade(label="Zoom", menu=zoom_menu)
        view_menu.add_checkbutton(label="Simple Mode", accelerator="3", variable=self.simple_mode, command=self.draw)
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Show sprite IDs", accelerator="4", variable=self.ids, command=self.draw)
        view_menu.add_checkbutton(label="Show grid", accelerator="5", variable=self.grid, command=self.draw)
        view_menu.add_separator()
        view_menu.add_command(label="Previous level", accelerator="Page Up", command=lambda: self.step(-1))
        view_menu.add_command(label="Next level", accelerator="Page Down", command=lambda: self.step(1))
        menubar.add_cascade(label="View", menu=view_menu)
        self.root.config(menu=menubar)

    def bind_map_shortcuts(self, window):
        for key in ("plus", "equal", "KP_Add"):
            window.bind(f"<KeyPress-{key}>", lambda event: self.step_zoom(1))
        for key in ("minus", "KP_Subtract"):
            window.bind(f"<KeyPress-{key}>", lambda event: self.step_zoom(-1))
        window.bind("<KeyPress-1>", lambda event: self.set_edit_mode("draw"))
        window.bind("<KeyPress-2>", lambda event: self.set_edit_mode("sprites"))
        window.bind("<KeyPress-3>", lambda event: self.toggle_overlay(self.simple_mode))
        window.bind("<KeyPress-4>", lambda event: self.toggle_overlay(self.ids))
        window.bind("<KeyPress-5>", lambda event: self.toggle_overlay(self.grid))

    def step_zoom(self, delta):
        sizes = [size for size, _ in ZOOM_LEVELS]
        index = sizes.index(self.zoom.get())
        target = max(0, min(len(sizes) - 1, index + delta))
        if target != index:
            self.zoom.set(sizes[target])
            self.draw()
        return "break"

    def set_edit_mode(self, mode):
        self.edit_mode.set(mode)
        self.change_mode()
        return "break"

    def toggle_overlay(self, option):
        option.set(not option.get())
        self.draw()
        return "break"

    def change_mode(self):
        self.finish_stroke()
        if self.edit_mode.get() == 'sprites':
            if self.sprite_window is None:
                self.sprite_window = SpriteWindow(self)
            else:
                self.sprite_window.window.deiconify()
                self.sprite_window.window.lift()
                self.sprite_window.refresh()
        elif self.sprite_window is not None:
            self.sprite_window.window.withdraw()

    def open_world_map(self):
        if self.document is None:
            messagebox.showinfo("World Map", "Open a Gauntlet ROM first.")
            return
        if self.world_map_window is None:
            try:
                grids = self.document.load_world_grids()
            except ValueError as error:
                messagebox.showerror("World Map", str(error))
                return
            self.world_map_window = WorldMapWindow(self, grids)
        self.world_map_window.window.deiconify()
        self.world_map_window.window.lift()

    def open_rom(self):
        path = filedialog.askopenfilename(
            filetypes=[("NES ROM", "*.nes"), ("All files", "*")]
        )
        if path:
            self.load(path)

    def load(self, path):
        self.finish_stroke()
        if not self.confirm_discard():
            return
        try:
            rom = GauntletROM(path)
            rom.load_level(1)
        except (OSError, ValueError, IndexError) as error:
            messagebox.showerror("Cannot open ROM", str(error))
            return
        if self.world_map_window is not None:
            self.world_map_window.window.destroy()
            self.world_map_window = None
        self.rom = rom
        self.document = EditorDocument(rom)
        self.save_path = None
        self.graphics = ROMGraphics(rom)
        self.footer_values = sorted({record.footer for record in rom.records})
        self.footer_selector["values"] = [f"${value:02X}" for value in self.footer_values]
        self.level_selector["values"] = [
            f"Level {n:03d} — Map ${m:02X}"
            + (" (no pointer)" if m >= len(rom.maps) else "")
            for n, m in enumerate(rom.levels, 1)
        ]
        self.map_selector["values"] = [f"${m:02X}" for m in range(len(rom.maps))]
        self.level_selector.current(0)
        self.select_level()

    def step(self, delta):
        if self.rom is None:
            return
        index = max(
            0, min(len(self.rom.levels) - 1, self.level_selector.current() + delta)
        )
        self.level_selector.current(index)
        self.select_level()

    def select_level(self, event=None):
        if self.rom is None:
            return
        index = self.level_selector.current()
        if index < 0:
            return
        map_id = self.rom.levels[index]
        self.map_selector.set(f"${map_id:02X}")
        self.show_map(map_id, f"Level {index + 1:03d}")

    def open_level_exit(self, level, room_exit):
        self.level_selector.current(level - 1)
        self.select_level()
        if self.cells is not None and room_exit is not None:
            y = room_exit.y - int(len(self.cells) // WIDTH != 32)
            self.canvas.xview_moveto(max(0, (room_exit.x - 4) / WIDTH))
            self.canvas.yview_moveto(max(0, (y - 4) / (len(self.cells) // WIDTH)))
        self.root.lift()

    def select_map(self, event=None):
        if self.rom is None:
            return
        map_id = self.map_selector.current()
        if map_id < 0:
            return
        self.level_selector.set("Direct map selection")
        self.show_map(map_id, "Direct map")

    def show_map(self, map_id, label):
        self.finish_stroke()
        if self.render_job is not None:
            self.root.after_cancel(self.render_job)
            self.render_job = None
        self.preview = None
        self.current_map = None
        self.current_label = label
        self.room_exits = []
        self.current_level_index = (
            self.level_selector.current() if label.startswith("Level") else None
        )
        self.root.title(f"Brutal Magic — {label} — {self.rom.path.name}")
        try:
            result = self.rom.load_map(map_id)
        except (ValueError, IndexError) as error:
            self.cells = None
            self.current_header = None
            self.footer_selector.set("")
            self.footer_selector.configure(state="disabled")
            if self.sprite_window is not None:
                self.sprite_window.refresh()
            self.graphics_snapshot = None
            self.draw()
            self.status.config(text=str(error))
            return
        self.current_map = map_id
        if self.current_level_index is not None:
            try:
                self.room_exits = read_exits(self.rom, self.current_level_index + 1)
            except (ValueError, IndexError):
                self.room_exits = []
        state = self.document.state(map_id)
        self.cells = state["cells"]
        self.current_header = bytes(state["header"])
        self.sync_appearance()
        try:
            self.preview = MapPreview(
                self.graphics, map_id, self.current_level_index, result["cells"], state["footer"]
            )
            self.graphics_snapshot = (
                self.preview.update(self.cells, self.current_header)
                if self.document.modified(map_id)
                else self.preview.snapshot
            )
        except (ValueError, IndexError) as error:
            self.graphics_snapshot = None
            messagebox.showerror("Graphics error", str(error))
        self.status.config(
            text="ROM graphics · default warrior · hover for source IDs"
            + (
                " · Magenta IDs: Hydra parts awaiting sprite composition"
                if self.graphics_snapshot and self.graphics_snapshot["unsupported"]
                else ""
            )
        )
        if result["needs_expansion"]:
            self.status.config(text="32-row room preview · Save ROM to expand the stock room record.")
        self.update_title()
        self.draw()
        if self.sprite_window is not None:
            self.sprite_window.refresh()

    def update_title(self):
        if self.rom:
            star = " *" if self.document and self.document.dirty else ""
            self.root.title(
                f"Brutal Magic — {self.current_label} — {self.rom.path.name}{star}"
            )

    def sync_appearance(self):
        if self.current_header is None:
            return
        footer = self.document.state(self.current_map)["footer"]
        self.footer_selector.configure(state="readonly")
        self.footer_selector.current(self.footer_values.index(footer))
        self.tileset_selector.current(self.current_header[4] >> 4)
        self.palette_selector.current(self.palette_values.index(self.current_header[5]))

    def refresh_edited(self):
        self.render_job = None
        if self.current_map is None:
            return
        state = self.document.state(self.current_map)
        self.cells = state["cells"]
        header_changed = self.current_header != bytes(state["header"])
        self.current_header = bytes(state["header"])
        self.sync_appearance()
        footer_changed = self.preview is None or self.preview.footer != state["footer"]
        try:
            if footer_changed:
                source = self.rom.load_map(self.current_map)
                self.preview = MapPreview(
                    self.graphics, self.current_map, self.current_level_index,
                    source["cells"], state["footer"]
                )
            self.graphics_snapshot = self.preview.update(self.cells, self.current_header)
        except (ValueError, IndexError) as error:
            self.graphics_snapshot = None
            messagebox.showerror("Preview error", str(error))
        self.update_title()
        self.draw()
        if (header_changed or footer_changed) and self.sprite_window is not None:
            self.sprite_window.refresh()

    def schedule_render(self):
        if self.render_job is None:
            self.render_job = self.root.after(16, self.refresh_edited)

    def paint(self, event, button):
        if self.current_map is None:
            return
        x = int(self.canvas.canvasx(event.x) // self.zoom.get())
        y = int(self.canvas.canvasy(event.y) // self.zoom.get())
        state = self.document.state(self.current_map)
        if not (0 <= x < WIDTH and 0 <= y < len(state["cells"]) // WIDTH):
            self.stroke_last = None
            return
        if button not in (1, 3):
            return
        value = 0 if button == 3 else self.selected_sprite if self.edit_mode.get() == 'sprites' else 2
        if self.stroke_before is None:
            self.stroke_before = self.document.copy(state)
        previous = self.stroke_last or (x, y)
        steps = max(abs(x - previous[0]), abs(y - previous[1]), 1)
        for n in range(steps + 1):
            px = round(previous[0] + (x - previous[0]) * n / steps)
            py = round(previous[1] + (y - previous[1]) * n / steps)
            index = py * WIDTH + px
            if state["cells"][index] == value:
                continue
            if value not in (0, 2, 15) and state["cells"][index] in (0, 2, 15):
                if sum(v not in (0, 2, 15) for v in state["cells"]) >= 126:
                    self.status.config(
                        text="Object limit reached (126); remove an object before placing another."
                    )
                    continue
            if value == 15:
                state["cells"][:] = [0 if v == 15 else v for v in state["cells"]]
            state["cells"][index] = value
        self.stroke_last = (x, y)
        self.cells = state["cells"]
        self.schedule_render()

    def finish_stroke(self):
        if self.stroke_before is not None and self.current_map is not None:
            changed = self.document.record(self.current_map, self.stroke_before)
            self.stroke_before = None
            self.stroke_last = None
            if changed:
                self.update_title()
                self.schedule_render()
        else:
            self.stroke_before = None
            self.stroke_last = None

    def change_appearance(self, event=None):
        if self.current_map is None:
            return
        self.finish_stroke()
        state = self.document.state(self.current_map)
        before = self.document.copy(state)
        state["header"][4] = (self.tileset_selector.current() << 4) | (
            state["header"][4] & 15
        )
        state["header"][5] = self.palette_values[self.palette_selector.current()]
        self.current_header = bytes(state["header"])
        if self.sprite_window is not None:
            self.sprite_window.refresh()
        if self.document.record(self.current_map, before):
            self.update_title()
            self.schedule_render()

    def change_footer(self, event=None):
        if self.current_map is None:
            return
        self.finish_stroke()
        state = self.document.state(self.current_map)
        before = self.document.copy(state)
        state["footer"] = self.footer_values[self.footer_selector.current()]
        if self.document.record(self.current_map, before):
            self.update_title()
            self.schedule_render()

    def history(self, redo=False):
        self.finish_stroke()
        if not self.document:
            return
        m = self.document.redo() if redo else self.document.undo()
        if m is None:
            return
        if m != self.current_map:
            self.map_selector.current(m)
            self.level_selector.set("Direct map selection")
            self.show_map(m, "Direct map")
        else:
            self.schedule_render()

    def undo(self):
        self.history()

    def redo(self):
        self.history(True)

    def open_level_file(self):
        if self.current_map is None:
            messagebox.showinfo("Open Level from File", "Open a ROM and select a room first.", parent=self.root)
            return
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Level files", "*.bin")])
        if not path:
            return
        self.finish_stroke()
        try:
            cells = read_level_file(path, len(self.document.state(self.current_map)["cells"]))
        except (OSError, ValueError) as error:
            messagebox.showerror("Level not opened", str(error), parent=self.root)
            return
        self.apply_level_files({self.current_map: cells}, f"Opened {Path(path).name}")

    def save_level_file(self):
        if self.current_map is None:
            messagebox.showinfo("Save Level to File", "Open a ROM and select a room first.", parent=self.root)
            return
        index = self.current_level_index
        initialfile = (level_filename(index) if index is not None
                       else f"map_{self.current_map:02X}.bin")
        path = filedialog.asksaveasfilename(
            parent=self.root, initialfile=initialfile, defaultextension=".bin",
            filetypes=[("Level files", "*.bin")],
        )
        if not path:
            return
        self.finish_stroke()
        try:
            Path(path).write_bytes(bytes(self.document.state(self.current_map)["cells"]))
        except OSError as error:
            messagebox.showerror("Level not saved", str(error), parent=self.root)
            return
        self.status.config(text=f"Saved {Path(path).name}")

    def import_level_files(self):
        if self.document is None:
            messagebox.showinfo("Import Multiple Levels", "Open a ROM first.", parent=self.root)
            return
        directory = filedialog.askdirectory(parent=self.root, title="Select folder containing level files")
        if not directory:
            return
        self.finish_stroke()
        try:
            maps, count = read_level_directory(directory, self.document)
        except (OSError, ValueError) as error:
            messagebox.showerror("Levels not imported", str(error), parent=self.root)
            return
        self.apply_level_files(maps, f"Imported {count} level files ({len(maps)} distinct maps)")

    def export_level_files(self):
        if self.document is None:
            messagebox.showinfo("Export Multiple Levels", "Open a ROM first.", parent=self.root)
            return
        directory = filedialog.askdirectory(parent=self.root, title="Select parent folder for the export")
        if not directory:
            return
        self.finish_stroke()
        try:
            target, count = export_levels(directory, self.document)
        except (OSError, ValueError) as error:
            messagebox.showerror("Levels not exported", str(error), parent=self.root)
            return
        self.status.config(text=f"Exported {count} levels to {target}")

    def apply_level_files(self, maps, status):
        if self.document.replace_level_cells(maps):
            if self.current_map in maps:
                if self.render_job is not None:
                    self.root.after_cancel(self.render_job)
                self.refresh_edited()
            else:
                self.update_title()
        self.status.config(text=status)

    def save_rom(self, save_as=False):
        self.finish_stroke()
        if not self.document:
            return
        path = None if save_as else self.save_path
        if not path:
            path = filedialog.asksaveasfilename(
                title="Save edited ROM",
                defaultextension=".nes",
                initialfile=self.rom.path.stem + "_edited.nes",
                filetypes=[("NES ROM", "*.nes")],
            )
        if not path:
            return
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            report = self.document.save(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("ROM not saved", str(error))
            return
        finally:
            self.root.config(cursor="")
        self.save_path = path
        self.rom = self.document.rom
        if self.world_map_window is not None:
            self.world_map_window.reload_rom()
        self.graphics = ROMGraphics(self.rom)
        self.show_map(
            self.current_map if self.current_map is not None else 0,
            self.current_label or "Direct map",
        )
        space = ", ".join(
            f"bank ${bank:02X}: {free} bytes free" for bank, _, free in report
        )
        self.status.config(
            text=f"Saved {Path(path).name}" + (" · " + space if space else "")
        )

    def confirm_discard(self):
        return (
            not self.document
            or not self.document.dirty
            or messagebox.askyesno("Unsaved edits", "Discard unsaved ROM edits?")
        )

    def close(self):
        self.finish_stroke()
        if self.confirm_discard():
            self.root.destroy()
