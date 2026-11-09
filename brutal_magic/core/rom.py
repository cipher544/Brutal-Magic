"""ROM layout, map records, and bank allocation."""

from dataclasses import dataclass
from pathlib import Path
from hashlib import sha256
import os
import struct
import tempfile

from .rle import decode_map, encode_map
from .header import EXTENDED_ROOM_FLAG
from .tiles import WIDTH
from .room import decode_signature
from .world_map import (
    moved_route_lines, read_grids, read_level_layouts, write_grids, write_level_layouts,
)
from .exits import read_exits
from .redirect import write_redirect


class BankOverflowError(ValueError):
    """A map bank cannot hold its rebuilt records."""


@dataclass(frozen=True)
class MapRecord:
    start: int
    end: int
    header: bytes
    encoded: bytes
    footer: int
    cells: tuple
    needs_expansion: bool = False

    @property
    def data(self):
        return self.header + self.encoded + bytes((self.footer,))


class GauntletROM:
    TABLES = ((0xA85, 35, 0x8010), (0xACB, 35, 0xA010), (0xB11, 25, 0xC010))
    # Stock records at bank ends have padding or unindexed data after the footer.
    STOCK_BANK_TAILS = {
        0x8010: "78ef0f2b043136af859584c81cec6f27672ff44b220a118391de0e712f8dfdbc",
        0xA010: "146974ed6a249c580ef3487d45e3cc02ad4b3c782c2d38f9140e2c215071a7e0",
        0xC010: "140fa7afa55a1bba03589a96151c5fa7a3764584af4b6e5f59681cf76c3f9835",
    }

    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        data = self.data
        if (
            len(data) != 196624
            or data[:4] != b"NES\x1a"
            or data[4:6] != bytes((8, 8))
            or data[6:8] != bytes((0x49, 0))
        ):
            raise ValueError(
                "Expected the Gauntlet (USA) mapper-4 iNES ROM without a trainer."
            )
        self.levels = list(data[0x7C8:0x830])
        self.maps = []
        self.records = []
        self.reserved = []
        for table, count, base in self.TABLES:
            pointers = struct.unpack_from("<" + "H" * count, data, table)
            if any(not 0xA003 <= p < 0xC000 for p in pointers) or any(
                a >= b for a, b in zip(pointers, pointers[1:])
            ):
                raise ValueError("Invalid map pointer table.")
            protected = []
            for index, pointer in enumerate(pointers):
                start = base + pointer - 0xA000
                limit = (
                    base + pointers[index + 1] - 0xA000
                    if index + 1 < count
                    else base + 0x2000
                )
                header = data[start : start + 10]
                payload = data[start + 10 : limit]
                needs_expansion = False
                if header[4] & EXTENDED_ROOM_FLAG:
                    stock_header = bytearray(header)
                    stock_header[4] &= ~EXTENDED_ROOM_FLAG
                    stock_cells, stock_size, stock_advanced = decode_map(payload, stock_header)
                    stock_end = stock_size + 1
                    stock_bank_tail = (
                        index == count - 1
                        and sha256(payload[:stock_end]).hexdigest() == self.STOCK_BANK_TAILS[base]
                    )
                    needs_expansion = (
                        stock_advanced >= len(stock_cells)
                        and (stock_end == len(payload) or stock_bank_tail)
                    )
                if needs_expansion:
                    cells = [2] * WIDTH + stock_cells + [2] * (4 * WIDTH)
                    consumed = stock_size
                else:
                    cells, consumed, advanced = decode_map(payload, header)
                    if advanced < len(cells):
                        raise ValueError("Map data crosses its record or bank boundary.")
                end = start + 10 + consumed + 1
                if end > limit:
                    raise ValueError("Map data crosses its record or bank boundary.")
                record = MapRecord(
                    start,
                    end,
                    header,
                    data[start + 10 : end - 1],
                    data[end - 1],
                    tuple(cells),
                    needs_expansion,
                )
                self.records.append(record)
                self.maps.append(
                    (start, limit if index + 1 < count else None, base + 0x2000)
                )
                # Unindexed data in a gap is not free space, even if it is not
                # referenced by the known map table.
                gap = data[end:limit]
                last = next((i for i in range(len(gap) - 1, -1, -1) if gap[i]), None)
                if last is not None:
                    protected.append((end, end + last + 1, gap[: last + 1]))
            self.reserved.append(protected)

    def load_map(self, map_id):
        if not 0 <= map_id < len(self.records):
            raise ValueError(f"Map ${map_id:02X} has no valid pointer in this ROM.")
        record = self.records[map_id]
        return dict(
            cells=list(record.cells),
            header=record.header,
            footer=record.footer,
            start=record.start,
            size=len(record.encoded),
            needs_expansion=record.needs_expansion,
        )

    def load_level(self, level):
        if not 1 <= level <= len(self.levels):
            raise ValueError("Level number outside the level table.")
        return self.load_map(self.levels[level - 1])

    def rebuild(self, edits, world_edits=None, redirect=None, layouts=None):
        """Build a complete ROM in memory before allowing any file writes."""
        output = bytearray(self.data)
        if world_edits:
            write_grids(output, world_edits)
        if layouts is not None:
            write_level_layouts(output, layouts)
            for offset, line in moved_route_lines(self.data, read_level_layouts(self.data), layouts).items():
                output[offset:offset + 4] = line
        if redirect is not None:
            if edits:
                raise ValueError("Save room edits separately before redirecting an exit.")
            write_redirect(self, output, redirect)
        packed = {}
        for map_id, state in edits.items():
            record = self.records[map_id]
            cells, header = state["cells"], bytes(state["header"])
            footer = bytes((state.get("footer", record.footer),))
            if not record.needs_expansion and tuple(cells) == record.cells and header[6:] == record.header[6:]:
                packed[map_id] = header + record.encoded + footer
            else:
                expected = decode_signature(header + bytes(cells) + footer)

                def valid(dictionary, stream):
                    return (
                        decode_signature(dictionary + stream + footer)
                        == expected
                    )

                header, encoded = encode_map(cells, header, validator=valid)
                if decode_map(encoded, header)[0] != list(cells):
                    raise ValueError(
                        f"Map ${map_id:02X} failed compression verification."
                    )
                packed[map_id] = header + encoded + footer
        report = []
        first_id = 0
        for bank_number, (table, count, base) in enumerate(self.TABLES):
            map_ids = range(first_id, first_id + count)
            first_id += count
            if not any(m in packed for m in map_ids):
                continue
            end = base + 0x2000
            records = [(m, packed.get(m, self.records[m].data)) for m in map_ids]
            cursor = base + 3
            placements = []
            for map_id, record in records:
                for protected_start, protected_end, _ in self.reserved[bank_number]:
                    if (
                        cursor < protected_end
                        and cursor + len(record) > protected_start
                    ):
                        cursor = protected_end
                if cursor + len(record) > end:
                    extra = cursor + len(record) - end
                    raise BankOverflowError(
                        f"Bank ${bank_number + 4:02X} is too small by at least {extra} byte(s). "
                        "No ROM was saved. Remove map data or simplify a map in this bank."
                    )
                placements.append((map_id, cursor, record))
                cursor += len(record)
            output[base + 3 : end] = bytes(end - base - 3)
            for protected_start, protected_end, data in self.reserved[bank_number]:
                output[protected_start:protected_end] = data
            for index, (map_id, start, record) in enumerate(placements):
                if not base + 3 <= start < start + len(record) <= end:
                    raise BankOverflowError("A record would cross its map bank.")
                output[start : start + len(record)] = record
                struct.pack_into("<H", output, table + index * 2, 0xA000 + start - base)
            report.append(
                (bank_number + 4, sum(len(r) for _, r in records), end - cursor)
            )
        if len(output) != len(self.data):
            raise ValueError("ROM size changed unexpectedly.")
        return bytes(output), report

    def save(self, path, edits, world_edits=None, redirect=None, layouts=None):
        edits = dict(edits)
        for map_id, record in enumerate(self.records):
            if record.needs_expansion and map_id not in edits:
                edits[map_id] = self.load_map(map_id)
        data, report = self.rebuild(edits, world_edits, redirect, layouts)
        destination = Path(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".brutal-magic-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            # Reopen the staged ROM and check every edited map before replacing
            # the destination. A failed save leaves the previous file intact.
            candidate = GauntletROM(temporary)
            for map_id, state in edits.items():
                record = candidate.records[map_id]
                if (record.needs_expansion or record.cells != tuple(state["cells"])
                        or record.footer != state.get("footer", self.records[map_id].footer)):
                    raise ValueError(
                        f"Saved map ${map_id:02X} differs from the edited map."
                    )
            if world_edits:
                grids = read_grids(candidate.data)
                if any(grids[region] != tuple(grid) for region, grid in world_edits.items()):
                    raise ValueError("Saved world map differs from the edited map.")
            if layouts is not None and read_level_layouts(candidate.data) != list(layouts):
                raise ValueError("Saved level positions differ from the edited world map.")
            if redirect is not None and not any(
                (entry.x, entry.y, entry.destination) ==
                (redirect.exit_x, redirect.exit_y, redirect.destination)
                for entry in read_exits(candidate, redirect.level)
            ):
                raise ValueError("Saved exit differs from the requested redirect.")
            os.replace(temporary, destination)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return GauntletROM(destination), report
