#!/usr/bin/env python3
"""

TODO:
* Still no dark themed title bars.

bnZ-OverlayCreator.py  —  v3.0

UI revamp — Direction C (Windows dark theme):

Architecture:
  The ttk.Treeview is replaced entirely by CanvasTable, a custom widget
  that draws all headers, rows, colours, and the selection accent bar
  directly onto a tk.Canvas. This gives full per-cell colour control
  without any platform-specific hacks.

Visual changes vs v2.5:
  - Compact header bar: logo pill, app title, all buttons right-aligned
  - Scrape button is primary (blue); all others are ghost style
  - URL bar sits below the header as its own row
  - Hit columns (A/C/D/M/P/NS) rendered in their configured overlay colours
  - HF column rendered in blue as the primary performance number
  - Zero hit values dimmed to reduce visual noise
  - Selected row: dark blue background + 3px blue left-border accent
  - Hovered row: slightly lighter background + dim blue accent
  - Status bar: connection indicator (grey/green dot) + last scraped time
  - Cell editor: dark background, blue focus ring, pre-selects value
  - PreviewWindow and SettingsWindow get matching dark title bars

Bug fixes applied during v3.0 stabilisation:
  - CanvasTable: custom Canvas scrollbar replaces tk.Scrollbar
    (native scrollbar ignores colour options on Windows)
  - Scrollbar hidden when content fits; shown and redrawn via <Configure>
    binding so it never flashes the wrong colour on first render
  - SettingsWindow: dark title bar via DwmSetWindowAttribute
  - SettingsWindow: after(50, focus_set) so Escape works immediately
    (grab_set() steals focus before the window is fully mapped)
  - PreviewWindow: dark title bar via DwmSetWindowAttribute
  - Cell editor: _commit_edit() called on any canvas click so clicking
    outside a cell saves the value (FocusOut alone is unreliable on Canvas)
  - Cell editor: _saved flag prevents double-fire when redraw() destroys
    the entry and triggers a second FocusOut
"""

from pathlib import Path
import os
import sys
import json
import csv
import logging
import threading
import datetime
import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageTk

# ------------------------
# Resource helper
# ------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ------------------------
# App directory helper
# ------------------------
def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


# ------------------------
# Logging
# ------------------------
_log_path = app_dir() / "error.log"
logging.basicConfig(
    filename=str(_log_path),
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ------------------------
# CONFIG
# ------------------------
CONFIG_FILE = app_dir() / "config.json"

_DEFAULT_CONFIG = {
    "ssi_username": "",
    "ssi_password": "",
    "font_path": "C:/Windows/Fonts/arial.ttf",
    "output_dir": "overlays",
    "output_width": 1920,
    "last_match_url": "",
    "window_geometry": None,
    "debug_mode": False,
    "colors": {
        "A":       [50,  205,  50],
        "C":       [255, 165,   0],
        "D":       [255, 105, 180],
        "M":       [220,  20,  60],
        "NS":      [138,  43, 226],
        "P":       [255, 215,   0],
        "bg":      [40,   40,  40, 220],
        "outline": [255, 255, 255, 255],
    },
}

_first_run = False
if not CONFIG_FILE.exists():
    _first_run = True
    with open(CONFIG_FILE, "w", encoding="utf-8") as _f:
        json.dump(_DEFAULT_CONFIG, _f, indent=2)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

def cfg_get(key, default=None):
    return CONFIG.get(key, default)

SSI_USERNAME = cfg_get("ssi_username")
SSI_PASSWORD = cfg_get("ssi_password")
FONT_PATH = resource_path(cfg_get("font_path", "C:/Windows/Fonts/arial.ttf"))
OUTPUT_DIR = Path(cfg_get("output_dir", "overlays"))
OUTPUT_WIDTH = int(cfg_get("output_width", 1920))
LAST_MATCH_URL = cfg_get("last_match_url", "")
WINDOW_GEOMETRY = cfg_get("window_geometry", None)
DEBUG_MODE = bool(cfg_get("debug_mode", False))

def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)

LOGIN_URL = "https://shootnscoreit.com/login/"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------
# CONSTANTS
# ------------------------
MAX_PREVIEW_WIDTH = 1100
PREVIEW_BTN_EXTRA_HEIGHT = 100
TOP_PADDING_DEFAULT = 400
PILL_RADIUS = 18
PILL_FONT_SIZE = 32
PILL_HPAD = 20
PILL_VPAD = 20
PILL_SPACING = 20

# UI palette
C_BG        = "#0f0f0f"   # window / outer bg
C_SURFACE   = "#141414"   # header / footer
C_PANEL     = "#111111"   # url bar
C_ROW_EVEN  = "#0f0f0f"
C_ROW_ODD   = "#131313"
C_ROW_HOVER = "#161616"
C_ROW_SEL   = "#0e1826"
C_BORDER    = "#1f1f1f"
C_BORDER2   = "#2a2a2a"
C_TEXT      = "#dddddd"
C_TEXT_DIM  = "#888888"
C_TEXT_HINT = "#444444"
C_ACCENT    = "#2563eb"   # blue accent / scrape button
C_HF        = "#60a5fa"   # HF column colour

# Button styles
BTN_STYLE = dict(
    bg="#1e1e1e", fg=C_TEXT_DIM,
    activebackground="#2a2a2a", activeforeground=C_TEXT,
    relief="flat", padx=10, pady=3,
    font=("Segoe UI", 9),
    borderwidth=1,
    highlightbackground=C_BORDER2,
    highlightthickness=1,
)
BTN_PRIMARY = dict(
    bg=C_ACCENT, fg="white",
    activebackground="#1d4ed8", activeforeground="white",
    relief="flat", padx=10, pady=3,
    font=("Segoe UI", 9, "bold"),
    borderwidth=0,
)

# Default overlay colors
DEFAULT_COLORS = {
    "A":       (50,  205,  50),
    "C":       (255, 165,   0),
    "D":       (255, 105, 180),
    "M":       (220,  20,  60),
    "NS":      (138,  43, 226),
    "P":       (255, 215,   0),
    "bg":      (40,   40,  40, 220),
    "outline": (255, 255, 255, 255),
}

def get_overlay_colors():
    saved = CONFIG.get("colors", {})
    result = {}
    for key, default in DEFAULT_COLORS.items():
        val = saved.get(key)
        if val and isinstance(val, list) and len(val) >= len(default):
            result[key] = tuple(val[:len(default)])
        else:
            result[key] = default
    return result

def _rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])


# ------------------------
# SCRAPER
# ------------------------
def create_logged_in_session():
    LOGIN_POST_URL = "https://shootnscoreit.com/login/?next=https://shootnscoreit.com/dashboard/"
    session = requests.Session()
    rpost = session.post(
        LOGIN_POST_URL,
        data={"username": SSI_USERNAME, "password": SSI_PASSWORD, "keep": "on"},
        headers={"Referer": LOGIN_URL},
        timeout=15,
    )
    if "/login/" in rpost.url:
        raise RuntimeError(
            "SSI login failed — the server redirected back to the login page.\n"
            "Please check your username and password in Settings."
        )
    return session

def _parse_table_rows_from_soup(soup):
    tables = soup.find_all("table")
    candidate_rows = []
    for table in tables:
        rows = table.find_all("tr")
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) >= 10:
                cols = [td.get_text(strip=True).replace("\xa0", " ") for td in tds]
                candidate_rows.append(cols)
        if candidate_rows:
            return candidate_rows
    return candidate_rows

def _parse_stage_from_cols(cols, source_label="row"):
    if len(cols) < 10:
        return None
    if cols[0].lower().startswith(("total", "summary")):
        return None
    try:
        return {
            "Stage": cols[0],
            "HF":    round(float(cols[1]) if cols[1] else 0.0, 2),
            "Time":  float(cols[2]) if cols[2] else 0.0,
            "Rounds": "",
            "A":  int(cols[4]) if cols[4] else 0,
            "C":  int(cols[5]) if cols[5] else 0,
            "D":  int(cols[6]) if cols[6] else 0,
            "M":  int(cols[7]) if cols[7] else 0,
            "P":  int(cols[8]) if cols[8] else 0,
            "NS": int(cols[9]) if cols[9] else 0,
        }
    except Exception as e:
        logger.error("Failed to parse %s: %s — cols were: %s", source_label, e, cols)
        return None

def scrape_scores_live(session, match_url):
    r = session.get(match_url, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    rows = _parse_table_rows_from_soup(soup)
    stages = []
    for i, cols in enumerate(rows):
        stage = _parse_stage_from_cols(cols, source_label=f"live row {i}")
        if stage is not None:
            stages.append(stage)
    return stages

def scrape_scores_debug_from_csv(csv_path="debug_rows.csv"):
    stages = []
    if not Path(csv_path).exists():
        return stages
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            stage = _parse_stage_from_cols(row, source_label=f"CSV row {i}")
            if stage is not None:
                stages.append(stage)
    return stages

def scrape_scores(session, match_url):
    debug_file = "debug_rows.csv"
    if DEBUG_MODE and os.path.exists(debug_file):
        return scrape_scores_debug_from_csv(debug_file)
    return scrape_scores_live(session, match_url)


# ------------------------
# NORMALISE
# ------------------------
def normalize_stage(stage):
    s = dict(stage)
    try:
        s["Time"] = float(s.get("Time", 0))
    except Exception:
        s["Time"] = 0.0
    try:
        s["HF"] = round(float(s.get("HF", 0)), 2)
    except Exception:
        s["HF"] = 0.0
    for k in ("A", "C", "D", "M", "NS", "P"):
        try:
            s[k] = int(s.get(k, 0))
        except Exception:
            s[k] = 0
    return s


# ------------------------
# OVERLAY
# ------------------------
def make_overlay(stage_info, font_path=FONT_PATH, outpath=None, output_width=None, top_padding=TOP_PADDING_DEFAULT):
    if output_width is None:
        output_width = OUTPUT_WIDTH

    _oc = get_overlay_colors()
    colors = {k: _oc[k] for k in ("A", "C", "D", "M", "NS", "P")}
    bg_color = _oc["bg"]
    outline_color = _oc["outline"]

    try:
        font_value = ImageFont.truetype(font_path, PILL_FONT_SIZE)
    except Exception:
        font_value = ImageFont.load_default()

    pill_data = []

    def pill_text(key, value=None):
        return str(key) if value is None else f"{key}: {value}"

    pill_data.append(("Stage", stage_info.get("Stage", ""), "white"))
    pill_data.append(("Time", f"{float(stage_info.get('Time', 0)):.2f}", "white"))
    pill_data.append(("HF", f"{float(stage_info.get('HF', 0)):.2f}", "white"))
    if stage_info.get("Rounds"):
        pill_data.append(("Rounds", stage_info["Rounds"], "white"))
    for key in ("A", "C", "D", "M", "NS", "P"):
        pill_data.append((key, stage_info.get(key, 0), colors.get(key, "white")))

    _dummy_draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))

    natural_widths = []
    pill_heights = []
    for label, value, color in pill_data:
        text = pill_text(label, value)
        minx, miny, maxx, maxy = _dummy_draw.textbbox((0, 0), text, font=font_value)
        text_w = maxx - minx
        text_h = maxy - miny
        natural_widths.append(text_w + 2 * PILL_HPAD)
        pill_heights.append(text_h + 2 * PILL_VPAD)

    max_h = max(pill_heights)
    total_natural_width = sum(natural_widths) + PILL_SPACING * (len(pill_data) - 1)
    scale = min(1.0, output_width / total_natural_width)

    total_scaled_width = sum(int(w * scale) for w in natural_widths) + PILL_SPACING * (len(pill_data) - 1)
    x = max(20, (output_width - total_scaled_width) // 2)
    y = top_padding

    img = Image.new("RGBA", (output_width, top_padding + max_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for i, (label, value, color) in enumerate(pill_data):
        text = pill_text(label, value)
        minx, miny, maxx, maxy = _dummy_draw.textbbox((0, 0), text, font=font_value)
        text_w = maxx - minx
        text_h = maxy - miny
        pill_w = int(natural_widths[i] * scale)
        pill_h = max_h
        text_y = y + (pill_h - text_h) // 2 - miny
        if label == "Stage":
            text_y += 4
        draw.rounded_rectangle([x, y, x + pill_w, y + pill_h], radius=PILL_RADIUS, outline=outline_color, width=2, fill=bg_color)
        text_x = x + (pill_w - text_w) // 2 - minx
        draw.text((text_x, text_y), text, font=font_value, fill=color)
        x += pill_w + PILL_SPACING

    if outpath:
        img.save(outpath, "PNG")
        return outpath
    return img



# ============================================================
# CANVAS TABLE  —  custom widget, full per-cell colour control
# ============================================================

class CanvasTable(tk.Frame):
    """
    A scrollable table drawn entirely on a tk.Canvas.
    Supports per-cell text colour, hover highlight, left-border
    selection accent, and double-click cell editing.
    All rendering is explicit — no ttk, no hacks.
    """

    COLS = ("Stage", "Time", "HF", "Rounds", "A", "C", "D", "M", "P", "NS")
    # Fractional widths — Stage is stretch, rest are fixed px set in _layout()
    COL_FIXED = {
        "Time": 74, "HF": 74, "Rounds": 60,
        "A": 48, "C": 48, "D": 48, "M": 48, "P": 48, "NS": 48,
    }
    ROW_H      = 28
    HEAD_H     = 26
    ACCENT_W   = 3
    FONT_HEAD  = ("Segoe UI", 8, "bold")
    FONT_ROW   = ("Segoe UI", 10)
    PAD_LEFT   = 10   # text left-pad inside Stage cell

    def __init__(self, master, on_double_click=None, **kw):
        super().__init__(master, bg=C_BG, **kw)
        self._stages       = []
        self._selected     = None   # row index
        self._hovered      = None   # row index
        self._on_dbl       = on_double_click
        self._col_widths   = {}     # col_name -> pixel width
        self._edit_entry   = None

        # Canvas + custom Canvas-drawn scrollbar (native tk.Scrollbar
        # ignores colour options on Windows; this gives full dark control)
        self._sb_canvas = tk.Canvas(self, width=10, bg=C_BG,
                                     highlightthickness=0, bd=0)
        self._cv = tk.Canvas(self, bg=C_BG, highlightthickness=0,
                              yscrollcommand=self._update_scrollbar)
        self._cv.pack(side="left", fill="both", expand=True)
        # _sb_canvas packed on demand by _update_scrollbar

        self._sb_dragging  = False
        self._sb_drag_start_y = 0
        self._sb_first     = 0.0
        self._sb_last      = 1.0

        self._sb_canvas.bind("<ButtonPress-1>",   self._sb_on_press)
        self._sb_canvas.bind("<B1-Motion>",       self._sb_on_drag)
        self._sb_canvas.bind("<ButtonRelease-1>", self._sb_on_release)
        self._sb_canvas.bind("<Configure>",        lambda e: self._sb_draw())

        self._cv.bind("<Configure>",       self._on_resize)
        self._cv.bind("<Button-1>",        self._on_click)
        self._cv.bind("<Double-Button-1>", self._on_double)
        self._cv.bind("<Motion>",          self._on_motion)
        self._cv.bind("<Leave>",           self._on_leave)
        self._cv.bind("<MouseWheel>",      self._on_scroll)

    # ------------------------------------------------------------------
    def _update_scrollbar(self, first, last):
        """Show/hide and redraw the custom Canvas scrollbar."""
        self._sb_first = float(first)
        self._sb_last  = float(last)
        if self._sb_first <= 0.0 and self._sb_last >= 1.0:
            self._sb_canvas.pack_forget()
        else:
            self._sb_canvas.pack(side="right", fill="y", before=self._cv)
        self._sb_draw()

    def _sb_draw(self):
        """Paint the scrollbar track and thumb."""
        sc  = self._sb_canvas
        sc.delete("all")
        w   = sc.winfo_width()  or 10
        h   = sc.winfo_height() or 200
        # Track
        sc.create_rectangle(0, 0, w, h, fill="#1a1a1a", outline="")
        # Thumb
        ty1 = int(self._sb_first * h)
        ty2 = int(self._sb_last  * h)
        ty2 = max(ty2, ty1 + 20)   # minimum thumb height
        fill = "#4a4a4a" if self._sb_dragging else "#3a3a3a"
        sc.create_rectangle(2, ty1, w - 2, ty2, fill=fill,
                            outline="", tags="thumb")

    def _sb_on_press(self, event):
        self._sb_dragging      = True
        self._sb_drag_start_y  = event.y
        self._sb_drag_start_top = self._sb_first
        self._sb_draw()

    def _sb_on_drag(self, event):
        if not self._sb_dragging:
            return
        h     = self._sb_canvas.winfo_height() or 200
        delta = (event.y - self._sb_drag_start_y) / h
        new_top = max(0.0, min(self._sb_drag_start_top + delta,
                               1.0 - (self._sb_last - self._sb_first)))
        self._cv.yview_moveto(new_top)

    def _sb_on_release(self, event):
        self._sb_dragging = False
        self._sb_draw()

    def load(self, stages):
        self._stages   = stages
        self._selected = None
        self._hovered  = None
        self._layout(self._cv.winfo_width() or 800)
        self.redraw()

    def get_selected_index(self):
        return self._selected

    # ------------------------------------------------------------------
    def _layout(self, total_w):
        """Compute column pixel widths given the current canvas width."""
        fixed_total = sum(self.COL_FIXED.values()) + self.ACCENT_W
        stage_w     = max(120, total_w - fixed_total - 2)
        self._col_widths = {"Stage": stage_w}
        self._col_widths.update(self.COL_FIXED)

    def _col_x(self, col_name):
        """Return the left x-coordinate of a column."""
        x = self.ACCENT_W
        for c in self.COLS:
            if c == col_name:
                return x
            x += self._col_widths.get(c, 0)
        return x

    def _row_y(self, row_idx):
        """Return the top y-coordinate of a data row (0-based), after header."""
        return self.HEAD_H + row_idx * self.ROW_H

    def _row_at_y(self, y):
        """Return data row index at canvas y, or None."""
        if y < self.HEAD_H:
            return None
        idx = (y - self.HEAD_H) // self.ROW_H
        if 0 <= idx < len(self._stages):
            return idx
        return None

    def _col_at_x(self, x):
        """Return column name at canvas x, or None."""
        cx = self.ACCENT_W
        for c in self.COLS:
            w = self._col_widths.get(c, 0)
            if cx <= x < cx + w:
                return c
            cx += w
        return None

    # ------------------------------------------------------------------
    def redraw(self):
        cv = self._cv
        cv.delete("all")

        total_w = cv.winfo_width() or 800
        self._layout(total_w)

        oc        = get_overlay_colors()
        hit_hex   = {k: _rgb_to_hex(oc[k]) for k in ("A","C","D","M","P","NS")}
        total_h   = self.HEAD_H + len(self._stages) * self.ROW_H

        cv.config(scrollregion=(0, 0, total_w, max(total_h, cv.winfo_height() or 600)))

        # ── Header ──
        cv.create_rectangle(0, 0, total_w, self.HEAD_H,
                            fill=C_SURFACE, outline="")
        cv.create_line(0, self.HEAD_H, total_w, self.HEAD_H,
                       fill=C_BORDER, width=1)

        for col in self.COLS:
            x = self._col_x(col)
            w = self._col_widths.get(col, 0)
            anchor = "w" if col == "Stage" else "center"
            tx     = (x + self.PAD_LEFT) if col == "Stage" else (x + w // 2)
            cv.create_text(tx, self.HEAD_H // 2,
                           text=col.upper(), fill=C_TEXT_HINT,
                           font=self.FONT_HEAD, anchor=anchor)

        # ── Rows ──
        for i, s in enumerate(self._stages):
            ry     = self._row_y(i)
            is_sel = (i == self._selected)
            is_hov = (i == self._hovered)

            if is_sel:
                row_bg = C_ROW_SEL
            elif is_hov:
                row_bg = C_ROW_HOVER
            else:
                row_bg = C_ROW_EVEN if i % 2 == 0 else C_ROW_ODD

            # Row background
            cv.create_rectangle(self.ACCENT_W, ry, total_w, ry + self.ROW_H,
                                fill=row_bg, outline="")

            # Separator line
            cv.create_line(self.ACCENT_W, ry + self.ROW_H - 1,
                           total_w, ry + self.ROW_H - 1,
                           fill=C_BORDER, width=1)

            # Left accent bar
            if is_sel:
                cv.create_rectangle(0, ry, self.ACCENT_W, ry + self.ROW_H,
                                    fill=C_ACCENT, outline="")
            elif is_hov:
                cv.create_rectangle(0, ry, self.ACCENT_W, ry + self.ROW_H,
                                    fill="#3b5fc0", outline="")
            else:
                cv.create_rectangle(0, ry, self.ACCENT_W, ry + self.ROW_H,
                                    fill=row_bg, outline="")

            ty = ry + self.ROW_H // 2   # text vertical centre

            # Stage — left-aligned
            x = self._col_x("Stage")
            w = self._col_widths["Stage"]
            stage_txt = str(s.get("Stage", ""))
            cv.create_text(x + self.PAD_LEFT, ty, text=stage_txt,
                           fill=C_TEXT, font=self.FONT_ROW,
                           anchor="w", width=w - self.PAD_LEFT - 4)

            # Time — dim
            self._draw_cell(cv, "Time", ty,
                f"{s.get('Time',0):.2f}" if isinstance(s.get('Time',0),(int,float)) else str(s.get('Time','')),
                C_TEXT_DIM)

            # HF — blue accent
            self._draw_cell(cv, "HF", ty,
                f"{s.get('HF',0):.2f}" if isinstance(s.get('HF',0),(int,float)) else str(s.get('HF','')),
                C_HF)

            # Rounds — dim
            self._draw_cell(cv, "Rounds", ty, str(s.get("Rounds", "")), C_TEXT_DIM)

            # Hit columns — use configured colour; dim if zero
            for k in ("A", "C", "D", "M", "P", "NS"):
                val  = s.get(k, 0)
                fill = hit_hex[k] if int(val or 0) > 0 else C_TEXT_HINT
                self._draw_cell(cv, k, ty, str(val), fill)

        # Vertical column dividers (subtle)
        for col in self.COLS[1:]:
            x = self._col_x(col)
            cv.create_line(x, 0, x, total_h, fill=C_BORDER, width=1)

    def _draw_cell(self, cv, col, ty, text, fill):
        x = self._col_x(col)
        w = self._col_widths.get(col, 0)
        cv.create_text(x + w // 2, ty, text=text, fill=fill,
                       font=self.FONT_ROW, anchor="center")

    # ------------------------------------------------------------------
    def _on_resize(self, event):
        self._layout(event.width)
        self.redraw()

    def _commit_edit(self):
        """Save and close any open cell editor, as if Enter was pressed."""
        e = self._edit_entry
        if e and e.winfo_exists():
            e.event_generate("<Return>")

    def _on_click(self, event):
        self._commit_edit()
        y   = self._cv.canvasy(event.y)
        idx = self._row_at_y(int(y))
        if idx is not None:
            self._selected = idx
            self.redraw()

    def _on_double(self, event):
        # Single-click already committed any open edit via _on_click
        y   = self._cv.canvasy(event.y)
        idx = self._row_at_y(int(y))
        col = self._col_at_x(event.x)
        if idx is not None and col is not None and self._on_dbl:
            self._on_dbl(idx, col)

    def _on_motion(self, event):
        y   = self._cv.canvasy(event.y)
        idx = self._row_at_y(int(y))
        if idx != self._hovered:
            self._hovered = idx
            self.redraw()

    def _on_leave(self, event):
        if self._hovered is not None:
            self._hovered = None
            self.redraw()

    def _on_scroll(self, event):
        self._cv.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ============================================================
# GUI  —  v3.0 Direction C
# ============================================================

class ScoringApp(tk.Tk):
    _RESIZE_W = 6

    def __init__(self):
        super().__init__()

        self.title("SSI Scoring Overlay Software")
        self.configure(bg=C_BG)
        self.geometry(WINDOW_GEOMETRY if WINDOW_GEOMETRY else "1200x680")
        self.minsize(900, 500)

        # Dark title bar — proven v2.5 approach using FindWindowW by title
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.FindWindowW(None, self.title())
            if hwnd:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20,
                    ctypes.byref(ctypes.c_int(1)),
                    ctypes.sizeof(ctypes.c_int(1)))
        except Exception:
            pass

        # Internal drag / resize state (kept for potential future use)
        self._drag_x      = 0
        self._drag_y      = 0
        self._resizing    = None
        self._resize_x    = 0
        self._resize_y    = 0
        self._resize_geom = (0, 0, 0, 0)

        self.session = None
        self.stages  = []

        if _first_run:
            self.after(200, self._show_first_run_welcome)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----------------------------------------------------------
    def _build_ui(self):
        # ── Header bar ──
        hdr = tk.Frame(self, bg=C_SURFACE, height=38)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Logo pill
        tk.Label(hdr, text="S", bg=C_ACCENT, fg="white",
                 font=("Segoe UI", 10, "bold"), padx=5).pack(
            side="left", padx=(10, 6), pady=7)

        tk.Label(hdr, text="SSI Scoring Overlay", bg=C_SURFACE,
                 fg=C_TEXT, font=("Segoe UI", 10, "bold")).pack(
            side="left", padx=(0, 12))

        # Buttons right-aligned, packed right-to-left.
        # Visual order left-to-right: Scrape | Preview | Export CSV | Export Overlays | Settings
        for text, cmd in (
            ("⚙ Settings",       self.on_settings),
            ("Export Overlays",  self.on_export_overlays),
            ("Export CSV",       self.on_export_csv),
            ("Preview Overlay",  self.on_preview),
        ):
            tk.Button(hdr, text=text, command=cmd, **BTN_STYLE).pack(
                side="right", padx=2, pady=6)

        self._scrape_btn = tk.Button(hdr, text="Scrape",
                                      command=self.on_scrape, **BTN_PRIMARY)
        self._scrape_btn.pack(side="right", padx=(2, 4), pady=6)

        # ── URL bar ──
        url_bar = tk.Frame(self, bg=C_PANEL, height=34)
        url_bar.pack(fill="x")
        url_bar.pack_propagate(False)

        tk.Label(url_bar, text="Match URL:", bg=C_PANEL,
                 fg=C_TEXT_HINT, font=("Segoe UI", 9)).pack(
            side="left", padx=(12, 6), pady=7)

        self.match_var = tk.StringVar(value=LAST_MATCH_URL)
        url_entry = tk.Entry(url_bar, textvariable=self.match_var,
                             bg="#181818", fg=C_TEXT_DIM,
                             insertbackground=C_TEXT_DIM,
                             relief="flat", font=("Segoe UI", 9),
                             highlightbackground=C_BORDER2,
                             highlightthickness=1)
        url_entry.pack(side="left", fill="x", expand=True, pady=6, padx=(0, 10))
        url_entry.bind("<Return>", lambda e: self.on_scrape())

        # ── Canvas table ──
        self.table = CanvasTable(self, on_double_click=self._on_edit_cell)
        self.table.pack(fill="both", expand=True)

        # ── Status bar ──
        sb = tk.Frame(self, bg=C_SURFACE, height=24)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)

        self._status_conn = tk.Label(sb, text="● not connected",
                                      bg=C_SURFACE, fg="#444444",
                                      font=("Segoe UI", 8))
        self._status_conn.pack(side="left", padx=(12, 16), pady=4)

        tk.Frame(sb, bg=C_BORDER, width=1).pack(side="left", fill="y", pady=4)

        self._status_time = tk.Label(sb, text="", bg=C_SURFACE,
                                      fg=C_TEXT_HINT, font=("Segoe UI", 8))
        self._status_time.pack(side="left", padx=12, pady=4)

    # ----------------------------------------------------------
    def _set_status_connected(self, ok: bool):
        if ok:
            self._status_conn.config(text="● connected", fg="#22c55e")
        else:
            self._status_conn.config(text="● not connected", fg="#444444")

    def _set_status_time(self):
        now = datetime.datetime.now().strftime("%H:%M")
        self._status_time.config(text=f"Last scraped {now}")

    def _set_scrape_btn(self, enabled: bool):
        self._scrape_btn.configure(state="normal" if enabled else "disabled")

    def _show_first_run_welcome(self):
        messagebox.showinfo(
            "Welcome to SSI Scoring Overlay",
            "A default config.json has been created next to the application.\n\n"
            "Please open ⚙ Settings to enter your Shoot'n Score It username "
            "and password before scraping.",
        )
        SettingsWindow(self)

    # ----------------------------------------------------------
    def _refresh_table(self):
        self.table.load(self.stages)

    def _on_edit_cell(self, row_idx, col_name):
        """Called by CanvasTable on double-click. Opens an inline entry widget."""
        if not self.stages or row_idx >= len(self.stages):
            return

        cv    = self.table._cv
        x     = self.table._col_x(col_name)
        w     = self.table._col_widths.get(col_name, 80)
        ry    = self.table._row_y(row_idx)
        # Convert canvas coords to widget coords (account for scroll)
        wy    = ry - int(cv.canvasy(0))

        if self.table._edit_entry:
            self.table._edit_entry.destroy()

        entry = tk.Entry(cv,
                         bg="#181818", fg=C_TEXT,
                         insertbackground=C_TEXT,
                         relief="flat", font=("Segoe UI", 10),
                         highlightbackground=C_ACCENT,
                         highlightthickness=1)
        entry.place(x=x, y=wy, width=w, height=CanvasTable.ROW_H)
        self.table._edit_entry = entry

        cur_val = str(self.stages[row_idx].get(col_name, ""))
        entry.insert(0, cur_val)
        entry.select_range(0, "end")
        entry.focus()

        _saved = [False]

        def save(event=None):
            if _saved[0]:
                return
            _saved[0] = True
            new_val = entry.get()
            entry.destroy()
            self.table._edit_entry = None
            self.stages[row_idx][col_name] = new_val
            self.table.redraw()

        def cancel(event=None):
            _saved[0] = True
            entry.destroy()
            self.table._edit_entry = None

        entry.bind("<Return>",   save)
        entry.bind("<FocusOut>", save)
        entry.bind("<Escape>",   cancel)

    # ----------------------------------------------------------
    # All actions identical to v2.5
    # ----------------------------------------------------------
    def on_scrape(self):
        url = self.match_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Enter a match URL first.")
            return
        if not CONFIG.get("ssi_username") or not CONFIG.get("ssi_password"):
            messagebox.showerror(
                "Credentials missing",
                "No username or password set.\n\nPlease open ⚙ Settings and enter "
                "your Shoot'n Score It credentials before scraping.",
            )
            return

        self._set_scrape_btn(False)
        self._set_status_connected(False)

        def _run():
            try:
                stages     = []
                debug_file = "debug_rows.csv"

                if DEBUG_MODE and os.path.exists(debug_file):
                    stages = scrape_scores_debug_from_csv(debug_file)

                if not stages:
                    self.session = create_logged_in_session()
                    stages       = scrape_scores_live(self.session, url)

                stages = [normalize_stage(s) for s in stages]

                if not stages:
                    def _no_data():
                        messagebox.showerror("No data", "No valid stages found at that URL.")
                        self._set_scrape_btn(True)
                    self.after(0, _no_data)
                    return

                def _done():
                    self.stages = stages
                    self._refresh_table()
                    self._set_status_connected(True)
                    self._set_status_time()
                    CONFIG["last_match_url"] = url
                    save_config()
                    self._set_scrape_btn(True)
                    if DEBUG_MODE:
                        src = "debug_rows.csv" if os.path.exists(debug_file) else "online"
                        messagebox.showinfo("Success",
                            f"DEBUG_MODE ON — {len(stages)} stages from {src}.")

                self.after(0, _done)

            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.error("Scraping failed: %s", e, exc_info=True)
                err_str = str(e)
                if "login" in err_str.lower() or "credential" in err_str.lower():
                    title = "Login failed"
                    msg   = ("Could not log in to Shoot'n Score It.\n\n"
                             "Please check your username and password in "
                             "⚙ Settings and try again.")
                else:
                    title = "Scraping failed"
                    msg   = ("Something went wrong while fetching scores.\n\n"
                             "Check that the match URL is correct and that you "
                             "have an internet connection.\n\n"
                             f"Detail: {err_str}")

                def _show_error(t=title, m=msg):
                    messagebox.showerror(t, m)
                    self._set_scrape_btn(True)

                self.after(0, _show_error)

        threading.Thread(target=_run, daemon=True).start()

    def on_preview(self):
        if not self.stages:
            messagebox.showwarning("No data", "Scrape first.")
            return
        idx = self.table.get_selected_index()
        PreviewWindow(self, self.stages, idx if idx is not None else 0)

    def on_export_csv(self):
        if not self.stages:
            messagebox.showwarning("No data", "Scrape first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        cols = ("Stage", "Time", "HF", "Rounds", "A", "C", "D", "M", "NS", "P")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for s in self.stages:
                w.writerow({c: s.get(c, "") for c in cols})
        messagebox.showinfo("Saved", f"CSV saved to {path}")

    def on_export_overlays(self):
        if not self.stages:
            messagebox.showwarning("No data", "Scrape first.")
            return
        outdir = OUTPUT_DIR
        outdir.mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(self.stages, start=1):
            safe = s.get("Stage", f"stage_{i}").replace(" ", "_").replace(".", "")
            make_overlay(s, font_path=FONT_PATH, outpath=str(outdir / f"{safe}.png"))
        messagebox.showinfo("Export complete", f"Overlays saved to {outdir}")

    def on_settings(self):
        SettingsWindow(self)

    def on_close(self):
        CONFIG["window_geometry"] = self.geometry()
        CONFIG["last_match_url"]  = self.match_var.get().strip()
        save_config()
        self.destroy()


# ============================================================
# PREVIEW WINDOW
# ============================================================

class PreviewWindow(tk.Toplevel):
    def __init__(self, master, stages, index):
        super().__init__(master)
        self.title("Overlay Preview")
        self.configure(bg=C_BG)
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.FindWindowW(None, self.title())
            if hwnd:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20,
                    ctypes.byref(ctypes.c_int(1)),
                    ctypes.sizeof(ctypes.c_int(1)))
        except Exception:
            pass
        self.stages = stages
        self.index  = index
        self.img_tk = None

        self.canvas = tk.Canvas(self, bg=C_BG, highlightthickness=0)
        self.canvas.pack(pady=(10, 0))

        btn_frame = tk.Frame(self, bg=C_BG)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="◀ Previous", command=self.prev_stage,
                  **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Next ▶",     command=self.next_stage,
                  **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Close",      command=self.destroy,
                  **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Save PNG",   command=self.save_current_png,
                  **BTN_PRIMARY).pack(side="left", padx=6)

        self.bind("<Left>",   lambda e: self.prev_stage())
        self.bind("<Right>",  lambda e: self.next_stage())
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("s",        lambda e: self.save_current_png())
        self.focus_set()
        self.show_stage()

    def _load_display_image(self):
        img = make_overlay(self.stages[self.index], font_path=FONT_PATH)
        if img.width > MAX_PREVIEW_WIDTH:
            h = int(img.height * MAX_PREVIEW_WIDTH / img.width)
            return img.resize((MAX_PREVIEW_WIDTH, h), Image.LANCZOS)
        return img

    def show_stage(self):
        display      = self._load_display_image()
        self.img_tk  = ImageTk.PhotoImage(display)
        iw, ih       = display.size
        self.canvas.config(width=iw, height=ih)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.img_tk, anchor="nw")
        self.geometry(f"{max(iw+40,500)}x{ih+PREVIEW_BTN_EXTRA_HEIGHT}")
        self.title(f"Overlay Preview — {self.stages[self.index].get('Stage','')}")

    def save_current_png(self):
        s    = self.stages[self.index]
        name = s.get("Stage", f"stage_{self.index}").replace(" ","_").replace(".","")
        path = filedialog.asksaveasfilename(
            defaultextension=".png", initialfile=f"{name}.png",
            filetypes=[("PNG files", "*.png")])
        if not path:
            return
        make_overlay(s, font_path=FONT_PATH, outpath=path)
        messagebox.showinfo("Saved", f"Overlay saved to {path}")

    def prev_stage(self):
        if self.index > 0:
            self.index -= 1
            self.show_stage()

    def next_stage(self):
        if self.index < len(self.stages) - 1:
            self.index += 1
            self.show_stage()


# ============================================================
# SETTINGS WINDOW
# ============================================================

class SettingsWindow(tk.Toplevel):
    _FIELDS = [
        ("ssi_username", "SSI Username", "text"),
        ("ssi_password", "SSI Password", "password"),
        ("font_path",    "Font Path",    "path"),
        ("output_dir",   "Output Dir",   "path"),
        ("debug_mode",   "Debug Mode",   "bool"),
    ]
    _COLOR_LABELS = [
        ("A",       "A"),
        ("C",       "C"),
        ("D",       "D"),
        ("M",       "M (Mike)"),
        ("NS",      "NS"),
        ("P",       "P (Proc.)"),
        ("bg",      "Pill background"),
        ("outline", "Pill outline"),
    ]

    def __init__(self, master):
        super().__init__(master)
        self.title("Settings")
        self.configure(bg="#111111")
        self.resizable(False, False)
        self.transient(master)
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.FindWindowW(None, self.title())
            if hwnd:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20,
                    ctypes.byref(ctypes.c_int(1)),
                    ctypes.sizeof(ctypes.c_int(1)))
        except Exception:
            pass
        self.grab_set()
        self.after(50, self.focus_set)

        self._vars           = {}
        self._show_pw        = {}
        self._color_values   = {}
        self._color_swatches = {}

        LABEL_W  = 18
        ENTRY_W  = 46
        pad_x, pad_y = 16, 5

        lbl_cfg   = dict(bg="#111111", fg=C_TEXT, anchor="w",
                         width=LABEL_W, font=("Segoe UI", 9))
        entry_cfg = dict(bg="#1a1a1a", fg=C_TEXT_DIM,
                         insertbackground=C_TEXT_DIM,
                         relief="flat", font=("Segoe UI", 9), width=ENTRY_W,
                         highlightbackground=C_BORDER2, highlightthickness=1)

        for row_i, (key, label, ftype) in enumerate(self._FIELDS):
            current = CONFIG.get(key, "")
            tk.Label(self, text=label + ":", **lbl_cfg).grid(
                row=row_i, column=0, padx=(pad_x, 8), pady=pad_y, sticky="w")

            if ftype == "bool":
                var = tk.BooleanVar(value=bool(current))
                self._vars[key] = var
                tk.Checkbutton(self, variable=var,
                               bg="#111111", fg=C_TEXT,
                               activebackground="#111111", activeforeground=C_TEXT,
                               selectcolor="#1a1a1a", relief="flat"
                               ).grid(row=row_i, column=1, padx=(0, pad_x),
                                      pady=pad_y, sticky="w")

            elif ftype == "password":
                var = tk.StringVar(value=str(current))
                self._vars[key] = var
                show_var = tk.BooleanVar(value=False)
                self._show_pw[key] = show_var
                frame = tk.Frame(self, bg="#111111")
                frame.grid(row=row_i, column=1, padx=(0, pad_x), pady=pad_y, sticky="w")
                entry = tk.Entry(frame, textvariable=var, show="●", **entry_cfg)
                entry.pack(side="left")
                tk.Button(frame, text="Show", width=5,
                          command=lambda sv=show_var, e=entry: (
                              sv.set(not sv.get()),
                              e.config(show="" if sv.get() else "●"),
                          ), **BTN_STYLE).pack(side="left", padx=(6, 0))

            elif ftype == "path":
                var = tk.StringVar(value=str(current))
                self._vars[key] = var
                frame = tk.Frame(self, bg="#111111")
                frame.grid(row=row_i, column=1, padx=(0, pad_x), pady=pad_y, sticky="w")
                tk.Entry(frame, textvariable=var, **entry_cfg).pack(side="left")

                def _make_browse(v=var, k=key):
                    def _browse():
                        if k == "font_path":
                            r = filedialog.askopenfilename(
                                title="Select font file",
                                filetypes=[("Font files", "*.ttf *.otf"),
                                           ("All files", "*.*")],
                                initialfile=v.get() or "")
                        else:
                            r = filedialog.askdirectory(
                                title="Select output directory",
                                initialdir=v.get() or ".")
                        if r:
                            v.set(r)
                    return _browse

                tk.Button(frame, text="Browse…", command=_make_browse(),
                          **BTN_STYLE).pack(side="left", padx=(6, 0))

            else:
                var = tk.StringVar(value=str(current))
                self._vars[key] = var
                tk.Entry(self, textvariable=var, **entry_cfg).grid(
                    row=row_i, column=1, padx=(0, pad_x), pady=pad_y, sticky="w")

        # Color section
        fc  = len(self._FIELDS)
        csr = fc

        ttk.Separator(self, orient="horizontal").grid(
            row=csr, column=0, columnspan=2,
            sticky="ew", padx=pad_x, pady=(10, 4))
        tk.Label(self, text="Overlay Colors", bg="#111111", fg="white",
                 font=("Segoe UI", 9, "bold")).grid(
            row=csr + 1, column=0, columnspan=2,
            padx=pad_x, pady=(2, 4), sticky="w")

        cc = get_overlay_colors()
        for i, (ckey, clabel) in enumerate(self._COLOR_LABELS):
            row  = csr + 2 + i
            rgba = cc[ckey]
            self._color_values[ckey] = list(rgba)
            tk.Label(self, text=clabel + ":", **lbl_cfg).grid(
                row=row, column=0, padx=(pad_x, 8), pady=(2, 2), sticky="w")
            frame = tk.Frame(self, bg="#111111")
            frame.grid(row=row, column=1, padx=(0, pad_x), pady=(2, 2), sticky="w")
            swatch = tk.Label(frame, bg=_rgb_to_hex(rgba), width=4,
                              relief="solid", borderwidth=1, cursor="hand2")
            swatch.pack(side="left", ipady=5, padx=(0, 8))
            self._color_swatches[ckey] = swatch
            swatch.bind("<Button-1>", lambda e, k=ckey: self._pick_color(k))
            alpha_part = f", A:{rgba[3]}" if len(rgba) == 4 else ""
            rgb_lbl = tk.Label(frame,
                               text=f"R:{rgba[0]}  G:{rgba[1]}  B:{rgba[2]}{alpha_part}",
                               bg="#111111", fg="#888888",
                               font=("Segoe UI", 8), width=28, anchor="w")
            rgb_lbl.pack(side="left")
            tk.Button(frame, text="Change…",
                      command=lambda k=ckey: self._pick_color(k),
                      **BTN_STYLE).pack(side="left")

        rr = csr + 2 + len(self._COLOR_LABELS)
        tk.Button(self, text="Reset colors to defaults",
                  command=self._reset_colors, **BTN_STYLE).grid(
            row=rr, column=0, columnspan=2, pady=(6, 2))

        sr = rr + 1
        ttk.Separator(self, orient="horizontal").grid(
            row=sr, column=0, columnspan=2,
            sticky="ew", padx=pad_x, pady=(8, 4))

        bf = tk.Frame(self, bg="#111111")
        bf.grid(row=sr + 1, column=0, columnspan=2, pady=(4, 12))
        tk.Button(bf, text="Save",   width=10,
                  command=self._save,    **BTN_PRIMARY).pack(side="left", padx=8)
        tk.Button(bf, text="Cancel", width=10,
                  command=self.destroy, **BTN_STYLE).pack(side="left", padx=8)

        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        mx = master.winfo_x() + master.winfo_width()  // 2
        my = master.winfo_y() + master.winfo_height() // 2
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{mx - w // 2}+{my - h // 2}")

    def _pick_color(self, k):
        init = _rgb_to_hex(self._color_values[k])
        res  = colorchooser.askcolor(color=init,
                                     title=f"Choose color — {k}", parent=self)
        if not res or not res[0]:
            return
        r, g, b = (int(x) for x in res[0])
        alpha   = self._color_values[k][3] if len(self._color_values[k]) == 4 else None
        self._color_values[k] = [r, g, b] + ([alpha] if alpha is not None else [])
        self._color_swatches[k].config(bg="#{:02x}{:02x}{:02x}".format(r, g, b))
        alpha_part = f", A:{alpha}" if alpha is not None else ""
        for w in self._color_swatches[k].master.winfo_children():
            if isinstance(w, tk.Label) and w is not self._color_swatches[k]:
                w.config(text=f"R:{r}  G:{g}  B:{b}{alpha_part}")
                break

    def _reset_colors(self):
        for ckey, default in DEFAULT_COLORS.items():
            self._color_values[ckey] = list(default)
            r, g, b = default[0], default[1], default[2]
            alpha   = default[3] if len(default) == 4 else None
            if ckey in self._color_swatches:
                self._color_swatches[ckey].config(
                    bg="#{:02x}{:02x}{:02x}".format(r, g, b))
            for w in self._color_swatches[ckey].master.winfo_children():
                if isinstance(w, tk.Label) and w is not self._color_swatches[ckey]:
                    alpha_part = f", A:{alpha}" if alpha is not None else ""
                    w.config(text=f"R:{r}  G:{g}  B:{b}{alpha_part}")
                    break

    def _save(self):
        for key, var in self._vars.items():
            val = var.get()
            CONFIG[key] = bool(val) if isinstance(var, tk.BooleanVar) else str(val).strip()
        CONFIG["colors"] = {k: v for k, v in self._color_values.items()}
        save_config()
        messagebox.showinfo(
            "Settings saved",
            "Settings have been saved to config.json.\n\n"
            "Changes to username, password, font path, and output directory\n"
            "will take effect the next time you start the application.\n\n"
            "Color changes take effect immediately.",
            parent=self,
        )
        self.destroy()


# ------------------------
# MAIN
# ------------------------
if __name__ == "__main__":
    app = ScoringApp()
    app.mainloop()