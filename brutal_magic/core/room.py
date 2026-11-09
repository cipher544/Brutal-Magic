"""Decode room commands and construct the game's wall and object tables."""

from .header import RAM_ADDRESSES, room_height
from ..graphics.memory import VideoMemory


class RoomDecoder:
    def __init__(self, payload):
        self.memory = VideoMemory()
        self.ram = self.memory.ram
        self.payload = payload
        self.position = 0
        self.x, self.y = 0, 1
        self.previous = 0
        r = self.ram
        r[0x300:0x304] = [255] * 4
        r[0x370:0x378] = [255] * 8
        for slot in range(3, 128):
            r[0x380 + slot] = slot + 1
        r[0x100:0x120] = [128] * 32
        r[0x180:0x187] = [128] * 7
        r[0x65] = 3

    def read(self):
        if self.position >= len(self.payload):
            raise ValueError("Compressed map ended before its footer.")
        value = self.payload[self.position]
        self.position += 1
        return value

    def unlink(self, slot):
        r = self.ram
        col = r[0x480 + slot] // 8 & 31
        current = r[0x100 + col]
        if current == slot:
            r[0x100 + col] = r[0x380 + slot]
        else:
            while current < 128:
                following = r[0x380 + current]
                if following == slot:
                    r[0x380 + current] = r[0x380 + slot]
                    break
                current = following
        for i in range(7):
            if r[0x180 + i] == slot:
                r[0x180 + i] = 128
                break

    def link(self, slot):
        r = self.ram
        col = r[0x480 + slot] // 8 & 31
        r[0x380 + slot] = r[0x100 + col]
        r[0x100 + col] = slot
        tile = r[0x400 + slot]
        if tile in (0x18, 0x19, 0x1B, 0x4B):
            for i in range(7):
                if r[0x180 + i] >= 128:
                    r[0x180 + i] = slot
                    break
        elif tile == 0x3D:
            r[0x186] = slot

    def remove(self, slot):
        self.unlink(slot)
        r = self.ram
        if slot >= 2:
            r[0x380 + slot] = r[0x65]
            r[0x65] = slot
        r[0x400 + slot] = 0

    def store(self, tile):
        r = self.ram
        x, y = self.x & 31, self.y & 31
        slot = r[0x100 + x]
        while slot < 128 and r[0x500 + slot] != (self.y * 8 & 255):
            slot = r[0x380 + slot]
        found = slot < 128
        if found and r[0x400 + slot] == 0x10:
            r[0x75] = (r[0x75] - 1) & 255
        if tile in (0, 2, 15):
            if found:
                self.remove(slot)
            if tile == 15:
                r[0x7F:0x81] = [x * 8, self.y * 8 & 255]
            address = 0x300 + y * 4 + x // 8
            if tile == 2:
                r[address] |= 1 << (x % 8)
            else:
                r[address] &= ~(1 << (x % 8))
            return
        if found:
            self.unlink(slot)
        else:
            slot = r[0x65]
            if slot >= 128:
                return
            r[0x65] = r[0x380 + slot]
            r[0x480 + slot], r[0x500 + slot] = x * 8, self.y * 8 & 255
        r[0x74] = slot
        r[0x400 + slot] = tile
        if tile == 0x10:
            r[0x75] = (r[0x75] + 1) & 255
        self.link(slot)

    def advance(self, count=1):
        row, self.x = divmod(self.x + count, 32)
        self.y = (self.y + row) & 255

    def horizontal(self, tile, count):
        if tile == 0:
            self.advance(count)
        elif tile == 0x3C:
            # A Hydra command creates three heads and twelve body sections.
            self.ram[0x69] = 0
            for _ in range(3):
                self.store(0x1B)
                self.ram[0x580 + self.ram[0x74]] = 0
                row = self.y
                self.y = (self.y - 1) & 255
                for _ in range(4):
                    self.store(0x3C)
                    self.ram[0x580 + self.ram[0x74]] = self.ram[0x69]
                    self.ram[0x69] += 1
                    self.y = (self.y - 1) & 255
                self.y = row
                self.advance()
            slot = self.ram[0x74]
            self.ram[0x400 + slot] = 0x48
            self.ram[0x580 + slot] = 0
            self.x = (self.x - 2) & 255
        else:
            for _ in range(count):
                self.store(tile)
                self.advance()

    def vertical(self, tile, count):
        row = self.y
        for _ in range(count):
            self.store(tile)
            self.y = (self.y - 1) & 255
        self.y = row
        self.advance()

    def decode(self):
        r = self.ram
        header = bytes(self.read() for _ in range(10))
        for address, value in zip(RAM_ADDRESSES, header):
            r[address] = value
        height = room_height(header)
        if height == 32:
            self.y = 0
            r[0x300:0x304] = [0] * 4
            r[0x370:0x378] = [0] * 8
        while self.y < height + (height != 32):
            command = self.read()
            if command < 0x40:
                self.previous = command
                self.horizontal(command, 1)
            elif command < 0x80:
                value = header[(6, 8, 7, 9)[(command - 0x40) >> 4]]
                mode, tile, count = value >> 6, value & 63, (command & 15) + 1
                self.previous = value
                if mode == 0:
                    (self.vertical if command & 0x10 else self.horizontal)(tile, count)
                elif mode == 1:
                    self.horizontal(0, count)
                    self.horizontal(tile, 1)
                elif mode == 2:
                    self.horizontal(tile, 1)
                    self.horizontal(0, count)
                else:
                    self.horizontal(2, count)
                    self.horizontal(tile, 1)
            elif command < 0xA0:
                self.horizontal(self.previous & 63, command - 0x80 + 1)
            elif command < 0xB0:
                self.horizontal(2, command - 0xA0 + 1)
            elif command < 0xC0:
                self.vertical(2, command - 0xB0 + 1)
            elif command < 0xE0:
                self.horizontal(0, command - 0xC0 + 1)
            else:
                self.horizontal(0, command - 0xE0 + 1)
                self.horizontal(2, 1)
        footer = self.read()
        r[11] = footer >> 4
        r[12] = 30 if footer & 15 == 15 else footer & 15
        if height != 32:
            r[0x378:0x37C] = r[0x300:0x304]
            r[0x37C:0x380] = r[0x374:0x378]
        return self.memory, footer


def decode_signature(payload):
    decoder = RoomDecoder(payload)
    memory, _ = decoder.decode()
    if decoder.position != len(payload):
        raise ValueError("Compressed map contains data after the footer.")
    r = memory.ram
    objects = sorted((r[0x480+i], r[0x500+i], r[0x400+i])
                     for i in range(128) if r[0x400+i])
    walls = r[0x300:0x380] if room_height(payload) == 32 else r[0x304:0x370]
    return bytes(walls), tuple(objects), tuple(r[0x7F:0x81]), tuple(r[11:13])


def prepare_objects(decoder, rom, level_index, stream_low, auxiliary_offsets=None):
    """Apply per-level replacements, exit selection, and object initial states."""
    r = decoder.ram
    count = r[0x75]
    r[0x75] = (stream_low % count + 1) if count >= 2 else count
    for address in range(0x66, 0x6D):
        r[address] = 128
    r[0x400:0x402] = [0x49, 0x49]
    if level_index is None:
        position = 0xB43
    else:
        pointer = int.from_bytes(rom[0x830+level_index*2:0x832+level_index*2], 'little')
        position = pointer - 0x8000 + 16
        r[0xA3] = level_index

    def read(slot):
        nonlocal position
        if auxiliary_offsets is not None:
            auxiliary_offsets[slot] = position
        value = rom[position]
        position += 1
        return value

    for slot in range(127, -1, -1):
        tile = r[0x400 + slot]
        if not tile:
            continue
        if 7 <= tile <= 12:
            index = tile - 7
            if index >= 3:
                index -= 3
            r[0x580+slot] = r[0x66+index]
            r[0x66+index] = slot
        elif tile == 5:
            r[0x580+slot] = 3
        elif tile == 4:
            r[0x580+slot] = read(slot)
        elif tile == 3:
            r[0x580+slot] = 8
        elif rom[0x5BEC+tile] & 0xC0:
            continue
        elif tile == 0x3E:
            r[0x580+slot] = r[0x69]
            r[0x69] = slot
        elif 0x12 <= tile < 0x2E:
            if tile == 0x1B:
                state = 100
            elif tile < 0x1C:
                state = 3
            else:
                state = (tile - 0x1C) % 3 + 1
            r[0x580+slot] = 20 if tile == 0x18 else state
        elif tile in (0x31, 0x32):
            r[0x580+slot] = 100
        elif tile in (0x2F, 0x11):
            r[0x580+slot] = read(slot)
        elif tile == 0x3D:
            decoder.unlink(slot)
            r[0x400+slot] = read(slot)
            decoder.link(slot)
        elif tile == 0x10 and r[0xC5] & 128:
            r[0x75] = (r[0x75]-1) & 255
            if r[0x75]:
                r[0x400+slot] = 0x47
                if not r[0xC4] & 64:
                    decoder.remove(slot)
