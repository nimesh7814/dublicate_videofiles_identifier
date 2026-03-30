# 🎬 Video Duplicate Manager

A fast, dark-themed desktop app for **Windows** that finds and removes duplicate video files across all subfolders — with fuzzy name matching, resolution gating, and Recycle Bin support.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![GUI](https://img.shields.io/badge/GUI-tkinter-informational)

---

## ✨ Features

- 🔍 **Fuzzy name matching** — catches `holiday.mp4`, `Holiday_Trip (1).mp4`, and `holiday-FINAL.mp4` as duplicates
- 📐 **Resolution gating** — same name + same size but different resolution = treated as separate files, not duplicates
- 📂 **Deep subfolder scanning** — recursively walks every subfolder under your chosen root
- ☑️ **Checkbox selection** per file — tick exactly what you want deleted
- ⚡ **Auto-select Copies** — automatically ticks every file with a Windows copy-suffix (`(1)`, `_2`, etc.), leaving originals untouched
- 🗑️ **Recycle Bin support** — deletes via `send2trash` so nothing is gone for good (falls back to permanent delete if not installed)
- 📊 **Rich metadata display** — resolution, codec, format, duration per file (powered by ffprobe)
- 🎚️ **Adjustable similarity slider** — tune how aggressively fuzzy matching works (50% – 100%)
- 🧵 **Threaded scanning** — UI stays responsive while scanning large folders
- 🏷️ **ORIGINAL / COPY badges** — clear visual labelling of which file came first

---

## 🖥️ Screenshot

> _Dark theme, grouped duplicate view with metadata chips and per-group actions._

---

## 📋 Requirements

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.8+ | tkinter is built-in on Windows |
| ffmpeg / ffprobe | any | For resolution, codec, duration metadata |
| send2trash | any | Optional — enables Recycle Bin delete |

---

## 🚀 Installation

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/video-duplicate-manager.git
cd video-duplicate-manager
```

### 2. Install ffmpeg (for video metadata)

```bash
winget install ffmpeg
```

Or download manually from [ffmpeg.org](https://ffmpeg.org/download.html) and add it to your PATH.

### 3. Install optional Python dependency

```bash
pip install send2trash
```

> Without `send2trash`, deleted files are **permanently removed**. With it, they go to the Recycle Bin.

### 4. Run

```bash
python video_duplicate_manager.py
```

---

## 🛠️ How It Works

Duplicate detection runs in three passes:

```
Pass 1 — Bucket all video files by file size
           (fast pre-filter: different sizes = definitely not duplicates)

Pass 2 — Within each size bucket, group files by fuzzy name similarity
           Names are normalised: separators collapsed, noise words stripped
           (hd, sd, 4k, 1080p, copy, final, edit, v2, part1, etc.)
           SequenceMatcher ratio ≥ threshold (default 72%) = same group

Pass 3 — After reading metadata, split any group where files differ in resolution
           1920x1080 and 1280x720 versions stay as separate groups
```

### Supported video formats

`.mp4` `.mkv` `.avi` `.mov` `.wmv` `.flv` `.webm` `.m4v` `.mpg` `.mpeg` `.ts` `.mts` `.m2ts` `.3gp` `.ogv` `.divx` `.xvid` `.rm` `.rmvb` `.vob` `.f4v`

---

## 🎮 Usage

1. **Launch** the app with `python video_duplicate_manager.py`
2. Click **"Choose Folder"** (top-right) and select your root folder
3. Wait for the scan + metadata pass to complete
4. Review the duplicate groups — each shows file name, folder, size, resolution, codec, duration
5. Use **"Auto-select ALL Copies"** to tick all copy-suffix files automatically, or tick manually
6. Click **"Delete ALL Checked"** (or the per-group delete button) — confirm the dialog
7. Done ✅

### Similarity slider

The **Name similarity** slider (top toolbar) controls how loosely names are matched:

| Setting | Behaviour |
|---|---|
| **100%** | Exact base name only (`movie.mp4` = `movie (1).mp4`) |
| **72%** (default) | Catches common variations (`Holiday Trip` ≈ `Holiday-Trip-FINAL`) |
| **50%** | Very aggressive — may produce false positives |

Adjust before scanning. The scan always uses whatever value the slider is set to.

---

## 🗂️ Project Structure

```
video-duplicate-manager/
├── video_duplicate_manager.py   # Main application (single file)
├── README.md
└── cleanup.bat                  # Optional: empty Recycle Bin + clear Explorer history
```

---

## 🧹 Bonus: cleanup.bat

Included `cleanup.bat` empties the Recycle Bin, clears Windows File Explorer search history, and clears the Recent Files list. Run it as Administrator.

---

## ⚙️ Configuration (in-code)

| Constant | Default | Description |
|---|---|---|
| `SIMILARITY_THRESHOLD` | `0.72` | Default fuzzy match ratio |
| `VIDEO_EXT` | 18 formats | Set of file extensions scanned |

---

## 🤝 Contributing

Pull requests welcome. For major changes please open an issue first.

1. Fork the repo
2. Create your branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

---

## 📄 License

MIT — free to use, modify, and distribute.
