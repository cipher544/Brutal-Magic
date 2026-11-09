"""Update the displayed map directly from editable cells."""

from copy import deepcopy


class MapPreview:
    def __init__(self, renderer, map_id, level_index, source, footer=None):
        self.renderer = renderer
        self.source = list(source)
        self.footer = footer
        self.snapshot = renderer.snapshot(map_id, level_index, footer=footer, show_all_exits=True)
        self.memory = deepcopy(self.snapshot["memory"])
        ram = self.memory.ram
        self.height = self.memory.height
        self.first_row = self.memory.first_row
        self.cells = [0] * len(source)
        for y in range(self.height):
            for x in range(32):
                if ram[0x300 + (y + self.first_row) * 4 + x // 8] & (1 << (x % 8)):
                    self.cells[y * 32 + x] = 2
        for slot in range(2, 128):
            tile = ram[0x400 + slot]
            x, y = ram[0x480 + slot] // 8, ram[0x500 + slot] // 8 - self.first_row
            if tile and 0 <= x < 32 and 0 <= y < self.height:
                self.cells[y * 32 + x] = tile
        self.spawn = next((i for i, v in enumerate(source) if v == 15), None)

        for index, tile in enumerate(source):
            if tile == 0x10:
                self.cells[index] = tile

    def cell(self, x, row):
        x &= 31
        row &= 31
        if self.first_row <= row < self.first_row + self.height:
            return self.cells[(row - self.first_row) * 32 + x]
        ram = self.memory.ram
        return 2 if ram[0x300 + row * 4 + x // 8] & (1 << (x % 8)) else 0

    def visible_wall(self, tile, header):
        if tile not in (2, 4, 5, 6, 7, 8, 9):
            return False
        flags = header[0] if tile in (4, 7, 8, 9) else header[1]
        return not flags & 0x80

    def metatile(self, x, y, tile, header):
        data = self.renderer.rom.data
        row = y + self.first_row
        if tile in (0, 15, 0x18, 0x19, 0x1B, 0x48):
            return 0
        if tile in (2, 4, 5, 6, 7, 8, 9):
            if not self.visible_wall(tile, header):
                return 0
            mask = 0
            for index in range(7, -1, -1):
                ny = ((row * 2 + data[0x53F3 + index]) & 0x3E) // 2
                nx = ((x * 2 + data[0x53FB + index]) & 0x3E) // 2
                wall = self.visible_wall(self.cell(nx, ny), header)
                mask = (mask >> 1) | (128 if wall else 0)
            return data[0x5AA0 + mask] + (0x30 if tile == 5 else 1)
        if tile in (13, 14):
            mask = 0
            for index in range(3, -1, -1):
                nx = ((x * 2 + data[0x53EB + index]) & 63) // 2
                ny = ((row * 2 + data[0x53EF + index]) & 63) // 2
                mask = (mask << 1) | (self.cell(nx, ny) in (13, 14))
            return data[(0x5FD8 if tile == 13 else 0x5FE8) + mask]
        if 0x12 <= tile <= 0x17:
            selector = (tile - 0x12) * 6
            ram = self.memory.ram
            first = data[0x5FA2 + selector + (ram[11] >> 1)]
            second = data[0x5FA2 + selector + (ram[12] >> 1)]
            return first or (second + 16 if second else 0)
        return data[0x5BA0 + tile]

    def update(self, cells, header):
        changed = {
            i for i, (old, new) in enumerate(zip(self.source, cells)) if old != new
        }
        for index in changed:
            self.cells[index] = 0 if cells[index] == 15 else cells[index]
        self.source[:] = cells
        self.spawn = next((i for i, v in enumerate(cells) if v == 15), None)
        memory = self.memory
        data = self.renderer.rom.data
        memory.chr_banks[2] = data[0x43B0 + (header[4] >> 4)]
        floor = data[0x5557 + (header[5] >> 4)]
        for offset in range(0, 16, 4):
            memory.ppu[0x3F00 + offset] = floor
        palette = data[0x5518 + (header[5] & 15) * 4 : 0x551B + (header[5] & 15) * 4]
        memory.ppu[0x3F0D:0x3F10] = palette
        affected = set(changed)
        for index in changed:
            y, x = divmod(index, 32)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = (x + dx) % 32, y + dy
                    if self.height == 32:
                        ny %= 32
                    if 0 <= ny < self.height and self.cells[ny * 32 + nx] in (
                        2,
                        4,
                        5,
                        6,
                        7,
                        8,
                        9,
                        13,
                        14,
                    ):
                        affected.add(ny * 32 + nx)
        for index in affected:
            tile = self.cells[index]
            y, x = divmod(index, 32)
            self.renderer.put_metatile(
                memory, x, y + self.first_row, self.metatile(x, y, tile, header)
            )
        rgb = bytearray(self.renderer.render_background(memory))
        unsupported = []
        for index, tile in enumerate(self.cells):
            y, x = divmod(index, 32)
            if tile in (0x18, 0x19):
                self.renderer.draw_sprite_metatile(
                    rgb, memory, x * 16, y * 16, data[0x5BA0 + tile]
                )
            elif tile in (0x1B, 0x48):
                unsupported.append((x, y, tile))
        if self.spawn is not None:
            y, x = divmod(self.spawn, 32)
            player_palette = [15] + memory.ram[0x1A3:0x1A6]
            tiles = [data[table + 16] for table in (0x5DF8, 0x5E58, 0x5EB8, 0x5F18)]
            for tile, (dx, dy) in zip(tiles, ((0, 0), (8, 0), (0, 8), (8, 8))):
                self.renderer.draw_sprite_tile(
                    rgb, memory, x * 16 + dx, y * 16 + dy, tile, player_palette, 0
                )
        self.snapshot = dict(self.snapshot, rgb=bytes(rgb), unsupported=unsupported)
        return self.snapshot
