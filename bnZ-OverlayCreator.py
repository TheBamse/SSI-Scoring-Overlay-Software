#!/usr/bin/env python3
"""
bnZ-OverlayCreator.py  —  Baseline v7.4

Fixes applied over v7.3:
- Scrape button re-enable handled explicitly per path (no finally race)
- Friendly error dialogs for login failure vs network/other errors
- NameError on lambda capture of except variable fixed
"""

from pathlib import Path
import os
import sys
import json
import csv
import logging
import threading
import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
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
# App directory helper (works for both script and PyInstaller .exe)
# ------------------------
def app_dir():
    """Return the directory next to the running script or .exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


# ------------------------
# Logging setup
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

if not CONFIG_FILE.exists():
    raise FileNotFoundError(
        f"Missing config.json in the same directory as the script/exe ({CONFIG_FILE})"
    )

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

def cfg_get(key, default=None):
    return CONFIG.get(key, default)

SSI_USERNAME = cfg_get("ssi_username")
SSI_PASSWORD = cfg_get("ssi_password")
FONT_PATH = resource_path(cfg_get("font_path", "DejaVuSans-Bold.ttf"))
OUTPUT_DIR = Path(cfg_get("output_dir", "overlays"))
OUTPUT_WIDTH = int(cfg_get("output_width", 1920))
LAST_MATCH_URL = cfg_get("last_match_url", "")
WINDOW_GEOMETRY = cfg_get("window_geometry", None)
DEBUG_MODE = bool(cfg_get("debug_mode", False))

if not SSI_USERNAME or not SSI_PASSWORD:
    raise ValueError("Missing 'ssi_username'/'ssi_password' in config.json.")

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

BTN_STYLE = dict(
    bg="#3a3a3a", fg="white",
    activebackground="#505050",
    relief="flat", padx=10, pady=4
)

# ------------------------
# SCRAPER
# ------------------------
def create_logged_in_session():
    # The login form POSTs directly — no CSRF token, no prior GET needed.
    # Success: the session is redirected to /dashboard/
    # Failure: the URL stays on /login/
    LOGIN_POST_URL = "https://shootnscoreit.com/login/?next=https://shootnscoreit.com/dashboard/"

    session = requests.Session()
    rpost = session.post(
        LOGIN_POST_URL,
        data={
            "username": SSI_USERNAME,
            "password": SSI_PASSWORD,
            "keep": "on",
        },
        headers={"Referer": LOGIN_URL},
        timeout=15,
    )

    # requests follows the redirect automatically; check where we landed
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
    """Parse a single row of columns into a stage dict. Returns None on failure."""
    if len(cols) < 10:
        return None
    if cols[0].lower().startswith(("total", "summary")):
        return None
    try:
        return {
            "Stage": cols[0],
            "HF": round(float(cols[1]) if cols[1] else 0.0, 2),
            "Time": float(cols[2]) if cols[2] else 0.0,
            "Rounds": "",
            "A": int(cols[4]) if cols[4] else 0,
            "C": int(cols[5]) if cols[5] else 0,
            "D": int(cols[6]) if cols[6] else 0,
            "M": int(cols[7]) if cols[7] else 0,
            "P": int(cols[8]) if cols[8] else 0,
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
    """Return a copy of stage with all numeric fields cast to their proper types."""
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

    colors = {
        "A": (50, 205, 50),
        "C": (255, 165, 0),
        "D": (255, 105, 180),
        "M": (220, 20, 60),
        "NS": (138, 43, 226),
        "P": (255, 215, 0),
    }
    bg_color = (40, 40, 40, 220)
    outline_color = (255, 255, 255, 255)

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

    # Reuse a single dummy draw for all textbbox measurements
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


# ------------------------
# GUI
# ------------------------
class ScoringApp(tk.Tk):
    def __init__(self):
        super().__init__()

        # --- Enable dark title bar on Windows ---
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.FindWindowW(None, self.title())
            if hwnd:
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                set_dark_mode = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    DWMWA_USE_IMMERSIVE_DARK_MODE,
                    ctypes.byref(set_dark_mode),
                    ctypes.sizeof(set_dark_mode)
                )
        except Exception:
            pass

        self.title("SSI Scoring Overlay Software")
        self.configure(bg="#1e1e1e")
        if WINDOW_GEOMETRY:
            self.geometry(WINDOW_GEOMETRY)
        else:
            self.geometry("1100x700")

        self.session = None
        self.stages = []

        # Top controls
        top = tk.Frame(self, bg="#1e1e1e")
        top.pack(fill="x", padx=8, pady=6)

        tk.Label(top, text="Match URL:", bg="#1e1e1e", fg="white").pack(side="left")
        self.match_var = tk.StringVar(value=LAST_MATCH_URL)
        self.entry_url = tk.Entry(top, textvariable=self.match_var, width=80,
                                  bg="#2d2d2d", fg="white", insertbackground="white")
        self.entry_url.pack(side="left", padx=(6, 8), fill="x", expand=True)

        tk.Button(top, text="Scrape", command=self.on_scrape, **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(top, text="Preview Overlay", command=self.on_preview, **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(top, text="Export CSV", command=self.on_export_csv, **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(top, text="Export Overlays", command=self.on_export_overlays, **BTN_STYLE).pack(side="left", padx=6)
        tk.Button(top, text="⚙ Settings", command=self.on_settings, **BTN_STYLE).pack(side="left", padx=6)

        # Dark-themed table
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Dark.Treeview",
                        background="#1e1e1e", fieldbackground="#1e1e1e",
                        foreground="white", rowheight=26, font=("Segoe UI", 11))
        style.configure("Dark.Treeview.Heading",
                        background="#2d2d2d", foreground="white", font=("Segoe UI", 12, "bold"))
        style.map("Dark.Treeview", background=[("selected", "#144870")])

        style.configure("Dark.Vertical.TScrollbar",
                        background="#2d2d2d", troughcolor="#1e1e1e", bordercolor="#1e1e1e")
        style.configure("Dark.Horizontal.TScrollbar",
                        background="#2d2d2d", troughcolor="#1e1e1e", bordercolor="#1e1e1e")

        columns = ("Stage", "Time", "HF", "Rounds", "A", "C", "D", "M", "NS", "P")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", style="Dark.Treeview")

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=110)

        self.tree.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        self.tree.tag_configure("darkrow", background="#1e1e1e", foreground="white")
        self.tree.tag_configure("altrow", background="#252526", foreground="white")
        self.tree.bind("<Double-1>", self.on_edit_cell)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.stages):
            vals = (
                s.get("Stage", ""),
                f"{s.get('Time', 0):.2f}" if isinstance(s.get("Time", 0), (int, float)) else s.get("Time", ""),
                f"{s.get('HF', 0):.2f}" if isinstance(s.get("HF", 0), (int, float)) else s.get("HF", ""),
                s.get("Rounds", ""),
                s.get("A", 0), s.get("C", 0), s.get("D", 0),
                s.get("M", 0), s.get("NS", 0), s.get("P", 0),
            )
            tag = "darkrow" if i % 2 == 0 else "altrow"
            self.tree.insert("", "end", values=vals, tags=(tag,))

        # Auto-size the Stage column to the longest name, with padding
        import tkinter.font as tkfont
        row_font = tkfont.Font(family="Segoe UI", size=11)
        heading_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        min_w = heading_font.measure("Stage") + 20
        max_w = max(
            (row_font.measure(str(s.get("Stage", ""))) for s in self.stages),
            default=min_w,
        )
        self.tree.column("Stage", width=max(min_w, max_w + 24))

    def _set_scrape_btn(self, enabled: bool):
        """Enable or disable the Scrape button. Must be called from the main thread."""
        state = "normal" if enabled else "disabled"
        for widget in self.winfo_children():
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Button) and child["text"] == "Scrape":
                        child.configure(state=state)

    def on_scrape(self):
        url = self.match_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Enter a match URL first.")
            return

        self._set_scrape_btn(False)

        def _run():
            # No finally block — each exit path re-enables the button explicitly.
            # A finally would always fire immediately, racing against blocking dialogs.
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
                    # No data — show dialog, then re-enable
                    def _no_data():
                        messagebox.showerror("No data", "No valid stages found at that URL.")
                        self._set_scrape_btn(True)
                    self.after(0, _no_data)
                    return

                # Success — populate table, then re-enable
                def _done():
                    self.stages = stages
                    self._refresh_table()
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

                # Capture values now; re-enable the button after the dialog is dismissed
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
        col_name = self.tree["columns"][col_index]

        bbox = self.tree.bbox(row_id, column=col_id)
        if not bbox:
            return
        x, y, width, height = bbox
        entry = tk.Entry(self.tree, bg="#2d2d2d", fg="white", insertbackground="white", relief="flat")
        entry.place(x=x, y=y, width=width, height=height)

        cur_val = self.tree.set(row_id, col_name)
        entry.insert(0, cur_val)
        entry.focus()

        def save_edit(event=None):
            new_val = entry.get()
            self.tree.set(row_id, col_name, new_val)
            entry.destroy()
            idx = self.tree.index(row_id)
            self.stages[idx][col_name] = new_val

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    def on_preview(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("No selection", "Select a stage first.")
            return
        idx = self.tree.index(sel[0])
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
        CONFIG["last_match_url"] = self.match_var.get().strip()
        save_config()
        self.destroy()


# ------------------------
# PREVIEW WINDOW
# ------------------------
class PreviewWindow(tk.Toplevel):
    def __init__(self, master, stages, index):
        super().__init__(master)
        self.title("Overlay Preview")
        self.configure(bg="#1e1e1e")

        self.stages = stages
        self.index = index

        self.img_tk = None
        self.canvas = tk.Canvas(self, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(pady=(10, 0))

        btn_frame = tk.Frame(self, bg="#1e1e1e")
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="◀ Previous", command=self.prev_stage, **BTN_STYLE).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Next ▶", command=self.next_stage, **BTN_STYLE).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Save PNG", command=self.save_current_png, **BTN_STYLE).pack(side="left", padx=8)

        self.bind("<Left>", lambda e: self.prev_stage())
        self.bind("<Right>", lambda e: self.next_stage())
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("s", lambda e: self.save_current_png())
        self.focus_set()

        self.show_stage()

    def _load_display_image(self):
        """Render the current stage and return a display-ready PIL image."""
        pil_img = make_overlay(self.stages[self.index], font_path=FONT_PATH, outpath=None)
        if pil_img.width > MAX_PREVIEW_WIDTH:
            new_h = int(pil_img.height * MAX_PREVIEW_WIDTH / pil_img.width)
            return pil_img.resize((MAX_PREVIEW_WIDTH, new_h), Image.LANCZOS)
        return pil_img

    def show_stage(self):
        display = self._load_display_image()
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
        s = self.stages[self.index]
        safe_name = s.get("Stage", f"stage_{self.index}").replace(" ", "_").replace(".", "")
        path = filedialog.asksaveasfilename(defaultextension=".png", initialfile=f"{safe_name}.png",
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


# ------------------------
# SETTINGS WINDOW
# ------------------------
class SettingsWindow(tk.Toplevel):
    # Fields shown in the dialog, in order.
    # Each entry: (config_key, label_text, field_type)
    # field_type: "text" | "password" | "path" | "bool"
    _FIELDS = [
        ("ssi_username",   "SSI Username",   "text"),
        ("ssi_password",   "SSI Password",   "password"),
        ("font_path",      "Font Path",      "path"),
        ("output_dir",     "Output Dir",     "path"),
        ("debug_mode",     "Debug Mode",     "bool"),
    ]

    def __init__(self, master):
        super().__init__(master)
        self.title("Settings")
        self.configure(bg="#1e1e1e")
        self.resizable(False, False)

        # Keep on top of main window
        self.transient(master)
        self.grab_set()

        self._vars = {}       # config_key -> tk variable
        self._show_pw = {}    # config_key -> bool (password visibility toggle)

        LABEL_W = 18
        ENTRY_W = 48

        lbl_cfg = dict(bg="#1e1e1e", fg="white", anchor="w",
                       width=LABEL_W, font=("Segoe UI", 10))
        entry_cfg = dict(bg="#2d2d2d", fg="white", insertbackground="white",
                         relief="flat", font=("Segoe UI", 10), width=ENTRY_W)

        pad_x, pad_y = 16, 6

        for row_i, (key, label, ftype) in enumerate(self._FIELDS):
            current = CONFIG.get(key, "")

            tk.Label(self, text=label + ":", **lbl_cfg).grid(
                row=row_i, column=0, padx=(pad_x, 8), pady=pad_y, sticky="w"
            )

            if ftype == "bool":
                var = tk.BooleanVar(value=bool(current))
                self._vars[key] = var
                tk.Checkbutton(
                    self, variable=var,
                    bg="#1e1e1e", fg="white",
                    activebackground="#1e1e1e", activeforeground="white",
                    selectcolor="#2d2d2d", relief="flat"
                ).grid(row=row_i, column=1, padx=(0, pad_x), pady=pad_y, sticky="w")

            elif ftype == "password":
                var = tk.StringVar(value=str(current))
                self._vars[key] = var
                show_var = tk.BooleanVar(value=False)
                self._show_pw[key] = show_var

                frame = tk.Frame(self, bg="#1e1e1e")
                frame.grid(row=row_i, column=1, padx=(0, pad_x), pady=pad_y, sticky="w")

                entry = tk.Entry(frame, textvariable=var, show="●", **entry_cfg)
                entry.pack(side="left")

                def _make_toggle(e=entry, sv=show_var):
                    def _toggle():
                        e.config(show="" if sv.get() else "●")
                    return _toggle

                toggle_btn = tk.Button(
                    frame, text="Show", width=5,
                    command=lambda sv=show_var, e=entry, btn_ref=[None]: (
                        sv.set(not sv.get()),
                        e.config(show="" if sv.get() else "●"),
                    ),
                    **BTN_STYLE
                )
                toggle_btn.pack(side="left", padx=(6, 0))

            elif ftype == "path":
                var = tk.StringVar(value=str(current))
                self._vars[key] = var

                frame = tk.Frame(self, bg="#1e1e1e")
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

                tk.Button(frame, text="Browse…", command=_make_browse(), **BTN_STYLE).pack(
                    side="left", padx=(6, 0)
                )

            else:  # "text"
                var = tk.StringVar(value=str(current))
                self._vars[key] = var
                tk.Entry(self, textvariable=var, **entry_cfg).grid(
                    row=row_i, column=1, padx=(0, pad_x), pady=pad_y, sticky="w"
                )

        # Separator
        sep_row = len(self._FIELDS)
        ttk.Separator(self, orient="horizontal").grid(
            row=sep_row, column=0, columnspan=2,
            sticky="ew", padx=pad_x, pady=(8, 4)
        )

        # Buttons row
        btn_frame = tk.Frame(self, bg="#1e1e1e")
        btn_frame.grid(row=sep_row + 1, column=0, columnspan=2, pady=(4, 12))
        tk.Button(btn_frame, text="Save", width=10, command=self._save, **BTN_STYLE).pack(
            side="left", padx=8
        )
        tk.Button(btn_frame, text="Cancel", width=10, command=self.destroy, **BTN_STYLE).pack(
            side="left", padx=8
        )

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

        # Centre over the main window
        self.update_idletasks()
        mx = master.winfo_x() + master.winfo_width() // 2
        my = master.winfo_y() + master.winfo_height() // 2
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{mx - w // 2}+{my - h // 2}")

    def _save(self):
        for key, var in self._vars.items():
            value = var.get()
            # Persist the correct Python type for booleans
            if isinstance(var, tk.BooleanVar):
                CONFIG[key] = bool(value)
            else:
                CONFIG[key] = str(value).strip()

        save_config()
        messagebox.showinfo(
            "Settings saved",
            "Settings have been saved to config.json.\n\n"
            "Changes to username, password, font path, and output directory\n"
            "will take effect the next time you start the application.",
            parent=self,
        )
        self.destroy()


# ------------------------
# MAIN
# ------------------------
if __name__ == "__main__":
    app = ScoringApp()
    app.mainloop()