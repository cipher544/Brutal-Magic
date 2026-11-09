"""World map painting window."""

import tkinter as tk
from tkinter import messagebox, ttk

from ..core.exits import read_exits
from ..core.redirect import RouteRedirect, branch_options, plan_redirect

from ..core.world_map import (
    CELL_TYPES, QUESTION, REGIONS, moved_route_lines, read_routes, route_line_offset,
)
from ..graphics.world_map import WorldMapPreview


ICON_NAMES = (
    "Blank", "Brick", "Tree", "Fire", "Gate", "Cracked block",
    "Door", "Red stone", "Blue question mark", "Treasure", "Gold question mark",
)


class WorldMapWindow:
    ZOOM = 2

    def __init__(self, editor, grids):
        self.editor = editor
        self.grids = grids
        self.layouts = editor.document.world_layouts
        self.move_source = None
        self.line_edits = {}
        self.preview = WorldMapPreview(editor.rom)
        self.routes = read_routes(editor.rom.data)
        self.selected_level = None
        self.exits = []
        self.inspected_level = None
        self.undo_stack = []
        self.redo_stack = []
        self.window = tk.Toplevel(editor.root)
        self.window.title("Brutal Magic — World Map")
        self.window.transient(editor.root)
        self.window.protocol("WM_DELETE_WINDOW", self.window.withdraw)

        bar = ttk.Frame(self.window, padding=6)
        bar.pack(fill="x")
        self.region = ttk.Combobox(
            bar, state="readonly", width=10,
            values=[f"Region {i + 1}" for i in range(REGIONS)],
        )
        self.region.current(0)
        self.region.pack(side="left")
        self.region.bind("<<ComboboxSelected>>", self.change_region)

        self.icon = ttk.Combobox(
            bar, state="readonly", width=18,
            values=[f"${i:X}  {ICON_NAMES[i]}" for i in range(CELL_TYPES)],
        )
        self.icon.current(1)
        self.icon.pack(side="left", padx=6)
        self.lines = tk.BooleanVar(master=self.window)
        ttk.Checkbutton(bar, text="Show route lines", variable=self.lines,
                        command=self.draw).pack(side="left")
        ttk.Button(bar, text="Undo", width=6,
                   command=lambda: self.history()).pack(side="right")
        ttk.Button(bar, text="Redo", width=6,
                   command=lambda: self.history(redo=True)).pack(side="right")

        options = ttk.Frame(self.window, padding=(6, 0, 6, 4))
        options.pack(fill="x")
        self.level_numbers = tk.BooleanVar(master=self.window, value=True)
        ttk.Checkbutton(options, text="Show level numbers", variable=self.level_numbers,
                        command=self.draw).pack(side="left")
        self.inspect_mode = tk.BooleanVar(master=self.window)
        ttk.Checkbutton(options, text="Inspect routes", variable=self.inspect_mode,
                        command=lambda: self.change_mode(self.move_mode)).pack(side="left", padx=8)
        self.move_mode = tk.BooleanVar(master=self.window)
        ttk.Checkbutton(options, text="Move levels", variable=self.move_mode,
                        command=lambda: self.change_mode(self.inspect_mode)).pack(side="left")

        self.canvas = tk.Canvas(
            self.window, width=256 * self.ZOOM, height=240 * self.ZOOM,
            highlightthickness=0,
        )
        self.canvas.pack()
        self.image = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Button-3>", self.erase)
        self.status = ttk.Label(self.window, padding=(6, 4))
        self.status.pack(fill="x")
        self.exit_panel = ttk.Frame(self.window, padding=(6, 0, 6, 6))
        self.exit_table = ttk.Treeview(
            self.exit_panel, columns=("position", "type", "destination", "route"),
            show="headings", selectmode="browse", height=4,
        )
        for name, label, width in (
            ("position", "Room X,Y", 75), ("type", "Exit type", 120),
            ("destination", "Destination", 95), ("route", "Parchment", 125),
        ):
            self.exit_table.heading(name, text=label)
            self.exit_table.column(name, width=width)
        self.exit_table.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(self.exit_panel, orient="vertical", command=self.exit_table.yview)
        scrollbar.pack(side="left", fill="y")
        self.exit_table.configure(yscrollcommand=scrollbar.set)
        self.exit_table.bind("<Double-1>", lambda event: self.open_room())
        actions = ttk.Frame(self.exit_panel, padding=(4, 0, 0, 0))
        actions.pack(side="right", fill="y")
        ttk.Button(actions, text="Open room", command=self.open_room).pack(fill="x")
        self.redirect_button = ttk.Button(actions, text="Redirect…", command=self.edit_redirect)
        self.redirect_button.pack(fill="x", pady=2)
        self.cancel_redirect = ttk.Button(actions, text="Clear redirect", command=self.clear_redirect)
        self.cancel_redirect.pack(fill="x")
        self.window.bind("<Control-z>", lambda event: self.history())
        self.window.bind("<Control-y>", lambda event: self.history(redo=True))
        self.window.bind("<Control-s>", lambda event: self.editor.save_rom())
        self.window.bind("<Control-Shift-S>", lambda event: self.editor.save_rom(True))
        self.draw()

    def reload_rom(self):
        self.preview = WorldMapPreview(self.editor.rom)
        self.routes = read_routes(self.editor.rom.data)
        self.draw()

    def edit_redirect(self):
        entry = self.selected_exit()
        document = self.editor.document
        if entry is None:
            messagebox.showinfo("Redirect exit", "Select an exit in the table first.", parent=self.window)
            return
        if any(document.modified(m) for m in document.maps):
            messagebox.showinfo("Redirect exit", "Save room edits first.", parent=self.window)
            return
        level = self.selected_level
        try:
            options, _, _, _ = branch_options(self.editor.rom, level, entry, self.grids, self.layouts)
            if not options:
                raise ValueError("This branch has no available neighboring destinations.")
        except (ValueError, IndexError) as error:
            messagebox.showinfo("Redirect exit", str(error), parent=self.window)
            return

        dialog = tk.Toplevel(self.window)
        dialog.title("Redirect exit")
        dialog.transient(self.window)
        dialog.grab_set()
        ttk.Label(dialog, text=f"Level {level} · {entry.kind} · ({entry.x}, {entry.y})",
                  padding=8).pack()
        targets = sorted(options)
        choice = ttk.Combobox(dialog, state="readonly",
                              values=[f"Level {target}" for target in targets])
        choice.current(0)
        choice.pack(padx=8)

        def apply():
            document.redirect = RouteRedirect(level, entry.x, entry.y, targets[choice.current()])
            self.lines.set(True)
            dialog.destroy()
            self.changed()

        ttk.Button(dialog, text="Stage redirect", command=apply).pack(pady=8)
        dialog.bind("<Escape>", lambda event: dialog.destroy())

    def clear_redirect(self):
        self.editor.document.redirect = None
        self.changed()

    def change_mode(self, other):
        other.set(False)
        self.change_region()

    def change_region(self, event=None):
        self.move_source = None
        self.selected_level = None
        self.draw()

    def selected_exit(self):
        selection = self.exit_table.selection()
        return self.exits[int(selection[0])] if selection else None

    def open_room(self):
        if self.selected_level:
            self.window.withdraw()
            self.editor.open_level_exit(self.selected_level, self.selected_exit())

    def draw_map(self):
        region = self.region.current()
        pixels = self.preview.render(region, self.grids[region], self.lines.get(), self.line_edits)
        self.photo = tk.PhotoImage(
            master=self.window, data=b"P6\n256 240\n255\n" + pixels, format="PPM"
        ).zoom(self.ZOOM)
        self.canvas.itemconfigure(self.image, image=self.photo)
        self.canvas.delete("grid")
        scale = 8 * self.ZOOM
        for level, (x, y) in zip(self.layouts[region], self.preview.positions):
            self.canvas.create_rectangle(
                x * scale, y * scale, (x + 2) * scale - 1, (y + 2) * scale - 1,
                outline="#00edff" if level and level == self.selected_level else "#665430",
                dash=(2, 4), tags="grid",
            )

            if level and self.level_numbers.get():
                right, bottom = (x + 2) * scale - 2, (y + 2) * scale - 2
                self.canvas.create_rectangle(right - 22, bottom - 14, right, bottom,
                                             fill="#222222", outline="", tags="grid")
                self.canvas.create_text(right - 2, bottom, anchor="se", text=str(level),
                                        fill="white", font="TkSmallCaptionFont", tags="grid")

    def draw(self):
        previous = self.selected_exit() if self.inspected_level == self.selected_level else None
        self.inspected_level = self.selected_level
        document = self.editor.document
        self.line_edits = {}
        if self.layouts != document.saved_world_layouts:
            self.line_edits = moved_route_lines(
                self.editor.rom.data, document.saved_world_layouts, self.layouts
            )
        pending = document.redirect
        redirect_error = None
        if pending:
            try:
                _, _, line, sprite = plan_redirect(
                    self.editor.rom, pending, self.grids, self.layouts
                )
            except (ValueError, IndexError) as error:
                redirect_error = str(error)
            else:
                self.line_edits[line] = sprite
        self.redirect_button.configure(state="disabled" if pending else "normal")
        self.cancel_redirect.configure(state="normal" if pending else "disabled")
        self.exit_table.delete(*self.exit_table.get_children())
        self.exits = []
        if self.inspect_mode.get() and self.selected_level:
            self.exit_panel.pack(fill="x")
            level = self.selected_level
            destinations = ", ".join(str(target) for target in self.routes.get(level, ()))
            map_id = self.editor.rom.levels[level - 1]
            try:
                self.exits = read_exits(self.editor.rom, level)
            except (ValueError, IndexError):
                self.status.config(text=f"Level {level} · Could not decode saved room exits")
            else:
                self.status.config(text=f"Level {level} · Map ${map_id:02X} · "
                                        f"Recorded routes: {destinations or 'none'} · Saved ROM")
            region = self.region.current()
            for i, entry in enumerate(self.exits):
                offset = route_line_offset(
                    self.editor.rom.data, region, level, entry.destination, self.routes
                )
                if offset is not None:
                    y = (self.line_edits[offset][0] if offset in self.line_edits
                         else self.editor.rom.data[offset])
                    route = "Recorded line" if y < 239 else "Recorded, no line"
                elif entry.destination in self.routes.get(level, ()):
                    route = "Recorded, no line"
                else:
                    route = "No recorded line"
                target = f"Level {entry.destination}" if entry.destination else "Finale"
                if pending and (level, entry.x, entry.y) == (pending.level, pending.exit_x, pending.exit_y):
                    target = f"Level {pending.destination}"
                    route = "Needs adjustment" if redirect_error else "Pending save"
                self.exit_table.insert("", "end", iid=str(i), values=(
                    f"{entry.x}, {entry.y}", entry.kind, target, route,
                ))
                if previous and (entry.x, entry.y, entry.kind) == (previous.x, previous.y, previous.kind):
                    self.exit_table.selection_set(str(i))
        else:
            self.exit_panel.pack_forget()
            if self.move_mode.get():
                text = "Pick a level, then click its new cell."
                if self.move_source is not None:
                    text = f"Moving Level {self.selected_level} · Click its new cell."
                self.status.config(text=text)
            else:
                self.status.config(text="Enable Inspect routes and click a level to see its destinations.")
        if redirect_error:
            self.status.config(text=f"Pending redirect: {redirect_error}")
        elif pending:
            self.status.config(text=f"Pending Level {pending.level} → Level {pending.destination} · Save ROM to apply")
        self.draw_map()

    def cell_at(self, event):
        scale = 8 * self.ZOOM
        for cell, (x, y) in enumerate(self.preview.positions):
            if x <= event.x / scale < x + 2 and y <= event.y / scale < y + 2:
                return cell
        return None

    def click(self, event):
        cell = self.cell_at(event)
        if cell is None:
            return
        if self.move_mode.get():
            self.move_level(cell)
        elif self.inspect_mode.get():
            self.selected_level = self.layouts[self.region.current()][cell] or None
            self.draw()
        else:
            self.paint(cell, self.icon.current())

    def erase(self, event):
        cell = self.cell_at(event)
        if cell is not None and not (self.inspect_mode.get() or self.move_mode.get()):
            self.paint(cell, 0)

    def move_level(self, cell):
        region = self.region.current()
        layout = self.layouts[region]
        source = self.move_source
        if source is None:
            if layout[cell]:
                self.move_source = cell
                self.selected_level = layout[cell]
                self.draw()
            return
        self.move_source = None
        self.selected_level = None
        if source == cell:
            self.draw()
            return
        if not self.routes:
            messagebox.showinfo("Move levels", "This ROM has an unsupported route table.", parent=self.window)
            self.draw()
            return
        icons = self.grids[region]
        moved_layout = list(layout)
        moved_icons = list(icons)
        moved_layout[source], moved_layout[cell] = moved_layout[cell], moved_layout[source]
        moved_icons[source], moved_icons[cell] = moved_icons[cell], moved_icons[source]
        self.record_edit(region, tuple(moved_icons), tuple(moved_layout))

    def paint(self, cell, value):
        region = self.region.current()
        before = self.grids[region]
        if before[cell] == value:
            return
        after = list(before)
        if value == QUESTION:
            # The game reserves a single OAM slot group for this icon.
            after = [0 if icon == QUESTION else icon for icon in after]
        after[cell] = value
        self.record_edit(region, tuple(after), self.layouts[region])

    def record_edit(self, region, icons, layout):
        before = self.grids[region], self.layouts[region]
        self.grids[region], self.layouts[region] = icons, layout
        self.undo_stack.append((region, before, (icons, layout)))
        self.redo_stack.clear()
        self.changed()

    def history(self, redo=False):
        source, destination = self.undo_stack, self.redo_stack
        if redo:
            source, destination = destination, source
        if source:
            region, before, after = entry = source.pop()
            destination.append(entry)
            self.grids[region], self.layouts[region] = after if redo else before
            self.move_source = None
            self.region.current(region)
            self.selected_level = None
            self.changed()

    def changed(self):
        self.editor.update_title()
        self.draw()
