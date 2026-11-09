"""Inspect exit objects in saved level data."""

from dataclasses import dataclass

from .header import room_height
from .room import RoomDecoder, prepare_objects


@dataclass(frozen=True)
class RoomExit:
    x: int
    y: int
    kind: str
    destination: int | None
    auxiliary_offset: int | None = None


def decode_level_objects(rom, level):
    map_id = rom.levels[level - 1]
    if map_id >= len(rom.records):
        return None
    record = rom.records[map_id]
    payload = record.data
    if record.needs_expansion:
        payload = record.header + bytes(record.cells) + bytes((record.footer,))
    decoder = RoomDecoder(payload)
    memory, _ = decoder.decode()
    ram = memory.ram
    original_ids = ram[0x400:0x480]
    offsets = {}
    prepare_objects(decoder, rom.data, level - 1, (record.start + decoder.position) & 255, offsets)
    return record, ram, original_ids, offsets


def read_exits(rom, level):
    """Return the potential successful exits of a one-based level."""
    decoded = decode_level_objects(rom, level)
    if decoded is None:
        return []
    record, ram, original_ids, offsets = decoded
    height = room_height(record.header)
    first_row = int(height != 32)

    random_normal = bool(record.header[2] & 0x80) and original_ids.count(0x10) > 1
    exits = []
    for slot in range(2, 128):
        source_id = original_ids[slot]
        object_id = ram[0x400 + slot]
        state = ram[0x580 + slot]
        if source_id == 0x10 or object_id == 0x10:
            kind, index = "Normal", level
            if source_id == 0x10 and random_normal:
                kind = "Normal (random)"
        elif object_id == 0x11:
            kind, index = "Destination exit", state & 0x7F
        elif object_id in (0x04, 0x2F) and state & 0x80:
            kind = "Secret wall" if object_id == 0x04 else "Locked chest"
            index = state & 0x7F
        else:
            continue

        # Successful exits in special rooms are adjusted by FinishRoomGameplay.
        if level == 100:
            destination = None
        elif record.header[3] & 0x80:
            destination = rom.data[
                0x1C611 + (record.header[2] & 7)
            ] + 1
        else:
            destination = index + 1 + bool(record.header[3] & 0x10)
        x = ram[0x480 + slot] // 8
        y = ram[0x500 + slot] // 8
        if 0 <= x < 32 and first_row <= y < first_row + height:
            offset = offsets.get(slot) if source_id in (0x04, 0x11, 0x2F) else None
            exits.append(RoomExit(x, y, kind, destination, offset))
    return sorted(exits, key=lambda entry: (entry.y, entry.x))
