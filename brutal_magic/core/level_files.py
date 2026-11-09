"""Raw level files, one object ID per cell in row-major order."""

from pathlib import Path
import re
from tempfile import TemporaryDirectory


LEVEL_DIRECTORY = "exported_leveles"
LEVEL_NAME = re.compile(r"level_([0-9a-f]{2})\.bin", re.IGNORECASE)


def level_filename(index):
    return f"level_{index:02X}.bin"


def read_level_file(path, size):
    path = Path(path)
    data = path.read_bytes()
    if len(data) != size:
        raise ValueError(f"{path.name} has {len(data)} bytes. Expected {size} for this room.")
    if any(value > 0x3F for value in data):
        raise ValueError(f"{path.name} contains a tile ID outside $00–$3F.")
    return data


def read_level_directory(directory, document):
    """Validate the entire batch before replacing any room cells."""
    maps = {}
    names = {}
    count = 0
    for path in sorted(Path(directory).iterdir()):
        match = LEVEL_NAME.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        index = int(match[1], 16)
        if index >= len(document.rom.levels) or document.rom.levels[index] not in document.maps:
            raise ValueError(f"{path.name} has no corresponding room in this ROM.")
        map_id = document.rom.levels[index]
        cells = read_level_file(path, len(document.state(map_id)["cells"]))
        if map_id in maps and maps[map_id] != cells:
            raise ValueError(
                f"{names[map_id]} and {path.name} share map ${map_id:02X} but contain different tiles."
            )
        maps[map_id] = cells
        names[map_id] = path.name
        count += 1
    if not count:
        raise ValueError("No level_XX.bin files found in this folder.")
    return maps, count


def export_levels(parent, document):
    parent = Path(parent)
    target = parent / LEVEL_DIRECTORY
    if target.exists():
        raise FileExistsError(f"{target} already exists. Choose a different parent folder.")
    with TemporaryDirectory(prefix=".brutal-magic-", dir=parent) as staging:
        folder = Path(staging) / LEVEL_DIRECTORY
        folder.mkdir()
        count = 0
        for index, map_id in enumerate(document.rom.levels):
            if map_id in document.maps:
                (folder / level_filename(index)).write_bytes(bytes(document.state(map_id)["cells"]))
                count += 1
        folder.rename(target)
    return target, count
