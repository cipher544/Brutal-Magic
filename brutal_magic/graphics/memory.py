"""Decoded room state, video memory, and NES palette-address aliases."""


class VideoMemory:
    def __init__(self):
        self.ram = [0] * 0x800
        self.ppu = bytearray(0x4000)
        self.first_row = 1
        self.height = 27
        # Separate storage for editor-only rows beyond the four NES nametables.
        self.extra_nametables = bytearray(0x800)
        self.chr_banks = [0x30, 0x32, 0x10, 0x2F, 0, 0x0A]

    @staticmethod
    def ppu_index(address):
        address &= 0x3FFF
        if address >= 0x3F00:
            address = 0x3F00 + (address & 31)
            if address in (0x3F10, 0x3F14, 0x3F18, 0x3F1C):
                address -= 16
        elif address >= 0x3000:
            address -= 0x1000
        return address

