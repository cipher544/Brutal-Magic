"""The five between-room route grids in PRG bank $07."""

import struct

WIDTH = 8
HEIGHT = 5
REGIONS = 5
CELL_TYPES = 11
QUESTION = 8
GRID_SIZE = WIDTH * HEIGHT // 2
POINTER_TABLE = 0xF7FC


def read_grids(data):
    pointers = struct.unpack_from("<5H", data, POINTER_TABLE)
    expected = tuple(0xB7F6 + GRID_SIZE * i for i in range(REGIONS))
    if pointers != expected:
        raise ValueError("This ROM uses an unsupported world map layout.")
    grids = [
        tuple(cell for byte in data[p + 0x4010:p + 0x4010 + GRID_SIZE]
              for cell in (byte >> 4, byte & 15))
        for p in pointers
    ]
    if any(cell >= CELL_TYPES for grid in grids for cell in grid):
        raise ValueError("This ROM uses unsupported world map icons.")
    return grids


def write_grids(output, edits):
    read_grids(output)
    for region, grid in edits.items():
        if (not 0 <= region < REGIONS or len(grid) != WIDTH * HEIGHT
                or any(not 0 <= cell < CELL_TYPES for cell in grid)
                or grid.count(QUESTION) > 1):
            raise ValueError("Invalid world map grid.")
        start = POINTER_TABLE + 2 * REGIONS + GRID_SIZE * region
        output[start:start + GRID_SIZE] = bytes(
            (grid[i] << 4) | grid[i + 1] for i in range(0, len(grid), 2)
        )


# Stock node positions inferred from the endpoints of the route sprites.
# Level 100 occupies the remaining finale node in Region 5.
LEVEL_GRIDS = (
    (
          0,   0,   0,   0,  19,  18,  17,   0,
          0,   0,   0,   0,  16,  15,  14,   0,
          0,   0,   8,   9,  10,  12,  13,   0,
          0,   7,   6,   5,   4,  11,   0,   0,
          0,   0,   0,   1,   2,   3,   0,   0,
    ),
    (
          0,  20,   0,   0,  37,  38,  39,   0,
          0,  21,   0,   0,  36,   0,  40,  41,
          0,  23,  22,  33,  34,  35,   0,   0,
          0,  24,  26,  32,  30,  31,   0,   0,
          0,  25,  27,  28,  29,   0,   0,   0,
    ),
    (
          0,   0,  56,  55,  54,  53,   0,   0,
         59,  60,  57,   0,  52,  51,   0,   0,
          0,  62,  58,   0,   0,  50,  49,  48,
          0,   0,  61,   0,   0,  45,  44,  47,
          0,   0,   0,   0,   0,  42,  43,  46,
    ),
    (
          0,   0,   0,   0,  63,  64,   0,   0,
          0,   0,   0,   0,   0,  65,   0,   0,
          0,   0,  78,  77,  66,  67,   0,   0,
          0,  74,  75,  76,   0,  68,   0,   0,
          0,  73,  72,  71,  70,  69,   0,   0,
    ),
    (
          0,   0,   0,  90,  91,  92,  93,   0,
          0,   0,  88,  89,   0,  95,  94,  97,
         85,  86,  87,   0,   0,  96,  99,  98,
         84,  82,  81,   0,   0,   0, 100,   0,
         83,  79,  80,   0,   0,   0,   0,   0,
    ),
)


def read_routes(data):
    """Read the transitions used by the game's parchment route tracker."""
    starts = data[0x7CBE:0x7D23]
    destinations = data[0x7D23:0x7DA2]
    routes = {}
    end = len(destinations)
    for source in range(len(starts) - 1, -1, -1):
        start = starts[source]
        if start == 0xFF:
            continue
        if start > end or any(index >= 100 for index in destinations[start:end]):
            return {}
        routes[source + 1] = tuple(index + 1 for index in destinations[start:end])
        end = start
    return routes


def route_line_offset(data, region, source, destination, routes):
    """Return the file offset of a route OAM record, if present."""
    options = routes.get(source, ())
    if destination not in options:
        return None
    index = data[0x7CBE + source - 1] + options.index(destination)
    index -= data[0x7CB9 + region]
    start, end = struct.unpack_from("<2H", data, 0xF86A + region * 2)
    address = end - (index + 1) * 4
    if index < 0 or not 0xA000 <= start <= address < end <= 0xC000:
        return None
    return address + 0x4010


def route_line_position(data, region, source, destination, routes):
    offset = route_line_offset(data, region, source, destination, routes)
    if offset is None:
        return None
    y, _, _, x = data[offset:offset + 4]
    return (x, y + 1) if y < 239 else None

def cell_positions(data):
    columns = data[0x6DE6:0x6DEE]
    return [
        ((column | data[0x6DF4 + row]) & 31,
         ((data[0x6DFC + row] & 3) * 256 + data[0x6DF4 + row]) // 32)
        for row in range(HEIGHT) for column in columns
    ]




# Stock PRG $07 ends in zero padding. A tagged, editor-only permutation
# keeps level IDs recoverable after the game-facing icon and line tables move.
LAYOUT_OFFSET = 0xFF72
LAYOUT_TAG = b"BMNODES1"
LAYOUT_END = LAYOUT_OFFSET + len(LAYOUT_TAG) + 100


def read_level_layouts(data):
    block = data[LAYOUT_OFFSET:LAYOUT_END]
    if not block.startswith(LAYOUT_TAG):
        return list(LEVEL_GRIDS)
    cells = block[len(LAYOUT_TAG):]
    layouts = []
    for stock in LEVEL_GRIDS:
        levels = sorted(filter(None, stock))
        grid = [0] * (WIDTH * HEIGHT)
        for level in levels:
            cell = cells[level - 1]
            if cell >= len(grid) or grid[cell]:
                raise ValueError("Invalid Brutal Magic level positions.")
            grid[cell] = level
        layouts.append(tuple(grid))
    return layouts


def write_level_layouts(output, layouts):
    block = output[LAYOUT_OFFSET:LAYOUT_END]
    if any(block) and not block.startswith(LAYOUT_TAG):
        raise ValueError("The ROM already uses the space reserved for world map positions.")
    if len(layouts) != REGIONS:
        raise ValueError("Invalid world map regions.")
    cells = bytearray(100)
    for stock, grid in zip(LEVEL_GRIDS, layouts):
        if len(grid) != WIDTH * HEIGHT or sorted(grid) != sorted(stock):
            raise ValueError("Levels must stay within their original region.")
        for cell, level in enumerate(grid):
            if level:
                cells[level - 1] = cell
    output[LAYOUT_OFFSET:LAYOUT_END] = LAYOUT_TAG + cells


def make_route_line(source, destination):
    sx, sy = source
    tx, ty = destination
    dx, dy = abs(tx - sx), abs(ty - sy)
    x, y = min(sx, tx) * 8, min(sy, ty) * 8
    if (dx, dy) == (3, 0):
        return bytes((y + 3, 0x3F, 3, x + 16))
    if (dx, dy) == (0, 3):
        return bytes((y + 15, 0x3E, 3, x + 4))
    if (dx, dy) == (3, 3):
        flip = 0x80 if (tx - sx) * (ty - sy) < 0 else 0
        return bytes((y + 15, 0x3D, 3 | flip, x + 16))
    return None


def moved_route_lines(data, before, after):
    """Reposition changed intra-region lines without changing visited bits."""
    routes = read_routes(data)
    if not routes:
        raise ValueError("The ROM has an unsupported parchment route table.")
    positions = cell_positions(data)
    changes = {}
    for region, (old_grid, new_grid) in enumerate(zip(before, after)):
        if old_grid == new_grid:
            continue
        old = {level: positions[i] for i, level in enumerate(old_grid) if level}
        new = {level: positions[i] for i, level in enumerate(new_grid) if level}
        for source in new:
            for target in routes.get(source, ()):
                if target not in new or (old[source], old[target]) == (new[source], new[target]):
                    continue
                offset = route_line_offset(data, region, source, target, routes)
                if offset is not None:
                    changes[offset] = make_route_line(new[source], new[target]) or bytes((0xFF, 0, 0, 0))
    return changes
