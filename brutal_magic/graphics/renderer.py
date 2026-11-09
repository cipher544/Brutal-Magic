"""ROM graphics and map rendering."""

from ..core.header import room_height
from ..core.room import RoomDecoder, prepare_objects
from .palette import NES_RGB


class ROMGraphics:
    WIDTH = 512

    def __init__(self, rom):
        self.rom = rom
        self.cache = {}

    def snapshot(self, map_id, level_index=None, cells=None, header=None, footer=None,
                 *, show_all_exits=False):
        key = (
            map_id,
            level_index,
            bytes(cells) if cells is not None else None,
            bytes(header) if header is not None else None,
            footer,
            show_all_exits,
        )
        if key in self.cache:
            return self.cache[key]
        rom = self.rom.data
        source = self.rom.load_map(map_id)
        room_header = bytes(header if header is not None else source["header"])
        height = room_height(room_header)
        first_row = int(height != 32)
        if cells is None and source["needs_expansion"]:
            cells = source["cells"]
        if cells is not None:
            if len(cells) != 32 * height or any(not 0 <= v <= 63 for v in cells):
                raise ValueError(f"Expected {32 * height} one-byte tile IDs ($00-$3F).")
            payload = bytes(cells)
        else:
            start = source["start"] + 10
            payload = rom[start:start + source["size"]]
        room_footer = source["footer"] if footer is None else footer
        decoder = RoomDecoder(room_header + payload + bytes((room_footer,)))
        mem, _ = decoder.decode()
        mem.first_row, mem.height = first_row, height
        ram = mem.ram
        if level_index is None:
            level_index = next((i for i, m in enumerate(self.rom.levels) if m == map_id), None)
        stream_low = (source["start"] if cells is not None or header is not None
                      else source["start"] + decoder.position) & 255
        prepare_objects(decoder, rom, level_index, stream_low)
        self.prepare_background(mem, room_header)
        # Moving ordinary enemies use background metatiles chosen from $BF92.
        # Draw their first facing/frame directly into the nametables.
        unsupported = []
        sprites = []
        for slot in range(2, 128):
            tile = ram[0x400 + slot]
            if not tile or ram[0x380 + slot] == slot:
                continue
            x = ram[0x480 + slot] // 8
            y = ram[0x500 + slot] // 8
            if not (0 <= x < 32 and first_row <= y < first_row + height):
                continue
            if 0x12 <= tile <= 0x17:
                selector = (tile - 0x12) * 6
                first = rom[0x5FA2 + selector + (ram[0x0B] >> 1)]
                second = rom[0x5FA2 + selector + (ram[0x0C] >> 1)]
                metatile = first if first else second + 16 if second else 0
                if metatile:
                    self.put_metatile(mem, x, y, metatile)
            elif tile in (0x18, 0x19):
                # The same metatile tables describe OAM tile numbers; sample
                # from the sprite pattern table and sprite palettes, not BG.
                sprites.append((x * 16, (y - first_row) * 16, rom[0x5BA0 + tile]))
            elif tile in (0x1B, 0x48):
                unsupported.append((x, y - 1, tile))
        if show_all_exits:
            # The editor shows placement even when room setup picks a single exit.
            placed_cells = source["cells"] if cells is None else cells
            exit_metatile = rom[0x5BA0 + 0x10]
            for index, tile in enumerate(placed_cells):
                if tile == 0x10:
                    y, x = divmod(index, 32)
                    self.put_metatile(mem, x, y + first_row, exit_metatile)
        rgb = bytearray(self.render_background(mem))
        for x, y, metatile in sprites:
            self.draw_sprite_metatile(rgb, mem, x, y, metatile)
        # Show a default warrior at the decoded player spawn, without HUD.
        spawn_x, spawn_y = ram[0x7F] * 2, ram[0x80] * 2 - first_row * 16
        if 0 <= spawn_x < 512 and 0 <= spawn_y < height * 16:
            tiles = [rom[table + 16] for table in (0x5DF8, 0x5E58, 0x5EB8, 0x5F18)]
            palette = [0x0F] + [ram[0x1A3 + i] for i in range(3)]
            for tile, (dx, dy) in zip(tiles, ((0, 0), (8, 0), (0, 8), (8, 8))):
                self.draw_sprite_tile(
                    rgb, mem, spawn_x + dx, spawn_y + dy, tile, palette, 0
                )
        rgb = bytes(rgb)
        result = dict(
            rgb=rgb,
            unsupported=unsupported,
            chr_banks=tuple(mem.chr_banks),
            ppu=bytes(mem.ppu),
            memory=mem,
        )
        if len(self.cache) >= 12:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = result
        return result

    def prepare_background(self, memory, header):
        """Select CHR banks, palettes, and metatiles from ROM tables."""
        r, rom = memory.ram, self.rom.data
        memory.chr_banks = [0x30, rom[0x6F0], rom[0x43B0+(header[4] >> 4)], 0x2F, r[11], r[12]]
        r[0x1A3:0x1A6] = rom[0x721:0x724]
        r[0x1A7:0x1AA] = rom[0x731:0x734]
        r[0x192:0x1A3] = rom[0x54EF:0x5500]
        r[0x1AA:0x1B2] = rom[0x5507:0x550F]
        offset = 0x5518+(header[5]&15)*4
        r[0x19F:0x1A2] = rom[offset:offset+3]
        for i in (0,4,8,12,16):
            r[0x192+i] = rom[0x5557+(header[5] >> 4)]
        if r[12] >= 12:
            for i in (1,2,3):
                r[0x192+i] = rom[0x550F+i]
                r[0x1AE+i] = rom[0x5513+i]
        for i in range(17):
            memory.ppu[memory.ppu_index(0x3F00+i)] = r[0x192+i]
        for i in range(8):
            memory.ppu[memory.ppu_index(0x3F18+i)] = r[0x1AA+i]
        memory.ppu[0x3F11:0x3F18] = bytes(r[0x1A3:0x1AA])
        def object_at(x, row):
            slot = r[0x100+(x&31)]
            while slot < 128:
                if r[0x500+slot] == (row*8 & 255):
                    return r[0x400+slot]
                slot = r[0x380+slot]
            return 0

        def select_metatile(x, row, tile):
            flags = rom[0x5BEC+tile]
            if flags & 128:
                visibility = header[0] if tile in (4,7,8,9) else header[1]
                if visibility & 128:
                    return 0
                mask = 0
                for i in range(7,-1,-1):
                    nx = ((x*2+rom[0x53FB+i]) & 62)//2
                    ny = ((row*2+rom[0x53F3+i]) & 62)//2
                    wall = (not header[1]&128 and
                            r[0x300+ny*4+nx//8] & (1 << (nx%8)))
                    neighbor = object_at(nx,ny)
                    visible = header[0] if neighbor in (4,7,8,9) else header[1]
                    wall = wall or (rom[0x5BEC+neighbor]&128 and not visible&128)
                    mask = (mask >> 1) | (128 if wall else 0)
                return rom[0x5AA0+mask]+(0x30 if tile==5 else 1)
            if flags & 64:
                mask = 0
                for i in range(3,-1,-1):
                    nx = ((x*2+rom[0x53EB+i]) & 63)//2
                    ny = ((row*2+rom[0x53EF+i]) & 63)//2
                    mask = (mask << 1) | (object_at(nx,ny) in (13,14))
                return rom[(0x5FE8 if tile==14 else 0x5FD8)+mask]
            return rom[0x5BA0+tile]

        # The game draws linked objects first, then ordinary walls over them.
        for column in range(31,-1,-1):
            slot = r[0x100+column]
            while slot < 128:
                tile = r[0x400+slot]
                x, row = r[0x480+slot]//8, r[0x500+slot]//8
                flags = rom[0x5BEC+tile]
                if tile not in (0x18,0x19,0x48):
                    if flags & 128 or flags & 64:
                        metatile = select_metatile(x,row,tile)
                    else:
                        metatile = rom[0x5BA0+tile]
                        if tile == 0x4B:
                            metatile += 1
                        if tile == 0x3C:
                            metatile += r[0x580+slot]
                    self.put_metatile(memory,x,row,metatile)
                slot = r[0x380+slot]
        if not header[1] & 128:
            for row in range(32 if memory.height == 32 else 30):
                for x in range(32):
                    if r[0x300+row*4+x//8] & (1 << (x%8)):
                        self.put_metatile(memory,x,row,select_metatile(x,row,2))

    def draw_sprite_tile(self, rgb, mem, x, y, tile, palette, attribute, width=512):
        rom = self.rom.data
        # MMC3 mode 0: sprite table $0000 uses the two 2 KiB CHR registers.
        bank = (mem.chr_banks[tile // 128] & 0xFE) + (tile % 128) // 64
        offset = 16 + 128 * 1024 + bank * 1024 + (tile % 64) * 16
        for py in range(8):
            sy = 7 - py if attribute & 0x80 else py
            lo, hi = rom[offset + sy], rom[offset + sy + 8]
            for px in range(8):
                bit = px if attribute & 0x40 else 7 - px
                value = ((lo >> bit) & 1) | (((hi >> bit) & 1) << 1)
                tx, ty = x + px, y + py
                if value and 0 <= tx < width and 0 <= ty < mem.height * 16:
                    at = (ty * width + tx) * 3
                    rgb[at : at + 3] = NES_RGB[palette[value] & 63]

    def draw_sprite_metatile(self, rgb, mem, x, y, metatile):
        rom = self.rom.data
        attribute = rom[0x5952 + metatile]
        palette = [mem.ppu[0x3F10 + (attribute & 3) * 4 + i] for i in range(4)]
        tiles = [rom[table + metatile] for table in (0x555E, 0x563B, 0x5718, 0x57F5)]
        for tile, (dx, dy) in zip(tiles, ((0, 0), (8, 0), (0, 8), (8, 8))):
            self.draw_sprite_tile(rgb, mem, x + dx, y + dy, tile, palette, attribute)

    @staticmethod
    def nametable(mem, tx, ty):
        column = (tx // 32) * 0x400
        if ty >= 60:
            return mem.extra_nametables, column
        return mem.ppu, 0x2000 + column + (ty // 30) * 0x800

    def put_metatile(self, mem, x, y, metatile):
        rom = self.rom.data
        for dx, dy, table in (
            (0, 0, 0x555E),
            (1, 0, 0x563B),
            (0, 1, 0x5718),
            (1, 1, 0x57F5),
        ):
            tx, ty = x * 2 + dx, y * 2 + dy
            nametable, nt = self.nametable(mem, tx, ty)
            lx, ly = tx % 32, ty % 30
            nametable[nt + ly * 32 + lx] = rom[table + metatile]
            address = nt + 0x3C0 + (ly // 4) * 8 + lx // 4
            shift = (ly % 4 // 2) * 4 + (lx % 4 // 2) * 2
            palette = rom[0x5952 + metatile] & 3
            nametable[address] = (nametable[address] & ~(3 << shift)) | (palette << shift)

    def render_background(self, mem, width=512):
        rom = self.rom.data
        banks = mem.chr_banks[2:6]
        output = bytearray(width * mem.height * 16 * 3)
        tiles = {}
        first_tile_row = mem.first_row * 2
        for ty in range(first_tile_row, first_tile_row + mem.height * 2):
            local_y = ty % 30
            y = (ty - first_tile_row) * 8
            for tx in range(width // 8):
                local_x = tx % 32
                nametable, table = self.nametable(mem, tx, ty)
                tile = nametable[table + local_y * 32 + local_x]
                attribute = nametable[table + 0x3C0 + (local_y // 4) * 8 + local_x // 4]
                shift = (local_y % 4 // 2) * 4 + (local_x % 4 // 2) * 2
                palette = (attribute >> shift) & 3
                key = (tile, palette)
                image = tiles.get(key)
                if image is None:
                    offset = 0x20010 + banks[tile // 64] * 1024 + (tile % 64) * 16
                    pixels = bytearray()
                    for row in range(8):
                        lo, hi = rom[offset + row], rom[offset + row + 8]
                        for bit in range(7, -1, -1):
                            value = ((lo >> bit) & 1) | (((hi >> bit) & 1) << 1)
                            color = (
                                mem.ppu[0x3F00 + (palette * 4 + value if value else 0)]
                                & 63
                            )
                            pixels.extend(NES_RGB[color])
                    image = tiles[key] = bytes(pixels)
                for row in range(8):
                    start = ((y + row) * width + tx * 8) * 3
                    output[start : start + 24] = image[row * 24 : (row + 1) * 24]
        return bytes(output)
