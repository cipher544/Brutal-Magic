"""Gauntlet map compression."""

from .header import room_height
from .tiles import WIDTH


def decode_map(data, header):
    """Decode visible cells and return the consumed byte count and cursor."""
    height = room_height(header)
    cells = [0] * (WIDTH * height)
    pos = 0
    previous_tile = 0

    def emit(value):
        nonlocal pos
        # Floor runs advance the cursor without erasing earlier vertical fills.
        if value and pos < len(cells):
            cells[pos] = value
        pos += 1

    def vertical(value, count):
        nonlocal pos
        row, col = divmod(pos, WIDTH)
        for _ in range(count):
            if row < height:
                cells[row * WIDTH + col] = value
            row = (row - 1) % 32
        pos += 1

    for used, command in enumerate(data, 1):
        if pos >= len(cells):
            return cells, used - 1, pos
        if command < 0x40:
            previous_tile = command
            emit(command)
        elif command < 0x80:
            value = header[(6, 8, 7, 9)[(command - 0x40) >> 4]]
            count = (command & 15) + 1
            mode, tile = value >> 6, value & 0x3F
            previous_tile = tile
            if mode == 0:
                if command & 0x10:
                    vertical(tile, count)
                else:
                    for _ in range(count):
                        emit(tile)
            elif mode == 1:
                for _ in range(count):
                    emit(0)
                emit(tile)
            elif mode == 2:
                emit(tile)
                for _ in range(count):
                    emit(0)
            else:
                for _ in range(count):
                    emit(0x02)
                emit(tile)
        elif command < 0xA0:
            if not pos:
                raise ValueError("Repeat command without a previous tile.")
            value = previous_tile
            for _ in range(command - 0x80 + 1):
                emit(value)
        elif command < 0xB0:
            for _ in range(command - 0xA0 + 1):
                emit(0x02)
        elif command < 0xC0:
            vertical(0x02, command - 0xB0 + 1)
        elif command < 0xE0:
            for _ in range(command - 0xC0 + 1):
                emit(0)
        else:
            for _ in range(command - 0xE0 + 1):
                emit(0)
            emit(0x02)
    return cells, len(data), pos


def _vertical_plan(cells, minimum):
    height = len(cells) // WIDTH
    base = list(cells)
    forced = {}
    for col in range(WIDTH):
        row = 0
        while row < height:
            if cells[row * WIDTH + col] != 2:
                row += 1
                continue
            start = row
            while row < height and cells[row * WIDTH + col] == 2:
                row += 1
            end = row
            while end - start >= minimum:
                count = min(16, end - start)
                bottom = end - 1
                for y in range(end - count, bottom):
                    base[y * WIDTH + col] = 0
                forced[bottom * WIDTH + col] = 0xB0 + count - 1
                end -= count
    return base, forced


def _shortest_stream(cells, header, forced):
    """Find the shortest forward stream for fixed shortcuts and vertical fills."""
    length = len(cells)
    # The last-tile register is separate from the most recently emitted cell.
    costs = [dict() for _ in range(length + 1)]
    costs[0][0] = (0, None)
    shortcuts = [
        (base, header[index])
        for base, index in ((0x40, 6), (0x50, 8), (0x60, 7), (0x70, 9))
    ]
    for pos in range(length):
        if not costs[pos]:
            continue
        transitions = []
        if pos in forced:
            transitions.append((1, None, forced[pos]))
        else:
            available = min(33, length - pos)
            for step in range(1, available):
                if pos + step in forced:
                    available = step
                    break
            transitions.append((1, cells[pos], cells[pos]))
            for n in range(1, min(32, available) + 1):
                segment = cells[pos : pos + n]
                if all(v == 0 for v in segment):
                    transitions.append((n, None, 0xC0 + n - 1))
                if n <= 16 and all(v == 2 for v in segment):
                    transitions.append((n, None, 0xA0 + n - 1))
                if (
                    n < available
                    and all(v == 0 for v in segment)
                    and cells[pos + n] == 2
                ):
                    transitions.append((n + 1, None, 0xE0 + n - 1))
            for command_base, value in shortcuts:
                mode, tile = value >> 6, value & 63
                if mode == 0 and command_base in (0x50, 0x70):
                    continue
                for n in range(1, 17):
                    pattern = (
                        [tile] * n
                        if mode == 0
                        else (
                            [0] * n + [tile]
                            if mode == 1
                            else [tile] + [0] * n if mode == 2 else [2] * n + [tile]
                        )
                    )
                    count = len(pattern)
                    if count <= available and cells[pos : pos + count] == pattern:
                        transitions.append((count, tile, command_base + n - 1))
        for previous, (cost, _) in list(costs[pos].items()):
            choices = transitions
            if pos not in forced:
                repeat = 0
                while (
                    repeat < min(32, length - pos)
                    and pos + repeat not in forced
                    and cells[pos + repeat] == previous
                ):
                    repeat += 1
                choices = transitions + [
                    (n, None, 0x80 + n - 1) for n in range(1, repeat + 1)
                ]
            for count, tile, command in choices:
                target = pos + count
                last = previous if tile is None else tile
                old = costs[target].get(last)
                if old is None or cost + 1 < old[0]:
                    costs[target][last] = (cost + 1, (pos, previous, command))
    last = min(costs[length], key=lambda tile: costs[length][tile][0])
    stream = bytearray()
    pos = length
    while pos:
        prev_pos, previous, command = costs[pos][last][1]
        stream.append(command)
        pos, last = prev_pos, previous
    stream.reverse()
    return bytes(stream)


def _shortcut_candidates(cells, header):
    """Choose useful header dictionaries without changing gameplay flags."""
    from collections import Counter

    scores = Counter()
    for pos, tile in enumerate(cells):
        if not tile:
            continue
        before = 0
        while before < 16 and pos - before - 1 >= 0 and cells[pos - before - 1] == 0:
            before += 1
        after = 0
        while (
            after < 16 and pos + after + 1 < len(cells) and cells[pos + after + 1] == 0
        ):
            after += 1
        walls = 0
        while walls < 16 and pos - walls - 1 >= 0 and cells[pos - walls - 1] == 2:
            walls += 1
        if before:
            scores[0x40 | tile] += min(before, 2)
        if after:
            scores[0x80 | tile] += min(after, 2)
        if walls:
            scores[0xC0 | tile] += min(walls, 2)
    ranked = [value for value, _ in scores.most_common(8)]
    if ranked:
        candidate = bytearray(header)
        for index, value in zip((6, 7, 8, 9), ranked):
            candidate[index] = value
        yield bytes(candidate)
        # The two horizontal-only slots can use plain repeated objects.
        runs = Counter()
        for a, b in zip(cells, cells[1:]):
            if a == b and a not in (0, 2):
                runs[a] += 1
        if runs:
            candidate[6] = runs.most_common(1)[0][0]
            yield bytes(candidate)


def encode_map(cells, header, validator=None):
    """Compare legal run encodings and return a verified header and stream."""
    if len(header) != 10:
        raise ValueError("A level header must contain ten bytes.")
    height = room_height(header)
    if len(cells) != WIDTH * height or any(
        type(v) is not int or not 0 <= v < 64 for v in cells
    ):
        raise ValueError(f"A map must contain {WIDTH * height} one-byte tile IDs ($00–$3F).")
    cells = list(cells)
    plans = [(cells, {})]
    for minimum in (2, 4, 8):
        plan = _vertical_plan(cells, minimum)
        if plan[1] and plan not in plans:
            plans.append(plan)
    dictionaries = list(
        dict.fromkeys((bytes(header), *_shortcut_candidates(cells, header)))
    )
    best = None
    for dictionary in dictionaries:
        for base, forced in plans:
            stream = _shortest_stream(base, dictionary, forced)
            decoded, consumed, _ = decode_map(stream, dictionary)
            if decoded != cells:
                continue
            if consumed != len(stream):
                continue
            if best is None or len(stream) < len(best[1]):
                if validator is None or validator(dictionary, stream):
                    best = (dictionary, stream)
    if best is None:
        raise ValueError("Cannot encode this map without changing its cells.")
    return best
