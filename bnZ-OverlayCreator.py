#!/usr/bin/env python3
"""
scoring_ui_customtk.py
CustomTkinter UI version of Baseline v3.

Keeps the baseline logic; replaces the UI with a modern dark CustomTkinter look.
"""

import io
import json
import csv
import requests
import sys
import os
import math
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageTk

# CustomTkinter
import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox

# ------------------------
# Resource helper (PyInstaller friendly)
# ------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ------------------------
# CONFIG
# ------------------------
CONFIG_FILE = resource_path("config.json")
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
FONT_PATH = resource_path(cfg_get("font_path", "DejaVuSans-Bold.ttf"))
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
# SCRAPER (same logic as baseline)
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
# OVERLAY generation (20px pill padding, 400px top padding)
# ------------------------
def make_overlay(stage_info, font_path=FONT_PATH, outpath=None, output_size=(2000, 300)):
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

    right_edge = x - spacing
    bottom_edge = y + max_h
    crop_box = (0, 0, right_edge + 20, bottom_edge + 20)

    img = img.crop(crop_box)

    if outpath is None:
        return img
    img.save(outpath, "PNG")
    return outpath

# ------------------------
# CustomTkinter UI (Dark modern look)
# ------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")  # built-in theme

class CustomScoringApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SSI Scoring Scraper — Modern")
        if WINDOW_GEOMETRY:
            self.geometry(WINDOW_GEOMETRY)
        else:
            self.geometry("1300x820")

        # state
        self.session = None
        self.stages = []

        # Top toolbar (CTkFrame)
        top_frame = ctk.CTkFrame(self, corner_radius=6)
        top_frame.pack(fill="x", padx=12, pady=12)

        lbl = ctk.CTkLabel(top_frame, text="Match URL:", anchor="w")
        lbl.pack(side="left", padx=(12, 8))

        self.match_var = ctk.StringVar(value=LAST_MATCH_URL)
        self.entry_url = ctk.CTkEntry(top_frame, textvariable=self.match_var, width=720)
        self.entry_url.pack(side="left", padx=(0, 12))

        self.btn_scrape = ctk.CTkButton(top_frame, text="Scrape", command=self.on_scrape, width=96)
        self.btn_preview = ctk.CTkButton(top_frame, text="Preview Overlay", command=self.on_preview, width=140)
        self.btn_export_csv = ctk.CTkButton(top_frame, text="Export CSV", command=self.on_export_csv, width=120)
        self.btn_export_ovs = ctk.CTkButton(top_frame, text="Export Overlays", command=self.on_export_overlays, width=140)

        for b in (self.btn_scrape, self.btn_preview, self.btn_export_csv, self.btn_export_ovs):
            b.pack(side="left", padx=8)

        # main area with left table and right preview
        main_frame = ctk.CTkFrame(self, corner_radius=6)
        main_frame.pack(fill="both", expand=True, padx=12, pady=(0,12))

        left_frame = ctk.CTkFrame(main_frame, corner_radius=6)
        left_frame.pack(side="left", fill="both", expand=True, padx=(12,8), pady=12)

        right_frame = ctk.CTkFrame(main_frame, width=380, corner_radius=6)
        right_frame.pack(side="right", fill="y", padx=(8,12), pady=12)

        # Treeview inside left frame
        columns = ("Stage", "Time", "HF", "Rounds", "A", "C", "D", "M", "NS", "P")
        self.tree = ttk.Treeview(left_frame, columns=columns, show="headings", selectmode="browse")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=110)
        # place Treeview with customtkinter wrapper
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        # bind double click for inline single-cell editing
        self.tree.bind("<Double-1>", self.on_edit_cell)

        # right preview area
        preview_label = ctk.CTkLabel(right_frame, text="Stage Preview", font=ctk.CTkFont(size=16, weight="bold"))
        preview_label.pack(pady=(12,8))

        # canvas for image preview
        self.preview_canvas = ctk.CTkCanvas(right_frame, width=340, height=200, highlightthickness=0)
        self.preview_canvas.pack(padx=12, pady=(0,12))

        # compact pill list inside right frame
        self.pill_container = ctk.CTkFrame(right_frame, corner_radius=6)
        self.pill_container.pack(fill="both", expand=False, padx=12, pady=(0,12))

        self.pill_labels = {}
        for k in ("Time", "HF", "Rounds", "A", "C", "D", "M", "NS", "P"):
            lbl = ctk.CTkLabel(self.pill_container, text=f"{k}: —", anchor="w")
            lbl.pack(fill="x", pady=4)
            self.pill_labels[k] = lbl

        # preview control buttons
        btns = ctk.CTkFrame(right_frame, corner_radius=6)
        btns.pack(fill="x", padx=12, pady=(0,12))
        self.prev_btn = ctk.CTkButton(btns, text="Prev", command=self.prev_stage)
        self.next_btn = ctk.CTkButton(btns, text="Next", command=self.next_stage)
        self.save_btn = ctk.CTkButton(btns, text="Save PNG", command=self.save_stage)
        self.prev_btn.pack(side="left", padx=6)
        self.next_btn.pack(side="left", padx=6)
        self.save_btn.pack(side="left", padx=6)

        # status bar
        self.status = ctk.CTkLabel(self, text="", anchor="w")
        self.status.pack(fill="x", padx=12, pady=(0,12))

        # bind escape to clear preview and close modal previews
        self.bind("<Escape>", lambda e: self._clear_preview_modal())

        # preview modal state
        self.preview_modal = None
        self.preview_index = 0
        self.tk_preview_image = None

    # ------------------------
    # Table refresh
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
    # Scrape handler
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
        save_config()
        self.status.configure(text=f"Scraped {len(self.stages)} stages.")

    # ------------------------
    # Inline single-cell editing
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
        # create an entry widget above the tree (use regular tk.Entry so it overlays)
        import tkinter as tk
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
            self.status.configure(text=f"Edited {col_name} for row {idx+1}")

        entry.bind("<Return>", save_edit)
        entry.bind("<FocusOut>", save_edit)
        entry.bind("<Escape>", lambda e: entry.destroy())

    # ------------------------
    # Normalize stage
    # ------------------------
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

    # ------------------------
    # Preview overlay: show modal and update right pane display
    # ------------------------
    def on_preview(self):
        sel = self.tree.selection()
        if sel:
            idx = self.tree.index(sel[0])
        else:
            idx = 0
        if not self.stages:
            messagebox.showwarning("No data", "No stages to preview.")
            return
        self.preview_index = idx
        self._open_preview_modal(self.preview_index)

    def _open_preview_modal(self, start_index):
        # open (or update) modal preview window
        if self.preview_modal and self.preview_modal.winfo_exists():
            try:
                self.preview_modal.lift()
                self._update_preview_modal(start_index)
                return
            except Exception:
                pass

        self.preview_modal = ctk.CTkToplevel(self)
        self.preview_modal.title("Preview Overlay")
        # bind escape to close
        self.preview_modal.bind("<Escape>", lambda e: self.preview_modal.destroy())

        # canvas inside modal
        canvas = ctk.CTkCanvas(self.preview_modal, highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        # button row
        btn_frame = ctk.CTkFrame(self.preview_modal)
        btn_frame.pack(fill="x", pady=6)
        ctk.CTkButton(btn_frame, text="Prev", command=self.prev_stage).pack(side="left", padx=6, pady=6)
        ctk.CTkButton(btn_frame, text="Next", command=self.next_stage).pack(side="left", padx=6, pady=6)
        ctk.CTkButton(btn_frame, text="Save as PNG", command=self.save_stage).pack(side="left", padx=6, pady=6)

        # store canvas reference on instance for updates
        self.preview_modal.canvas = canvas
        self._update_preview_modal(start_index)

    def _update_preview_modal(self, idx):
        if not (0 <= idx < len(self.stages)):
            return
        stage = self._normalize_stage(self.stages[idx])
        pil_img = make_overlay(stage, font_path=FONT_PATH, outpath=None)

        # convert to PhotoImage
        self.tk_preview_image = ImageTk.PhotoImage(pil_img)
        canvas = self.preview_modal.canvas
        canvas.delete("all")
        canvas.config(width=pil_img.width, height=pil_img.height)
        canvas.create_image(0, 0, anchor="nw", image=self.tk_preview_image)
        # auto-size modal window
        try:
            self.preview_modal.geometry(f"{pil_img.width}x{pil_img.height+60}")
        except Exception:
            pass
        # also update right-side preview pane (scaled)
        self._update_right_preview(stage, pil_img)

    def _update_right_preview(self, stage, pil_img):
        # update pill labels on right
        self.pill_labels["Time"].configure(text=f"Time: {stage.get('Time','')}")
        self.pill_labels["HF"].configure(text=f"HF: {stage.get('HF','')}")
        self.pill_labels["Rounds"].configure(text=f"Rounds: {stage.get('Rounds','')}")
        for k in ("A", "C", "D", "M", "NS", "P"):
            self.pill_labels[k].configure(text=f"{k}: {stage.get(k,0)}")

        # scale image to fit preview_canvas width (~340)
        max_w = 320
        scale = min(1.0, max_w / pil_img.width)
        display = pil_img if scale == 1.0 else pil_img.resize((int(pil_img.width*scale), int(pil_img.height*scale)), Image.LANCZOS)
        self.tk_preview_small = ImageTk.PhotoImage(display)
        # clear and show
        self.preview_canvas.configure(width=display.width, height=display.height)
        # need to access underlying tkinter Canvas, CTkCanvas has .tk_canvas
        try:
            tk_canvas = self.preview_canvas._canvas if hasattr(self.preview_canvas, "_canvas") else self.preview_canvas
        except Exception:
            tk_canvas = self.preview_canvas
        tk_canvas.delete("all")
        tk_canvas.create_image(0, 0, anchor="nw", image=self.tk_preview_small)
        # keep reference
        self._last_preview_stage = stage

    # ------------------------
    # Prev/Next for modal
    # ------------------------
    def prev_stage(self):
        if not self.stages:
            return
        self.preview_index = (self.preview_index - 1) % len(self.stages)
        if self.preview_modal and self.preview_modal.winfo_exists():
            self._update_preview_modal(self.preview_index)

    def next_stage(self):
        if not self.stages:
            return
        self.preview_index = (self.preview_index + 1) % len(self.stages)
        if self.preview_modal and self.preview_modal.winfo_exists():
            self._update_preview_modal(self.preview_index)

    # ------------------------
    # Save current modal stage as PNG
    # ------------------------
    def save_stage(self):
        if not self.stages:
            return
        idx = self.preview_index
        stage = self._normalize_stage(self.stages[idx])
        safe_name = stage.get("Stage", f"stage_{idx}").replace(" ", "_").replace(".", "")
        path = filedialog.asksaveasfilename(defaultextension=".png", initialfile=f"{safe_name}.png")
        if not path:
            return
        make_overlay(stage, font_path=FONT_PATH, outpath=path)
        messagebox.showinfo("Saved", f"Overlay saved to {path}")

    def _clear_preview_modal(self):
        if self.preview_modal and self.preview_modal.winfo_exists():
            try:
                self.preview_modal.destroy()
            except Exception:
                pass

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
        self.status.configure(text=f"CSV saved to {path}")
        messagebox.showinfo("Saved", f"CSV saved to {path}")

    # ------------------------
    # Export Overlays (manual choose folder)
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
        self.status.configure(text=f"Exported {len(self.stages)} overlays to {outdir}")
        messagebox.showinfo("Export complete", f"Overlays saved to {outdir}")

    # ------------------------
    # Close/save and exit
    # ------------------------
    def on_close(self):
        CONFIG["window_geometry"] = self.geometry()
        CONFIG["last_match_url"] = self.match_var.get().strip()
        save_config()
        self.destroy()


# ------------------------
# MAIN
# ------------------------
if __name__ == "__main__":
    app = CustomScoringApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
