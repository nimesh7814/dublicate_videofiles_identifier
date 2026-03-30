#!/usr/bin/env python3
"""
Video Duplicate Manager  —  Windows Edition
============================================
Finds duplicate video files ACROSS ALL SUBFOLDERS by matching:
  • Similar canonical base name (fuzzy match, stripping copy-suffixes)  AND same file size
  • AND same resolution (once metadata is read)

Features
--------
  • Checkbox per file — tick any files you want deleted
  • "Auto-select Copies" — auto-ticks every file that has a copy-suffix, leaving originals
  • "Delete All Checked" — deletes every ticked file at once (with confirmation)
  • Per-group delete button as well
  • Clean table layout: file name, folder, size, resolution, format, codec, duration
  • Fuzzy name similarity — catches "holiday", "Holiday_trip", "holiday-2024" as duplicates
  • Resolution included in duplicate key — same name+size but different res = NOT duplicates

Requirements
------------
  Python 3.8+   (tkinter built-in on Windows)
  ffmpeg        winget install ffmpeg
  send2trash    pip install send2trash   (Recycle Bin support — recommended)

Run
---
  python video_duplicate_manager.py
"""

import os, re, sys, json, ctypes, subprocess, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple

# ── Optional: Recycle Bin support ────────────────────────────────────────────
try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False

# ── Windows DPI awareness ─────────────────────────────────────────────────────
if sys.platform == "win32":
    try:    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try: ctypes.windll.user32.SetProcessDPIAware()
        except Exception: pass

# =============================================================================
# 1. DUPLICATE DETECTION
# =============================================================================

COPY_SUFFIX_RE = re.compile(r'(?:\s*\(\d+\)|_\d+)$')

# Separators / noise tokens to strip when normalising names for fuzzy comparison
_SEP_RE    = re.compile(r'[\s\-_\.]+')
_NOISE_RE  = re.compile(r'\b(hd|sd|fhd|uhd|4k|2k|720p|1080p|2160p|480p|copy|final|edit|v\d+|part\d+)\b', re.I)

VIDEO_EXT = {
    '.mp4','.mkv','.avi','.mov','.wmv','.flv','.webm','.m4v',
    '.mpg','.mpeg','.ts','.mts','.m2ts','.3gp','.ogv',
    '.divx','.xvid','.rm','.rmvb','.vob','.f4v',
}

# Similarity threshold — 0.0 (any) … 1.0 (exact).  0.72 works well in practice.
SIMILARITY_THRESHOLD = 0.72


def _norm(p: str) -> str:
    return str(Path(p).resolve())


def _stem_base(filename: str) -> str:
    """'holiday (2).mp4' -> 'holiday',  'clip_5.mkv' -> 'clip'"""
    return COPY_SUFFIX_RE.sub('', Path(filename).stem).strip()


def _normalise_for_similarity(name: str) -> str:
    """
    Lower-case, strip copy-suffixes, collapse separators, remove noise tokens.
    'Holiday - Trip_2 (FINAL) 1080p' -> 'holidaytrip'
    """
    base = _stem_base(name)
    base = _NOISE_RE.sub('', base)
    base = _SEP_RE.sub('', base)
    return base.lower().strip()


def _similarity(a: str, b: str) -> float:
    """
    Normalised edit-distance similarity in [0, 1].
    Uses the built-in difflib SequenceMatcher — no extra deps needed.
    """
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def is_copy(filename: str) -> bool:
    return bool(COPY_SUFFIX_RE.search(Path(filename).stem))


# ---------------------------------------------------------------------------
# Two-pass scan
#   Pass 1 — group by EXACT (base_lower, size)   → guaranteed duplicates
#   Pass 2 — within same-size buckets, merge groups whose normalised names
#             are similar enough                  → fuzzy duplicates
#   Pass 3 — after metadata is available, split any merged group whose
#             members differ in resolution        → resolution gate
# ---------------------------------------------------------------------------

def scan_for_duplicates(
    root_dir: str,
    progress_cb: Optional[Callable] = None,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> List[List[Dict]]:
    """
    Walk root_dir recursively (all subfolders).

    Duplicate criteria:
      1. Same file size  (fast pre-filter)
      2. Similar base name  (fuzzy, SIMILARITY_THRESHOLD)
      Resolution is checked *after* metadata enrichment — see split_by_resolution().

    Returns list-of-groups sorted: originals first then copies within each group.
    """
    # ── Pass 1: bucket by size ────────────────────────────────────────────────
    by_size: Dict[int, List[Dict]] = defaultdict(list)

    all_files: List[str] = []
    for dirpath, _, fnames in os.walk(root_dir):
        for fn in fnames:
            if Path(fn).suffix.lower() in VIDEO_EXT:
                all_files.append(os.path.join(dirpath, fn))

    total = len(all_files)
    for i, fp in enumerate(all_files, 1):
        if progress_cb:
            progress_cb(i, total, fp)
        try:
            size = os.path.getsize(fp)
        except OSError:
            continue
        fn = os.path.basename(fp)
        by_size[size].append({
            'path':     _norm(fp),
            'filename': fn,
            'size':     size,
            '_norm':    _normalise_for_similarity(fn),   # cached, removed later
        })

    # ── Pass 2: within each size-bucket, group by fuzzy name similarity ───────
    groups: List[List[Dict]] = []

    for size, files in by_size.items():
        if len(files) < 2:
            continue
        # Union-Find to merge similar names inside the same size bucket
        parent = list(range(len(files)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                sim = _similarity(files[i]['_norm'], files[j]['_norm'])
                if sim >= similarity_threshold:
                    union(i, j)

        clustered: Dict[int, List[Dict]] = defaultdict(list)
        for idx, f in enumerate(files):
            clustered[find(idx)].append(f)

        for cluster in clustered.values():
            if len(cluster) < 2:
                continue
            # Strip the internal helper key
            for f in cluster:
                f.pop('_norm', None)
            # Sort: originals first, then copies, then alphabetically
            cluster.sort(key=lambda f: (is_copy(f['filename']), f['filename'].lower()))
            groups.append(cluster)

    # Clean up _norm from any single-file buckets that passed through
    groups.sort(key=lambda g: _stem_base(g[0]['filename']).lower())
    return groups


def split_by_resolution(groups: List[List[Dict]]) -> List[List[Dict]]:
    """
    After metadata enrichment, split any group that contains files with
    DIFFERENT resolutions — same name + same size but different res means
    they are NOT the same video.

    Groups where ALL members share the same resolution (or all are 'Unknown')
    are kept as-is.
    """
    result: List[List[Dict]] = []
    for group in groups:
        by_res: Dict[str, List[Dict]] = defaultdict(list)
        for f in group:
            res = f.get('resolution', 'Unknown')
            by_res[res].append(f)

        if len(by_res) == 1:
            # All same resolution — keep the group intact
            result.append(group)
        else:
            # Split into per-resolution sub-groups; only keep those with 2+ files
            for res, subgroup in by_res.items():
                if len(subgroup) >= 2:
                    result.append(subgroup)
            # If splitting left nothing with 2+ files, drop entirely

    result.sort(key=lambda g: _stem_base(g[0]['filename']).lower())
    return result


# =============================================================================
# 2. VIDEO METADATA
# =============================================================================

def _find_ffprobe() -> Optional[str]:
    pf = os.environ.get('ProgramFiles', r'C:\Program Files')
    for cmd in ['ffprobe', 'ffprobe.exe',
                os.path.join(pf, 'ffmpeg', 'bin', 'ffprobe.exe'),
                r'C:\ffmpeg\bin\ffprobe.exe']:
        try:
            kw = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
            r  = subprocess.run([cmd, '-version'], capture_output=True, timeout=5, **kw)
            if r.returncode == 0:
                return cmd
        except Exception:
            continue
    return None

FFPROBE = _find_ffprobe()

def get_video_info(path: str) -> Dict:
    fallback = {'resolution':'Unknown','codec':'Unknown',
                'format': Path(path).suffix.upper().lstrip('.'),'duration':'--:--'}
    if not FFPROBE:
        return fallback
    try:
        kw = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        r  = subprocess.run(
            [FFPROBE,'-v','quiet','-print_format','json','-show_streams','-show_format', path],
            capture_output=True, text=True, timeout=20, **kw)
        d  = json.loads(r.stdout)
        fmt = d.get('format', {})
        vs  = next((s for s in d.get('streams',[]) if s.get('codec_type')=='video'), {})
        w, h = vs.get('width',0), vs.get('height',0)
        dur  = float(fmt.get('duration', 0) or 0)
        m, s = divmod(int(dur), 60)
        hh, m = divmod(m, 60)
        return {
            'resolution': f"{w}x{h}" if w and h else 'Unknown',
            'codec':      vs.get('codec_name','Unknown').upper(),
            'format':     fmt.get('format_long_name', fallback['format'])
                            .replace('QuickTime / MOV','MOV')
                            .replace('Matroska / WebM','MKV'),
            'duration':   f"{hh:02d}:{m:02d}:{s:02d}" if hh else f"{m:02d}:{s:02d}",
        }
    except Exception:
        return fallback

def enrich(group: List[Dict]) -> List[Dict]:
    return [{**f, **get_video_info(f['path'])} for f in group]

def human_size(b: int) -> str:
    for u in ('B','KB','MB','GB','TB'):
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"


# =============================================================================
# 3. COLOUR / FONT TOKENS
# =============================================================================

BG       = "#0f1117"
PANEL    = "#16181f"
HDR      = "#1e2130"
ROW_A    = "#1a1d28"
ROW_B    = "#161925"
ROW_SEL  = "#1e2d1e"
ACCENT   = "#e05c6e"
GREEN    = "#3ecf8e"
BLUE     = "#5b9cf6"
YELLOW   = "#f0c060"
TEXT     = "#e8eaf0"
MUTED    = "#636b80"
BORDER   = "#252835"

FN  = ("Segoe UI",     10, "bold")
FL  = ("Consolas",      9)
FC  = ("Segoe UI",      9)
FCV = ("Segoe UI",      9, "bold")
FH  = ("Segoe UI",     11, "bold")
FSM = ("Segoe UI",      9)


# =============================================================================
# 4. FILE ROW WIDGET
# =============================================================================

class FileRow(tk.Frame):
    def __init__(self, parent, info: Dict, row_index: int,
                 check_var: tk.BooleanVar, on_check: Callable, **kw):
        bg = ROW_A if row_index % 2 == 0 else ROW_B
        super().__init__(parent, bg=bg, **kw)
        self.info      = info
        self.bg        = bg
        self.check_var = check_var
        self.on_check  = on_check
        self._build()

    def _lbl(self, parent, text, fg=TEXT, font=FSM, **kw):
        return tk.Label(parent, text=text, fg=fg, bg=self.bg, font=font, **kw)

    def _chip(self, parent, label: str, value: str, val_fg: str):
        f = tk.Frame(parent, bg=HDR, padx=8, pady=4)
        tk.Label(f, text=label, fg=MUTED, bg=HDR, font=("Segoe UI",7,"bold")).pack(anchor='w')
        tk.Label(f, text=value, fg=val_fg, bg=HDR, font=FCV).pack(anchor='w')
        return f

    def _refresh_bg(self):
        new_bg = ROW_SEL if self.check_var.get() else self.bg
        def _set(w, c):
            try:
                w.config(bg=c)
                for ch in w.winfo_children():
                    _set(ch, c)
            except Exception:
                pass
        _set(self, new_bg)
        for chip in self._chips:
            for w in chip.winfo_children():
                try: w.config(bg=HDR)
                except Exception: pass
            try: chip.config(bg=HDR)
            except Exception: pass

    def _build(self):
        self._chips = []

        top = tk.Frame(self, bg=self.bg)
        top.pack(fill='x', padx=8, pady=(8, 3))

        cb = tk.Checkbutton(
            top, variable=self.check_var,
            bg=self.bg, activebackground=self.bg,
            selectcolor=self.bg,
            fg=GREEN, activeforeground=GREEN,
            cursor='hand2',
            command=lambda: (self._refresh_bg(), self.on_check()),
        )
        cb.pack(side='left', padx=(0, 4))

        badge_text = " ORIGINAL " if not is_copy(self.info['filename']) else "   COPY   "
        badge_bg   = GREEN        if not is_copy(self.info['filename']) else ACCENT
        tk.Label(
            top, text=badge_text,
            fg=BG, bg=badge_bg,
            font=("Segoe UI", 7, "bold"),
            padx=2,
        ).pack(side='left', padx=(0, 8))

        fn_frame = tk.Frame(top, bg=self.bg)
        fn_frame.pack(side='left', fill='x', expand=True)

        fn_box = tk.Text(
            fn_frame,
            height=1, wrap='none',
            bg=self.bg, fg=TEXT,
            font=FN,
            relief='flat', borderwidth=0, highlightthickness=0,
            cursor='arrow',
        )
        fn_box.insert('1.0', self.info['filename'])
        fn_box.config(state='disabled')
        fn_box.pack(fill='x')

        if len(self.info['filename']) > 80:
            fn_box.config(height=2, wrap='word')

        chips_frame = tk.Frame(top, bg=self.bg)
        chips_frame.pack(side='right', padx=(8, 0))

        chip_data = [
            ("SIZE",       human_size(self.info['size']),          TEXT),
            ("RESOLUTION", self.info.get('resolution','Unknown'),  YELLOW),
            ("FORMAT",     self.info.get('format','Unknown'),      BLUE),
            ("CODEC",      self.info.get('codec','Unknown'),       MUTED),
            ("DURATION",   self.info.get('duration','--:--'),      MUTED),
        ]
        for lbl, val, vfg in chip_data:
            c = self._chip(chips_frame, lbl, val, vfg)
            c.pack(side='left', padx=(0, 4))
            self._chips.append(c)

        folder_row = tk.Frame(self, bg=self.bg)
        folder_row.pack(fill='x', padx=8, pady=(0, 8))

        tk.Label(
            folder_row, text="FOLDER",
            fg=MUTED, bg=self.bg,
            font=("Segoe UI", 7, "bold"),
        ).pack(side='left', padx=(26, 6))

        folder_val = str(Path(self.info['path']).parent)
        fv_box = tk.Text(
            folder_row,
            height=1, wrap='none',
            bg=PANEL, fg=GREEN,
            font=FL,
            relief='flat', borderwidth=0, highlightthickness=0,
            padx=6, pady=2,
            cursor='arrow',
        )
        fv_box.insert('1.0', folder_val)
        fv_box.config(state='disabled')
        fv_box.pack(side='left', fill='x', expand=True)

        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')


# =============================================================================
# 5. GROUP WIDGET
# =============================================================================

class GroupWidget(tk.Frame):
    def __init__(self, parent, group: List[Dict], group_id: int,
                 on_any_check: Callable, **kw):
        super().__init__(parent, bg=PANEL, **kw)
        self.group        = group
        self.group_id     = group_id
        self.on_any_check = on_any_check
        self.check_vars: List[tk.BooleanVar] = [tk.BooleanVar(value=False) for _ in group]
        self._build()

    def checked_files(self) -> List[Dict]:
        return [f for f, v in zip(self.group, self.check_vars) if v.get()]

    def auto_select_copies(self):
        for f, v in zip(self.group, self.check_vars):
            v.set(is_copy(f['filename']))
        self._refresh_rows()

    def delete_checked(self) -> Tuple[int, List[str]]:
        to_del = self.checked_files()
        if not to_del:
            return 0, []
        errors, count = [], 0
        for f in to_del:
            try:
                if HAS_SEND2TRASH:
                    send2trash(f['path'])
                else:
                    os.remove(f['path'])
                count += 1
            except Exception as e:
                errors.append(f"{f['filename']}: {e}")
        return count, errors

    def _refresh_rows(self):
        for row in self._rows:
            row._refresh_bg()

    def _build(self):
        bname   = _stem_base(self.group[0]['filename'])
        n_files = len(self.group)
        wasted  = sum(f['size'] for f in self.group[1:])

        # ── HEADER BAR ───────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=HDR, pady=0)
        hdr.pack(fill='x')

        left = tk.Frame(hdr, bg=HDR)
        left.pack(side='left', padx=10, pady=8)

        tk.Label(
            left, text=f'"{bname}"',
            fg=TEXT, bg=HDR, font=("Segoe UI", 11, "bold"),
        ).pack(side='left')

        # Show shared resolution in header
        res_vals = set(f.get('resolution','Unknown') for f in self.group)
        res_str  = next(iter(res_vals)) if len(res_vals) == 1 else "mixed"
        tk.Label(
            left,
            text=f"  —  {n_files} files  |  {res_str}  |  ~{human_size(wasted)} reclaimable",
            fg=MUTED, bg=HDR, font=FSM,
        ).pack(side='left')

        right = tk.Frame(hdr, bg=HDR)
        right.pack(side='right', padx=10, pady=6)

        self._mk_btn(right, "Auto-select Copies",
                     self._on_auto_select, ACCENT, BG).pack(side='left', padx=(0, 6))
        self._mk_btn(right, "Delete Checked in Group",
                     self._on_delete_group, ACCENT, BG).pack(side='left')

        # ── COLUMN HEADERS ───────────────────────────────────────────────────
        col_hdr = tk.Frame(self, bg=BORDER)
        col_hdr.pack(fill='x')
        for txt, anchor, expand in [
            ("  ✓   BADGE   FILE NAME",   'w', True),
            ("SIZE / RESOLUTION / FORMAT / CODEC / DURATION", 'e', False),
        ]:
            tk.Label(col_hdr, text=txt, fg=MUTED, bg=BORDER,
                     font=("Segoe UI", 7, "bold"), anchor=anchor,
                     padx=8, pady=3).pack(
                side='left' if anchor == 'w' else 'right',
                fill='x', expand=expand)

        # ── FILE ROWS ────────────────────────────────────────────────────────
        self._rows: List[FileRow] = []
        for i, (fi, var) in enumerate(zip(self.group, self.check_vars)):
            row = FileRow(self, fi, i, var, on_check=self.on_any_check)
            row.pack(fill='x')
            self._rows.append(row)

        tk.Frame(self, bg=ACCENT, height=2).pack(fill='x')

    def _mk_btn(self, parent, text, cmd, bg, fg):
        return tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg=fg,
            font=("Segoe UI", 8, "bold"),
            relief='flat', cursor='hand2',
            padx=10, pady=4,
            activebackground="#b84455", activeforeground=BG,
        )

    def _on_auto_select(self):
        self.auto_select_copies()
        self.on_any_check()

    def _on_delete_group(self):
        files = self.checked_files()
        if not files:
            messagebox.showinfo("Nothing checked",
                                "Tick at least one file in this group first.")
            return
        self._confirm_and_delete(files)

    def _confirm_and_delete(self, files: List[Dict]):
        names = "\n".join(f"  • {f['filename']}\n    {Path(f['path']).parent}" for f in files)
        note  = ("Files will be moved to the Recycle Bin." if HAS_SEND2TRASH
                 else "Files will be PERMANENTLY deleted.\n(pip install send2trash for Recycle Bin)")
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete {len(files)} file(s)?\n\n{names}\n\n{note}",
            icon='warning'
        ):
            return
        count, errors = self.delete_checked()
        if errors:
            messagebox.showerror("Errors", "\n".join(errors))
        if count:
            messagebox.showinfo("Done", f"{count} file(s) removed.")
            self.destroy()
            self.on_any_check()


# =============================================================================
# 6. MAIN APP WINDOW
# =============================================================================

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Video Duplicate Manager")
        self.geometry("1100x780")
        self.minsize(900, 560)
        self.configure(bg=BG)
        self._groups: List[List[Dict]]         = []
        self._group_widgets: List[GroupWidget] = []
        self._build_ui()
        self._warn_no_ffprobe()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_toolbar()
        self._build_action_bar()
        self._build_progress()
        self._build_stats()
        self._build_scroll()
        self._show_placeholder()

    def _mk_btn(self, parent, text, cmd, bg=GREEN, fg=BG, **kw):
        return tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg=fg,
            font=("Segoe UI", 9, "bold"),
            relief='flat', cursor='hand2',
            padx=12, pady=5,
            activebackground="#2fa875", activeforeground=BG,
            **kw,
        )

    def _build_toolbar(self):
        # Row 1: title + Choose Folder button (always visible)
        row1 = tk.Frame(self, bg=BG, pady=10)
        row1.pack(fill='x', padx=16)

        tk.Label(row1, text="VIDEO DUPLICATE MANAGER",
                 fg=ACCENT, bg=BG,
                 font=("Segoe UI", 15, "bold")).pack(side='left')

        self._mk_btn(row1, "  Choose Folder  ",
                     self._choose_folder).pack(side='right')

        # Row 2: selected path + similarity slider
        row2 = tk.Frame(self, bg=BG, pady=2)
        row2.pack(fill='x', padx=16)

        self._dir_var = tk.StringVar(value="No folder selected")
        tk.Label(row2, textvariable=self._dir_var,
                 fg=MUTED, bg=BG, font=("Consolas", 9)).pack(side='left')

        slider_frame = tk.Frame(row2, bg=BG)
        slider_frame.pack(side='right', padx=(0, 4))
        tk.Label(slider_frame, text="Name similarity:",
                 fg=MUTED, bg=BG, font=FSM).pack(side='left')
        self._sim_var = tk.DoubleVar(value=SIMILARITY_THRESHOLD)
        sim_slider = ttk.Scale(slider_frame, from_=0.5, to=1.0,
                               variable=self._sim_var, orient='horizontal',
                               length=120)
        sim_slider.pack(side='left', padx=4)
        self._sim_lbl = tk.Label(slider_frame,
                                  text=f"{SIMILARITY_THRESHOLD:.0%}",
                                  fg=YELLOW, bg=BG, font=FSM, width=4)
        self._sim_lbl.pack(side='left')
        self._sim_var.trace_add('write', lambda *_: self._sim_lbl.config(
            text=f"{self._sim_var.get():.0%}"))

    def _build_action_bar(self):
        bar = tk.Frame(self, bg=HDR, pady=8)
        bar.pack(fill='x', padx=0)

        left = tk.Frame(bar, bg=HDR)
        left.pack(side='left', padx=16)

        self._btn_auto = self._mk_btn(
            left, "Auto-select ALL Copies",
            self._auto_select_all, ACCENT, BG)
        self._btn_auto.pack(side='left', padx=(0, 8))

        self._btn_del_checked = self._mk_btn(
            left, "Delete ALL Checked",
            self._delete_all_checked, ACCENT, BG)
        self._btn_del_checked.pack(side='left', padx=(0, 8))

        self._btn_clr = self._mk_btn(
            left, "Clear All Selections",
            self._clear_all, HDR, MUTED)
        self._btn_clr.config(activebackground=PANEL)
        self._btn_clr.pack(side='left')

        self._checked_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._checked_var,
                 fg=YELLOW, bg=HDR,
                 font=("Segoe UI", 9)).pack(side='right', padx=16)

        for btn in (self._btn_auto, self._btn_del_checked, self._btn_clr):
            btn.config(state='disabled')

    def _build_progress(self):
        self._prog_frame = tk.Frame(self, bg=BG)
        self._prog_frame.pack(fill='x', padx=16, pady=(4, 0))

        self._prog_lbl = tk.Label(self._prog_frame, text="",
                                   fg=MUTED, bg=BG, font=("Consolas", 9))
        self._prog_lbl.pack(side='left')

        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure("D.Horizontal.TProgressbar",
                         troughcolor=PANEL, background=GREEN,
                         borderwidth=0, lightcolor=GREEN, darkcolor=GREEN)
        self._prog_bar = ttk.Progressbar(self._prog_frame,
                                          style="D.Horizontal.TProgressbar",
                                          mode='determinate', length=360)
        self._prog_bar.pack(side='left', padx=10)
        self._prog_frame.pack_forget()

    def _build_stats(self):
        self._stats_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self._stats_var,
                 fg=GREEN, bg=BG, font=FSM).pack(anchor='w', padx=18, pady=(4, 2))

    def _build_scroll(self):
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill='both', expand=True, padx=10, pady=(0, 8))

        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient='vertical', command=self._canvas.yview)
        self._inner = tk.Frame(self._canvas, bg=BG)

        self._inner.bind("<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self._inner, anchor='nw')
        self._canvas.configure(yscrollcommand=vsb.set)

        vsb.pack(side='right', fill='y')
        self._canvas.pack(side='left', fill='both', expand=True)
        self._canvas.bind_all("<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))

    def _show_placeholder(self):
        f = tk.Frame(self._inner, bg=BG)
        f.pack(fill='both', expand=True, pady=100)
        tk.Label(f, text="Choose a folder above to scan for duplicate video files",
                 fg=MUTED, bg=BG, font=("Segoe UI", 13)).pack()
        tk.Label(f,
            text="Duplicates are matched by: similar name  +  same file size  +  same resolution",
            fg=MUTED, bg=BG, font=FSM).pack(pady=4)
        if not FFPROBE:
            tk.Label(f,
                text="  ffprobe not found — video details will show as Unknown.\n"
                     "  Run:  winget install ffmpeg  then restart.",
                fg=ACCENT, bg=BG, font=FSM).pack(pady=8)

    # ── Folder selection & scan ───────────────────────────────────────────────

    def _choose_folder(self):
        folder = filedialog.askdirectory(title="Select root folder to scan")
        if not folder:
            return
        folder = _norm(folder)
        self._dir_var.set(folder)
        self._start_scan(folder)

    def _start_scan(self, folder: str):
        for w in self._inner.winfo_children():
            w.destroy()
        self._group_widgets.clear()
        self._stats_var.set("Scanning…")
        self._checked_var.set("")
        self._prog_frame.pack(fill='x', padx=16, pady=(4, 0))
        self._prog_bar['value'] = 0
        for btn in (self._btn_auto, self._btn_del_checked, self._btn_clr):
            btn.config(state='disabled')

        sim_threshold = self._sim_var.get()

        def run():
            def on_prog(cur, tot, fp):
                pct  = cur / tot * 100 if tot else 0
                name = Path(fp).name[:60]
                self.after(0, lambda p=pct, c=cur, t=tot, n=name:
                    self._set_prog(p, f"Scanning {c}/{t}: {n}"))

            raw = scan_for_duplicates(folder, progress_cb=on_prog,
                                       similarity_threshold=sim_threshold)

            # Enrich with metadata
            enriched: List[List[Dict]] = []
            n = len(raw)
            for i, g in enumerate(raw, 1):
                nm = g[0]['filename'][:60]
                self.after(0, lambda p=100*i/n if n else 100, nm=nm, i=i, n=n:
                    self._set_prog(p, f"Reading metadata {i}/{n}: {nm}"))
                enriched.append(enrich(g))

            # Resolution gate — split groups that differ in resolution
            final = split_by_resolution(enriched)

            self.after(0, lambda: self._show_results(final))

        threading.Thread(target=run, daemon=True).start()

    def _set_prog(self, pct, label):
        self._prog_bar['value'] = pct
        self._prog_lbl.config(text=label)

    # ── Results ───────────────────────────────────────────────────────────────

    def _show_results(self, groups: List[List[Dict]]):
        self._groups = groups
        self._prog_frame.pack_forget()

        for w in self._inner.winfo_children():
            w.destroy()
        self._group_widgets.clear()

        if not groups:
            tk.Label(self._inner, text="No duplicates found!",
                     fg=GREEN, bg=BG,
                     font=("Segoe UI", 14, "bold")).pack(pady=60)
            self._stats_var.set("Scan complete — no duplicates found.")
            return

        total_files = sum(len(g) for g in groups)
        reclaimable = sum(sum(f['size'] for f in g[1:]) for g in groups)
        self._stats_var.set(
            f"{len(groups)} group(s)  ·  {total_files} files  ·  "
            f"~{human_size(reclaimable)} reclaimable space"
        )

        for i, g in enumerate(groups):
            gw = GroupWidget(self._inner, g, i, on_any_check=self._update_checked_count)
            gw.pack(fill='x', padx=6, pady=(0, 10))
            self._group_widgets.append(gw)

        for btn in (self._btn_auto, self._btn_del_checked, self._btn_clr):
            btn.config(state='normal')

        self._update_checked_count()

    def _update_checked_count(self):
        total = sum(
            len(gw.checked_files())
            for gw in self._group_widgets
            if gw.winfo_exists()
        )
        self._checked_var.set(f"{total} file(s) checked" if total else "")

    # ── Global actions ────────────────────────────────────────────────────────

    def _auto_select_all(self):
        for gw in self._group_widgets:
            if gw.winfo_exists():
                gw.auto_select_copies()
        self._update_checked_count()

    def _clear_all(self):
        for gw in self._group_widgets:
            if gw.winfo_exists():
                for v in gw.check_vars:
                    v.set(False)
                gw._refresh_rows()
        self._update_checked_count()

    def _delete_all_checked(self):
        all_checked: List[Dict] = []
        for gw in self._group_widgets:
            if gw.winfo_exists():
                all_checked.extend(gw.checked_files())

        if not all_checked:
            messagebox.showinfo("Nothing checked",
                                "Use 'Auto-select All Copies' or manually tick files first.")
            return

        size_total = sum(f['size'] for f in all_checked)
        names_preview = "\n".join(
            f"  • {f['filename']}\n    {Path(f['path']).parent}"
            for f in all_checked[:12]
        )
        if len(all_checked) > 12:
            names_preview += f"\n  … and {len(all_checked)-12} more"

        note = ("Files will be moved to the Recycle Bin." if HAS_SEND2TRASH
                else "Files will be PERMANENTLY deleted.\n(pip install send2trash for Recycle Bin)")

        if not messagebox.askyesno(
            "Confirm Delete All Checked",
            f"Delete {len(all_checked)} file(s)  (~{human_size(size_total)})?\n\n"
            f"{names_preview}\n\n{note}",
            icon='warning'
        ):
            return

        errors, total_del = [], 0
        for gw in self._group_widgets:
            if gw.winfo_exists():
                cnt, errs = gw.delete_checked()
                total_del += cnt
                errors.extend(errs)

        for gw in list(self._group_widgets):
            if not gw.winfo_exists():
                self._group_widgets.remove(gw)

        if errors:
            messagebox.showerror("Some errors", "\n".join(errors))
        if total_del:
            messagebox.showinfo("Done", f"{total_del} file(s) removed successfully.")

        self._update_checked_count()

    # ── Startup warning ───────────────────────────────────────────────────────

    def _warn_no_ffprobe(self):
        if not FFPROBE:
            messagebox.showwarning(
                "ffprobe not found",
                "ffprobe could not be found on this machine.\n\n"
                "Video resolution, codec and duration will show as 'Unknown'.\n"
                "The resolution duplicate-gate will not work without it.\n\n"
                "Fix:  Open a Command Prompt and run\n"
                "        winget install ffmpeg\n"
                "then restart this program.",
            )


# =============================================================================
# 7. ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    App().mainloop()