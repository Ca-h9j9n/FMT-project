# FMT Emulation Toolkit 1.00

A toolkit for **FM TOWNS** that generates files for use with emulators such as MAME and RetroArch (MAME/MESS cores).
* compatible with 64-bit versions of Windows 10 and 11

---

## Disk Image Utility

Create various types of disk images.

### New Image Creation

Click the button for the disk image you want to create.

### Floppy Disk Images (640 KB / 720 KB / 1.23 MB / 1.44 MB)

* Creates blank floppy disk images
* Default extension: `.img`
* Supported formats: `RAW` (`.img`, `.hdm`, `.bin`) and `.d88`
* To create a formatted disk image, please check the Full Format box
* Click an [FD] button, then choose the destination and file name

**IMPORTANT**
Of the disk images this software creates, MAME can mount only the 1.23MB RAW format.
(Some special formats may fail to mount.)
D88 images created with this tool are not compatible with MAME.

---

### Hard Drive (HDD)

* Creates hard drive images (10–127 MB, default: 40 MB)
* Default extension: `.h0` (`.h1`–`.h4` also available)
* Click Left ”HDD” and select a save location

---

### IC Card (IC Memory Card)

* Creates an 8 MB PCMCIA SRAM Card image
* Extension: `.icm`
* Click Left "IC Card" and select a save location

---

### CHD Conversion

* Click **Start Conversion**, select a `.cue` file, and choose an output location
* Converts .bin/`.cue` and `.ccd` CD images to the CHD format
* Requires `chdman.exe` in the same folder

**IMPORTANT**
If `chdman.exe` is missing, this feature will be disabled.
It is included in official MAME distributions.

* Progress is shown via progress bar and log
* Can be cancelled (partial files will be deleted automatically)

---

## CMD File Generator

Create `.cmd` files to launch FM TOWNS games in MAME / RetroArch.

### System Model

* Select the FM TOWNS BIOS
* Some unofficial BIOS may work if renamed to `fmtowns.zip`
* Marty systems do NOT support HDD or a second floppy drive

### RAM Size

* Default: 2 MB
* Recommended: 2–8 MB

### Disk Images

Assign images to each drive:

* `FD1` / `FD2` / `CD (CHD)` / `HDD` / `IC Card`

**IMPORTANT**

* CD-ROM images must be converted to CHD
* HDD requires enabling the drive in Towns system software
* IC Card requires driver loading at OS startup

### Generate CMD

* Creates a `.cmd` file after configuration
* A preview dialog will appear before saving

Example:

```bash
fmtownshr -ramsize 4m -flop1 "fd1.img" -flop2 "fd2.img" -cdrm "cd.chd" -hard1 "hdd.h0" -memc "ic.icm"
```

* Filenames are wrapped in quotes to support spaces
* CMD files are portable across OS (Windows / Linux / Android)
* Media changes must be done from the MAME menu (not RetroArch)

**IMPORTANT**
Place BIOS, disk images, and CMD file in the SAME folder.

---

## Log Window

* Green: Information / Success
* Yellow: Warnings (unsupported features, etc.)
* Red: Errors (missing chdman.exe, invalid input size, etc.)

---

## Build

pyinstaller --noupx --onefile --noconsole --clean --icon=fmt.ico --add-data "fmt.png;." -w FMT_Emulation_Toolkit.py

---

## Notes

This software is a Python-based rebuild of CMDMaker and BDMaker, originally developed in HSP.
AI was used during development.

---

## Author

Ca
YouTube: https://www.youtube.com/channel/UCBkaMScCzCRX_uOEeChVwdQ
