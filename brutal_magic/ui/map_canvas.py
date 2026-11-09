"""Map image, grid, and object overlays."""

import math
import tkinter as tk
from ..core.tiles import WIDTH, NAMES


FLOOR_TILES = {0, 1, 10, 11, 12}
WALL_TILES = {2, 3, 5, 6, 7, 8, 9}


class MapCanvasView:
    def draw(self):
        self.canvas.delete("all")
        self.photo = None
        if self.cells is None:
            return
        size = self.zoom.get()
        height = len(self.cells) // WIDTH
        self.canvas.config(scrollregion=(0, 0, WIDTH * size, height * size))
        simple = self.simple_mode.get()
        graphical = not simple and self.graphics_snapshot is not None
        show_grid = self.grid.get()
        show_ids = self.ids.get()
        if graphical:
            ppm = f"P6\n512 {height * 16}\n255\n".encode("ascii") + self.graphics_snapshot["rgb"]
            native = tk.PhotoImage(data=ppm, format="PPM")
            divisor = math.gcd(size, 16)
            self.photo = native.zoom(size // divisor).subsample(16 // divisor)
            self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        if simple:
            for index, value in enumerate(self.cells):
                y, x = divmod(index, WIDTH)
                if value in FLOOR_TILES:
                    color = "white"
                elif value in WALL_TILES:
                    color = "black"
                else:
                    color = "yellow"
                self.canvas.create_rectangle(
                    x * size,
                    y * size,
                    (x + 1) * size,
                    (y + 1) * size,
                    fill=color,
                    outline="",
                )
        for index, value in enumerate(self.cells):
            y, x = divmod(index, WIDTH)
            if show_grid:
                self.canvas.create_rectangle(
                    x * size,
                    y * size,
                    (x + 1) * size,
                    (y + 1) * size,
                    outline="#929AA0",
                )
            if show_ids and value not in (0, 2):
                self.canvas.create_rectangle(
                    x * size,
                    y * size,
                    x * size + size,
                    y * size + max(10, size // 2),
                    fill="#20242A",
                    outline="",
                )
                self.canvas.create_text(
                    (x + 0.5) * size,
                    y * size + max(5, size // 4),
                    text=f"{value:02X}",
                    font=("Consolas", max(8, size // 3)),
                    fill="white",
                )
        if graphical:
            for x, y, value in self.graphics_snapshot["unsupported"]:
                self.canvas.create_rectangle(
                    x * size,
                    y * size,
                    (x + 1) * size,
                    (y + 1) * size,
                    outline="#FF50DE",
                    width=2,
                )
                self.canvas.create_text(
                    (x + 0.5) * size,
                    (y + 0.5) * size,
                    text=f"{value:02X}",
                    fill="#FF50DE",
                )

    def exits_match_room(self):
        if self.current_map is None or not self.room_exits:
            return False
        record = self.rom.records[self.current_map]
        return tuple(self.cells) == record.cells and self.current_header == record.header

    def hover(self, event):
        if self.cells is None:
            return
        x, y = int(self.canvas.canvasx(event.x) // self.zoom.get()), int(
            self.canvas.canvasy(event.y) // self.zoom.get()
        )
        if 0 <= x < WIDTH and 0 <= y < len(self.cells) // WIDTH:
            value = self.cells[y * WIDTH + x]
            if self.exits_match_room():
                room_y = y + int(len(self.cells) // WIDTH != 32)
                for entry in self.room_exits:
                    if (entry.x, entry.y) == (x, room_y):
                        destination = f"Level {entry.destination}" if entry.destination else "Finale"
                        self.status.config(text=f"X: {x:02d}  Y: {room_y:02d}  ·  {entry.kind} → {destination}")
                        return
            self.status.config(
                text=f'X: {x:02d}  Y: {y:02d}  |  Map byte: ${value:02X}  |  {NAMES.get(value, "Object / sprite")}'
            )
