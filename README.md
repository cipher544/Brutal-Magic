# Brutal Magic

A Level Editor for the NES version of Gauntlet(USA). Run `main.py` with Python 3, then open your
ROM. Requires Python 3 with Tkinter, which is included in standard Windows Python 
installations. No additional packages are needed.

## Editing

- Edit → Draw Mode (`1`): left click or drag adds walls.
- Right click or drag: clear cells to floor.
- Edit → Add Sprites (`2`): opens the sprite window; left click or drag places the selected sprite.
- The sprite window shows an ID/description combo and a 16×16 ROM graphics preview.
- Closing the sprite window returns to Draw Mode.
- Tileset and Palette: change the current map's background appearance.
- Sprite Tileset: choose the map footer byte from the combinations found in the
  loaded ROM. This controls the enemy graphics banks.
- Edit → Undo / Redo: reverse a stroke or property change (`Ctrl+Z` / `Ctrl+Y`).
- File → Open ROM: load a ROM (`Ctrl+O`).
- File → Save ROM: compress and write your edits (`Ctrl+S`).
- File → Save ROM as: write a separate ROM copy.
- View → Zoom: 100%, 150%, or 200%. Press `+` or `-` to step through them.
- View → Simple Mode (`3`): white floor, black walls, and yellow sprites.
- View → Show sprite IDs (`4`): toggle the ID overlay in either view.
- View → Show grid (`5`): toggle the map grid.

All maps remain in memory while you work. Levels using the same map share its
edits.

## Uncompressed level files

- **File → Save Level to File** writes the current room as a raw binary.
  **Open Level from File** loads a raw binary into the selected room.
- **Export Multiple Levels** creates an `exported_leveles` folder under the
  selected parent folder. Files are numbered by zero-based hexadecimal level
  index, starting at `level_00.bin` for Level 1. Levels without a room are
  skipped. **Import Multiple Levels** reads matching names from a folder.
- Each file contains one byte per tile, left to right and top to bottom.
  Floor is `$00`, wall is `$02`, and other tiles keep their normal IDs.
  A stock room takes 864 bytes and a 32-row room takes 1,024 bytes.
- The raw format stores tile IDs only. Import uses the selected room's
  dimensions and keeps its header settings, sprite footer, and level
  auxiliary data. Levels sharing a room must import identical tiles.
  **Save ROM** compresses and writes the imported rooms.