"""Render the parchment screen from the game's menu tiles and palettes."""

import struct

from ..core.world_map import REGIONS, WIDTH, cell_positions
from .memory import VideoMemory
from .renderer import ROMGraphics


class WorldMapPreview:
    def __init__(self, rom):
        self.data = rom.data
        self.graphics = ROMGraphics(rom)
        self.positions = cell_positions(self.data)

    def rectangle(self, index):
        start = struct.unpack_from("<H", self.data, 0xE4DA + index * 2)[0] + 0x4010
        width, height = self.data[start:start + 2]
        return width, height, self.data[start + 2:start + 2 + width * height]

    def render(self, region, grid, show_routes=False, line_edits=None):
        data = self.data
        mem = VideoMemory()
        mem.first_row, mem.height = 0, 15
        mem.chr_banks = [0x1A, 0x1C, 0x1A, 0x3E, 0x1C, 0x1D]
        mem.ppu[0x2000:0x23C0] = (
            bytes([0x7F] * 32)
            + bytes([0x7F] + [0x19] * 30 + [0x7F]) * 28
            + bytes([0x7F] * 32)
        )
        mem.ppu[0x23C0:0x2400] = data[0xFD32:0xFD72]
        mem.ppu[0x3F00:0x3F20] = data[0xFED2:0xFEF2]
        sprites = []

        def background(tiles, width, height, x, y):
            for row in range(height):
                start = 0x2000 + (y + row) * 32 + x
                mem.ppu[start:start + width] = tiles[row * width:(row + 1) * width]

        for index, x, y in ((6, 1, 1), (7, 1, 26), (8, 1, 10),
                            (9, 28, 10), (0x26, 9, 10)):
            width, height, tiles = self.rectangle(index)
            background(tiles, width, height, x, y)

        for slot in reversed(range(REGIONS)):
            entry = slot if slot <= region else slot + REGIONS
            index = data[0x6C61 + entry]
            x = data[0x6C7F + entry]
            width, height, tiles = self.rectangle(index & 0x7F)
            if index & 0x80:
                attr = data[0x6C6B + entry]
                sprites.extend((x + i % width * 8, 16 + i // width * 8, tile, attr)
                               for i, tile in enumerate(tiles))
            else:
                background(tiles, width, height, x, 2)

        if show_routes:
            start, end = struct.unpack_from("<2H", data, 0xF86A + region * 2)
            for offset in range(start + 0x4010, end + 0x4010, 4):
                record = line_edits.get(offset) if line_edits else None
                y, tile, attr, x = record if record is not None else data[offset:offset + 4]
                sprites.append((x, y + 1, tile, attr))

        icons = data[0x6E23:0x6E2E]
        for i, (value, (x, y)) in enumerate(zip(grid, self.positions)):
            tile = icons[value]
            if tile == 1:
                sprite_y = data[0x6DEE + i // WIDTH] + 1
                sprites.extend((x * 8 + j % 2 * 8, sprite_y + j // 2 * 8, 0x39 + j, 3)
                               for j in range(4))
            elif tile:
                background(bytes((tile, tile + 1, tile + 2, tile + 3)), 2, 2, x, y)

        pixels = bytearray(self.graphics.render_background(mem, width=256))
        for x, y, tile, attr in reversed(sprites):
            start = 0x3F10 + (attr & 3) * 4
            self.graphics.draw_sprite_tile(
                pixels, mem, x, y, tile, mem.ppu[start:start + 4], attr, width=256
            )
        return bytes(pixels)
