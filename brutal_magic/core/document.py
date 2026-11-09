"""In-memory maps and grouped edit history."""


from .world_map import read_grids, read_level_layouts


class EditorDocument:
    def __init__(self, rom):
        self.rom = rom
        self.maps = {
            m: {"cells": list(r.cells), "header": list(r.header), "footer": r.footer}
            for m, r in enumerate(rom.records)
        }
        self.world_grids = None
        self.redirect = None
        self.saved_world_grids = None
        self.world_layouts = None
        self.saved_world_layouts = None
        self.undo_stack = []
        self.redo_stack = []
        self.saved = {m: self.copy(state) for m, state in self.maps.items()}

    def load_world_grids(self):
        if self.world_grids is None:
            grids = read_grids(self.rom.data)
            self.world_layouts = read_level_layouts(self.rom.data)
            self.saved_world_layouts = self.world_layouts.copy()
            self.world_grids = grids
            self.saved_world_grids = self.world_grids.copy()
        return self.world_grids

    def state(self, map_id):
        return self.maps[map_id]

    @staticmethod
    def copy(state):
        return {"cells": list(state["cells"]), "header": list(state["header"]),
                "footer": state["footer"]}

    def record(self, map_id, before):
        return self.record_group({map_id: before})

    def record_group(self, before):
        after = {map_id: self.copy(self.state(map_id)) for map_id in before}
        changes = [(map_id, state, after[map_id]) for map_id, state in before.items()
                   if state != after[map_id]]
        if not changes:
            return False
        self.undo_stack.append(changes)
        self.redo_stack.clear()
        return True

    def replace_level_cells(self, maps):
        before = {map_id: self.copy(self.state(map_id)) for map_id in maps}
        for map_id, cells in maps.items():
            self.state(map_id)["cells"] = list(cells)
        return self.record_group(before)

    def undo(self):
        if not self.undo_stack:
            return None
        changes = self.undo_stack.pop()
        for map_id, before, _ in changes:
            self.maps[map_id] = self.copy(before)
        self.redo_stack.append(changes)
        return changes[0][0]

    def redo(self):
        if not self.redo_stack:
            return None
        changes = self.redo_stack.pop()
        for map_id, _, after in changes:
            self.maps[map_id] = self.copy(after)
        self.undo_stack.append(changes)
        return changes[0][0]

    def modified(self, map_id):
        return self.rom.records[map_id].needs_expansion or self.maps[map_id] != self.saved[map_id]

    @property
    def dirty(self):
        return (
            self.redirect is not None or self.world_grids != self.saved_world_grids
            or self.world_layouts != self.saved_world_layouts
            or any(self.modified(m) for m in self.maps)
        )

    def save(self, path):
        edits = {m: state for m, state in self.maps.items() if self.modified(m)}
        world_edits = {}
        if self.world_grids is not None:
            world_edits = {region: grid for region, grid in enumerate(self.world_grids)
                           if grid != self.saved_world_grids[region]}
        layouts = self.world_layouts if self.world_layouts != self.saved_world_layouts else None
        rom, report = self.rom.save(path, edits, world_edits, self.redirect, layouts)
        if layouts is not None:
            self.saved_world_layouts = layouts.copy()
        self.redirect = None
        if self.world_grids is not None:
            self.saved_world_grids = self.world_grids.copy()
        self.rom = rom
        for map_id, state in self.maps.items():
            state["header"] = list(rom.records[map_id].header)
        self.saved = {m: self.copy(state) for m, state in self.maps.items()}
        return report
