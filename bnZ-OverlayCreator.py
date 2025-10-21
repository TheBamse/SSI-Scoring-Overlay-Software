#!/usr/bin/env python3
"""
bnZ-OverlayCreator.py  —  Baseline v6.0

Fixes:
- Dark title bar on Windows
- Removed extra status bar / scrollbar artifact
- Preview window shows full first overlay immediately
"""

from pathlib import Path
import os
import sys
import json
import csv
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
# CONFIG
# ------------------------
CONFIG_FILE = resource_path("config.json")
if not Path(CONFIG_FILE).exists():
    raise FileNotFoundError(
        "Missing config.json. Create it with keys: 'ssi_username','ssi_password','font_path','output_dir'."
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
    debug_file = "debug_rows.csv"
    # If DEBUG_MODE and the file exists, load debug CSV
    if DEBUG_MODE and os.path.exists(debug_file):
        return scrape_scores_debug_from_csv(debug_file)
    # Otherwise scrape live
    return scrape_scores_live(session, match_url)


# ------------------------
# OVERLAY
# ------------------------
def make_overlay(stage_info, font_path=FONT_PATH, outpath=None, output_width=None, top_padding=400):
    # Use configured OUTPUT_WIDTH if not explicitly provided
    if output_width is None:
        output_width = OUTPUT_WIDTH
    spacing = 20
    base_hpad = 20
    base_vpad = 20
    radius = 18
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
        font_value = ImageFont.truetype(font_path, 32)
    except Exception:
        font_value = ImageFont.load_default()

    pill_data = []
    def pill_text(key, value=None):
        return str(key) if value is None else f"{key}: {value}"

    # Stage and standard pills
    pill_data.append(("Stage", stage_info.get("Stage", ""), "white"))
    pill_data.append(("Time", f"{float(stage_info.get('Time',0)):.2f}", "white"))
    pill_data.append(("HF", f"{float(stage_info.get('HF',0)):.2f}", "white"))
    if stage_info.get("Rounds"):
        pill_data.append(("Rounds", stage_info["Rounds"], "white"))
    for key in ("A", "C", "D", "M", "NS", "P"):
        pill_data.append((key, stage_info.get(key,0), colors.get(key,"white")))

    # Compute natural widths and max height
    natural_widths = []
    pill_heights = []
    for label, value, color in pill_data:
        text = pill_text(label, value)
        minx, miny, maxx, maxy = ImageDraw.Draw(Image.new("RGBA",(10,10))).textbbox((0,0), text, font=font_value)
        text_w = maxx - minx
        text_h = maxy - miny
        natural_widths.append(text_w + 2*base_hpad)
        pill_heights.append(text_h + 2*base_vpad)

    max_h = max(pill_heights)
    total_natural_width = sum(natural_widths) + spacing*(len(pill_data)-1)
    scale = min(1.0, output_width / total_natural_width)

    # Compute starting x to center pills
    total_scaled_width = sum(int(w * scale) for w in natural_widths) + spacing*(len(pill_data)-1)
    x = max(20, (output_width - total_scaled_width)//2)
    y = top_padding

    # Create image
    img = Image.new("RGBA", (output_width, top_padding + max_h), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    # Draw pills with vertically centered text
    for i, (label, value, color) in enumerate(pill_data):
        text = pill_text(label, value)
        minx, miny, maxx, maxy = draw.textbbox((0,0), text, font=font_value)
        text_w = maxx - minx
        text_h = maxy - miny
        pill_w = int(natural_widths[i] * scale)
        pill_h = max_h
        # Vertical centering
        text_y = y + (pill_h - text_h)//2 - miny

        # Stage pill visual tweak
        if label == "Stage":
            text_y += 4  # nudge down for visual centering

        draw.rounded_rectangle([x, y, x + pill_w, y + pill_h], radius=radius, outline=outline_color, width=2, fill=bg_color)
        text_x = x + (pill_w - text_w)//2 - minx
        draw.text((text_x, text_y), text, font=font_value, fill=color)
        x += pill_w + spacing

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

        self.title("SSI Scoring Scraper")
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

        button_style = dict(bg="#3a3a3a", fg="white", activebackground="#505050", relief="flat", padx=10, pady=4)
        tk.Button(top, text="Scrape", command=self.on_scrape, **button_style).pack(side="left", padx=6)
        tk.Button(top, text="Preview Overlay", command=self.on_preview, **button_style).pack(side="left", padx=6)
        tk.Button(top, text="Export CSV", command=self.on_export_csv, **button_style).pack(side="left", padx=6)
        tk.Button(top, text="Export Overlays", command=self.on_export_overlays, **button_style).pack(side="left", padx=6)

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

        # yscroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview, style="Dark.Vertical.TScrollbar")
        # self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(fill="both", expand=True, padx=8, pady=(6, 0))
        # yscroll.pack(side="right", fill="y")
        # remove horizontal scrollbar packing
        # xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview, style="Dark.Horizontal.TScrollbar")
        # xscroll.pack(side="bottom", fill="x")
        
        # row tag styles
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

    def on_scrape(self):
        url = self.match_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Enter a match URL first.")
            return

        try:
            self.stages = []
            debug_file = "debug_rows.csv"

            # Step 1: Load debug CSV if present and debug mode
            if DEBUG_MODE and os.path.exists(debug_file):
                self.stages = scrape_scores_debug_from_csv(debug_file)
                print("[DEBUG] Loaded stages from debug_rows.csv")

            # Step 2: Live scrape if stages are empty
            if not self.stages:
                self.session = create_logged_in_session()  # always create session for live scraping
                self.stages = scrape_scores_live(self.session, url)
                if DEBUG_MODE:
                    print("[INFO] Scraped stages online")

            # Step 3: Check if we actually got any data
            if not self.stages:
                messagebox.showerror("No data", "No valid stages found.")
                return

            # Step 4: Refresh table and save last URL
            self._refresh_table()
            CONFIG["last_match_url"] = url
            save_config()

            # Optional debug-only success popup with CSV info
            if DEBUG_MODE:
                if os.path.exists(debug_file):
                    messagebox.showinfo(
                        "Success",
                        f"DEBUG_MODE is ON — loaded {len(self.stages)} stages from debug_rows.csv."
                    )
                else:
                    messagebox.showinfo(
                        "Success",
                        f"DEBUG_MODE is ON — scraped {len(self.stages)} stages online."
                    )

        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("Error", f"Scraping failed:\n{e}")

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
# PREVIEW WINDOW
# ------------------------
class PreviewWindow(tk.Toplevel):
    def __init__(self, master, stages, index):
        super().__init__(master)
        self.title("Overlay Preview")
        self.configure(bg="#1e1e1e")

        self.stages = stages
        self.index = index

        # Prepare the image first
        s = self.master._normalize_stage(self.stages[self.index])
        pil_img = make_overlay(s, font_path=FONT_PATH, outpath=None)

        # Scale image if too wide
        max_width = 1100
        if pil_img.width > max_width:
            new_w = max_width
            new_h = int(pil_img.height * new_w / pil_img.width)
            display = pil_img.resize((new_w, new_h), Image.LANCZOS)
        else:
            display = pil_img

        self.img_tk = ImageTk.PhotoImage(display)
        img_w, img_h = display.size

        # Set window geometry to fit image + button row
        geom_w = max(img_w + 40, 500)
        geom_h = img_h + 100  # extra space for buttons
        self.geometry(f"{geom_w}x{geom_h}")

        # Canvas exactly the size of the image
        self.canvas = tk.Canvas(self, width=img_w, height=img_h, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(pady=(10, 0))  # small top padding
        self.canvas.create_image(0, 0, image=self.img_tk, anchor="nw")  # draw at top-left

        # Button frame
        btn_frame = tk.Frame(self, bg="#1e1e1e")
        btn_frame.pack(pady=10)
        btn_style = dict(bg="#3a3a3a", fg="white", activebackground="#505050",
                         relief="flat", padx=10, pady=4)
        tk.Button(btn_frame, text="◀ Previous", command=self.prev_stage, **btn_style).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Next ▶", command=self.next_stage, **btn_style).pack(side="left", padx=8)
        tk.Button(btn_frame, text="Save PNG", command=self.save_current_png, **btn_style).pack(side="left", padx=8)

        # Keybindings
        self.bind("<Left>", lambda e: self.prev_stage())
        self.bind("<Right>", lambda e: self.next_stage())
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("s", lambda e: self.save_current_png())
        self.focus_set()

    def show_stage(self):
        s = self.master._normalize_stage(self.stages[self.index])
        pil_img = make_overlay(s, font_path=FONT_PATH, outpath=None)

        # Scale image if necessary
        max_width = 1100
        if pil_img.width > max_width:
            new_w = max_width
            new_h = int(pil_img.height * new_w / pil_img.width)
            display = pil_img.resize((new_w, new_h), Image.LANCZOS)
        else:
            display = pil_img

        self.img_tk = ImageTk.PhotoImage(display)
        img_w, img_h = display.size

        # Resize canvas to image size
        self.canvas.config(width=img_w, height=img_h)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.img_tk, anchor="nw")

        # Resize window to fit image + buttons
        geom_w = max(img_w + 40, 500)
        geom_h = img_h + 100
        self.geometry(f"{geom_w}x{geom_h}")

        self.title(f"Overlay Preview — {s.get('Stage','')}")

    def save_current_png(self):
        s = self.master._normalize_stage(self.stages[self.index])
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
# MAIN
# ------------------------
if __name__ == "__main__":
    app = ScoringApp()
    app.mainloop()
