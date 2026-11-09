"""Redirect one existing branch and its matching parchment line."""

from dataclasses import dataclass

from .exits import decode_level_objects, read_exits
from .world_map import (
    cell_positions, make_route_line, read_grids, read_level_layouts, read_routes,
    route_line_offset,
)


@dataclass(frozen=True)
class RouteRedirect:
    level: int
    exit_x: int
    exit_y: int
    destination: int


def branch_options(rom, level, entry, grids=None, layouts=None):
    """Return legal targets and the offsets to update for a selected exit."""
    old = entry.destination
    aux = entry.auxiliary_offset
    if aux is None or not 0x8FE <= aux < 0xA85 or not old:
        raise ValueError("Choose an existing exit with its own destination byte.")
    exits = read_exits(rom, level)
    if entry not in exits or sum(other.destination == old for other in exits) != 1:
        raise ValueError("This destination is shared by multiple exits in the room.")
    if rom.records[rom.levels[level - 1]].header[3] & 0x90:
        raise ValueError("Timed rooms use special destination rules.")
    data = rom.data
    routes = read_routes(data)
    layouts = read_level_layouts(data) if layouts is None else layouts
    region = next((i for i, layout in enumerate(layouts) if level in layout), None)
    if region is None:
        raise ValueError("This level has no parchment node.")
    layout = layouts[region]
    line_offset = route_line_offset(data, region, level, old, routes)
    if line_offset is None or routes[level].count(old) != 1:
        raise ValueError("This branch needs a unique recorded parchment line.")
    route_index = data[0x7CBE + level - 1] + routes[level].index(old)

    for other in range(1, min(len(rom.levels), 103) + 1):
        if other == level:
            continue
        decoded = decode_level_objects(rom, other)
        if decoded and aux in decoded[3].values():
            raise ValueError(f"This destination byte is also used by Level {other}.")

    positions = cell_positions(data)
    icons = (read_grids(data) if grids is None else grids)[region]
    source = layout.index(level)
    sx, sy = positions[source]
    options = {}
    for cell, target in enumerate(layout):
        if (not target or target == level or target in routes[level]
                or any(other.destination == target for other in exits)
                or not icons[source] or not icons[cell]
                or rom.levels[target - 1] >= len(rom.records)):
            continue
        line = make_route_line((sx, sy), positions[cell])
        if line is not None:
            options[target] = line
    return options, aux, 0x7D23 + route_index, line_offset


def plan_redirect(rom, redirect, grids, layouts):
    """Resolve the same byte changes for preview and save."""
    entry = next((entry for entry in read_exits(rom, redirect.level)
                  if (entry.x, entry.y) == (redirect.exit_x, redirect.exit_y)), None)
    if entry is None:
        raise ValueError("The selected exit is unavailable.")
    options, aux, route, line = branch_options(rom, redirect.level, entry, grids, layouts)
    target = redirect.destination
    if target not in options:
        raise ValueError("Select a neighboring level with an available route.")
    return aux, route, line, options[target]


def write_redirect(rom, output, redirect):
    """Apply the exit, lookup and OAM changes to the same staged ROM."""
    aux, route, line, sprite = plan_redirect(
        rom, redirect, read_grids(output), read_level_layouts(output)
    )
    destination = redirect.destination - 1
    output[aux] = (output[aux] & 0x80) | destination
    output[route] = destination
    output[line:line + 4] = sprite
