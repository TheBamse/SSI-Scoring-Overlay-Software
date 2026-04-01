# Changelog
## v3.0

### New
- Completely redesigned UI — dark theme throughout with a modern flat aesthetic
- Custom canvas-based table replaces the system treeview, enabling per-cell colour rendering
- Hit columns (A, C, D, M, P, NS) now display in their configured overlay colours directly in the table
- HF (hit factor) column highlighted in blue as the primary performance number
- Zero hit values are dimmed to reduce visual noise — only non-zero hits stand out
- Selected row shows a blue left-border accent and dark blue background
- Hovered row highlights with a lighter background and a dim blue accent
- Status bar at the bottom shows connection state (grey/green dot) and last scraped time
- Vertical and horizontal scrollbars appear automatically when content exceeds the visible area, and disappear when not needed — both are dark-themed to match the UI
- Window is freely resizable in both directions with no enforced minimum size
- Preview Overlay window now has a Close button between Next and Save PNG
- Preview Overlay and Settings windows match the dark theme of the main window

### Changed
- Buttons are right-aligned in the header bar; order left to right: Scrape → Preview Overlay → Export CSV → Export Overlays → ⚙ Settings
- Cell editor opens with the existing value pre-selected — type immediately to overwrite
- Clicking anywhere outside an open cell editor now saves the value (previously required pressing Enter)
- Double-clicking a new cell while editing another now commits the first edit before opening the second
- Stage column auto-sizes to the longest stage name after each scrape
- Preview Overlay defaults to the first stage when none is selected rather than showing an error

---

## v2.5

### New
- Auto-creates a default `config.json` on first run — no more crash on missing file
- First-run welcome dialog opens Settings automatically so credentials can be entered straight away
- Scrape is blocked with a clear message if username or password are not set
- Overlay pill colours (A, C, D, M, P, NS, background, outline) are now configurable from within the app via ⚙ Settings
- Native system RGB colour picker for each colour with a live swatch preview
- Reset colours to defaults button in Settings
- Clicking a colour swatch opens the colour picker (same as the Change… button)
- Settings window: browse buttons for font path and output directory

### Changed
- Preview Overlay defaults to the first stage when none is selected rather than showing an error
- Double-click cell edit pre-selects the existing value — type a digit to overwrite immediately
- Login rewritten: direct POST to the correct form action URL, success detected by final redirect URL rather than page body text — more reliable and one fewer network request
- Scrape runs in a background thread — the UI stays responsive while fetching
- Scrape button re-enables correctly after errors — no more permanently disabled button on login failure
- Error messages split into two categories: login failure (with a pointer to Settings) and network/scrape errors (with technical detail)
- Stage column auto-sizes to the longest stage name after each scrape

### Fixed
- Scrape button stayed disabled after a failed login attempt
- Error message after scrape failure showed a `NameError` instead of the actual error text
- `config.json` missing caused an immediate crash on startup

---

## v2.0 — v2.4 (internal builds)

### New
- Settings window (⚙ Settings button) — edit all config fields from within the app without touching `config.json` directly
- Password field has a Show/Hide toggle
- Font path and output directory have Browse buttons
- Window size and last used match URL are saved automatically on close and restored on next launch
- Debug mode toggle in Settings

### Changed
- All error and parse failures in the scraper are now logged to `error.log` next to the application instead of being silently swallowed
- `error.log` path is resolved correctly whether running as a Python script or a PyInstaller `.exe`
- Scrape errors include the row that failed and the values that caused the failure
- Stage, Time, and HF values are normalised to the correct types immediately after scraping — editing and exporting always receive clean data

### Fixed
- Scraper silently dropped rows that failed to parse with no indication of what went wrong
- Login check was fragile — relied on detecting the word "logout" in the page body
- Duplicate image-scaling logic in the preview window
- `_normalize_stage` was called in three separate places; now called once after scraping

---

## v1.0

- Initial release
- Scrapes stage scores from Shoot'n Score It match pages
- Displays results in a dark-themed table
- Overlay image generation with configurable pill layout per stage
- Preview window with Previous/Next navigation and Save PNG
- Export all overlays as PNG files
- Export scores as CSV
- Config loaded from `config.json`
- Debug mode: load scores from a local `debug_rows.csv` instead of scraping live