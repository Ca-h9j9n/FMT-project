import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import subprocess
import os
import json
import time
import threading
import re
import sys
import textwrap
import shutil
import math
import tempfile
import struct
from collections import deque
last_dir = None

def get_config_path():
    appdata_dir = os.getenv("APPDATA")
    app_dir = os.path.join(appdata_dir, "FMT_Emulation_Tools")
    os.makedirs(app_dir, exist_ok=True)
    return os.path.join(app_dir, "cmd_config.json")

CONFIG_FILE = get_config_path()

def load_config():
    default_config = {
        "last_dir": os.getcwd()
    }

    try:
        if not os.path.exists(CONFIG_FILE):
            return default_config

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"Config load failed: {e}")

        # May be damaged → Create a backup
        try:
            backup_path = CONFIG_FILE + ".bak"
            if os.path.exists(CONFIG_FILE):
                os.replace(CONFIG_FILE, backup_path)
                print(f"Broken config backed up to: {backup_path}")
        except Exception as e2:
            print(f"Backup failed: {e2}")

        # Regenerate default settings
        try:
            save_config(default_config)
            print("Default config recreated")
        except Exception as e3:
            print(f"Config recreate failed: {e3}")

        return default_config

def save_config(cfg):
    temp_path = CONFIG_FILE + ".tmp"

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        # Replace atomically
        os.replace(temp_path, CONFIG_FILE)

    except Exception as e:
        print(f"Config save failed: {e}")

def update_last_dir(path):
    global last_dir
    try:
        last_dir = os.path.dirname(path)
        config["last_dir"] = last_dir
        save_config(config)
    except Exception as e:
        print(f"last_dir update failed: {e}")

config = load_config()
last_dir = config.get("last_dir", os.getcwd())

def extract_progress(line):
    match = re.search(r'(\d+(\.\d+)?)%', line)
    if match:
        return float(match.group(1))
    return None

# ========================
# ===== Image Tool =======
# ========================

class AppState:
    def __init__(self):
        self.process = None
        self.cancel_event = threading.Event()
        self.current_output = None
        self.progress = 0
        self.is_running = False
        self.input_file = None
        self.output_file = None
        self.is_closing = False
        self.success = False
        self.cancelled = False

state = AppState()

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# ========================
# == Main window (root) ==
# ========================
root = tk.Tk()
try:
    icon = tk.PhotoImage(file=resource_path("fmt.png"))
    root.iconphoto(True, icon)
except Exception as e:
    print("icon load failed:", e)

root.title("FMT Emulation Toolkit 1.0")

progress_var = tk.DoubleVar()

progress_bar = ttk.Progressbar(
    root,
    variable=progress_var,
    maximum=100
)

def _update_progress_ui(value):
    progress_var.set(value)

def safe_update_progress(value):
    try:
        if value < state.progress:
            return  # Backflow prevention

        state.progress = value

        if root.winfo_exists():
            root.after(0, _update_progress_ui, value)

    except Exception:
        pass

root.geometry("390x550")
root.resizable(False, False) 

main_frame = tk.Frame(root)
main_frame.pack(fill="both", expand=True)

# ========================
# Left: Image Tool
# ========================
image_frame = tk.Frame(main_frame, bg="#d0d0d0", bd=1, relief="solid")
image_frame.pack(
    side="left",
    fill="both",
    expand=True,
    padx=(10, 5),   # left10 / right5
    pady=10
)
image_frame.pack_propagate(False)
image_frame.configure(width=180)
tk.Label(
    image_frame,
    text="Disk Image Utility",
    bg="#d0d0d0",
    font=("Segoe UI", 10, "bold")
).pack(anchor="w", padx=5, pady=5)


# ========================
# Right: Command Tool
# ========================
cmd_frame = tk.Frame(main_frame, bg="#c0c0c0", bd=1, relief="solid")
cmd_frame.pack(
    side="left",
    fill="both",
    expand=True,
    padx=(5, 10),   # left5 / right10
    pady=10
)
cmd_frame.pack_propagate(False)
cmd_frame.configure(width=180)

tk.Label(
    cmd_frame,
    text="CMD File Generator",
    bg="#c0c0c0",
    font=("Segoe UI", 10, "bold")
).pack(anchor="w", padx=5, pady=5)


# ========================
# Styles
# ========================
style = ttk.Style()
style.theme_use("default")
style.configure("Modern.TButton",
    font=("Segoe UI", 9),
    padding=(2, 1)
)
style.configure("Big.TButton",
    font=("Segoe UI", 9),
    padding=(2, 18)
)
style.configure("Accent.TButton",
    font=("Segoe UI", 10, "bold"),
    padding=(4, 10),
    foreground="white",
    background="#777777"
)

style.map("Accent.TButton",
    background=[("active", "#005A9E")]
)


# ========================
# Frames
# ========================
left_frame = tk.Frame(image_frame)
left_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)

right_frame = tk.Frame(cmd_frame)
right_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)


# =========================
# File Creation Helper
# =========================
def create_file(path, size, fill=0x00, suppress_warn=False):
    """
    Creates a raw blank file of a specified size filled with a specific byte value.
    Unused variable 'fd_type' has been removed for cleanup.
    """
    with open(path, "wb") as f:
        f.write(bytes([fill]) * size)

from enum import IntEnum

# =========================
# Disk Size Definitions (Enum)
# =========================
class DiskSize(IntEnum):
    SIZE_640KB  = 655360
    SIZE_720KB  = 737280
    SIZE_123MB  = 1261568  # 1232 * 1024
    SIZE_144MB  = 1474560
    SIZE_144KB  = 1474560

# Full format parameter definitions for each disk size
# (tracks, heads, sectors, spc, fat_sectors, root_entries, fat_count, media)
FULL_FORMAT_PARAMS = {
    DiskSize.SIZE_640KB:  (80, 2, 8, 1, 2, 112, 2, 0xFB),
    DiskSize.SIZE_720KB:  (80, 2, 9, 2, 3, 112, 2, 0xF9),
    DiskSize.SIZE_123MB:  (77, 2, 8, 1, 2, 192, 2, 0xFE),
    DiskSize.SIZE_144MB:  (80, 2, 18, 1, 9, 224, 2, 0xF0),
}

# =========================
# Common Entry (Unified wrapper)
# =========================
def format_fd_image(path, size, suppress_warn=False):
    """
    Common entry point for D88 generation and external calls.
    """
    apply_full_format(path, size)

# =========================
# Standard FAT12 format
# =========================

def format_standard(path, tracks, heads, sectors, spc, fat_sectors, root_entries, fat_count, media):
    SECTOR_SIZE = 512
    total_sectors = tracks * heads * sectors

    # -----------------
    # Initialize All (Fill with Zeros)
    # -----------------
    with open(path, "wb") as f:
        f.write(b'\x00' * (total_sectors * SECTOR_SIZE))

    with open(path, "r+b") as f:

        # -----------------
        # Boot Sector
        # -----------------
        boot = bytearray(SECTOR_SIZE)

        boot[0:3] = b'\xEB\x3C\x90'
        boot[3:11] = b'MSDOS3.1'

        boot[11:13] = (512).to_bytes(2, 'little')
        boot[13] = spc
        boot[14:16] = (1).to_bytes(2, 'little')
        boot[16] = fat_count
        boot[17:19] = root_entries.to_bytes(2, 'little')
        boot[19:21] = total_sectors.to_bytes(2, 'little')
        boot[21] = media
        boot[22:24] = fat_sectors.to_bytes(2, 'little')
        boot[24:26] = sectors.to_bytes(2, 'little')
        boot[26:28] = heads.to_bytes(2, 'little')

        boot[28:32] = (0).to_bytes(4, 'little')
        boot[32:36] = (0).to_bytes(4, 'little')

        boot[510:512] = b'\x55\xAA'

        f.seek(0)
        f.write(boot)

        # -----------------
        # FAT
        # -----------------
        reserved_sectors = 1
        fat_start = reserved_sectors * SECTOR_SIZE

        for i in range(fat_count):
            f.seek(fat_start + i * fat_sectors * SECTOR_SIZE)

            fat = bytearray(fat_sectors * SECTOR_SIZE)
            fat[0] = media
            fat[1] = 0xFF
            fat[2] = 0xFF

            f.write(fat)

        # -----------------
        # Root Directory
        # -----------------
        root_dir_sectors = (root_entries * 32 + 511) // 512
        root_start = fat_start + fat_count * fat_sectors * SECTOR_SIZE

        f.seek(root_start)
        f.write(b'\x00' * (root_entries * 32))

# =========================
# 1.23MB（PC-98）
# =========================
def format_123(path):
    SECTOR_SIZE = 1024  # Highest Priority (not 512)

    tracks = 77
    heads = 2
    sectors = 8

    total_sectors = tracks * heads * sectors

    fat_sectors = 2
    root_entries = 192
    fat_count = 2
    media = 0xFE

    total_size = total_sectors * SECTOR_SIZE

    # -----------------
    # Initialize All (Filling with Zeros Recommended)
    # -----------------
    with open(path, "wb") as f:
        f.write(b'\x00' * total_size)

    with open(path, "r+b") as f:

        # -----------------
        # Boot Sector
        # -----------------
        boot = bytearray(SECTOR_SIZE)

        boot[0:3] = b'\xEB\x3C\x90'
        boot[3:11] = b'NEC 3.3 '

        boot[11:13] = (1024).to_bytes(2, 'little')   # 1,024 bytes
        boot[13] = 1                                 # sectors per cluster
        boot[14:16] = (1).to_bytes(2, 'little')      # reserved
        boot[16] = fat_count
        boot[17:19] = root_entries.to_bytes(2, 'little')
        boot[19:21] = total_sectors.to_bytes(2, 'little')
        boot[21] = media
        boot[22:24] = fat_sectors.to_bytes(2, 'little')
        boot[24:26] = sectors.to_bytes(2, 'little')
        boot[26:28] = heads.to_bytes(2, 'little')

        # Drive number, etc. (Any value is fine)
        boot[36] = 0x00
        boot[38] = 0x29

        # Signature (Extremely Important)
        boot[1022:1024] = b'\x55\xAA'

        f.seek(0)
        f.write(boot)

        # -----------------
        # FAT Area
        # -----------------
        fat_start = SECTOR_SIZE  # One sector after the reservation

        fat_size_bytes = fat_sectors * SECTOR_SIZE

        fat = bytearray(fat_size_bytes)
        fat[0] = media
        fat[1] = 0xFF
        fat[2] = 0xFF

        for i in range(fat_count):
            f.seek(fat_start + i * fat_size_bytes)
            f.write(fat)

        # -----------------
        # Root Directory
        # -----------------
        root_start = fat_start + fat_count * fat_size_bytes
        root_size = root_entries * 32

        f.seek(root_start)
        f.write(b'\x00' * root_size)

        # -----------------
        # Data Area
        # -----------------
        data_start = root_start + root_size

        f.seek(data_start)
        f.write(b'\x00' * (total_size - data_start))

# ========================
# FAT Utilities
# ========================
def calc_fat_size(total_sectors, reserved, root_entries, sector_size, fat_count, spc):

    root_dir_sectors = ((root_entries * 32) + (sector_size - 1)) // sector_size

    # Approximation → Convergence
    fat_size = 1
    while True:
        data_sectors = total_sectors - (reserved + fat_count * fat_size + root_dir_sectors)
        clusters = data_sectors // spc

        fat_bytes = ((clusters + 2) * 3 + 1) // 2
        required_fat_sectors = (fat_bytes + sector_size - 1) // sector_size

        if required_fat_sectors == fat_size:
            return fat_size

        fat_size = required_fat_sectors

def init_fat12(f, fat_start, fat_size_bytes, fat_count, media_byte):
    for i in range(fat_count):
        offset = fat_start + i * fat_size_bytes
        f.seek(offset)

        fat = bytearray([0x00] * fat_size_bytes)

        # FAT12 Reserved Cluster (0,1)
        fat[0] = media_byte
        fat[1] = 0xFF
        fat[2] = 0xFF

        f.write(fat)

# =========================
# Full Format (Main Logic)
# =========================
def apply_full_format(path, size):
#    safe_update_log(f"Starting full format: {path} ({size})")

    # Safe type conversion
    if isinstance(size, DiskSize):
        disk_size = size
    else:
        disk_size = DiskSize(int(size))

    # 1.23MB
    if disk_size == DiskSize.SIZE_123MB:
        create_raw_blank(path, 77, 2, 8, 1024)
        apply_full_format_123(path)
#        safe_update_log("Full format completed (1.23MB)")
        return

    # Standard format
    params = FULL_FORMAT_PARAMS.get(disk_size)
    if not params:
        raise ValueError(f"Unsupported full format size: {size}")

    tracks, heads, sectors, spc, fat_sectors, root_entries, fat_count, media = params

    create_raw_blank(path, tracks, heads, sectors, 512)

    format_standard(
        path,
        tracks,
        heads,
        sectors,
        spc,
        fat_sectors,
        root_entries,
        fat_count,
        media
    )

#    safe_update_log("Full format completed successfully")

# ========================
# Full Format (1.23MB)
# ========================
def apply_full_format_123(path):
    try:
        with open(path, "r+b") as f:

            SECTOR_SIZE = 1024  # PC-98 1.23MB
            TOTAL_SECTORS = 1232

            reserved = 1
            fat_count = 2
            root_entries = 192
            spc = 1
            media = 0xFE

            # ========================
            # FAT Size Calculation
            # ========================
            fat_size = calc_fat_size(
                TOTAL_SECTORS,
                reserved,
                root_entries,
                SECTOR_SIZE,
                fat_count,
                spc
            )

            fat_bytes = fat_size * SECTOR_SIZE

            # ========================
            # Boot Sector
            # ========================
            f.seek(0)
            boot = bytearray(SECTOR_SIZE)

            boot[0:3] = b'\xEB\x3C\x90'
            boot[3:11] = b'NEC 3.3 '   # Tsugaru Compatible

            boot[11:13] = SECTOR_SIZE.to_bytes(2, 'little')
            boot[13] = spc
            boot[14:16] = reserved.to_bytes(2, 'little')
            boot[16] = fat_count
            boot[17:19] = root_entries.to_bytes(2, 'little')
            boot[19:21] = TOTAL_SECTORS.to_bytes(2, 'little')
            boot[21] = media
            boot[22:24] = fat_size.to_bytes(2, 'little')
            boot[24:26] = (8).to_bytes(2, 'little')
            boot[26:28] = (2).to_bytes(2, 'little')

            boot[1022:1024] = b'\x55\xAA'

            f.write(boot)

            # ========================
            # FAT
            # ========================
            fat_start = SECTOR_SIZE * reserved

            init_fat12(
                f,
                fat_start,
                fat_bytes,
                fat_count,
                media
            )

            # ========================
            # Root Directory
            # ========================
            root_start = fat_start + fat_count * fat_bytes

            root_size = root_entries * 32
            root_sectors = (root_size + SECTOR_SIZE - 1) // SECTOR_SIZE
            root_size_aligned = root_sectors * SECTOR_SIZE

            f.seek(root_start)
            f.write(b'\x00' * root_size_aligned)

            # ========================
            # Data Area
            # ========================
            data_start = root_start + root_size_aligned
            total_size = SECTOR_SIZE * TOTAL_SECTORS

            f.seek(data_start)
            f.write(b'\xF6' * (total_size - data_start))

    except Exception as e:
        print("full format failed:", e)

def create_raw_blank(path, tracks, heads, sectors, sector_size):
    total = tracks * heads * sectors * sector_size

    with open(path, "wb") as f:
        f.write(b'\xE5' * total)

def create_d88_from_raw(d88_path, raw_path, tracks, heads, sectors, sector_size):

    import struct

    with open(raw_path, "rb") as f:
        raw = f.read()

    expected_size = tracks * heads * sectors * sector_size

    if len(raw) != expected_size:
        print("WARNING: RAW size mismatch")
        print(f" expected={expected_size} actual={len(raw)}")

    # =========================
    # D88 Header (688 bytes)
    # =========================
    header = bytearray(688)

    disk_name = b'FMT_D88_DISK'
    header[0:16] = disk_name.ljust(16, b'\x00')

    header[0x1A] = 0x00  # writeable

    # Disk type
    if expected_size in (1232 * 1024, 1474560):
        header[0x1B] = 0x20  # 2HD
    elif expected_size in (640 * 1024, 720 * 1024):
        header[0x1B] = 0x10  # 2DD
    else:
        header[0x1B] = 0x00

    # =========================
    # Track Offsets (164 entries)
    # =========================
    offset = 688
    track_offsets = []

    track_size = sectors * (16 + sector_size)

    total_tracks = tracks * heads

    for i in range(164):
        if i < total_tracks:
            struct.pack_into("<I", header, 0x20 + i * 4, offset)
            track_offsets.append(offset)
            offset += track_size
        else:
            struct.pack_into("<I", header, 0x20 + i * 4, 0)

    # Disk size
    struct.pack_into("<I", header, 0x1C, offset)

    # =========================
    # Write D88
    # =========================
    with open(d88_path, "wb") as f:

        f.write(header)

        ptr = 0

        size_to_n = {
            128: 0,
            256: 1,
            512: 2,
            1024: 3
        }
        N = size_to_n[sector_size]

        for track in range(tracks):
            for head in range(heads):

                for sec in range(1, sectors + 1):

                    sec_header = bytearray(16)

                    sec_header[0] = track
                    sec_header[1] = head
                    sec_header[2] = sec
                    sec_header[3] = N

                    # sectors per track
                    struct.pack_into("<H", sec_header, 4, sectors)

                    # Important: Density (MFM)
                    sec_header[6] = 0x40

                    # deleted mark
                    sec_header[7] = 0x00

                    # status
                    struct.pack_into("<H", sec_header, 8, 0)

                    # reserved
                    struct.pack_into("<H", sec_header, 10, 0)
                    struct.pack_into("<H", sec_header, 12, 0)

                    # data size
                    struct.pack_into("<H", sec_header, 14, sector_size)

                    f.write(sec_header)

                    # sector data
                    sector_data = raw[ptr:ptr + sector_size]

                    if len(sector_data) < sector_size:
                        sector_data += b'\x00' * (sector_size - len(sector_data))

                    f.write(sector_data)

                    ptr += sector_size


def create_d88(path, size, mode):

    raw_path = path + ".tmp.img"

    try:
        size = DiskSize(int(size))
    except ValueError:
        raise ValueError(f"Unsupported disk size: {size}")

    if size == DiskSize.SIZE_640KB:
        tracks, heads, sectors, sector_size = 80, 2, 8, 512
    elif size == DiskSize.SIZE_720KB:
        tracks, heads, sectors, sector_size = 80, 2, 9, 512
    elif size == DiskSize.SIZE_144KB:
        tracks, heads, sectors, sector_size = 80, 2, 18, 512
    elif size == DiskSize.SIZE_123MB:
        tracks, heads, sectors, sector_size = 77, 2, 8, 1024
    else:
        raise ValueError(f"Unsupported disk size: {size}")

    # -----------------
    # RAW Generation
    # -----------------
    if mode == "blank":
        create_raw_blank(raw_path, tracks, heads, sectors, sector_size)
    else:
        format_fd_image(raw_path, size)

    # -----------------
    # D88 Conversion
    # -----------------
    create_d88_from_raw(path, raw_path, tracks, heads, sectors, sector_size)

    # -----------------
    # Cleanup
    # -----------------
    try:
        if os.path.exists(raw_path):
            os.remove(raw_path)
    except:
        pass

# =========================
# FD Creation Function (Calling side)
# =========================
def create_fd(size, label):
    # Open the File Save Dialog
    clear_runtime_log()
    file_path = filedialog.asksaveasfilename(
        defaultextension=".img",
        filetypes=[
            ("FD Images (*.img *.hdm *.bin *.d88)", "*.img *.hdm *.bin *.d88"),
            ("FD Image (*.img)", "*.img"),
            ("FD Image (*.hdm)", "*.hdm"),
            ("FD Image (*.bin)", "*.bin"),
            ("D88 Image (*.d88)", "*.d88"),
            ("All files", "*.*")
        ],
        title=f"Create {label}"
    )

    if not file_path:
        safe_update_log("FD creation cancelled")
        return

    ext = os.path.splitext(file_path)[1].lower()
    is_full = full_format_var.get()

    # =========================
    # Creating D88
    # =========================
    if ext == ".d88":
        try:
            mode = "formatted" if is_full else "blank"
            create_d88(file_path, size, mode)
            safe_update_log(f"D88 disk image ({mode}) created: {file_path}")

        except Exception as e:
            msg = f"D88 creation failed: {e}"
            safe_update_log(msg, "error")
            messagebox.showerror("Error", msg)
            return

        # Warning for D88 (displayed only once at the end)
        if size in (640 * 1024, 737280, 1232 * 1024, 1474560):
            safe_update_log("D88: MAME does not support this disk image.", "warn")

    # =========================
    # Creating Raw / Standard Image
    # =========================
    else:
        try:
            if is_full:
                # Call a general-purpose full-format function.
                apply_full_format(file_path, size)
                safe_update_log(f"Raw Disk image (formatted) created: {file_path}")

            else:
                # Blank (reliable branching using DiskSize Enum)
                try:
                    disk_size_enum = DiskSize(int(size))
                except ValueError:
                    raise ValueError(f"Unsupported disk size: {size}")

                if disk_size_enum == DiskSize.SIZE_640KB:
                    create_raw_blank(file_path, 80, 2, 8, 512)
                elif disk_size_enum == DiskSize.SIZE_720KB:
                    create_raw_blank(file_path, 80, 2, 9, 512)
                elif disk_size_enum == DiskSize.SIZE_144KB:
                    create_raw_blank(file_path, 80, 2, 18, 512)
                elif disk_size_enum == DiskSize.SIZE_123MB:
                    create_raw_blank(file_path, 77, 2, 8, 1024)
                else:
                    raise ValueError(f"Unsupported disk size: {size}")

                safe_update_log(f"Raw Disk image (blank) created: {file_path}")

        except Exception as e:
            msg = f"Disk creation failed: {e}"
            safe_update_log(msg, "error")
            messagebox.showerror("Error", msg)
            return

        # Warning for RAW (Displayed only once at the end; common to both Full and Blank)
        if size in (640 * 1024, 737280, 1474560):
            safe_update_log("RAW: MAME does not support this disk image.", "warn")

    # Completion Message
    messagebox.showinfo("Success", f"{label} image created successfully")

def create_hdd():
    clear_runtime_log() 
    try:
        mb = int(hdd_entry.get().strip())
    except ValueError:
        msg = "Please enter a valid number."
        messagebox.showerror("Error", msg)
        safe_update_log(msg, "error")
        return

    if mb < 10 or mb > 127:
        msg = "Please enter a value between 10MB to 127 MB."
        messagebox.showerror("Error", msg)
        safe_update_log(msg, "error")
        return

    size = mb * 1048576

    path = filedialog.asksaveasfilename(
        defaultextension=".h0",
        filetypes=[
            ("HDD Image (*.h0 *.h1 *.h2 *.h3 *.h4)", "*.h0 *.h1 *.h2 *.h3 *.h4"),
            ("HDD Image (*.h0)", "*.h0"),
            ("HDD Image (*.h1)", "*.h1"),
            ("HDD Image (*.h2)", "*.h2"),
            ("HDD Image (*.h3)", "*.h3"),
            ("HDD Image (*.h4)", "*.h4"),
            ("All files", "*.*")
        ]
    )

    if not path:
        safe_update_log("HDD creation cancelled")
        return

    if not os.path.splitext(path)[1]:
        path += ".h0"

    create_file(path, size)
    safe_update_log(f"HDD image ({mb} MB) created: {path}")
    messagebox.showinfo("Success", f"{mb} MB HDD image created successfully.")

def create_ic():
    clear_runtime_log() 
    size = 8388608

    path = filedialog.asksaveasfilename(
        defaultextension=".icm",
        filetypes=[("IC Card Memory Image", "*.icm")]
    )

    if not path:
        safe_update_log("IC image creation cancelled")
        return

    if not path.lower().endswith(".icm"):
        path += ".icm"

    chunk = b'\xFF' * (1024 * 1024)

    with open(path, "wb") as f:
        for _ in range(size // len(chunk)):
            f.write(chunk)
        f.write(b'\xFF' * (size % len(chunk)))

    safe_update_log(f"IC card image created: {path}")
    messagebox.showinfo("Success", "IC card memory image created successfully.")

def check_chdman():
    if not find_chdman():
        messagebox.showwarning(
            "CHD Conversion Disabled",
            "chdman was not found.\n\n"
            "The CHD conversion feature is currently disabled.\n\n"
            "Please ensure chdman.exe is placed in the same folder as this application."
        )
        return False
    return True


# ========================
# chdman detection
# ========================
def find_chdman():
    exe_dir = os.path.dirname(
        sys.executable if getattr(sys, 'frozen', False) else __file__
    )
    chdman_path = os.path.join(exe_dir, "chdman.exe")

    if os.path.exists(chdman_path):
        return chdman_path  # Return the pass
    return None

def _delete_worker(path):
    for _ in range(5):  # 5try
        try:
            time.sleep(0.5)

            if not os.path.exists(path):
                return

            if os.path.isfile(path):
                os.remove(path)
            else:
                shutil.rmtree(path)

            safe_update_log("Temporary file deleted")
            return

        except Exception:
            continue

    safe_update_log("Delete failed (retry limit)")

def safe_delete(path):
    if not path:
        return

    try:
        if not os.path.exists(path):
            safe_update_log("Nothing to delete")
            return

        threading.Thread(
            target=_delete_worker,
            args=(path,),
            daemon=True
        ).start()

    except Exception as e:
        safe_update_log(f"Delete failed ({type(e).__name__})")

def on_complete():
    messagebox.showinfo("Success", "CHD conversion completed successfully.")


# =====================================
# Common Process Termination Procedures
# =====================================
def terminate_process():
    try:
        proc = state.process
        if not proc or proc.poll() is not None:
            return

        # ===== 1. First, stop gently =====
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

        # ===== 2. Wait a moment =====
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

        # ===== 3. If you're still alive, force quit =====
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

        # ===== 4. Final Standby =====
        try:
            proc.wait(timeout=2)
        except Exception:
            pass

        # ===== 5. Close stdout (Important)=====
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass

    except Exception as e:
        print(f"terminate_process error: {e}")

def run_chd(chdman_path):
    output = getattr(state, "current_output", None)
    exit_code = None

    state.cancelled = False
    state.cancel_event.clear()

    state.progress = 0
    safe_update_progress(0)

    try:
        chdman_path = find_chdman()

        if not chdman_path or not os.path.exists(chdman_path):
            safe_update_log("chdman not found", "error")
            state.success = False
            return

        # This is important (CCD compatible)
        input_file = getattr(state, "prepared_input", state.input_file)

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW

        state.process = subprocess.Popen(
            [
                chdman_path,
                "createcd",
                "-f",
                "-i", input_file,
                "-o", state.output_file
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags
        )

        # =========================
        # stdout monitoring
        # =========================
        if state.process and state.process.stdout:
            buffer = ""

            while True:
                if state.cancel_event.is_set():
                    break

                ch = state.process.stdout.read(1)

                if not ch:
                    break

                if ch == "\r" or ch == "\n":
                    line = buffer.strip()
                    buffer = ""

                    if line:
                        safe_update_log(line)

                        # Progress Analysis (*Deduplication)
                        if "%" in line:
                            progress = extract_progress(line)
                            if progress is not None:
                                safe_update_progress(progress)
                else:
                    buffer += ch

        # ================================
        # Waiting for normal termination
        # ================================
        if state.process and not state.cancel_event.is_set():
            try:
                if state.process.poll() is None:
                    state.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                safe_update_log("Timeout waiting process")
                terminate_process()

    except Exception as e:
        safe_update_log(f"Error ({type(e).__name__}): {e}")

    finally:
        # =========================
        # Process completed
        # =========================
        terminate_process()

        if state.process:
            try:
                state.process.wait(timeout=5)
            except:
                pass

            exit_code = state.process.returncode

        # =========================
        # Result Processing
        # =========================
        if state.cancel_event.is_set():
            terminate_process()

            if output and os.path.exists(output):
                safe_delete(output)

            safe_update_log("CHD conversion cancelled")
            state.success = False

        else:
            if exit_code == 0:
                safe_update_progress(100)
                safe_update_log("CHD conversion completed")
                state.success = True
            else:
                if output and os.path.exists(output):
                    safe_delete(output)

                safe_update_log(f"CHD conversion failed (code={exit_code})")
                state.success = False

        # =========================
        # Temporary CUE deletion (CCD support)
        # =========================
        temp_cue = getattr(state, "temp_cue", None)
        if temp_cue and os.path.exists(temp_cue):
            try:
                os.remove(temp_cue)
                safe_update_log("Temporary CUE deleted")
            except Exception:
                safe_update_log("Failed to delete temp CUE", "warn")

        # =========================
        # Cleanup
        # =========================
        state.process = None
        state.is_running = False
        state.cancel_event.clear()
        state.cancelled = False
        state.temp_cue = None  # Resetting just to be safe.

        safe_enable_button()


# ========================
# Cancel button
# ========================
def cancel():
    if not state.is_running:
        return

    state.cancelled = True
    state.cancel_event.set()
    safe_update_log("Cancelling...")

    terminate_process()


# ========================
# Close Window
# ========================
def on_close():
    if state.is_closing:
        return

    if not messagebox.askokcancel("Confirm Exit", "Do you want to close the app?"):
        return

    state.is_closing = True
    root.after(0, root.quit)

    try:
        if state.process and state.process.poll() is None:
            state.process.terminate()

        state.cancel_event.set()

        if state.current_output and os.path.exists(state.current_output):
            os.remove(state.current_output)

    except Exception as e:
        print(f"close error: {e}")

    finally:
        root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)

def safe_disable_button():
    if root.winfo_exists():
        try:
            root.after(0, lambda: convert_button.config(state="disabled"))
        except Exception as e:
            print(f"button state change failed: {e}")

def safe_enable_button():
    if root.winfo_exists():
        try:
            root.after(0, lambda: convert_button.config(state="normal"))
        except Exception as e:
            print(f"button state change failed: {e}")

def generate_cue_from_ccd(ccd_path):
    base = os.path.splitext(ccd_path)[0]

    img_path = base + ".img"
    sub_path = base + ".sub"
    cue_path = base + "_temp.cue"

    if not os.path.exists(img_path):
        raise FileNotFoundError("IMG file not found")

    tracks = []
    current_track = None

    # =========================
    # CCD analysis
    # =========================
    with open(ccd_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()

            # TRACK開始
            m = re.match(r"\[TRACK (\d+)\]", line)
            if m:
                if current_track:
                    tracks.append(current_track)

                current_track = {
                    "num": int(m.group(1)),
                    "mode": None,
                    "index00": None,
                    "index01": None
                }
                continue

            if current_track is None:
                continue

            # MODE
            if line.startswith("MODE="):
                mode_val = int(line.split("=")[1])

                if mode_val == 0:
                    current_track["mode"] = "AUDIO"
                else:
                    current_track["mode"] = "MODE1/2352"

            # INDEX
            if line.startswith("INDEX 0="):
                current_track["index00"] = line.split("=")[1]

            if line.startswith("INDEX 1="):
                current_track["index01"] = line.split("=")[1]

    if current_track:
        tracks.append(current_track)

    if not tracks:
        raise RuntimeError("No tracks found in CCD")

    # =========================
    # CUE generation
    # =========================
    cue_lines = []
    cue_lines.append(f'FILE "{os.path.basename(img_path)}" BINARY')

    for t in tracks:
        cue_lines.append(f'  TRACK {t["num"]:02d} {t["mode"]}')

        if t["index00"]:
            cue_lines.append(f'    INDEX 00 {t["index00"]}')

        if t["index01"]:
            cue_lines.append(f'    INDEX 01 {t["index01"]}')
        else:
            cue_lines.append(f'    INDEX 01 00:00:00')

    with open(cue_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cue_lines))

    return cue_path

def prepare_input_file(input_path):
    ext = os.path.splitext(input_path)[1].lower()

    temp_cue = None

    if ext == ".ccd":
        safe_update_log("CCD detected → generating temporary CUE")

        try:
            temp_cue = generate_cue_from_ccd(input_path)
            return temp_cue, temp_cue  # Files in use, items to be deleted
        except Exception as e:
            safe_update_log(f"CCD conversion failed: {e}", "error")
            return None, None

    elif ext in [".cue", ".bin"]:
        return input_path, None

    else:
        safe_update_log("Unsupported file format", "error")
        return None, None

def convert_chd():
    clear_runtime_log()

    # Multiple activation prevention
    if state.is_running:
        safe_update_log("Already running")
        return

    state.is_running = True
    state.cancel_event.clear()

    chdman_path = find_chdman()

    if not chdman_path:
        safe_update_log("chdman.exe not found", "error")
        state.is_running = False
        return

    # =========================
    # Input file (CCD-compatible)
    # =========================
    state.input_file = filedialog.askopenfilename(
        filetypes=[("CUE/CCD Files", "*.cue *.ccd")]
    )

    if not state.input_file:
        safe_update_log("CHD conversion cancelled")
        state.is_running = False
        return

    prepared_input, temp_cue = prepare_input_file(state.input_file)

    if not prepared_input:
        state.is_running = False
        return

    state.prepared_input = prepared_input
    state.temp_cue = temp_cue

    # =========================
    # Output file
    # =========================
    state.output_file = filedialog.asksaveasfilename(
        defaultextension=".chd",
        filetypes=[("CHD Image", "*.chd")]
    )

    if not state.output_file:
        safe_update_log("CHD conversion cancelled")
        state.is_running = False
        return

    state.current_output = state.output_file

    # UI Control
    safe_disable_button()

    if log_text.winfo_exists():
        log_text.delete("1.0", tk.END)
        log_text.config(wrap="word")

    # Start thread
    thread = threading.Thread(
        target=run_chd,
        args=(chdman_path,),
        daemon=True
    )
    thread.start()

# ========================
# UI (Left)
# ========================
tk.Label(left_frame, text="New Image Creation", font=("Arial", 10, "bold")).pack(pady=(2, 0))

fd_buttons = [] 

for size, name in [
    (655360, "640 KB FD"),
    (737280, "720 KB FD"),
    (1261568, "1.23 MB FD"),
    (1474560, "1.44 MB FD")
]:
    btn = ttk.Button(
        left_frame,
        text=name,
        width=16,
        style="Modern.TButton",
        command=lambda s=size, n=name: create_fd(s, n)
    )
    btn.pack(pady=4)

    fd_buttons.append((btn, size)) 


# ========================
# Full Format
# ========================
full_format_var = tk.BooleanVar(value=False)

full_frame = tk.Frame(left_frame)
# Set the top padding to 0 and the bottom padding to 12
full_frame.pack(pady=(0, 12)) 

tk.Checkbutton(
    full_frame,
    text="Full Format",
    variable=full_format_var
).pack(side="left")

# ========================
# HDD Create
# ========================
ttk.Button(left_frame, text="HDD", width=16,
           style="Modern.TButton",
           command=create_hdd).pack(pady=(2, 4))

hdd_frame = tk.Frame(left_frame)
hdd_frame.pack(pady=3)

hdd_entry = tk.Entry(hdd_frame, width=4, justify="center")
hdd_entry.pack(side="left")
hdd_entry.insert(0, "40")

tk.Label(hdd_frame, text="MB").pack(side="left", padx=3)

# ========================
# IC Card Create
# ========================
ttk.Button(left_frame, text="IC Card", width=16,
           style="Modern.TButton",
           command=create_ic).pack(pady=(16, 4))

ttk.Separator(left_frame, orient="horizontal").pack(fill="x", pady=(10, 6))

# ========================
# CHD Conversion
# ========================
tk.Label(left_frame, text="CHD Conversion", font=("Arial", 10, "bold")).pack(pady=(5, 0))

convert_button = ttk.Button(
    left_frame,
    text="Start Conversion",
    width=16,
    style="Accent.TButton",
    command=convert_chd
)
convert_button.pack(pady=6)

ttk.Button(left_frame, text="Cancel", width=12,
           style="Modern.TButton",
           command=cancel).pack(pady=2)

# ========================
# Log Functions
# ========================

# It holds 50 lines internally.
log_lines = deque(maxlen=50)

def prepare_log_text(text, width=65):
    """Wrap long logs at word boundaries."""
    lines = text.splitlines()
    formatted_lines = []
    for line in lines:
        if len(line) > width:
            formatted_lines.append(textwrap.fill(line, width=width))
        else:
            formatted_lines.append(line)
    return "\n".join(formatted_lines)


def _update_log_ui(text, tag=None):
    try:
        if not log_text.winfo_exists():
            return

        # --- Pre-processing ---
        if text:
            text = text.replace("\r\n", "\n").replace("\r", "")
            text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
            text = prepare_log_text(text, width=65)
            text = text.rstrip("\n")

        if not text or not text.strip():
            return

        if tag is None:
            tag = "info"

        # --- Log storage (max. 50 lines)---
        log_lines.append((text, tag))

        # --- UI update ---
        log_text.configure(state="normal")
        log_text.delete("1.0", tk.END)

        log_text.configure(wrap="word")

        # Tag Settings
        log_text.tag_configure("default", justify="left")
        log_text.tag_configure("error", justify="left", foreground="red")
        log_text.tag_configure("warn", justify="left", foreground="yellow")

        # --- Display only the last three lines. ---
        display_lines = list(log_lines)[-3:]

        total = len(display_lines)
        for i, (line, line_tag) in enumerate(display_lines):
            clean_line = line.rstrip("\n")
            suffix = "" if i == total - 1 else "\n"
            current_tag = line_tag if line_tag in ["error", "warn"] else "default"
            log_text.insert(tk.END, clean_line + suffix, current_tag)

        # Scroll & Draw
        log_text.update_idletasks()
        log_text.see(tk.END)
        log_text.xview_moveto(0)
        log_text.configure(state="disabled")

    except Exception as e:
        print(f"log update failed: {e}")


def safe_update_log(text, level="info"):
    if state.is_closing:
        return

    prefix = ""
    if level == "error":
        prefix = "[ERROR] "
    elif level == "warn":
        prefix = "[WARN] "

    text = f"{prefix}{text.replace(chr(13), '').rstrip(chr(10))}"
    root.after(0, _update_log_ui, text, level)


def clear_runtime_log():
    if root.winfo_exists():
        root.after(0, _clear_log_ui)


def _clear_log_ui():
    try:
        log_lines.clear()
        log_text.configure(state="normal")
        log_text.delete("1.0", tk.END)
        log_text.configure(state="disabled")
    except Exception:
        pass

def show_cmd_preview(cmd):
    try:
        clear_runtime_log()

        # Split the command into individual options.
        parts = cmd.split(" -")

        for i, part in enumerate(parts):
            line = part if i == 0 else "-" + part
            safe_update_log(line.rstrip("\r\n"), "info")

    except Exception as e:
        print(f"cmd preview failed: {e}")

def startup_check():
    if not find_chdman():
        convert_button.config(state="disabled")

        safe_update_log(
            "chdman not found. Conversion is disabled.",
            "error"
        )

        messagebox.showwarning(
            "CHD Conversion Disabled",
            "chdman was not found.\n\n"
            "CHD conversion feature will be disabled.\n\n"
            "Please chdman.exe in the same folder."
        )


# ==========================
# ===== CMD Creator ========
# ==========================

cmd_bios = tk.StringVar(value="fmtowns")
cmd_memory = tk.StringVar(value="2")

cmd_fd1 = None
cmd_fd2 = None
cmd_chd = None
cmd_hdd = None
cmd_ic = None

def get_name(path):
    return os.path.basename(path)

def cmdmaker_select_fd1():
    global cmd_fd1
    clear_runtime_log()

    # Filter Settings: Allow only specified file extensions
    file_types = [("Image files", "*.img *.hdm *.bin *.d88"), ("All files", "*.*")]
    path = filedialog.askopenfilename(initialdir=last_dir, filetypes=file_types)

    if not path:
        safe_update_log("FD1 selection cancelled")
        return

    cmd_fd1 = path
    label_fd1.config(text=get_name(path))
    update_last_dir(path)
    safe_update_log(f"[MOUNT] FD1 : {path}")
    update_all_eject_buttons() 

def cmdmaker_select_fd2():
    global cmd_fd2
    clear_runtime_log()

    bios = cmd_bios.get()

    if bios in ["fmtmarty", "fmtmarty2", "carmarty"]:
        msg = "This model supports only a single drive."
        messagebox.showerror("Error", msg)
        safe_update_log(msg, "error")
        return

    # Filter Settings: Allow only specified file extensions
    file_types = [("Image files", "*.img *.hdm *.bin *.d88"), ("All files", "*.*")]
    path = filedialog.askopenfilename(initialdir=last_dir, filetypes=file_types)

    if not path:
        safe_update_log("FD2 selection cancelled")
        return

    cmd_fd2 = path
    label_fd2.config(text=get_name(path))
    update_last_dir(path)
    safe_update_log(f"[MOUNT] FD2 : {path}")
    update_all_eject_buttons()

def cmdmaker_select_chd():
    global cmd_chd
    clear_runtime_log()

    path = filedialog.askopenfilename(
        initialdir=last_dir,
        filetypes=[("CHD", "*.chd")]
    )

    if not path:
        safe_update_log("CHD selection cancelled")
        return

    cmd_chd = path
    label_chd.config(text=get_name(path))
    update_last_dir(path)
    safe_update_log(f"[MOUNT] CHD : {path}")
    update_all_eject_buttons()

def cmdmaker_select_hdd():
    global cmd_hdd
    clear_runtime_log()

    bios = cmd_bios.get()

    if bios in ["fmtmarty", "fmtmarty2", "carmarty"]:
        msg = "This model does not support hard drives."
        messagebox.showerror("Error", msg)
        safe_update_log(msg, "error")
        return

    # Set h0 through h4 as allowed, and make “All files” selectable
    file_types = [
        ("HDD Images", "*.h0 *.h1 *.h2 *.h3 *.h4"),
        ("All files", "*.*")
    ]
    
    path = filedialog.askopenfilename(
        initialdir=last_dir,
        filetypes=file_types
    )

    if not path:
        safe_update_log("HDD selection cancelled")
        return

    cmd_hdd = path
    label_hdd.config(text=get_name(path))
    update_last_dir(path)
    safe_update_log(f"[MOUNT] HDD : {path}")
    update_all_eject_buttons()

def cmdmaker_select_ic():
    global cmd_ic
    clear_runtime_log()

    path = filedialog.askopenfilename(
        initialdir=last_dir,
        filetypes=[("IC", "*.icm")]
    )

    if not path:
        safe_update_log("IC selection cancelled")
        return

    cmd_ic = path
    label_ic.config(text=get_name(path))
    update_last_dir(path)
    safe_update_log(f"[MOUNT] IC  : {path}")
    update_all_eject_buttons()


# =========================
# Unmount Process
# =========================
def cmdmaker_unmount_fd1():
    global cmd_fd1
    clear_runtime_log()
    cmd_fd1 = ""
    label_fd1.config(text="(No media)")
    safe_update_log("FD1 unmounted")

    update_all_eject_buttons()

def cmdmaker_unmount_fd2():
    global cmd_fd2
    clear_runtime_log()
    cmd_fd2 = ""
    label_fd2.config(text="(No media)")
    safe_update_log("FD2 unmounted")

    update_all_eject_buttons()

def cmdmaker_unmount_chd():
    global cmd_chd
    clear_runtime_log()
    cmd_chd = ""
    label_chd.config(text="(No media)")
    safe_update_log("CHD unmounted")

    update_all_eject_buttons()

def cmdmaker_unmount_hdd():
    global cmd_hdd
    clear_runtime_log()
    cmd_hdd = ""
    label_hdd.config(text="(No media)")
    safe_update_log("HDD unmounted")

    update_all_eject_buttons()

def cmdmaker_unmount_ic():
    global cmd_ic
    clear_runtime_log()
    cmd_ic = ""
    label_ic.config(text="(No media)")
    safe_update_log("IC unmounted")

    update_all_eject_buttons()

def on_machine_change(event):
    global cmd_hdd, cmd_fd2

    bios = cmd_bios.get()

    if bios in ["fmtowns", "fmtmarty", "fmtmarty2", "carmarty"]:
        cmd_hdd = None
        label_hdd.config(text="(No media)")

    if bios in ["fmtmarty", "fmtmarty2", "carmarty"]:
        cmd_fd2 = None
        label_fd2.config(text="(No media)")

def cmdmaker_build_command():
    try:
        mem = int(cmd_memory.get())
        if mem < 1 or mem > 99:
            raise ValueError
    except ValueError:
        msg = "Please enter a value between 1MB to 99MB."
        messagebox.showerror("Error", msg)
        safe_update_log(msg, "error")
        return None

    cmd = f'{cmd_bios.get()} -ramsize {mem}m'

    if cmd_fd1:
        cmd += f' -flop1 "{get_name(cmd_fd1)}"'
    if cmd_fd2:
        cmd += f' -flop2 "{get_name(cmd_fd2)}"'
    if cmd_chd:
        cmd += f' -cdrm "{get_name(cmd_chd)}"'
    if cmd_hdd:
        cmd += f' -hard1 "{get_name(cmd_hdd)}"'
    if cmd_ic:
        cmd += f' -memc "{get_name(cmd_ic)}"'

    return cmd

def cmdmaker_clear():
    global cmd_fd1, cmd_fd2, cmd_chd, cmd_hdd, cmd_ic

    cmd_fd1 = None
    cmd_fd2 = None
    cmd_chd = None
    cmd_hdd = None
    cmd_ic = None

    label_fd1.config(text="(No media)")
    label_fd2.config(text="(No media)")
    label_chd.config(text="(No media)")
    label_hdd.config(text="(No media)")
    label_ic.config(text="(No media)")
    update_all_eject_buttons()

def update_all_eject_buttons():
    btn_un_fd1.config(state="normal" if cmd_fd1 else "disabled")
    btn_un_fd2.config(state="normal" if cmd_fd2 else "disabled")
    btn_un_chd.config(state="normal" if cmd_chd else "disabled")
    btn_un_hdd.config(state="normal" if cmd_hdd else "disabled")
    btn_un_ic.config(state="normal" if cmd_ic else "disabled")

def cmdmaker_save():
    global last_dir

    # First, build the input data
    cmd = cmdmaker_build_command()
    if not cmd:
        return

    # Clear the log before starting processing
    clear_runtime_log()

    # Confirmation Dialog
    root.update_idletasks()
    if not messagebox.askokcancel("Confirm", cmd):
        safe_update_log("CMD creation cancelled")
        return

    path = filedialog.asksaveasfilename(
        defaultextension=".cmd",
        filetypes=[("cmd file", "*.cmd")],
        initialdir=last_dir
    )

    if not path:
        safe_update_log("CMD creation cancelled")
        return

    # File-Saving Process
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(cmd)

        last_dir = os.path.dirname(path)
        config["last_dir"] = last_dir
        save_config(config)

        # Display results in the log (use `safe_update_log` to standardize status management)
        safe_update_log("CMD file saved successfully:")
        safe_update_log(cmd) # Even if there are multiple lines, they will be displayed as long as they fit within the `deque`'s `maxlen=3`.

        messagebox.showinfo("Success", "CMD file saved.")

        # Reset Process
        cmdmaker_clear()
        cmd_bios.set("fmtowns")
        cmd_memory.set("2")
        on_machine_change(None)

    except Exception as e:
        safe_update_log(f"Failed to save: {e}", "error")
        messagebox.showerror("Error", f"Could not save file: {e}")


# ========================
# UI (Right)
# ========================
tk.Label(right_frame, text="System Model", font=("Arial", 10, "bold")).pack(pady=(2, 4))

# Modify the code to store the combo box in a variable
machine_combo = ttk.Combobox(
    right_frame,
    textvariable=cmd_bios,
    values=[
        "fmtowns","fmtownsux","fmtownshr","fmtownsftv",
        "fmtownsmx","fmtmarty","fmtmarty2","carmarty"
    ],
    state="readonly",
    width=16
)
machine_combo.pack(pady=0)

machine_combo.bind("<<ComboboxSelected>>", on_machine_change)


tk.Label(right_frame, text="RAM Size", font=("Arial", 10, "bold")).pack(pady=2)

mem_frame = tk.Frame(right_frame)
mem_frame.pack(pady=(0, 6))

tk.Entry(mem_frame, textvariable=cmd_memory, width=4, justify="center").pack(side="left")
tk.Label(mem_frame, text="MB").pack(side="left", padx=5)

def make_btn(text, cmd):
    return ttk.Button(
        right_frame,
        text=text,
        width=14,
        style="Modern.TButton",
        command=cmd
    )

def make_unmount_btn(cmd):
    return ttk.Button(
        right_frame,
        text="⏏",
        width=3,
        style="Modern.TButton",
        command=cmd
    )


tk.Label(
    right_frame,
    text="Disk Images",
    font=("Arial", 10, "bold")
).pack(pady=(2, 0))

media_frame = tk.Frame(
    right_frame,
    padx=4,
    pady=4
)
media_frame.pack(padx=2, pady=(2, 0))

# First, create a `log_frame` under the `root` directory and pack it.
log_frame = tk.Frame(root, bg="black")
log_frame.pack(side="bottom", fill="x", padx=10, pady=(5, 10))

log_text = tk.Text(log_frame, height=3, bg="black", fg="#00FF00", 
                   bd=0, highlightthickness=0, 
                   font=("Consolas", 8), 
                   wrap="word")

# Disable frame width restriction (make it follow the parent frame)
log_text.config(width=1)
log_text.pack(fill="both", expand=True)

log_text.tag_configure("info", foreground="#00FF00", justify="left")
log_text.tag_configure("error", foreground="red", justify="left")
log_text.tag_configure("warn", foreground="yellow", justify="left")

# Then create the `inner_frame`
inner_frame = tk.Frame(media_frame, padx=4)
inner_frame.pack()


# ========================
# FD1
# ========================
row_fd1 = tk.Frame(inner_frame)
row_fd1.pack(fill="x", pady=1)

# Frame for Center Alignment
center_fd1 = tk.Frame(row_fd1)
center_fd1.pack()

btn_fd1 = make_btn("FD 1", cmdmaker_select_fd1)
btn_fd1.pack(in_=center_fd1, side="left", padx=(0, 6))

btn_un_fd1 = make_unmount_btn(cmdmaker_unmount_fd1)
btn_un_fd1.pack(in_=center_fd1, side="left")
btn_un_fd1.config(state="disabled")

label_fd1 = tk.Label(inner_frame, text="(No media)", anchor="center")
label_fd1.pack(fill="x")

# ========================
# FD2
# ========================
row_fd2 = tk.Frame(inner_frame)
row_fd2.pack(fill="x", pady=1)

center_fd2 = tk.Frame(row_fd2)
center_fd2.pack()

btn_fd2 = make_btn("FD 2", cmdmaker_select_fd2)
btn_fd2.pack(in_=center_fd2, side="left", padx=(0, 6))

btn_un_fd2 = make_unmount_btn(cmdmaker_unmount_fd2)
btn_un_fd2.pack(in_=center_fd2, side="left")
btn_un_fd2.config(state="disabled")

label_fd2 = tk.Label(inner_frame, text="(No media)", anchor="center")
label_fd2.pack(fill="x")

# ========================
# CHD
# ========================
row_chd = tk.Frame(inner_frame)
row_chd.pack(fill="x", pady=1)

center_chd = tk.Frame(row_chd)
center_chd.pack()

btn_chd = make_btn("CD (CHD)", cmdmaker_select_chd)
btn_chd.pack(in_=center_chd, side="left", padx=(0, 6))

btn_un_chd = make_unmount_btn(cmdmaker_unmount_chd)
btn_un_chd.pack(in_=center_chd, side="left")
btn_un_chd.config(state="disabled")

label_chd = tk.Label(inner_frame, text="(No media)", anchor="center")
label_chd.pack(fill="x")

# ========================
# HDD
# ========================
row_hdd = tk.Frame(inner_frame)
row_hdd.pack(fill="x", pady=1)

center_hdd = tk.Frame(row_hdd)
center_hdd.pack()

btn_hdd = make_btn("HDD", cmdmaker_select_hdd)
btn_hdd.pack(in_=center_hdd, side="left", padx=(0, 6))

btn_un_hdd = make_unmount_btn(cmdmaker_unmount_hdd)
btn_un_hdd.pack(in_=center_hdd, side="left")
btn_un_hdd.config(state="disabled")

label_hdd = tk.Label(inner_frame, text="(No media)", anchor="center")
label_hdd.pack(fill="x")

# ========================
# IC
# ========================
row_ic = tk.Frame(inner_frame)
row_ic.pack(fill="x", pady=1)

center_ic = tk.Frame(row_ic)
center_ic.pack()

btn_ic = make_btn("IC Card", cmdmaker_select_ic)
btn_ic.pack(in_=center_ic, side="left", padx=(0, 6))

btn_un_ic = make_unmount_btn(cmdmaker_unmount_ic)
btn_un_ic.pack(in_=center_ic, side="left")
btn_un_ic.config(state="disabled")

label_ic = tk.Label(inner_frame, text="(No media)", anchor="center")
label_ic.pack(fill="x")

# ========================
# Progress
# ========================
progress_bar.pack(fill="x", padx=10, pady=0)

ttk.Button(
    right_frame,
    text="Create .cmd File",
    width=16,
    style="Accent.TButton",
    command=cmdmaker_save
).pack(pady=0)

root.after(100, lambda: safe_update_log("FMT Emulation Toolkit Initialized."))
root.after(200, startup_check)

root.update_idletasks()
root.mainloop()