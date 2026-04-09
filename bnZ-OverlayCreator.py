#!/usr/bin/env python3
"""
bnZ-OverlayCreator.py  —  v3.0  (development build)

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
  - All dialogs (info, warning, error) use a custom dark-themed Toplevel
    instead of the system messagebox, keeping the dark aesthetic throughout

Functional changes vs v2.5:
  - Credentials read from CONFIG at scrape time, not stale startup constants;
    username/password changes in Settings take effect on the next scrape
    without requiring a restart
  - scrape_scores() removed — dead code that was never called by the GUI
  - Export Overlays runs in a background thread; progress shown in status bar
  - Window geometry clamped to screen bounds on load, preventing an
    off-screen window after a monitor is disconnected
  - scrape_scores_debug_from_csv resolves debug_rows.csv via app_dir(),
    working correctly in both script and PyInstaller exe contexts
  - Silent bare excepts in normalize_stage now log the field name and error

Known platform notes:
  - Dark title bar: works reliably on Windows 11. On Windows 10 a
    withdraw/deiconify cycle is required after the DWM attribute call to
    force the non-client area to repaint immediately.
  - Rounded corners: Windows 11 only via DWM attribute 33. Not supported
    on Windows 10 regardless of build version. Deferred to v4.0.
  - Resize: status bar must be packed before the table (side="bottom"
    widgets must precede expand=True widgets in tkinter's pack manager).

Bug fixes:
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
  - DWM titlebar calls consolidated into shared helpers (_apply_dark_titlebar_hwnd,
    _dark_titlebar_toplevel) with Win10 attr-19 fallback after Win11 attr-20
"""

from pathlib import Path
import os, sys, json, csv, logging, threading, datetime
import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageTk

def resource_path(relative_path):
    try: base_path = sys._MEIPASS
    except: base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def app_dir():
    if getattr(sys, "frozen", False): return Path(sys.executable).parent
    return Path(__file__).parent

_log_path = app_dir() / "error.log"
logging.basicConfig(filename=str(_log_path), level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)

CONFIG_FILE = app_dir() / "config.json"
_DEFAULT_CONFIG = {
    "ssi_username": "", "ssi_password": "",
    "font_path": "C:/Windows/Fonts/arial.ttf",
    "output_dir": "overlays", "output_width": 1920,
    "last_match_url": "", "window_geometry": None, "debug_mode": False,
    "colors": {"A":[50,205,50],"C":[255,165,0],"D":[255,105,180],
               "M":[220,20,60],"NS":[138,43,226],"P":[255,215,0],
               "bg":[40,40,40,220],"outline":[255,255,255,255]},
}
_first_run = False
if not CONFIG_FILE.exists():
    _first_run = True
    with open(CONFIG_FILE, "w", encoding="utf-8") as _f: json.dump(_DEFAULT_CONFIG, _f, indent=2)
with open(CONFIG_FILE, "r", encoding="utf-8") as f: CONFIG = json.load(f)

def cfg_get(key, default=None): return CONFIG.get(key, default)
def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(CONFIG, f, indent=2)

# Module-level constants — credentials intentionally NOT here so Settings
# changes take effect immediately without restarting.
FONT_PATH       = resource_path(cfg_get("font_path", "C:/Windows/Fonts/arial.ttf"))
OUTPUT_DIR      = Path(cfg_get("output_dir", "overlays"))
OUTPUT_WIDTH    = int(cfg_get("output_width", 1920))
LAST_MATCH_URL  = cfg_get("last_match_url", "")
WINDOW_GEOMETRY = cfg_get("window_geometry", None)
DEBUG_MODE      = bool(cfg_get("debug_mode", False))
LOGIN_URL       = "https://shootnscoreit.com/login/"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_PREVIEW_WIDTH = 1100; PREVIEW_BTN_EXTRA_HEIGHT = 100; TOP_PADDING_DEFAULT = 400
PILL_RADIUS = 18; PILL_FONT_SIZE = 32; PILL_HPAD = 20; PILL_VPAD = 20; PILL_SPACING = 20

C_BG="#0f0f0f"; C_SURFACE="#141414"; C_PANEL="#111111"
C_ROW_EVEN="#0f0f0f"; C_ROW_ODD="#131313"; C_ROW_HOVER="#161616"; C_ROW_SEL="#0e1826"
C_BORDER="#1f1f1f"; C_BORDER2="#2a2a2a"; C_TEXT="#dddddd"; C_TEXT_DIM="#888888"
C_TEXT_HINT="#444444"; C_ACCENT="#2563eb"; C_HF="#60a5fa"

BTN_STYLE = dict(bg="#1e1e1e", fg=C_TEXT_DIM, activebackground="#2a2a2a",
    activeforeground=C_TEXT, relief="flat", padx=10, pady=3, font=("Segoe UI", 9),
    borderwidth=1, highlightbackground=C_BORDER2, highlightthickness=1)
BTN_PRIMARY = dict(bg=C_ACCENT, fg="white", activebackground="#1d4ed8",
    activeforeground="white", relief="flat", padx=10, pady=3,
    font=("Segoe UI", 9, "bold"), borderwidth=0)

DEFAULT_COLORS = {"A":(50,205,50),"C":(255,165,0),"D":(255,105,180),
    "M":(220,20,60),"NS":(138,43,226),"P":(255,215,0),
    "bg":(40,40,40,220),"outline":(255,255,255,255)}

def get_overlay_colors():
    saved = CONFIG.get("colors", {}); result = {}
    for key, default in DEFAULT_COLORS.items():
        val = saved.get(key)
        result[key] = tuple(val[:len(default)]) if val and isinstance(val, list) and len(val) >= len(default) else default
    return result

def _rgb_to_hex(rgb): return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])

def _apply_dark_titlebar_hwnd(hwnd):
    """Try Win11 attr 20, fall back to Win10 attr 19."""
    try:
        import ctypes
        val = ctypes.byref(ctypes.c_int(1))
        sz  = ctypes.sizeof(ctypes.c_int(1))
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, val, sz) != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, val, sz)
    except Exception:
        pass

def _dark_titlebar_toplevel(win):
    """Call after update_idletasks() on any Toplevel or Tk window."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, win.title())
        if hwnd:
            _apply_dark_titlebar_hwnd(hwnd)
    except Exception:
        pass

def dark_dialog(parent, title, message, kind="info"):
    """A dark-themed replacement for messagebox.showinfo / showerror / showwarning."""
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg="#111111")
    dlg.resizable(False, False)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.update_idletasks(); _dark_titlebar_toplevel(dlg)
    icon_map = {"info": ("ℹ", C_ACCENT), "error": ("✕", "#ef4444"), "warning": ("⚠", "#f59e0b")}
    icon_txt, icon_col = icon_map.get(kind, ("ℹ", C_ACCENT))
    top = tk.Frame(dlg, bg="#111111"); top.pack(padx=20, pady=(18, 8), fill="x")
    tk.Label(top, text=icon_txt, bg="#111111", fg=icon_col,
        font=("Segoe UI", 16, "bold")).pack(side="left", anchor="n", padx=(0, 12))
    tk.Label(top, text=message, bg="#111111", fg=C_TEXT,
        font=("Segoe UI", 9), justify="left", wraplength=360, anchor="w").pack(side="left", fill="x", expand=True)
    bf = tk.Frame(dlg, bg="#111111"); bf.pack(pady=(4, 16))
    tk.Button(bf, text="OK", width=10, command=dlg.destroy, **BTN_PRIMARY).pack()
    dlg.bind("<Return>", lambda e: dlg.destroy())
    dlg.bind("<Escape>", lambda e: dlg.destroy())
    dlg.update_idletasks()
    px = parent.winfo_x() + parent.winfo_width() // 2
    py = parent.winfo_y() + parent.winfo_height() // 2
    w, h = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry(f"+{px - w // 2}+{py - h // 2}")
    dlg.focus_set()
    parent.wait_window(dlg)

# ------------------------
# SCRAPER
# ------------------------
def create_logged_in_session():
    """Read credentials fresh from CONFIG — Settings changes take effect immediately."""
    LOGIN_POST_URL = "https://shootnscoreit.com/login/?next=https://shootnscoreit.com/dashboard/"
    session = requests.Session()
    rpost = session.post(LOGIN_POST_URL,
        data={"username": CONFIG.get("ssi_username", ""),
              "password": CONFIG.get("ssi_password", ""), "keep": "on"},
        headers={"Referer": LOGIN_URL}, timeout=15)
    if "/login/" in rpost.url:
        raise RuntimeError("SSI login failed — check username/password in Settings.")
    return session

def _parse_table_rows_from_soup(soup):
    candidate_rows = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 10:
                candidate_rows.append([td.get_text(strip=True).replace("\xa0", " ") for td in tds])
        if candidate_rows: return candidate_rows
    return candidate_rows

def _parse_stage_from_cols(cols, source_label="row"):
    if len(cols) < 10 or cols[0].lower().startswith(("total", "summary")): return None
    try:
        return {"Stage": cols[0], "HF": round(float(cols[1] or 0), 2),
            "Time": float(cols[2] or 0), "Rounds": "",
            "A": int(cols[4] or 0), "C": int(cols[5] or 0), "D": int(cols[6] or 0),
            "M": int(cols[7] or 0), "P": int(cols[8] or 0), "NS": int(cols[9] or 0)}
    except Exception as e:
        logger.error("Failed to parse %s: %s — cols were: %s", source_label, e, cols); return None

def scrape_scores_live(session, match_url):
    r = session.get(match_url, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    return [s for i, c in enumerate(_parse_table_rows_from_soup(soup))
            for s in [_parse_stage_from_cols(c, f"live row {i}")] if s]

def scrape_scores_debug_from_csv():
    """Resolve debug_rows.csv via app_dir() — correct in both script and PyInstaller exe."""
    csv_path = app_dir() / "debug_rows.csv"
    if not csv_path.exists(): return []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return [s for i, row in enumerate(csv.reader(f))
                for s in [_parse_stage_from_cols(row, f"CSV row {i}")] if s]


# ------------------------
# NORMALISE
# ------------------------
def normalize_stage(stage):
    s = dict(stage)
    for key, conv, default in [("Time", float, 0.0), ("HF", lambda v: round(float(v), 2), 0.0)]:
        try: s[key] = conv(s.get(key, 0))
        except Exception as e:
            logger.error("normalize_stage: could not convert %s — %s", key, e); s[key] = default
    for k in ("A", "C", "D", "M", "NS", "P"):
        try: s[k] = int(s.get(k, 0))
        except Exception as e:
            logger.error("normalize_stage: could not convert %s — %s", k, e); s[k] = 0
    return s

# ------------------------
# OVERLAY
# ------------------------
def make_overlay(stage_info, font_path=FONT_PATH, outpath=None, output_width=None, top_padding=TOP_PADDING_DEFAULT):
    if output_width is None: output_width = OUTPUT_WIDTH
    _oc = get_overlay_colors()
    colors = {k: _oc[k] for k in ("A","C","D","M","NS","P")}
    bg_color = _oc["bg"]; outline_color = _oc["outline"]
    try: font_value = ImageFont.truetype(font_path, PILL_FONT_SIZE)
    except: font_value = ImageFont.load_default()
    pill_data = [("Stage", stage_info.get("Stage",""), "white"),
        ("Time", f"{float(stage_info.get('Time',0)):.2f}", "white"),
        ("HF",   f"{float(stage_info.get('HF',0)):.2f}", "white")]
    if stage_info.get("Rounds"): pill_data.append(("Rounds", stage_info["Rounds"], "white"))
    for key in ("A","C","D","M","NS","P"): pill_data.append((key, stage_info.get(key,0), colors.get(key,"white")))
    _dd = ImageDraw.Draw(Image.new("RGBA",(10,10)))
    def pill_text(k, v=None): return str(k) if v is None else f"{k}: {v}"
    nw=[]; ph=[]
    for lbl,val,_ in pill_data:
        tx=pill_text(lbl,val); mn=_dd.textbbox((0,0),tx,font=font_value)
        nw.append((mn[2]-mn[0])+2*PILL_HPAD); ph.append((mn[3]-mn[1])+2*PILL_VPAD)
    max_h=max(ph); scale=min(1.0,output_width/(sum(nw)+PILL_SPACING*(len(pill_data)-1)))
    tsw=sum(int(w*scale) for w in nw)+PILL_SPACING*(len(pill_data)-1)
    x=max(20,(output_width-tsw)//2); y=top_padding
    img=Image.new("RGBA",(output_width,top_padding+max_h),(0,0,0,0))
    draw=ImageDraw.Draw(img)
    for i,(lbl,val,col) in enumerate(pill_data):
        tx=pill_text(lbl,val); mn=_dd.textbbox((0,0),tx,font=font_value)
        tw=mn[2]-mn[0]; th=mn[3]-mn[1]; pw=int(nw[i]*scale)
        ty2=y+(max_h-th)//2-mn[1]+(4 if lbl=="Stage" else 0)
        draw.rounded_rectangle([x,y,x+pw,y+max_h],radius=PILL_RADIUS,outline=outline_color,width=2,fill=bg_color)
        draw.text((x+(pw-tw)//2-mn[0],ty2),tx,font=font_value,fill=col)
        x+=pw+PILL_SPACING
    if outpath: img.save(outpath,"PNG"); return outpath
    return img


# ============================================================
# CANVAS TABLE
# ============================================================
class CanvasTable(tk.Frame):
    """Scrollable table on tk.Canvas — per-cell colour, hover, selection accent."""
    COLS = ("Stage","Time","HF","Rounds","A","C","D","M","P","NS")
    COL_FIXED = {"Time":74,"HF":74,"Rounds":60,"A":48,"C":48,"D":48,"M":48,"P":48,"NS":48}
    ROW_H=28; HEAD_H=26; ACCENT_W=3
    FONT_HEAD=("Segoe UI",8,"bold"); FONT_ROW=("Segoe UI",10); PAD_LEFT=10

    def __init__(self, master, on_double_click=None, **kw):
        super().__init__(master, bg=C_BG, **kw)
        self._stages=[]; self._selected=None; self._hovered=None
        self._on_dbl=on_double_click; self._col_widths={}; self._edit_entry=None
        self._sb_canvas   = tk.Canvas(self, width=10,  bg=C_BG, highlightthickness=0, bd=0)
        self._sb_h_canvas = tk.Canvas(self, height=10, bg=C_BG, highlightthickness=0, bd=0)
        self._cv = tk.Canvas(self, bg=C_BG, highlightthickness=0,
            yscrollcommand=self._update_scrollbar_v, xscrollcommand=self._update_scrollbar_h)
        self._cv.pack(side="left", fill="both", expand=True)
        self._sb_dragging=False; self._sb_drag_start_y=0; self._sb_first=0.0; self._sb_last=1.0
        self._sb_h_dragging=False; self._sb_h_drag_start_x=0; self._sb_h_first=0.0; self._sb_h_last=1.0
        self._sb_canvas.bind("<ButtonPress-1>",   self._sb_on_press)
        self._sb_canvas.bind("<B1-Motion>",       self._sb_on_drag)
        self._sb_canvas.bind("<ButtonRelease-1>", self._sb_on_release)
        self._sb_canvas.bind("<Configure>",       lambda e: self._sb_draw())
        self._sb_h_canvas.bind("<ButtonPress-1>",   self._sb_h_on_press)
        self._sb_h_canvas.bind("<B1-Motion>",       self._sb_h_on_drag)
        self._sb_h_canvas.bind("<ButtonRelease-1>", self._sb_h_on_release)
        self._sb_h_canvas.bind("<Configure>",       lambda e: self._sb_h_draw())
        self._cv.bind("<Configure>",        self._on_resize)
        self._cv.bind("<Button-1>",         self._on_click)
        self._cv.bind("<Double-Button-1>",  self._on_double)
        self._cv.bind("<Motion>",           self._on_motion)
        self._cv.bind("<Leave>",            self._on_leave)
        self._cv.bind("<MouseWheel>",       self._on_scroll)
        self._cv.bind("<Shift-MouseWheel>", self._on_scroll_h)

    def _update_scrollbar_v(self, first, last):
        self._sb_first=float(first); self._sb_last=float(last)
        if self._sb_first<=0.0 and self._sb_last>=1.0: self._sb_canvas.pack_forget()
        else: self._sb_canvas.pack(side="right", fill="y", before=self._cv)
        self._sb_draw()

    def _sb_draw(self):
        sc=self._sb_canvas; sc.delete("all")
        w=sc.winfo_width() or 10; h=sc.winfo_height() or 200
        sc.create_rectangle(0,0,w,h,fill="#1a1a1a",outline="")
        ty1=int(self._sb_first*h); ty2=max(int(self._sb_last*h),ty1+20)
        sc.create_rectangle(2,ty1,w-2,ty2,fill="#4a4a4a" if self._sb_dragging else "#3a3a3a",outline="")

    def _sb_on_press(self, event):
        self._sb_dragging=True; self._sb_drag_start_y=event.y; self._sb_drag_start_top=self._sb_first; self._sb_draw()
    def _sb_on_drag(self, event):
        if not self._sb_dragging: return
        h=self._sb_canvas.winfo_height() or 200; delta=(event.y-self._sb_drag_start_y)/h
        self._cv.yview_moveto(max(0.0,min(self._sb_drag_start_top+delta,1.0-(self._sb_last-self._sb_first))))
    def _sb_on_release(self, event): self._sb_dragging=False; self._sb_draw()

    def _update_scrollbar_h(self, first, last):
        self._sb_h_first=float(first); self._sb_h_last=float(last)
        if self._sb_h_first<=0.0 and self._sb_h_last>=1.0: self._sb_h_canvas.pack_forget()
        else: self._sb_h_canvas.pack(side="bottom", fill="x", before=self._cv)
        self._sb_h_draw()

    def _sb_h_draw(self):
        sc=self._sb_h_canvas; sc.delete("all")
        w=sc.winfo_width() or 200; h=sc.winfo_height() or 10
        sc.create_rectangle(0,0,w,h,fill="#1a1a1a",outline="")
        tx1=int(self._sb_h_first*w); tx2=max(int(self._sb_h_last*w),tx1+20)
        sc.create_rectangle(tx1,2,tx2,h-2,fill="#4a4a4a" if self._sb_h_dragging else "#3a3a3a",outline="")

    def _sb_h_on_press(self, event):
        self._sb_h_dragging=True; self._sb_h_drag_start_x=event.x; self._sb_h_drag_start_left=self._sb_h_first; self._sb_h_draw()
    def _sb_h_on_drag(self, event):
        if not self._sb_h_dragging: return
        w=self._sb_h_canvas.winfo_width() or 200; delta=(event.x-self._sb_h_drag_start_x)/w
        self._cv.xview_moveto(max(0.0,min(self._sb_h_drag_start_left+delta,1.0-(self._sb_h_last-self._sb_h_first))))
    def _sb_h_on_release(self, event): self._sb_h_dragging=False; self._sb_h_draw()

    def load(self, stages):
        self._stages=stages; self._selected=None; self._hovered=None
        self._layout(self._cv.winfo_width() or 800); self.redraw()
    def get_selected_index(self): return self._selected

    def _layout(self, total_w):
        stage_w=max(120, total_w-sum(self.COL_FIXED.values())-self.ACCENT_W-2)
        self._col_widths={"Stage":stage_w}; self._col_widths.update(self.COL_FIXED)

    def _col_x(self, col_name):
        x=self.ACCENT_W
        for c in self.COLS:
            if c==col_name: return x
            x+=self._col_widths.get(c,0)
        return x

    def _row_y(self, idx): return self.HEAD_H+idx*self.ROW_H
    def _row_at_y(self, y):
        if y<self.HEAD_H: return None
        idx=(y-self.HEAD_H)//self.ROW_H
        return idx if 0<=idx<len(self._stages) else None
    def _col_at_x(self, x):
        cx=self.ACCENT_W
        for c in self.COLS:
            w=self._col_widths.get(c,0)
            if cx<=x<cx+w: return c
            cx+=w
        return None

    def redraw(self):
        cv=self._cv; cv.delete("all")
        total_w=cv.winfo_width() or 800; self._layout(total_w)
        oc=get_overlay_colors(); hit_hex={k:_rgb_to_hex(oc[k]) for k in ("A","C","D","M","P","NS")}
        total_h=self.HEAD_H+len(self._stages)*self.ROW_H
        min_cw=sum(self.COL_FIXED.values())+self.ACCENT_W+120
        cv.config(scrollregion=(0,0,max(total_w,min_cw),max(total_h,cv.winfo_height() or 600)))
        cv.create_rectangle(0,0,total_w,self.HEAD_H,fill=C_SURFACE,outline="")
        cv.create_line(0,self.HEAD_H,total_w,self.HEAD_H,fill=C_BORDER,width=1)
        for col in self.COLS:
            x=self._col_x(col); w=self._col_widths.get(col,0)
            tx=(x+self.PAD_LEFT) if col=="Stage" else (x+w//2)
            cv.create_text(tx,self.HEAD_H//2,text=col.upper(),fill=C_TEXT_HINT,
                font=self.FONT_HEAD,anchor="w" if col=="Stage" else "center")
        for i,s in enumerate(self._stages):
            ry=self._row_y(i); isel=(i==self._selected); ihov=(i==self._hovered)
            row_bg=C_ROW_SEL if isel else (C_ROW_HOVER if ihov else (C_ROW_EVEN if i%2==0 else C_ROW_ODD))
            cv.create_rectangle(self.ACCENT_W,ry,total_w,ry+self.ROW_H,fill=row_bg,outline="")
            cv.create_line(self.ACCENT_W,ry+self.ROW_H-1,total_w,ry+self.ROW_H-1,fill=C_BORDER,width=1)
            ac=C_ACCENT if isel else ("#3b5fc0" if ihov else row_bg)
            cv.create_rectangle(0,ry,self.ACCENT_W,ry+self.ROW_H,fill=ac,outline="")
            ty=ry+self.ROW_H//2
            sx=self._col_x("Stage"); sw=self._col_widths["Stage"]
            cv.create_text(sx+self.PAD_LEFT,ty,text=str(s.get("Stage","")),fill=C_TEXT,
                font=self.FONT_ROW,anchor="w",width=sw-self.PAD_LEFT-4)
            self._dc(cv,"Time",ty,f"{s.get('Time',0):.2f}" if isinstance(s.get('Time',0),(int,float)) else str(s.get('Time','')),C_TEXT_DIM)
            self._dc(cv,"HF",ty,f"{s.get('HF',0):.2f}" if isinstance(s.get('HF',0),(int,float)) else str(s.get('HF','')),C_HF)
            self._dc(cv,"Rounds",ty,str(s.get("Rounds","")),C_TEXT_DIM)
            for k in ("A","C","D","M","P","NS"):
                val=s.get(k,0)
                self._dc(cv,k,ty,str(val),hit_hex[k] if int(val or 0)>0 else C_TEXT_HINT)
        for col in self.COLS[1:]:
            x=self._col_x(col); cv.create_line(x,0,x,total_h,fill=C_BORDER,width=1)

    def _dc(self, cv, col, ty, text, fill):
        x=self._col_x(col); w=self._col_widths.get(col,0)
        cv.create_text(x+w//2,ty,text=text,fill=fill,font=self.FONT_ROW,anchor="center")

    def _on_resize(self, event): self._layout(event.width); self.redraw()
    def _commit_edit(self):
        e=self._edit_entry
        if e and e.winfo_exists(): e.event_generate("<Return>")
    def _on_click(self, event):
        self._commit_edit(); y=self._cv.canvasy(event.y); idx=self._row_at_y(int(y))
        if idx is not None: self._selected=idx; self.redraw()
    def _on_double(self, event):
        y=self._cv.canvasy(event.y); idx=self._row_at_y(int(y)); col=self._col_at_x(event.x)
        if idx is not None and col is not None and self._on_dbl: self._on_dbl(idx,col)
    def _on_motion(self, event):
        idx=self._row_at_y(int(self._cv.canvasy(event.y)))
        if idx!=self._hovered: self._hovered=idx; self.redraw()
    def _on_leave(self, event):
        if self._hovered is not None: self._hovered=None; self.redraw()
    def _on_scroll(self, event): self._cv.yview_scroll(int(-1*(event.delta/120)),"units")
    def _on_scroll_h(self, event): self._cv.xview_scroll(int(-1*(event.delta/120)),"units")


# ============================================================
# GUI
# ============================================================
class ScoringApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SSI Scoring Overlay Software")
        self.configure(bg=C_BG)

        # Clamp saved geometry to screen bounds — prevents off-screen window
        # after a monitor is disconnected.
        geom = WINDOW_GEOMETRY
        if geom:
            try:
                parts = geom.replace("+", " +").replace("-", " -").split()
                if len(parts) == 3:
                    wx = max(0, min(int(parts[1]), self.winfo_screenwidth() - 200))
                    wy = max(0, min(int(parts[2]), self.winfo_screenheight() - 100))
                    geom = f"{parts[0]}+{wx}+{wy}"
            except Exception:
                geom = "1200x680"
        else:
            geom = "1200x680"
        self.geometry(geom)

        # Dark title bar deferred — see _apply_dark_titlebar called via after(100) below.

        self.session = None; self.stages = []
        if _first_run: self.after(200, self._show_first_run_welcome)
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._apply_dark_titlebar)

    def _apply_dark_titlebar(self):
        self.update_idletasks()
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, self.title())
            if hwnd:
                val = ctypes.byref(ctypes.c_int(1))
                sz  = ctypes.sizeof(ctypes.c_int(1))
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, val, sz) != 0:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, val, sz)
                # Force Win10 to repaint the non-client area immediately
                self.withdraw()
                self.deiconify()
        except Exception:
            pass

    def _build_ui(self):
        hdr = tk.Frame(self, bg=C_SURFACE, height=38)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        tk.Label(hdr, text="S", bg=C_ACCENT, fg="white",
            font=("Segoe UI",10,"bold"), padx=5).pack(side="left", padx=(10,6), pady=7)
        tk.Label(hdr, text="SSI Scoring Overlay", bg=C_SURFACE,
            fg=C_TEXT, font=("Segoe UI",10,"bold")).pack(side="left", padx=(0,12))
        for text, cmd in (("\u2699 Settings", self.on_settings),
            ("Export Overlays", self.on_export_overlays),
            ("Export CSV", self.on_export_csv),
            ("Preview Overlay", self.on_preview)):
            tk.Button(hdr, text=text, command=cmd, **BTN_STYLE).pack(side="right", padx=2, pady=6)
        self._scrape_btn = tk.Button(hdr, text="Scrape", command=self.on_scrape, **BTN_PRIMARY)
        self._scrape_btn.pack(side="right", padx=(2,4), pady=6)

        url_bar = tk.Frame(self, bg=C_PANEL, height=34)
        url_bar.pack(fill="x"); url_bar.pack_propagate(False)
        tk.Label(url_bar, text="Match URL:", bg=C_PANEL,
            fg=C_TEXT_HINT, font=("Segoe UI",9)).pack(side="left", padx=(12,6), pady=7)
        self.match_var = tk.StringVar(value=LAST_MATCH_URL)
        ue = tk.Entry(url_bar, textvariable=self.match_var, bg="#181818", fg=C_TEXT_DIM,
            insertbackground=C_TEXT_DIM, relief="flat", font=("Segoe UI",9),
            highlightbackground=C_BORDER2, highlightthickness=1)
        ue.pack(side="left", fill="x", expand=True, pady=6, padx=(0,10))
        ue.bind("<Return>", lambda e: self.on_scrape())

        # Status bar BEFORE table (side="bottom" must precede expand=True)
        sb = tk.Frame(self, bg=C_SURFACE, height=24)
        sb.pack(fill="x", side="bottom"); sb.pack_propagate(False)
        self._status_conn = tk.Label(sb, text="\u25cf not connected",
            bg=C_SURFACE, fg="#444444", font=("Segoe UI",8))
        self._status_conn.pack(side="left", padx=(12,16), pady=4)
        tk.Frame(sb, bg=C_BORDER, width=1).pack(side="left", fill="y", pady=4)
        self._status_time = tk.Label(sb, text="", bg=C_SURFACE,
            fg=C_TEXT_HINT, font=("Segoe UI",8))
        self._status_time.pack(side="left", padx=12, pady=4)

        self.table = CanvasTable(self, on_double_click=self._on_edit_cell)
        self.table.pack(fill="both", expand=True)

    def _set_status_connected(self, ok):
        self._status_conn.config(text="\u25cf connected" if ok else "\u25cf not connected",
            fg="#22c55e" if ok else "#444444")
    def _set_status_text(self, text, fg=None):
        self._status_conn.config(text=text, fg=fg or C_TEXT_DIM)
    def _set_status_time(self):
        self._status_time.config(text=f"Last scraped {datetime.datetime.now().strftime('%H:%M')}")
    def _set_scrape_btn(self, enabled):
        self._scrape_btn.configure(state="normal" if enabled else "disabled")
    def _set_btn_state(self, fragment, enabled):
        state = "normal" if enabled else "disabled"
        for w in self.winfo_children():
            if isinstance(w, tk.Frame):
                for child in w.winfo_children():
                    if isinstance(child, tk.Button) and fragment in child["text"]:
                        child.configure(state=state)

    def _show_first_run_welcome(self):
        dark_dialog(self, "Welcome to SSI Scoring Overlay",
            "A default config.json has been created next to the application.\n\n"
            "Please open \u2699 Settings to enter your Shoot'n Score It username "
            "and password before scraping.")
        SettingsWindow(self)

    def _refresh_table(self): self.table.load(self.stages)

    def _on_edit_cell(self, row_idx, col_name):
        if not self.stages or row_idx >= len(self.stages): return
        cv=self.table._cv; x=self.table._col_x(col_name)
        w=self.table._col_widths.get(col_name,80)
        wy=self.table._row_y(row_idx)-int(cv.canvasy(0))
        if self.table._edit_entry: self.table._edit_entry.destroy()
        entry=tk.Entry(cv,bg="#181818",fg=C_TEXT,insertbackground=C_TEXT,
            relief="flat",font=("Segoe UI",10),highlightbackground=C_ACCENT,highlightthickness=1)
        entry.place(x=x,y=wy,width=w,height=CanvasTable.ROW_H)
        self.table._edit_entry=entry
        entry.insert(0,str(self.stages[row_idx].get(col_name,"")))
        entry.select_range(0,"end"); entry.focus()
        _saved=[False]
        def save(event=None):
            if _saved[0]: return
            _saved[0]=True; new_val=entry.get(); entry.destroy()
            self.table._edit_entry=None; self.stages[row_idx][col_name]=new_val; self.table.redraw()
        def cancel(event=None):
            _saved[0]=True; entry.destroy(); self.table._edit_entry=None
        entry.bind("<Return>",save); entry.bind("<FocusOut>",save); entry.bind("<Escape>",cancel)

    def on_scrape(self):
        url = self.match_var.get().strip()
        if not url: dark_dialog(self, "Error", "Enter a match URL first.", kind="error"); return
        if not CONFIG.get("ssi_username") or not CONFIG.get("ssi_password"):
            dark_dialog(self, "Credentials missing",
                "No username or password set.\n\n"
                "Please open \u2699 Settings and enter your Shoot'n Score It credentials before scraping.",
                kind="error"); return
        self._set_scrape_btn(False); self._set_status_connected(False)
        def _run():
            try:
                stages=[]; dbf=app_dir()/"debug_rows.csv"
                if DEBUG_MODE and dbf.exists(): stages=scrape_scores_debug_from_csv()
                if not stages:
                    self.session=create_logged_in_session()
                    stages=scrape_scores_live(self.session,url)
                stages=[normalize_stage(s) for s in stages]
                if not stages:
                    self.after(0,lambda:(dark_dialog(self,"No data","No valid stages found at that URL.",kind="error"),self._set_scrape_btn(True))); return
                def _done():
                    self.stages=stages; self._refresh_table(); self._set_status_connected(True)
                    self._set_status_time(); CONFIG["last_match_url"]=url; save_config(); self._set_scrape_btn(True)
                    if DEBUG_MODE:
                        src="debug_rows.csv" if dbf.exists() else "online"
                        dark_dialog(self,"Success",f"DEBUG_MODE ON — {len(stages)} stages from {src}.")
                self.after(0,_done)
            except Exception as e:
                import traceback; traceback.print_exc(); logger.error("Scraping failed: %s",e,exc_info=True)
                err_str=str(e)
                title,msg=("Login failed",
                    "Could not log in to Shoot'n Score It.\n\n"
                    "Please check your username and password in \u2699 Settings and try again."
                ) if "login" in err_str.lower() or "credential" in err_str.lower() else (
                    "Scraping failed",
                    f"Something went wrong while fetching scores.\n\n"
                    f"Check the URL and your internet connection.\n\nDetail: {err_str}"
                )
                self.after(0,lambda t=title,m=msg:(dark_dialog(self,t,m,kind="error"),self._set_scrape_btn(True)))
        threading.Thread(target=_run,daemon=True).start()

    def on_preview(self):
        if not self.stages: dark_dialog(self, "No data", "Scrape first.", kind="warning"); return
        idx=self.table.get_selected_index(); PreviewWindow(self,self.stages,idx if idx is not None else 0)

    def on_export_csv(self):
        if not self.stages: dark_dialog(self, "No data", "Scrape first.", kind="warning"); return
        path=filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if not path: return
        cols=("Stage","Time","HF","Rounds","A","C","D","M","NS","P")
        with open(path,"w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
            for s in self.stages: w.writerow({c:s.get(c,"") for c in cols})
        dark_dialog(self, "Saved", f"CSV saved to {path}")

    def on_export_overlays(self):
        """Export overlays in a background thread with status bar progress."""
        if not self.stages: dark_dialog(self, "No data", "Scrape first.", kind="warning"); return
        outdir=OUTPUT_DIR; outdir.mkdir(parents=True,exist_ok=True)
        stages=list(self.stages); total=len(stages)
        self._set_scrape_btn(False); self._set_btn_state("Export Overlays",False)
        def _run():
            try:
                for i,s in enumerate(stages,start=1):
                    self.after(0,lambda i=i:self._set_status_text(f"Exporting {i}/{total}\u2026",C_TEXT_DIM))
                    safe=s.get("Stage",f"stage_{i}").replace(" ","_").replace(".","")
                    make_overlay(s,font_path=FONT_PATH,outpath=str(outdir/f"{safe}.png"))
                def _done():
                    self._set_status_connected(bool(self.stages))
                    self._set_scrape_btn(True); self._set_btn_state("Export Overlays",True)
                    dark_dialog(self, "Export complete", f"{total} overlay(s) saved to {outdir}")
                self.after(0,_done)
            except Exception as e:
                logger.error("Export overlays failed: %s",e,exc_info=True)
                self.after(0,lambda m=str(e):(self._set_scrape_btn(True),self._set_btn_state("Export Overlays",True),dark_dialog(self,"Export failed",f"Export failed:\n{m}",kind="error")))
        threading.Thread(target=_run,daemon=True).start()

    def on_settings(self): SettingsWindow(self)

    def on_close(self):
        CONFIG["window_geometry"]=self.geometry(); CONFIG["last_match_url"]=self.match_var.get().strip()
        save_config(); self.destroy()


# ============================================================
# PREVIEW WINDOW
# ============================================================
class PreviewWindow(tk.Toplevel):
    def __init__(self, master, stages, index):
        super().__init__(master)
        self.title("Overlay Preview"); self.configure(bg=C_BG)
        self.update_idletasks(); _dark_titlebar_toplevel(self)
        self.stages=stages; self.index=index; self.img_tk=None
        self.canvas=tk.Canvas(self,bg=C_BG,highlightthickness=0); self.canvas.pack(pady=(10,0))
        bf=tk.Frame(self,bg=C_BG); bf.pack(pady=10)
        tk.Button(bf,text="◄ Previous",command=self.prev_stage,**BTN_STYLE).pack(side="left",padx=6)
        tk.Button(bf,text="Next ►",    command=self.next_stage,**BTN_STYLE).pack(side="left",padx=6)
        tk.Button(bf,text="Close",          command=self.destroy,   **BTN_STYLE).pack(side="left",padx=6)
        tk.Button(bf,text="Save PNG",       command=self.save_current_png,**BTN_PRIMARY).pack(side="left",padx=6)
        self.bind("<Left>",  lambda e:self.prev_stage())
        self.bind("<Right>", lambda e:self.next_stage())
        self.bind("<Escape>",lambda e:self.destroy())
        self.bind("s",       lambda e:self.save_current_png())
        self.focus_set(); self.show_stage()

    def _load_display_image(self):
        img=make_overlay(self.stages[self.index],font_path=FONT_PATH)
        if img.width>MAX_PREVIEW_WIDTH:
            return img.resize((MAX_PREVIEW_WIDTH,int(img.height*MAX_PREVIEW_WIDTH/img.width)),Image.LANCZOS)
        return img

    def show_stage(self):
        d=self._load_display_image(); self.img_tk=ImageTk.PhotoImage(d)
        iw,ih=d.size; self.canvas.config(width=iw,height=ih); self.canvas.delete("all")
        self.canvas.create_image(0,0,image=self.img_tk,anchor="nw")
        self.geometry(f"{max(iw+40,500)}x{ih+PREVIEW_BTN_EXTRA_HEIGHT}")
        self.title(f"Overlay Preview — {self.stages[self.index].get('Stage','')}")

    def save_current_png(self):
        s=self.stages[self.index]
        name=s.get("Stage",f"stage_{self.index}").replace(" ","_").replace(".","")
        path=filedialog.asksaveasfilename(defaultextension=".png",initialfile=f"{name}.png",filetypes=[("PNG files","*.png")])
        if not path: return
        make_overlay(s,font_path=FONT_PATH,outpath=path)
        dark_dialog(self, "Saved", f"Overlay saved to {path}")

    def prev_stage(self):
        if self.index>0: self.index-=1; self.show_stage()
    def next_stage(self):
        if self.index<len(self.stages)-1: self.index+=1; self.show_stage()


# ============================================================
# SETTINGS WINDOW
# ============================================================
class SettingsWindow(tk.Toplevel):
    _FIELDS=[("ssi_username","SSI Username","text"),("ssi_password","SSI Password","password"),
        ("font_path","Font Path","path"),("output_dir","Output Dir","path"),("debug_mode","Debug Mode","bool")]
    _COLOR_LABELS=[("A","A"),("C","C"),("D","D"),("M","M (Mike)"),("NS","NS"),
        ("P","P (Proc.)"),("bg","Pill background"),("outline","Pill outline")]

    def __init__(self, master):
        super().__init__(master)
        self.title("Settings"); self.configure(bg="#111111")
        self.resizable(False,False); self.transient(master)
        self.update_idletasks(); _dark_titlebar_toplevel(self)
        self.grab_set(); self.after(50,self.focus_set)
        self._vars={}; self._show_pw={}; self._color_values={}; self._color_swatches={}
        LABEL_W=18; ENTRY_W=46; pad_x,pad_y=16,5
        lbl_cfg=dict(bg="#111111",fg=C_TEXT,anchor="w",width=LABEL_W,font=("Segoe UI",9))
        entry_cfg=dict(bg="#1a1a1a",fg=C_TEXT_DIM,insertbackground=C_TEXT_DIM,
            relief="flat",font=("Segoe UI",9),width=ENTRY_W,highlightbackground=C_BORDER2,highlightthickness=1)

        for row_i,(key,label,ftype) in enumerate(self._FIELDS):
            current=CONFIG.get(key,"")
            tk.Label(self,text=label+":",**lbl_cfg).grid(row=row_i,column=0,padx=(pad_x,8),pady=pad_y,sticky="w")
            if ftype=="bool":
                var=tk.BooleanVar(value=bool(current)); self._vars[key]=var
                tk.Checkbutton(self,variable=var,bg="#111111",fg=C_TEXT,activebackground="#111111",
                    activeforeground=C_TEXT,selectcolor="#1a1a1a",relief="flat").grid(row=row_i,column=1,padx=(0,pad_x),pady=pad_y,sticky="w")
            elif ftype=="password":
                var=tk.StringVar(value=str(current)); self._vars[key]=var
                sv=tk.BooleanVar(value=False); self._show_pw[key]=sv
                fr=tk.Frame(self,bg="#111111"); fr.grid(row=row_i,column=1,padx=(0,pad_x),pady=pad_y,sticky="w")
                ent=tk.Entry(fr,textvariable=var,show="●",**entry_cfg); ent.pack(side="left")
                tk.Button(fr,text="Show",width=5,command=lambda s=sv,e=ent:(s.set(not s.get()),e.config(show="" if s.get() else "●")),**BTN_STYLE).pack(side="left",padx=(6,0))
            elif ftype=="path":
                var=tk.StringVar(value=str(current)); self._vars[key]=var
                fr=tk.Frame(self,bg="#111111"); fr.grid(row=row_i,column=1,padx=(0,pad_x),pady=pad_y,sticky="w")
                tk.Entry(fr,textvariable=var,**entry_cfg).pack(side="left")
                def _mb(v=var,k=key):
                    def _b():
                        r=(filedialog.askopenfilename(title="Select font file",filetypes=[("Font files","*.ttf *.otf"),("All files","*.*")],initialfile=v.get() or "") if k=="font_path" else filedialog.askdirectory(title="Select output directory",initialdir=v.get() or "."))
                        if r: v.set(r)
                    return _b
                tk.Button(fr,text="Browse…",command=_mb(),**BTN_STYLE).pack(side="left",padx=(6,0))
            else:
                var=tk.StringVar(value=str(current)); self._vars[key]=var
                tk.Entry(self,textvariable=var,**entry_cfg).grid(row=row_i,column=1,padx=(0,pad_x),pady=pad_y,sticky="w")

        fc=len(self._FIELDS); csr=fc
        ttk.Separator(self,orient="horizontal").grid(row=csr,column=0,columnspan=2,sticky="ew",padx=pad_x,pady=(10,4))
        tk.Label(self,text="Overlay Colors",bg="#111111",fg="white",font=("Segoe UI",9,"bold")).grid(row=csr+1,column=0,columnspan=2,padx=pad_x,pady=(2,4),sticky="w")
        cc=get_overlay_colors()
        for i,(ckey,clabel) in enumerate(self._COLOR_LABELS):
            row=csr+2+i; rgba=cc[ckey]; self._color_values[ckey]=list(rgba)
            tk.Label(self,text=clabel+":",**lbl_cfg).grid(row=row,column=0,padx=(pad_x,8),pady=(2,2),sticky="w")
            fr=tk.Frame(self,bg="#111111"); fr.grid(row=row,column=1,padx=(0,pad_x),pady=(2,2),sticky="w")
            sw=tk.Label(fr,bg=_rgb_to_hex(rgba),width=4,relief="solid",borderwidth=1,cursor="hand2")
            sw.pack(side="left",ipady=5,padx=(0,8)); self._color_swatches[ckey]=sw
            sw.bind("<Button-1>",lambda e,k=ckey:self._pick_color(k))
            ap=f", A:{rgba[3]}" if len(rgba)==4 else ""
            rl=tk.Label(fr,text=f"R:{rgba[0]}  G:{rgba[1]}  B:{rgba[2]}{ap}",bg="#111111",fg="#888888",font=("Segoe UI",8),width=28,anchor="w")
            rl.pack(side="left")
            tk.Button(fr,text="Change…",command=lambda k=ckey:self._pick_color(k),**BTN_STYLE).pack(side="left")

        rr=csr+2+len(self._COLOR_LABELS)
        tk.Button(self,text="Reset colors to defaults",command=self._reset_colors,**BTN_STYLE).grid(row=rr,column=0,columnspan=2,pady=(6,2))
        sr=rr+1
        ttk.Separator(self,orient="horizontal").grid(row=sr,column=0,columnspan=2,sticky="ew",padx=pad_x,pady=(8,4))
        bf=tk.Frame(self,bg="#111111"); bf.grid(row=sr+1,column=0,columnspan=2,pady=(4,12))
        tk.Button(bf,text="Save",  width=10,command=self._save,   **BTN_PRIMARY).pack(side="left",padx=8)
        tk.Button(bf,text="Cancel",width=10,command=self.destroy, **BTN_STYLE).pack(side="left",padx=8)
        self.bind("<Escape>",lambda e:self.destroy())
        self.update_idletasks()
        mx=master.winfo_x()+master.winfo_width()//2; my=master.winfo_y()+master.winfo_height()//2
        w,h=self.winfo_width(),self.winfo_height()
        self.geometry(f"+{mx-w//2}+{my-h//2}")

    def _pick_color(self, k):
        res=colorchooser.askcolor(color=_rgb_to_hex(self._color_values[k]),title=f"Choose color — {k}",parent=self)
        if not res or not res[0]: return
        r,g,b=(int(x) for x in res[0]); alpha=self._color_values[k][3] if len(self._color_values[k])==4 else None
        self._color_values[k]=[r,g,b]+([alpha] if alpha is not None else [])
        self._color_swatches[k].config(bg="#{:02x}{:02x}{:02x}".format(r,g,b))
        ap=f", A:{alpha}" if alpha is not None else ""
        for w in self._color_swatches[k].master.winfo_children():
            if isinstance(w,tk.Label) and w is not self._color_swatches[k]:
                w.config(text=f"R:{r}  G:{g}  B:{b}{ap}"); break

    def _reset_colors(self):
        for ckey,default in DEFAULT_COLORS.items():
            self._color_values[ckey]=list(default); r,g,b=default[0],default[1],default[2]
            alpha=default[3] if len(default)==4 else None
            if ckey in self._color_swatches: self._color_swatches[ckey].config(bg="#{:02x}{:02x}{:02x}".format(r,g,b))
            ap=f", A:{alpha}" if alpha is not None else ""
            for w in self._color_swatches[ckey].master.winfo_children():
                if isinstance(w,tk.Label) and w is not self._color_swatches[ckey]:
                    w.config(text=f"R:{r}  G:{g}  B:{b}{ap}"); break

    def _save(self):
        for key,var in self._vars.items():
            val=var.get(); CONFIG[key]=bool(val) if isinstance(var,tk.BooleanVar) else str(val).strip()
        CONFIG["colors"]={k:v for k,v in self._color_values.items()}; save_config()
        dark_dialog(self, "Settings saved",
            "All changes have been saved.\n\n"
            "Credentials and color changes take effect immediately on the next scrape or export.\n\n"
            "Font path and output directory changes require a restart to take effect.",
            kind="info")
        self.destroy()


# ------------------------
# MAIN
# ------------------------
if __name__ == "__main__":
    app = ScoringApp()
    app.mainloop()