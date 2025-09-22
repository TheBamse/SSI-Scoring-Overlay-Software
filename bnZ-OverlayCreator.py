#!/usr/bin/env python3
"""
scoring_ui.py - Baseline v2 + Escape closes preview window
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

# ------------------------
# CONFIG
# ------------------------
CONFIG_FILE = "config.json"
if not Path(CONFIG_FILE).exists():
    raise FileNotFoundError(
        "Missing config.json. Must contain: 'ssi_username', 'ssi_password', 'font_path', 'output_dir'."
    )

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

if not SSI_USERNAME or not SSI_PASSWORD:
    raise ValueError("Missing 'ssi_username'/'ssi_password' in config.json.")


def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)


LOGIN_URL = "https://shootnscoreit.com/login/"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------
# SCRAPER
# ------------------------
def create_logged_in_session():
    session = requests.Session()
    rget = session.get(LOGIN_URL, timeout=10)
    payload = {}
    headers = {}

    soup = BeautifulSoup(rget.text, "html.parser")
    token_input = soup.find("input", {"name": "csrfmiddlewaretoken"}) or soup.find("input", {"name": "csrf_token"})
    if token_input and token_input.get("value"):
        payload[token_input.get("name")] = token_input.get("value")
    headers["Referer"] = LOGIN_URL

    payload["username"] = SSI_USERNAME
    payload["password"] = SSI_PASSWORD
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
# OVERLAY
# ------------------------
def make_overlay(stage_info, font_path=FONT_PATH, outpath=None, output_size=(2000, 700)):
    # Start with canvas (extra height for padding)
    width, height = output_size
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
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

    # Draw pills with top padding = 400px
    x = 20
    spacing = 20
    y = 400
    max_h = 0

    w, h = draw_pill_exact(x, y, stage_info.get("Stage", ""), None, "white"); x += w + spacing; max_h = max(max_h, h)
    w, h = draw_pill_exact(x, y, "Time", f"{float(stage_info.get('Time', 0)):.2f}", "white"); x += w + spacing; max_h = max(max_h, h)
    w, h = draw_pill_exact(x, y, "HF", f"{float(stage_info.get('HF', 0)):.2f}", "white"); x += w + spacing; max_h = max(max_h, h)

    if stage_info.get("Rounds"):
        w, h = draw_pill_exact(x, y, "Rounds", stage_info["Rounds"], "white"); x += w + spacing; max_h = max(max_h, h)

    for key in ("A", "C", "D", "M", "NS", "P"):
        w, h = draw_pill_exact(x, y, key, stage_info.get(key, 0), colors.get(key, "white"))
        x += w + spacing
        max_h = max(max_h, h)

    # Crop content + padding
    right_edge = x - spacing
    bottom_edge = y + max_h
    crop_box = (0, 0, right_edge + 20, bottom_edge + 20)

    img = img.crop(crop_box)

    if outpath is None:
        return img
    img.save(outpath, "PNG")
    return outpath

# ------------------------
# GUI
# ------------------------
class ScoringApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SSI Scoring Scraper")
        if WINDOW_GEOMETRY:
            self.geometry(WINDOW_GEOMETRY)
        else:
            self.geometry("1100x700")

        self.session = None
        self.stages = []

        top = tk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        tk.Label(top, text="Match URL:").pack(side="left")
        self.match_var = tk.StringVar(value=LAST_MATCH_URL)
        self.entry_url = tk.Entry(top, textvariable=self.match_var, width=80)
        self.entry_url.pack(side="left", padx=(6, 8), fill="x", expand=True)

        tk.Button(top, text="Scrape", command=self.on_scrape).pack(side="left", padx=6)
        tk.Button(top, text="Preview Overlay", command=self.on_preview).pack(side="left", padx=6)
        tk.Button(top, text="Export CSV", command=self.on_export_csv).pack(side="left", padx=6)
        tk.Button(top, text="Export Overlays", command=self.on_export_overlays).pack(side="left", padx=6)

        columns = ("Stage", "Time", "HF", "Rounds", "A", "C", "D", "M", "NS", "P")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=110)
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)
        self.tree.bind("<Double-1>", self.on_edit_cell)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

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
        save_config()
        messagebox.showinfo("Success", f"Scraped {len(self.stages)} stages.")

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
        entry = tk.Entry(self.tree)
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

    def _normalize_stage(self, stage):
        s = dict(stage)
        try: s["Time"] = float(s.get("Time", 0))
        except: s["Time"] = 0.0
        try: s["HF"] = round(float(s.get("HF", 0)), 2)
        except: s["HF"] = 0.0
        for k in ("A", "C", "D", "M", "NS", "P"):
            try: s[k] = int(s.get(k, 0))
            except: s[k] = 0
        return s

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
        if not path: return
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
            s_norm = self._normalize_stage(s)
            safe_name = s_norm.get("Stage", f"stage_{i}").replace(" ", "_").replace(".", "")
            outpath = outdir / f"{safe_name}.png"
            make_overlay(s_norm, font_path=FONT_PATH, outpath=str(outpath))
        messagebox.showinfo("Export complete", f"Overlays saved to {outdir}")

    def on_close(self):
        CONFIG["window_geometry"] = self.geometry()
        CONFIG["last_match_url"] = self.match_var.get().strip()
        save_config()
        self.destroy()

# ------------------------
# Preview window
# ------------------------
class PreviewWindow(tk.Toplevel):
    def __init__(self, master, stages, start_index):
        super().__init__(master)
        self.title("Preview Overlay")
        self.stages = stages
        self.index = start_index
        self.canvas = tk.Canvas(self)
        self.canvas.pack(fill="both", expand=True)

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x")
        tk.Button(btn_frame, text="Prev", command=self.prev_stage).pack(side="left", padx=6, pady=6)
        tk.Button(btn_frame, text="Next", command=self.next_stage).pack(side="left", padx=6, pady=6)
        tk.Button(btn_frame, text="Save as PNG", command=self.save_stage).pack(side="left", padx=6, pady=6)

        # Escape key closes window
        self.bind("<Escape>", lambda e: self.destroy())

        self.display_stage(self.index)

    def display_stage(self, idx):
        if not (0 <= idx < len(self.stages)):
            return
        stage = self.master._normalize_stage(self.stages[idx])
        pil_img = make_overlay(stage, font_path=FONT_PATH, outpath=None)
        self.tk_img = ImageTk.PhotoImage(pil_img)
        self.canvas.config(width=pil_img.width, height=pil_img.height)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        self.geometry(f"{pil_img.width}x{pil_img.height+50}")  # auto-size window
        self.stage_data = stage

    def prev_stage(self):
        if self.index > 0:
            self.index -= 1
            self.display_stage(self.index)

    def next_stage(self):
        if self.index < len(self.stages)-1:
            self.index += 1
            self.display_stage(self.index)

    def save_stage(self):
        stage = self.stage_data
        outpath = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")])
        if outpath:
            make_overlay(stage, font_path=FONT_PATH, outpath=outpath)
            messagebox.showinfo("Saved", f"Overlay saved to {outpath}")

# ------------------------
# Main
# ------------------------
if __name__ == "__main__":
    app = ScoringApp()
    app.mainloop()
