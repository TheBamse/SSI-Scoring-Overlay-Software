## Changelog for version 3.0:

### New features:
* Complete UI rewrite using a custom dark Windows theme. The stage table is now a fully custom-drawn canvas widget with per-cell colour support, hover and selection states, and a blue left-border accent on the selected row.
* Hit columns (A/C/D/M/P/NS) are now rendered in their configured overlay colours directly in the table, and the HF column is highlighted in blue as the primary performance metric. Zero values are dimmed to reduce visual noise.
* All application dialogs (errors, warnings, confirmations) now use a custom dark-themed dialog consistent with the rest of the UI, replacing the default Windows system dialogs.
* Export Overlays now runs in a background thread with live progress shown in the status bar, keeping the UI responsive during export.
* A status bar has been added at the bottom of the main window showing a connection indicator (grey/green dot) and the time of the last successful scrape.

### Improvements:
* Credentials are now read at scrape time rather than on startup, meaning username and password changes in Settings take effect immediately without restarting the application.
* Window position is now saved and restored between sessions. If a saved position would place the window off-screen (e.g. after disconnecting a monitor), it is automatically clamped back into view.
* The debug CSV path now resolves correctly in both script and compiled exe contexts.
* Errors in stage data normalisation now log the specific field name and error rather than failing silently.

### Bug fixes:
* Removed a dead `scrape_scores()` function that was never called by the GUI.
* The custom canvas scrollbar now hides correctly when all content fits on screen, and redraws without flashing the wrong colour on first render.
* Clicking outside an active cell editor now correctly saves the value. Previously, relying on `FocusOut` alone was unreliable on Canvas widgets.
* A double-fire bug in the cell editor where `redraw()` could trigger a second `FocusOut` after the entry was already saved has been fixed.
* Dark title bars now apply correctly on both Windows 10 and Windows 11 across all windows, including dialogs. Windows 10 required a specific repaint cycle that was not previously accounted for.
* Settings window `Escape` key now works immediately on open. Previously, `grab_set()` stole focus before the window was fully mapped.

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