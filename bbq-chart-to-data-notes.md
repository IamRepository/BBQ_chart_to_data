# BBQ Chart to Data: code notes

Last updated 8 October 2026 for v1.4.0. Repo: github.com/IamRepository/BBQ_chart_to_data (public). Streamlit app on Streamlit Community Cloud; files are uploaded to GitHub manually through the web interface.

## Conventions
- Release zip: "BBQ Chart to Data vX.Y.Z.zip", inner folder named the same.
- Every release zip includes this file, updated for that release.
- Keep files at the top level (subfolders did not survive manual upload in the other projects).
- After uploading a release that changes more than app.py, reboot the app (Manage app, ⋮, Reboot app). A release that adds packages.txt needs the reboot so Tesseract gets installed.
- Output: Timestamp in "%d/%m/%Y %H:%M" (day first), then "Ambient temperature (unit)", "Meat temperature (unit)". CSV is UTF-8 with BOM (Excel shows °C correctly). The Cook Profile Dashboard's profile_loader imports it as two profiles (checked for v1.0.0).

## User's chart (feedback 7 Oct 2026, v1.0.0)
Phone probe app: legend dots "Internal" (red #fa3a37), "Target" (purple #dd55fd), "Ambient" (lavender #9ba5fa); flat target line at 100 °C; red internal line with a pink gradient fill and a red peak marker; dashed grey gridlines; y labels 0°, 24°, 48°, 72°, 96°, 119°, 143° (rounded, scale max probably ~143.3); x labels 4h … 24h (elapsed); "Cook Again" red button under the chart. v1.0.0 failed on it: the lavender line was too pale for the colour finder, the target line was taken as ambient (hotter of two), and the axes had to be typed (default 100 left at the top). The screenshot the user sent was of the app view, with overlays covering the original lines, so testing uses a replica (example_chart.make_probe_example). Still to do: test with the original phone screenshot.

## v1.1.1 (feedback 7 Oct 2026 on v1.1.0)
The ambient trace stopped at the 10 h drop. Cause: the app draws its pink shading under the meat line translucently over the ambient line, so inside it the ambient line is #a49ee7 instead of #9ba5fa (confirmed from the user's screenshot). v1.1.0 saw two colours, and the "best-matching colour wins" rule gave the tinted pixels to the second colour. Fix: _merge_shades in colour_candidates joins colours that are close (< 60 RGB) and either occupy different columns (overlap < 35 %) or, where both appear, the second lies within the first's vertical extent in > 70 % of shared columns (pixels on a third line ignored). The merged candidate keeps `variants`; trace_line/coverage_map take `shades` (a pixel counts if it fits any shade; competition only against other lines). The replica now draws its shading translucently over the ambient line (alpha 0.16 → 0.03) to reproduce this.

## v1.4.0 (8 Oct 2026)
- Title "BBQ Chart to :material/dashboard: Data"; page icon :material/dashboard:.
- time_picker(): times are no longer st.time_input; a popover button showing HH:MM opens hour pills (00-23), minute pills (every 5) and an exact-minute box. Time kept in session_state (start_time, x1_time, x2_time), not as a widget key.
- Table drawn as HTML (html_table) because st.dataframe cannot centre headings: sticky header, centred headings and values, colours from st.context.theme.type.
- Download: save_button() in st.html(unsafe_allow_javascript=True); uses the browser Save dialog (window.showSaveFilePicker, Chrome/Edge) with the suggested name, otherwise a normal download. Suggested file name = uploaded screenshot name without extension (examples: probe_app_example / clock_times_example).
- Tested in Chromium (light and dark): picker sets the start, headings centred, Save dialog called with the name (stubbed in the test), fallback download name correct.

## v1.3.0 (gaps, 8 Oct 2026)
- Data gaps: the user's second chart has no data from ~10 h to ~22.5 h (the app joins it with grey dotted lines), then a short stretch at the end. trace_line now looks for further pieces of the line in the columns the main path does not use (_best_path run again, up to 4 pieces, each ≥ max(3, 0.4 % of width) columns), so the end stretch is traced.
- dg.fill_gaps(table): straight-line interpolation in time between the last value before and the first after each gap, per column; nothing added before the first or after the last value. App: toggle "Join gaps with straight lines" (on), filled stretches dotted in the chart, values in table and CSV, optional "Filled" column (Step 6).
- remove_markers: line width measured from solid pixel runs (the coverage estimate ran low on JPEG and removed real line), square ≥ 5 px, and the whole marker region is removed (its thin edges left a fake bump next to a gap). User chart peak 85.4 °C (app 85.6).
- Axis notes ("Read 7 labels…", "Read elapsed-time labels…") moved into the (?) of Scale / Times. Headings "Step 1: …" to "Step 6: Export". Suggested file name follows the start time until the user edits it.
- Replica: make_probe_example(gap=(start, end)).

## v1.2.0 (layout, 8 Oct 2026)
- "Created by Imran Abdul Majid" above the version line (AUTHOR in version.py). Less space above the title (CSS padding on stMainBlockContainer).
- Step 1 in a frame: uploader beside "Or try an example" with two short buttons side by side (Probe app, Clock times; descriptions in tooltips).
- Screenshot panel and steps 2-4 each in a bordered container.
- Metrics: bordered, value only ("88 %"); explanations in the (?) help; values scale with the window (CSS clamp) so nothing is cut off. Checked at 1600, 1150 and 820 px wide.
- "Rows" renamed "Time step between rows". Table values centred (column_config alignment).
- File name box next to Download CSV; ".csv" added if missing, characters not allowed in file names removed.
- Line names shortened (legend word + colour name) so they fit narrow windows.

## v1.1.2 (checked on the user's original screenshot, 8 Oct 2026)
Original phone screenshot (1153 x 2576 JPEG, cook of 21 June 2026, labels 0-180° step 30, 4h-24h, no data 16.5-19.5 h, app peak 85.6 °C) runs through: all 7 temperature labels and 6 time labels read, legend assigns Internal/Ambient, target ignored, ambient traced inside the shading (no second shade needed on this one). Fixes:
- remove_markers (digitizer): opening with a square ~1.8 x line width removes solid blobs in the line colour (the red ▼ peak marker raised the meat peak to 89.7; now 86.0 vs 85.6 in the app). Skipped for "Top edge" mode and for blobs larger than max(1 % of the area, 25 squares).
- Gaps inside the cook stay as empty rows (regular clock); only empty rows at the ends are dropped (_trim_empty_ends).
- read_date / parse_date (chart_text): date above the chart ('Jun 21, 2026', '21.06.2026', ...) fills the start date; the warning then asks only for the start time.
- Gridlines in the original are within ±1 px of even spacing, so the fitted scale is within ~0.3 °C of the labels.

## Files
- app.py: five steps. Axes: segmented control "From the axis labels" (default when read) or manual references. Elapsed-hour charts ask for start date + start time (time at 0 h); clock charts ask for the date at the first label. Table rows are anchored to the start time (elapsed) or midnight (clock), and none before 0 h. Lines: legend roles first (flat lines never auto-assigned), else ambient = line hotter over the first 20 % of the shared time (dg.hotter_early). Overlay shows the labels used as pink dotted lines. A warning shows while the start date/time is the placeholder. IMAGE_KEYS cleared when a new image arrives (sha1 digest). Text reading is cached per image (about 4-6 s).
- chart_text.py (Tesseract via pytesseract; packages.txt installs tesseract-ocr):
  - y_label_boxes / x_label_boxes: ink segmentation beside / under the plot (long axis lines removed); x labels from the first text line with ≥2 boxes inside the plot width.
  - _readings: each box read at heights 32/48/64 px, psm 7, digit whitelist; superscripts (°) removed by column segmentation first.
  - _fit: every pair of candidates from different labels proposes a line; the one explaining most labels wins; least squares on those. Misreads are dropped.
  - Labels snap to a gridline only when centred on it (0.35 x text height for y, 0.2 x width for x).
  - Time kinds: elapsed ("4h", "1h30", "90m"), clock ("18:00", unwrapped past midnight), plain numbers (treated as hours).
  - read_legend: psm 11 over the area above/around the plot; fuzzy word match (ROLE_WORDS); marker colour = coloured pixels left of the word, else the word's own colour.
- digitizer.py:
  - detect_layout: rows qualify on their own extent (dashed gridlines in narrow charts) with ≥30 % grey density; rows whose neighbourhood has a coloured core (chroma > 60) are flat data lines, not gridlines. Crossing lines bridged using chroma > 40 (not the saturation ratio, which is high for near-black backgrounds).
  - colour_candidates: saturation > 0.18 (pastel lines) and _line_like (less colour a few px to one side), so fills are not lines; coverage ≥ 6 % of columns.
  - coverage_map(…, others): pixels another candidate colour explains better are dropped; grey pixels (chroma < 45 % of the expected blend) are dropped for coloured lines.
  - trace_line: dynamic programming over column runs, as in v1.0.0.
  - is_flat: 5-95 % row range < max(2 px, 1 % of plot height).
  - build_table(anchor, not_before).
- example_chart.py: make_example (clock times, legend inside the plot) and make_probe_example (replica of the user's app).
- test_digitizer.py (20 tests) and test_chart_text.py (17 tests; skipped without Tesseract).

## Measured accuracy (v1.1.0)
Replica of the probe app, per-minute table vs true curves, excluding minutes where the curve jumps: mean 0.07-0.12 °C (1080 px PNG), 0.15-0.19 °C (582 px), 0.08-0.13 °C (JPEG q80). Rounded labels add up to ~0.3 °C at the top of the scale. Example chart: mean 0.03 °C.

## Open ideas
1. Second Y axis (separate calibration per line).
2. Click on the screenshot to place references (streamlit-image-coordinates) instead of choosing gridlines.
3. Hide line markers (peak triangle) from the trace.
