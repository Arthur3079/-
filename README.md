# DiskCleaner

DiskCleaner — desktop utility (PyQt5) for scanning disks, finding junk, large, duplicate, and old files.

## Features
- **Disk Map**: visualize space usage by top folders.
- **Junk Scanner**: find temporary and common junk files.
- **Large Files**: detect files bigger than configurable threshold.
- **Duplicates**: identify duplicates by hash and size.
- **Old Files**: find files older than configurable age.
- Dark UI theme and status bar summary.

## Project structure

```text
DiskCleaner/
  main.py
  core/
  gui/
  logs/
requirements.txt
config.py
install.bat
run.bat
```

## Installation
1. Install Python 3.10+.
2. (Windows) Open **Command Prompt as Administrator**.
3. From project root run:
   ```bat
   install.bat
   ```

## Run
- Standard run:
  ```bat
  run.bat
  ```
- Or directly:
  ```bat
  python DiskCleaner/main.py
  ```

## Run as Administrator (Windows)
Some folders (for example `C:\Windows`, `Program Files`) can require elevated privileges.

1. Search for **Command Prompt**.
2. Right click → **Run as administrator**.
3. Run `run.bat` from the project folder.

## Usage scenarios
1. Select drive in left panel (e.g., `C:/`, `D:/`).
2. Open **Junk Scanner** and scan common temporary folders.
3. Open **Large Files** to review space-heavy files.
4. Open **Duplicates** to free redundant copies.
5. Open **Old Files** for archival/cleanup candidates.

## Example screens
_Currently placeholder examples — add real screenshots after first run._

- Main window with tab set and status summary.
- Large Files tab after scan.
- Duplicates tab with grouped duplicate entries.

## Notes
- Paths are normalized with Windows-safe prefix (`\\?\`) when needed.
- Access checks are done before scan operations.
- Cleanup log is saved at `DiskCleaner/logs/cleanup_log.txt`.
