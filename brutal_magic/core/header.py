"""Interpret map header fields."""

EXTENDED_ROOM_FLAG = 0x01


def room_height(header):
    return 32 if header[4] & EXTENDED_ROOM_FLAG else 27


RAM_ADDRESSES = (0xC7, 0xC6, 0xC5, 0xC4, 0x63, 0xC3, 0x39, 0x3B, 0x3A, 0x3C)
BONUS_DESTINATIONS = (19, 27, 47, 55, 68, 71, 82, 91)
RLE_COMMANDS = ((0x40, 0x4F), (0x60, 0x6F), (0x50, 0x5F), (0x70, 0x7F))


def decode_shortcut(value):
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError("Shortcut must be one byte.")
    return (
        value & 0x3F,
        (
            "repeat tile (horizontal or vertical, selected by command)",
            "N floor cells, then tile",
            "tile, then N floor cells",
            "N wall cells, then tile",
        )[value >> 6],
    )


def describe_header(header):
    if len(header) != 10 or any(
        not isinstance(v, int) or not 0 <= v <= 255 for v in header
    ):
        raise ValueError("Header must contain exactly ten bytes.")
    h = header
    spawn = [
        name
        for bit, name in (
            (1, "ghost"),
            (2, "grunt"),
            (16, "sorcerer"),
            (32, "alternate grunt"),
        )
        if h[0] & bit
    ]
    fast = [
        name
        for bit, name in (
            (1, "ghost"),
            (2, "grunt + alternate grunt"),
            (4, "demon"),
            (8, "lobber"),
            (16, "sorcerer"),
        )
        if h[1] & bit
    ]
    timer = 99 if h[3] & 0x80 else 30 if h[3] & 0x10 else None
    rows = [
        (
            "Generator / special-wall flags",
            f"Long generator cooldown (128 vs 64 ticks): {', '.join(spawn) or 'none'}; "
            f"hide walls $04/$07-$09: {bool(h[0] & 0x80)}. No consumer found for set bits ${h[0] & 0x4C:02X}.",
        ),
        (
            "Movement / ordinary-wall flags",
            f"Short movement cooldown (6 vs 18 ticks): {', '.join(fast) or 'none'}; "
            f"hide ordinary walls: {bool(h[1] & 0x80)}. No consumer found for set bits ${h[1] & 0x60:02X}.",
        ),
        (
            "Exit / treasure-room / clue flags",
            f"Randomize normal exits: {bool(h[2] & 0x80)}; treasure return selector: {h[2] & 7} "
            f"(Level {BONUS_DESTINATIONS[h[2] & 7]} when treasure mode is active); "
            f"clue-collected flag: {bool(h[2] & 0x20)}. No consumer found for set bits ${h[2] & 0x58:02X}.",
        ),
        (
            "Level rules",
            f"Timer: {str(timer) + ' seconds' if timer else 'off'}; horizontal camera unclamped: {bool(h[3] & 0x20)}; "
            f"player shots: {'stun' if h[3] & 1 else '16 damage' if h[3] & 2 else 'no effect'}; "
            f"retain discarded exits as $47: {bool(h[3] & 0x40)}. No consumer found for set bits ${h[3] & 0x0C:02X}.",
        ),
        (
            "Background graphics selector",
            f"Tileset index: {h[4] >> 4}; CHR slot $1000. Room height: {room_height(h)} rows.",
        ),
        (
            "Background palette selector",
            f"Background/floor color index: {h[5] >> 4}; wall palette index: {h[5] & 15}. These index ROM tables, not NES color numbers.",
        ),
    ]
    for value, (first, last) in zip(h[6:], RLE_COMMANDS):
        tile, pattern = decode_shortcut(value)
        rows.append(
            (
                f"RLE ${first:02X}-${last:02X}",
                f"Tile ${tile:02X}; {pattern}; N = command low nibble + 1.",
            )
        )
    return [
        (n + 1, RAM_ADDRESSES[n], h[n], title, description)
        for n, (title, description) in enumerate(rows)
    ]
