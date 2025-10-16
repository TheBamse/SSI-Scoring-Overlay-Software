#!/usr/bin/env python3
"""
scoring_ui_dark.py
Option 3: Dark Mode Focus GUI for SSI Scoring Scraper
- Reads config.json (same keys as baseline v3)
- Supports DEBUG_MODE -> debug_rows.csv
- Editable table, inline cell editing
- Preview pane on the right with overlay rendering
- Export CSV and Export Overlays
- Overlay rendering uses 20px pill padding + 400px top transparent padding
"""

import io
import json
import csv
import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageTk
import math
import sys
import os

# ------------------------
# CONFIG
# ------------------------
CONFIG_FILE = "config.json"
if not Path(CONFIG_FILE).exists():
    raise FileNotFoundError("Missing config.json (ssi_username, ssi_password, font_path, output_dir).")

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)


def cfg_get(key, default=None):
    return CONFIG.get(key, default)


SSI_USERNAME = cfg_get("ssi_username")
SSI_PASSWORD = cfg_get("ssi_password")
FONT_PATH = cfg_get("font_path", "DejaVuSans-Bold.ttf")
OUTPUT_DIR = Path(cfg_get("output_dir", "overlays"))
LAST_MATCH_URL = cfg_get("last_match_url", "")
WINDOW_GEOMETRY = cfg_get("window_geometry", None)
DEBUG_MODE = bool(cfg_get("debug_mode", False))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------
# SCRAPER (same approach as baseline)
# ------------------------
LOGIN_URL = "https://shootnscoreit.com/login/"


def create_logged_in_session():
    session = requests.Session()
    rget = session.get(LOGIN_URL, timeout=10)
    soup = BeautifulSoup(rget.text, "html.parser")
    payload = {}
    token_input = soup.find("input", {"name": "csrfmiddlewaretoken"}) or soup.find("input", {"name": "csrf_token"})
    if token_input and token_input.get("value"):
        payload[token_input.get("name")] = token_input.get("value")
    payload["username"] = SSI_USERNAME
    payload["password"] = SSI_PASSWORD
    headers = {"Referer": LOGIN_URL}
    rpost = session.post(LOGIN_URL, data=payload, headers=headers, timeout=15)
    body = (rpost.text or "").lower()
    if ("logout" not in body) and ("sign out" not in body) and ("incorrect" in body or rpost.status_code >= 400):
        raise RuntimeError("SSI login failed — check credentials in config.json")
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


def scrape_scores_live(session, match_url):
    r = session.get(match_url, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    rows = _parse_table_rows_from_soup(soup)
    stages = []
    for cols in rows:
        if len(cols) < 10:
            continue
        if cols[0].lower().startswith(("total", "summary")):
            continue
        try:
            stage = {
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
            stages.append(stage)
        except Exception:
            continue
    return stages


def scrape_scores_debug_from_csv(csv_path="debug_rows.csv"):
    stages = []
    if not Path(csv_path).exists():
        return stages
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 10:
                continue
            try:
                stage = {
                    "Stage": row[0],
                    "HF": round(float(row[1]) if row[1] else 0.0, 2),
                    "Time": float(row[2]) if row[2] else 0.0,
                    "Rounds": "",
                    "A": int(row[4]) if row[4] else 0,
                    "C": int(row[5]) if row[5] else 0,
                    "D": int(row[6]) if row[6] else 0,
                    "M": int(row[7]) if row[7] else 0,
                    "P": int(row[8]) if row[8] else 0,
                    "NS": int(row[9]) if row[9] else 0,
                }
                stages.append(stage)
            except Exception:
                continue
    return stages


def scrape_scores(session, match_url):
    if DEBUG_MODE:
        return scrape_scores_debug_from_csv()
    return scrape_scores_live(session, match_url)


# ------------------------
# OVERLAY generation (matching baseline style)
# ------------------------
def make_overlay(stage_info, font_path=FONT_PATH, outpath=None, output_size=(2000, 300)):
    # create canvas with extra 400px height for top padding
    width, height = output_size
    img = Image.new("RGBA", (width, height + 400), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font_value = ImageFont.truetype(font_path, 32)
    except Exception:
        font_value = ImageFont.load_default()

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

    def draw_pill_exact(x, y, label, value=None, color="white", hpad=20, vpad=20, radius=18):
        text = str(label) if value is None else f"{label}: {value}"
        minx, miny, maxx, maxy = draw.textbbox((0, 0), text, font=font_value)
        text_w = maxx - minx
        text_h = maxy - miny
        pill_w = int(text_w + 2 * hpad)
        pill_h = int(text_h + 2 * vpad)

        draw.rounded_rectangle([x, y, x + pill_w, y + pill_h],
                               radius=radius, outline=outline_color, width=2, fill=bg_color)
        draw_x = x + hpad - minx
        draw_y = y + vpad - miny
        draw.text((draw_x, draw_y), text, font=font_value, fill=color)
        return pill_w, pill_h

    # layout
    x = 20
    spacing = 20
    y = 400  # top transparent padding
    max_h = 0

    # Stage, Time, HF, optional Rounds
    w, h = draw_pill_exact(x, y, stage_info.get("Stage", ""), None, "white"); x += w + spacing; max_h = max(max_h, h)
    w, h = draw_pill_exact(x, y, "Time", f"{float(stage_info.get('Time', 0)):.2f}", "white"); x += w + spacing; max_h = max(max_h, h)
    w, h = draw_pill_exact(x, y, "HF", f"{float(stage_info.get('HF', 0)):.2f}", "white"); x += w + spacing; max_h = max(max_h, h)

    if stage_info.get("Rounds"):
        w, h = draw_pill_exact(x, y, "Rounds", stage_info["Rounds"], "white"); x += w + spacing; max_h = max(max_h, h)

    for key in ("A", "C", "D", "M", "NS", "P"):
        w, h = draw_pill_exact(x, y, key, stage_info.get(key, 0), colors.get(key, "white"))
        x += w + spacing
        max_h = max(max_h, h)

    # crop to content (keep left padding and same right padding)
    right_edge = x - spacing
    bottom_edge = y + max_h
    crop_box = (0, 0, right_edge + 20, bottom_edge + 20)
    img = img.crop(crop_box)
    if outpath is None:
        return img
    img.save(outpath, "PNG")
    return outpath


# ------------------------
# Dark theme helpers
# ------------------------
DARK_BG = "#0f1518"
CARD_BG = "#15191c"
PILL_BG = "#1f2629"
TEXT = "#e6eef2"
SUBTEXT = "#b9c3c8"
ACCENT = "#3b82f6"
BTN_BG = "#1b2226"
OUTLINE = "#2b3336"


def setup_dark_style(root):
    style = ttk.Style(root)
    # use clam for easier widget color customization
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=DARK_BG)
    style.configure("TLabel", background=DARK_BG, foreground=TEXT, font=("Segoe UI", 11))
    style.configure("Header.TLabel", font=("Segoe UI", 18, "bold"))
    style.configure("TButton", background=BTN_BG, foreground=TEXT, relief="flat", padding=8)
    style.map("TButton",
              background=[("active", OUTLINE)])
    style.configure("Treeview", background=CARD_BG, fieldbackground=CARD_BG, foreground=TEXT, rowheight=30,
                    font=("Segoe UI", 11))
    style.configure("Treeview.Heading", background=CARD_BG, foreground=SUBTEXT, font=("Segoe UI", 11, "bold"))
    style.layout("TButton", [('Button.border', {'sticky': 'nswe', 'children':
        [('Button.padding', {'sticky': 'nswe', 'children':
            [('Button.label', {'sticky': 'nswe'})]})]})])


# ------------------------
# GUI App
# ------------------------
class DarkScoringApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SSI Scoring Scraper — Dark")
        if WINDOW_GEOMETRY:
            self.geometry(WINDOW_GEOMETRY)
        else:
            self.geometry("1300x800")
        self.configure(bg=DARK_BG)

        setup_dark_style(self)

        self.session = None
        self.stages = []

        # Top toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=10)

        tk.Label(toolbar, text="Match URL:", background=DARK_BG, foreground=TEXT).pack(side="left", padx=(6, 6))
        self.match_var = tk.StringVar(value=LAST_MATCH_URL)
        self.entry_url = tk.Entry(toolbar, textvariable=self.match_var, width=70,
                                  bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat")
        self.entry_url.pack(side="left", padx=(0, 10))

        self.btn_scrape = ttk.Button(toolbar, text="Scrape", command=self.on_scrape)
        self.btn_preview = ttk.Button(toolbar, text="Preview Overlay", command=self.on_preview)
        self.btn_export_csv = ttk.Button(toolbar, text="Export CSV", command=self.on_export_csv)
        self.btn_export_ovs = ttk.Button(toolbar, text="Export Overlays", command=self.on_export_overlays)

        for b in (self.btn_scrape, self.btn_preview, self.btn_export_csv, self.btn_export_ovs):
            b.pack(side="left", padx=6)

        # Main area: left table, right preview pane
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        left = ttk.Frame(main)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right = ttk.Frame(main, width=380)
        right.pack(side="right", fill="y")

        # Treeview (table)
        columns = ("Stage", "Time", "HF", "Rounds", "A", "C", "D", "M", "NS", "P")
        self.tree = ttk.Treeview(left, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=100)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.on_edit_cell)

        # Right preview card
        preview_card = tk.Frame(right, bg=CARD_BG, bd=0, highlightthickness=0)
        preview_card.pack(fill="both", expand=False, padx=6, pady=6)

        self.preview_title = tk.Label(preview_card, text="Stage preview", bg=CARD_BG, fg=TEXT,
                                      font=("Segoe UI", 16, "bold"))
        self.preview_title.pack(pady=(14, 8))

        # Canvas to show overlay image
        self.preview_canvas = tk.Canvas(preview_card, bg=CARD_BG, highlightthickness=0)
        self.preview_canvas.pack(padx=16, pady=(0, 16))

        # preview pills frame for textual representation
        pills_frame = tk.Frame(preview_card, bg=CARD_BG)
        pills_frame.pack(fill="x", padx=12, pady=(0, 12))

        self.pill_labels = {}
        for k in ("Time", "HF", "Rounds", "A", "C", "D", "M", "NS", "P"):
            lbl = tk.Label(pills_frame, text=f"{k}: —", bg=PILL_BG, fg=TEXT, padx=10, pady=8, relief="groove")
            lbl.pack(fill="x", pady=4)
            self.pill_labels[k] = lbl

        # Close preview button
        close_btn = ttk.Button(preview_card, text="Close Preview", command=self._clear_preview)
        close_btn.pack(pady=(8, 12), padx=12, fill="x")

        # keyboard binding to allow Esc to clear preview if preview canvas is focused
        self.bind_all("<Escape>", lambda e: self._clear_preview())

        # status bar
        self.status = tk.Label(self, text="", bg=DARK_BG, fg=SUBTEXT, anchor="w")
        self.status.pack(fill="x", side="bottom", padx=12, pady=(0, 8))

    # ------------------------
    # Table refresh / helpers
    # ------------------------
    def _refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        for s in self.stages:
            vals = (
                s.get("Stage", ""),
                f"{s.get('Time', 0):.2f}" if isinstance(s.get("Time", 0), (int, float)) else s.get("Time", ""),
                f"{s.get('HF', 0):.2f}" if isinstance(s.get("HF", 0), (int, float)) else s.get("HF", ""),
                s.get("Rounds", ""),
                s.get("A", 0), s.get("C", 0), s.get("D", 0),
                s.get("M", 0), s.get("NS", 0), s.get("P", 0),
            )
            self.tree.insert("", "end", values=vals)

    # ------------------------
    # Scrape button
    # ------------------------
    def on_scrape(self):
        url = self.match_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Enter a match URL first.")
            return
        try:
            if not DEBUG_MODE:
                self.session = create_logged_in_session()
            self.stages = scrape_scores(self.session, url)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return
        if not self.stages:
            messagebox.showinfo("No data", "No valid stages found.")
            return
        self._refresh_table()
        CONFIG["last_match_url"] = url
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, indent=2)
        self.status.config(text=f"Scraped {len(self.stages)} stages.")

    # ------------------------
    # Inline cell editing
    # ------------------------
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
        entry = tk.Entry(self.tree, bg=CARD_BG, fg=TEXT, insertbackground=TEXT, relief="flat")
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
            self.status.config(text=f"Edited {col_name} for row {idx+1}")

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    # ------------------------
    # Preview overlay (uses selection or first)
    # ------------------------
    def on_preview(self):
        sel = self.tree.selection()
        idx = 0
        if sel:
            idx = self.tree.index(sel[0])
        if not self.stages:
            messagebox.showwarning("No data", "No stages to preview.")
            return
        stage = self._normalize_stage(self.stages[idx])
        self._show_preview(stage)

    def _normalize_stage(self, stage):
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

    def _show_preview(self, stage):
        # update pills text
        self.preview_title.config(text=stage.get("Stage", "Stage"))
        for k in self.pill_labels:
            val = stage.get(k, "")
            if (k in ("Time", "HF") and isinstance(val, float)) or isinstance(val, (int, float)):
                self.pill_labels[k].config(text=f"{k}: {val}")
            else:
                self.pill_labels[k].config(text=f"{k}: {val}")

        # render overlay image scaled to preview canvas width
        pil_img = make_overlay(stage, font_path=FONT_PATH, outpath=None)
        # scale down if too big for preview canvas area
        max_w = 320
        scale = min(1.0, max_w / pil_img.width)
        display = pil_img if scale == 1.0 else pil_img.resize((int(pil_img.width * scale), int(pil_img.height * scale)), Image.LANCZOS)
        self.tk_preview = ImageTk.PhotoImage(display)
        self.preview_canvas.config(width=display.width, height=display.height)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(0, 0, anchor="nw", image=self.tk_preview)
        self.status.config(text=f"Previewing {stage.get('Stage','')}")
        # ensure Escape closes preview: already bound globally

    def _clear_preview(self):
        self.preview_canvas.delete("all")
        self.preview_title.config(text="Stage preview")
        for k in self.pill_labels:
            self.pill_labels[k].config(text=f"{k}: —")
        self.status.config(text="Preview cleared")

    # ------------------------
    # Export CSV
    # ------------------------
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
        self.status.config(text=f"CSV exported to {path}")
        messagebox.showinfo("Saved", f"CSV saved to {path}")

    # ------------------------
    # Export overlays
    # ------------------------
    def on_export_overlays(self):
        if not self.stages:
            messagebox.showwarning("No data", "Scrape first.")
            return
        outdir = filedialog.askdirectory()
        if not outdir:
            return
        for i, s in enumerate(self.stages, start=1):
            s_norm = self._normalize_stage(s)
            safe_name = s_norm.get("Stage", f"stage_{i}").replace(" ", "_").replace(".", "")
            outpath = Path(outdir) / f"{safe_name}.png"
            make_overlay(s_norm, font_path=FONT_PATH, outpath=str(outpath))
        self.status.config(text=f"Exported {len(self.stages)} overlays to {outdir}")
        messagebox.showinfo("Export complete", f"Overlays saved to {outdir}")

    # ------------------------
    # Close/save and exit
    # ------------------------
    def on_close(self):
        CONFIG["window_geometry"] = self.geometry()
        CONFIG["last_match_url"] = self.match_var.get().strip()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, indent=2)
        self.destroy()


# ------------------------
# MAIN
# ------------------------
if __name__ == "__main__":
    app = DarkScoringApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
