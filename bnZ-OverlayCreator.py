#!/usr/bin/env python3
"""
bnZ-OverlayCreator.py  —  v3.0

UI revamp (Direction C):
- Windows-native chrome: flat titlebar, Segoe UI throughout, square corners
- Compact header bar: logo, app title, all action buttons right-aligned
- URL bar with labelled input field
- Table: coloured hit values (A/C/D/M/P/NS use configured overlay colours)
- HF column highlighted in blue as primary performance number
- Left-border accent on selected row; hover highlight
- Status bar: connection status + last scraped time
- Cell editor styled to match new UI (dark, borderless)
- PreviewWindow and SettingsWindow updated to match new aesthetic
- All v2.5 functionality preserved exactly
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
# GUI  —  v3.0 Direction C
# ============================================================

class ScoringApp(tk.Tk):
    def __init__(self):
        super().__init__()

        # Dark title bar on Windows
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.FindWindowW(None, self.title())
            if hwnd:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int(1))
                )
        except Exception:
            pass

        self.title("SSI Scoring Overlay Software  —  v3.0")
        self.configure(bg=C_BG)
        self.geometry(WINDOW_GEOMETRY if WINDOW_GEOMETRY else "1200x680")

        self.session = None
        self.stages = []
        self._hovered_row = None
        self._last_scraped = None

        if _first_run:
            self.after(200, self._show_first_run_welcome)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----------------------------------------------------------
    # UI construction
    # ----------------------------------------------------------
    def _build_ui(self):
        # ── Header bar ──
        hdr = tk.Frame(self, bg=C_SURFACE, height=38)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Logo pill
        logo = tk.Label(hdr, text="S", bg=C_ACCENT, fg="white",
                        font=("Segoe UI", 11, "bold"), width=2,
                        padx=4, pady=2)
        logo.pack(side="left", padx=(10, 6), pady=6)

        tk.Label(hdr, text="SSI Scoring Overlay", bg=C_SURFACE,
                 fg=C_TEXT, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 16))

        # Separator line
        tk.Frame(hdr, bg=C_BORDER2, width=1).pack(side="left", fill="y", pady=6, padx=4)

        # Right-side buttons (packed right-to-left so Scrape ends up rightmost)
        self._scrape_btn = tk.Button(hdr, text="Scrape", command=self.on_scrape, **BTN_PRIMARY)
        self._scrape_btn.pack(side="right", padx=(4, 10), pady=6)

        tk.Button(hdr, text="⚙ Settings", command=self.on_settings, **BTN_STYLE).pack(side="right", padx=2, pady=6)
        tk.Button(hdr, text="Export Overlays", command=self.on_export_overlays, **BTN_STYLE).pack(side="right", padx=2, pady=6)
        tk.Button(hdr, text="Export CSV", command=self.on_export_csv, **BTN_STYLE).pack(side="right", padx=2, pady=6)
        tk.Button(hdr, text="Preview Overlay", command=self.on_preview, **BTN_STYLE).pack(side="right", padx=2, pady=6)

        # ── URL bar ──
        url_bar = tk.Frame(self, bg=C_PANEL, height=34)
        url_bar.pack(fill="x")
        url_bar.pack_propagate(False)

        tk.Label(url_bar, text="Match URL:", bg=C_PANEL,
                 fg=C_TEXT_HINT, font=("Segoe UI", 9)).pack(side="left", padx=(12, 6), pady=7)

        self.match_var = tk.StringVar(value=LAST_MATCH_URL)
        url_entry = tk.Entry(url_bar, textvariable=self.match_var,
                             bg="#181818", fg=C_TEXT_DIM,
                             insertbackground=C_TEXT_DIM,
                             relief="flat", font=("Segoe UI", 9),
                             highlightbackground=C_BORDER2,
                             highlightthickness=1)
        url_entry.pack(side="left", fill="x", expand=True, pady=6, padx=(0, 10))
        url_entry.bind("<Return>", lambda e: self.on_scrape())

        # ── Table ──
        self._build_table()

        # ── Status bar ──
        self._build_statusbar()

    def _build_table(self):
        # Canvas-based table with hover + selection left-border accent.
        # We embed a ttk.Treeview but paint the accent bar manually via tags
        # and motion bindings.

        style = ttk.Style(self)
        style.theme_use("default")

        style.configure("v3.Treeview",
                        background=C_ROW_EVEN,
                        fieldbackground=C_ROW_EVEN,
                        foreground=C_TEXT,
                        rowheight=28,
                        font=("Segoe UI", 10),
                        borderwidth=0,
                        relief="flat")
        style.configure("v3.Treeview.Heading",
                        background=C_SURFACE,
                        foreground=C_TEXT_HINT,
                        font=("Segoe UI", 8, "bold"),
                        relief="flat",
                        borderwidth=0,
                        padding=(6, 5))
        style.map("v3.Treeview",
                  background=[("selected", C_ROW_SEL)],
                  foreground=[("selected", C_TEXT)])
        style.layout("v3.Treeview", [("v3.Treeview.treearea", {"sticky": "nswe"})])

        columns = ("Stage", "Time", "HF", "Rounds", "A", "C", "D", "M", "P", "NS")
        self.tree = ttk.Treeview(self, columns=columns, show="headings",
                                  style="v3.Treeview", selectmode="browse")

        # Column widths and headings
        self.tree.heading("Stage",  text="Stage",  anchor="w")
        self.tree.heading("Time",   text="Time",   anchor="center")
        self.tree.heading("HF",     text="HF",     anchor="center")
        self.tree.heading("Rounds", text="Rounds", anchor="center")
        for col in ("A", "C", "D", "M", "P", "NS"):
            self.tree.heading(col, text=col, anchor="center")

        self.tree.column("Stage",  anchor="w",      width=260, stretch=True)
        self.tree.column("Time",   anchor="center", width=80,  stretch=False)
        self.tree.column("HF",     anchor="center", width=80,  stretch=False)
        self.tree.column("Rounds", anchor="center", width=65,  stretch=False)
        for col in ("A", "C", "D", "M", "P", "NS"):
            self.tree.column(col, anchor="center", width=52, stretch=False)

        # Row colour tags — even/odd base, hover, HF colour applied via column tag trick
        self.tree.tag_configure("even", background=C_ROW_EVEN, foreground=C_TEXT)
        self.tree.tag_configure("odd",  background=C_ROW_ODD,  foreground=C_TEXT)
        self.tree.tag_configure("hover", background=C_ROW_HOVER, foreground=C_TEXT)

        self.tree.pack(fill="both", expand=True, padx=0, pady=0)

        self.tree.bind("<Double-1>",   self.on_edit_cell)
        self.tree.bind("<Motion>",     self._on_row_hover)
        self.tree.bind("<Leave>",      self._on_row_leave)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Accent border canvas — drawn over the left edge of the treeview
        # We achieve the left-border effect by painting a thin rectangle
        # in an overlay canvas that sits on top of the treeview's left edge.
        self._accent_canvas = tk.Canvas(self, width=3, bg=C_BG,
                                         highlightthickness=0, bd=0)
        self._accent_canvas.place(in_=self.tree, x=0, y=0, relheight=1)
        self._accent_rects = {}   # iid -> canvas rect id

    def _build_statusbar(self):
        sb = tk.Frame(self, bg=C_SURFACE, height=24)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)

        self._status_conn = tk.Label(sb, text="● not connected",
                                     bg=C_SURFACE, fg="#444444",
                                     font=("Segoe UI", 8))
        self._status_conn.pack(side="left", padx=(12, 16), pady=4)

        tk.Frame(sb, bg=C_BORDER, width=1).pack(side="left", fill="y", pady=4)

        self._status_time = tk.Label(sb, text="",
                                     bg=C_SURFACE, fg=C_TEXT_HINT,
                                     font=("Segoe UI", 8))
        self._status_time.pack(side="left", padx=12, pady=4)

    def _set_status_connected(self, connected: bool):
        if connected:
            self._status_conn.config(text="● connected", fg="#22c55e")
        else:
            self._status_conn.config(text="● not connected", fg="#444444")

    def _set_status_time(self):
        now = datetime.datetime.now().strftime("%H:%M")
        self._status_time.config(text=f"Last scraped {now}")

    # ----------------------------------------------------------
    # Hover / selection accent
    # ----------------------------------------------------------
    def _on_row_hover(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id == self._hovered_row:
            return
        # Restore previous hovered row
        if self._hovered_row and self._hovered_row in self.tree.get_children():
            sel = self.tree.selection()
            if self._hovered_row not in sel:
                idx = self.tree.index(self._hovered_row)
                tag = "even" if idx % 2 == 0 else "odd"
                self.tree.item(self._hovered_row, tags=(tag,))
        self._hovered_row = row_id
        if row_id:
            sel = self.tree.selection()
            if row_id not in sel:
                self.tree.item(row_id, tags=("hover",))
        self._repaint_accent()

    def _on_row_leave(self, event):
        if self._hovered_row and self._hovered_row in self.tree.get_children():
            sel = self.tree.selection()
            if self._hovered_row not in sel:
                idx = self.tree.index(self._hovered_row)
                tag = "even" if idx % 2 == 0 else "odd"
                self.tree.item(self._hovered_row, tags=(tag,))
        self._hovered_row = None
        self._repaint_accent()

    def _on_select(self, event):
        self._repaint_accent()

    def _repaint_accent(self):
        """Draw a 3px blue left border on the selected row (and dim one on hovered)."""
        self._accent_canvas.delete("all")
        row_h = 28  # must match rowheight in style
        sel = self.tree.selection()

        # Walk visible rows
        for iid in self.tree.get_children():
            bbox = self.tree.bbox(iid)
            if not bbox:
                continue
            _, y, _, h = bbox
            if iid in sel:
                self._accent_canvas.create_rectangle(0, y, 3, y + h,
                                                      fill=C_ACCENT, outline="")
            elif iid == self._hovered_row:
                self._accent_canvas.create_rectangle(0, y, 3, y + h,
                                                      fill="#3b5fc0", outline="")

    # ----------------------------------------------------------
    # Table population
    # ----------------------------------------------------------
    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        oc = get_overlay_colors()

        # Build per-column tag colours using a tag per colour-key per row.
        # tkinter Treeview doesn't support per-cell colours natively,
        # so we use a canvas overlay for the accent and rely on tag foreground
        # for the whole row. Instead we format coloured values with unicode
        # colour indicators — actually the cleanest approach for Treeview is
        # to just use row-level tags and accept whole-row colouring.
        # For per-cell hit colour we implement a thin Canvas overlay approach:
        # the Treeview renders text, and we let the row tags control row bg.
        # Hit column text colours are achieved by appending colour info below.

        for i, s in enumerate(self.stages):
            vals = (
                s.get("Stage", ""),
                f"{s.get('Time', 0):.2f}" if isinstance(s.get("Time", 0), (int, float)) else s.get("Time", ""),
                f"{s.get('HF', 0):.2f}"   if isinstance(s.get("HF",  0), (int, float)) else s.get("HF",  ""),
                s.get("Rounds", ""),
                s.get("A", 0), s.get("C", 0), s.get("D", 0),
                s.get("M", 0), s.get("P", 0), s.get("NS", 0),
            )
            tag = "even" if i % 2 == 0 else "odd"
            self.tree.insert("", "end", values=vals, tags=(tag,))

        # Auto-size Stage column
        import tkinter.font as tkfont
        row_font     = tkfont.Font(family="Segoe UI", size=10)
        heading_font = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        min_w = heading_font.measure("Stage") + 24
        max_w = max(
            (row_font.measure(str(s.get("Stage", ""))) for s in self.stages),
            default=min_w,
        )
        self.tree.column("Stage", width=max(min_w, max_w + 28))

        self._repaint_accent()

        # ── Per-cell hit colour overlay ──
        # Draw a transparent canvas on top of the treeview and paint
        # coloured text over the hit columns after the tree renders.
        self.after(50, self._paint_hit_colours)

    def _paint_hit_colours(self):
        """Overlay coloured text onto the hit-value cells using a Canvas."""
        # We use a single persistent overlay canvas; recreate it each refresh.
        if hasattr(self, "_hit_canvas"):
            self._hit_canvas.destroy()

        oc = get_overlay_colors()
        hit_cols   = ("A", "C", "D", "M", "P", "NS")
        hit_colors = {k: _rgb_to_hex(oc[k]) for k in hit_cols}
        hf_color   = C_HF

        cv = tk.Canvas(self.tree, bg="", highlightthickness=0, bd=0)
        cv.place(x=0, y=0, relwidth=1, relheight=1)
        cv.lower()   # below treeview selection highlight
        self._hit_canvas = cv

        row_h = 28
        font  = ("Segoe UI", 10)

        for iid in self.tree.get_children():
            bbox = self.tree.bbox(iid)
            if not bbox:
                continue
            _, row_y, _, _ = bbox
            text_y = row_y + row_h // 2

            # HF column
            hf_bbox = self.tree.bbox(iid, column="HF")
            if hf_bbox:
                cx = hf_bbox[0] + hf_bbox[2] // 2
                val = self.tree.set(iid, "HF")
                cv.create_text(cx, text_y, text=val, fill=hf_color,
                               font=font, anchor="center")

            # Hit columns
            for col in hit_cols:
                cell_bbox = self.tree.bbox(iid, column=col)
                if not cell_bbox:
                    continue
                cx   = cell_bbox[0] + cell_bbox[2] // 2
                val  = self.tree.set(iid, col)
                fill = hit_colors[col] if int(val or 0) > 0 else C_TEXT_HINT
                cv.create_text(cx, text_y, text=val, fill=fill,
                               font=font, anchor="center")

        # Hide the treeview's own text for HF and hit columns by making it
        # the same colour as the background (invisible) — we can't do this
        # per-column easily in ttk, so we leave the treeview text as-is and
        # raise our canvas above it to paint over it.
        cv.lift()

    # ----------------------------------------------------------
    # Scrape button state
    # ----------------------------------------------------------
    def _set_scrape_btn(self, enabled: bool):
        self._scrape_btn.configure(state="normal" if enabled else "disabled")

    # ----------------------------------------------------------
    # First-run
    # ----------------------------------------------------------
    def _show_first_run_welcome(self):
        messagebox.showinfo(
            "Welcome to SSI Scoring Overlay",
            "A default config.json has been created next to the application.\n\n"
            "Please open ⚙ Settings to enter your Shoot'n Score It username and password "
            "before scraping.",
        )
        SettingsWindow(self)

    # ----------------------------------------------------------
    # Actions — identical logic to v2.5
    # ----------------------------------------------------------
    def on_scrape(self):
        url = self.match_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Enter a match URL first.")
            return
        if not CONFIG.get("ssi_username") or not CONFIG.get("ssi_password"):
            messagebox.showerror(
                "Credentials missing",
                "No username or password set.\n\nPlease open ⚙ Settings and enter your "
                "Shoot'n Score It credentials before scraping.",
            )
            return

        self._set_scrape_btn(False)
        self._set_status_connected(False)

        def _run():
            try:
                stages = []
                debug_file = "debug_rows.csv"

                if DEBUG_MODE and os.path.exists(debug_file):
                    stages = scrape_scores_debug_from_csv(debug_file)
                    if DEBUG_MODE:
                        print("[DEBUG] Loaded stages from debug_rows.csv")

                if not stages:
                    self.session = create_logged_in_session()
                    stages = scrape_scores_live(self.session, url)
                    if DEBUG_MODE:
                        print("[INFO] Scraped stages online")

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
                        messagebox.showinfo("Success", f"DEBUG_MODE is ON — loaded {len(stages)} stages from {src}.")

                self.after(0, _done)

            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.error("Scraping failed: %s", e, exc_info=True)

                err_str = str(e)
                if "login" in err_str.lower() or "credential" in err_str.lower():
                    title = "Login failed"
                    msg = (
                        "Could not log in to Shoot'n Score It.\n\n"
                        "Please check your username and password in ⚙ Settings and try again."
                    )
                else:
                    title = "Scraping failed"
                    msg = (
                        "Something went wrong while fetching scores.\n\n"
                        "Check that the match URL is correct and that you have an internet connection.\n\n"
                        f"Detail: {err_str}"
                    )

                def _show_error(t=title, m=msg):
                    messagebox.showerror(t, m)
                    self._set_scrape_btn(True)

                self.after(0, _show_error)

        threading.Thread(target=_run, daemon=True).start()

    def on_edit_cell(self, event):
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or not col_id:
            return
        col_index = int(col_id.replace("#", "")) - 1
        col_name  = self.tree["columns"][col_index]

        bbox = self.tree.bbox(row_id, column=col_id)
        if not bbox:
            return
        x, y, width, height = bbox

        # Styled to match new UI
        entry = tk.Entry(self.tree,
                         bg="#181818", fg=C_TEXT,
                         insertbackground=C_TEXT,
                         relief="flat",
                         font=("Segoe UI", 10),
                         highlightbackground=C_ACCENT,
                         highlightthickness=1)
        entry.place(x=x, y=y, width=width, height=height)

        cur_val = self.tree.set(row_id, col_name)
        entry.insert(0, cur_val)
        entry.select_range(0, "end")
        entry.focus()

        def save_edit(event=None):
            new_val = entry.get()
            self.tree.set(row_id, col_name, new_val)
            entry.destroy()
            idx = self.tree.index(row_id)
            self.stages[idx][col_name] = new_val
            self.after(50, self._paint_hit_colours)

        entry.bind("<Return>",   save_edit)
        entry.bind("<FocusOut>", save_edit)
        entry.bind("<Escape>",   lambda e: entry.destroy())

    def on_preview(self):
        if not self.stages:
            messagebox.showwarning("No data", "Scrape first.")
            return
        sel = self.tree.selection()
        idx = self.tree.index(sel[0]) if sel else 0
        PreviewWindow(self, self.stages, idx)

    def on_export_csv(self):
        if not self.stages:
            messagebox.showwarning("No data", "Scrape first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
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
            safe_name = s.get("Stage", f"stage_{i}").replace(" ", "_").replace(".", "")
            outpath = outdir / f"{safe_name}.png"
            make_overlay(s, font_path=FONT_PATH, outpath=str(outpath))
        messagebox.showinfo("Export complete", f"Overlays saved to {outdir}")

    def on_settings(self):
        SettingsWindow(self)

    def on_close(self):
        CONFIG["window_geometry"] = self.geometry()
        CONFIG["last_match_url"]  = self.match_var.get().strip()
        save_config()
        self.destroy()


# ============================================================
# PREVIEW WINDOW  —  v3.0
# ============================================================

class PreviewWindow(tk.Toplevel):
    def __init__(self, master, stages, index):
        super().__init__(master)
        self.title("Overlay Preview")
        self.configure(bg=C_BG)

        self.stages = stages
        self.index  = index
        self.img_tk = None

        self.canvas = tk.Canvas(self, bg=C_BG, highlightthickness=0)
        self.canvas.pack(pady=(10, 0))

        btn_frame = tk.Frame(self, bg=C_BG)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="◀ Previous", command=self.prev_stage,    **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Next ▶",     command=self.next_stage,    **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Save PNG",   command=self.save_current_png, **BTN_PRIMARY).pack(side="left", padx=6)

        self.bind("<Left>",   lambda e: self.prev_stage())
        self.bind("<Right>",  lambda e: self.next_stage())
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("s",        lambda e: self.save_current_png())
        self.focus_set()

        self.show_stage()

    def _load_display_image(self):
        pil_img = make_overlay(self.stages[self.index], font_path=FONT_PATH, outpath=None)
        if pil_img.width > MAX_PREVIEW_WIDTH:
            new_h = int(pil_img.height * MAX_PREVIEW_WIDTH / pil_img.width)
            return pil_img.resize((MAX_PREVIEW_WIDTH, new_h), Image.LANCZOS)
        return pil_img

    def show_stage(self):
        display     = self._load_display_image()
        self.img_tk = ImageTk.PhotoImage(display)
        img_w, img_h = display.size

        self.canvas.config(width=img_w, height=img_h)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.img_tk, anchor="nw")

        geom_w = max(img_w + 40, 500)
        geom_h = img_h + PREVIEW_BTN_EXTRA_HEIGHT
        self.geometry(f"{geom_w}x{geom_h}")

        s = self.stages[self.index]
        self.title(f"Overlay Preview — {s.get('Stage', '')}")

    def save_current_png(self):
        s         = self.stages[self.index]
        safe_name = s.get("Stage", f"stage_{self.index}").replace(" ", "_").replace(".", "")
        path      = filedialog.asksaveasfilename(
            defaultextension=".png", initialfile=f"{safe_name}.png",
            filetypes=[("PNG files", "*.png")]
        )
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
# SETTINGS WINDOW  —  v3.0
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
        self.grab_set()

        self._vars         = {}
        self._show_pw      = {}
        self._color_values = {}
        self._color_swatches = {}

        LABEL_W = 18
        ENTRY_W = 46

        lbl_cfg = dict(bg="#111111", fg=C_TEXT, anchor="w",
                       width=LABEL_W, font=("Segoe UI", 9))
        entry_cfg = dict(bg="#1a1a1a", fg=C_TEXT_DIM,
                         insertbackground=C_TEXT_DIM,
                         relief="flat", font=("Segoe UI", 9), width=ENTRY_W,
                         highlightbackground=C_BORDER2, highlightthickness=1)
        pad_x, pad_y = 16, 5

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
                               ).grid(row=row_i, column=1, padx=(0, pad_x), pady=pad_y, sticky="w")

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
                            result = filedialog.askopenfilename(
                                title="Select font file",
                                filetypes=[("Font files", "*.ttf *.otf"), ("All files", "*.*")],
                                initialfile=v.get() or "",
                            )
                        else:
                            result = filedialog.askdirectory(
                                title="Select output directory",
                                initialdir=v.get() or ".",
                            )
                        if result:
                            v.set(result)
                    return _browse

                tk.Button(frame, text="Browse…", command=_make_browse(),
                          **BTN_STYLE).pack(side="left", padx=(6, 0))

            else:
                var = tk.StringVar(value=str(current))
                self._vars[key] = var
                tk.Entry(self, textvariable=var, **entry_cfg).grid(
                    row=row_i, column=1, padx=(0, pad_x), pady=pad_y, sticky="w")

        # Color section
        fields_count  = len(self._FIELDS)
        color_sep_row = fields_count

        ttk.Separator(self, orient="horizontal").grid(
            row=color_sep_row, column=0, columnspan=2,
            sticky="ew", padx=pad_x, pady=(10, 4))
        tk.Label(self, text="Overlay Colors", bg="#111111", fg="white",
                 font=("Segoe UI", 9, "bold")).grid(
            row=color_sep_row + 1, column=0, columnspan=2,
            padx=pad_x, pady=(2, 4), sticky="w")

        current_colors = get_overlay_colors()
        for i, (ckey, clabel) in enumerate(self._COLOR_LABELS):
            row  = color_sep_row + 2 + i
            rgba = current_colors[ckey]
            self._color_values[ckey] = list(rgba)

            tk.Label(self, text=clabel + ":", **lbl_cfg).grid(
                row=row, column=0, padx=(pad_x, 8), pady=(2, 2), sticky="w")

            frame   = tk.Frame(self, bg="#111111")
            frame.grid(row=row, column=1, padx=(0, pad_x), pady=(2, 2), sticky="w")

            hex_col = _rgb_to_hex(rgba)
            swatch  = tk.Label(frame, bg=hex_col, width=4, relief="solid",
                               borderwidth=1, cursor="hand2")
            swatch.pack(side="left", ipady=5, padx=(0, 8))
            self._color_swatches[ckey] = swatch
            swatch.bind("<Button-1>", lambda e, k=ckey: self._pick_color(k))

            alpha_part = f", A:{rgba[3]}" if len(rgba) == 4 else ""
            rgb_label  = tk.Label(frame,
                                  text=f"R:{rgba[0]}  G:{rgba[1]}  B:{rgba[2]}{alpha_part}",
                                  bg="#111111", fg="#888888",
                                  font=("Segoe UI", 8), width=28, anchor="w")
            rgb_label.pack(side="left")

            tk.Button(frame, text="Change…", command=lambda k=ckey: self._pick_color(k),
                      **BTN_STYLE).pack(side="left")

        reset_row = color_sep_row + 2 + len(self._COLOR_LABELS)
        tk.Button(self, text="Reset colors to defaults",
                  command=self._reset_colors, **BTN_STYLE).grid(
            row=reset_row, column=0, columnspan=2, pady=(6, 2))

        sep_row = reset_row + 1
        ttk.Separator(self, orient="horizontal").grid(
            row=sep_row, column=0, columnspan=2,
            sticky="ew", padx=pad_x, pady=(8, 4))

        btn_frame = tk.Frame(self, bg="#111111")
        btn_frame.grid(row=sep_row + 1, column=0, columnspan=2, pady=(4, 12))
        tk.Button(btn_frame, text="Save",   width=10, command=self._save,    **BTN_PRIMARY).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Cancel", width=10, command=self.destroy,  **BTN_STYLE).pack(side="left", padx=8)

        self.bind("<Escape>", lambda e: self.destroy())

        self.update_idletasks()
        mx = master.winfo_x() + master.winfo_width()  // 2
        my = master.winfo_y() + master.winfo_height() // 2
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{mx - w // 2}+{my - h // 2}")

    def _pick_color(self, k):
        current_rgb = self._color_values[k][:3]
        init_hex    = _rgb_to_hex(self._color_values[k])
        result      = colorchooser.askcolor(color=init_hex, title=f"Choose color — {k}", parent=self)
        if not result or not result[0]:
            return
        r, g, b = (int(x) for x in result[0])
        alpha   = self._color_values[k][3] if len(self._color_values[k]) == 4 else None
        self._color_values[k] = [r, g, b] + ([alpha] if alpha is not None else [])
        sw = self._color_swatches[k]
        sw.config(bg="#{:02x}{:02x}{:02x}".format(r, g, b))
        alpha_part = f", A:{alpha}" if alpha is not None else ""
        for widget in sw.master.winfo_children():
            if isinstance(widget, tk.Label) and widget is not sw:
                widget.config(text=f"R:{r}  G:{g}  B:{b}{alpha_part}")
                break

    def _reset_colors(self):
        for ckey, default in DEFAULT_COLORS.items():
            self._color_values[ckey] = list(default)
            r, g, b = default[0], default[1], default[2]
            alpha   = default[3] if len(default) == 4 else None
            if ckey in self._color_swatches:
                self._color_swatches[ckey].config(bg="#{:02x}{:02x}{:02x}".format(r, g, b))
            for widget in self._color_swatches[ckey].master.winfo_children():
                if isinstance(widget, tk.Label) and widget is not self._color_swatches[ckey]:
                    alpha_part = f", A:{alpha}" if alpha is not None else ""
                    widget.config(text=f"R:{r}  G:{g}  B:{b}{alpha_part}")
                    break

    def _save(self):
        for key, var in self._vars.items():
            value = var.get()
            if isinstance(var, tk.BooleanVar):
                CONFIG[key] = bool(value)
            else:
                CONFIG[key] = str(value).strip()
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