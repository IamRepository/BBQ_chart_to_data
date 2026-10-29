# Chart-2-Data (formerly BBQ Chart to Data): code notes

Last updated 29 October 2026 for v1.7.2. Repo: github.com/IamRepository/BBQ_chart_to_data (public). Streamlit app on Streamlit Community Cloud. Since v1.5.0 (16 Oct 2026) Claude has push access to the repo (granted in the session) and commits releases straight to main; before that, files were uploaded manually through the GitHub web interface (the v1.5.0 manual upload was never committed, which is why the app kept showing v1.4.0).

## Conventions
- Release zip (when one is made): "Chart-2-Data vX.Y.Z.zip", inner folder named the same (before v1.7.2: "BBQ Chart to Data vX.Y.Z.zip").
- Every release zip includes this file, updated for that release.
- Keep files at the top level (subfolders did not survive manual upload in the other projects).
- After uploading a release that changes more than app.py, reboot the app (Manage app, ⋮, Reboot app). A release that adds packages.txt needs the reboot so Tesseract gets installed.
- Output: Timestamp in "%d/%m/%Y %H:%M" (day first), then "Ambient temperature (unit)", "Meat temperature (unit)". CSV is UTF-8 with BOM (Excel shows °C correctly). The Cook Profile Dashboard's profile_loader imports it as two profiles (checked for v1.0.0).

## User's chart (feedback 7 Oct 2026, v1.0.0)
Phone probe app: legend dots "Internal" (red #fa3a37), "Target" (purple #dd55fd), "Ambient" (lavender #9ba5fa); flat target line at 100 °C; red internal line with a pink gradient fill and a red peak marker; dashed grey gridlines; y labels 0°, 24°, 48°, 72°, 96°, 119°, 143° (rounded, scale max probably ~143.3); x labels 4h … 24h (elapsed); "Cook Again" red button under the chart. v1.0.0 failed on it: the lavender line was too pale for the colour finder, the target line was taken as ambient (hotter of two), and the axes had to be typed (default 100 left at the top). The screenshot the user sent was of the app view, with overlays covering the original lines, so testing uses a replica (example_chart.make_probe_example). Still to do: test with the original phone screenshot.

## v1.1.1 (feedback 7 Oct 2026 on v1.1.0)
The ambient trace stopped at the 10 h drop. Cause: the app draws its pink shading under the meat line translucently over the ambient line, so inside it the ambient line is #a49ee7 instead of #9ba5fa (confirmed from the user's screenshot). v1.1.0 saw two colours, and the "best-matching colour wins" rule gave the tinted pixels to the second colour. Fix: _merge_shades in colour_candidates joins colours that are close (< 60 RGB) and either occupy different columns (overlap < 35 %) or, where both appear, the second lies within the first's vertical extent in > 70 % of shared columns (pixels on a third line ignored). The merged candidate keeps `variants`; trace_line/coverage_map take `shades` (a pixel counts if it fits any shade; competition only against other lines). The replica now draws its shading translucently over the ambient line (alpha 0.16 → 0.03) to reproduce this.

## Audit 16 Oct 2026: Weber Smoque XL screenshot (fixed in v1.6.0, see below)
1920x1080 landscape chart, one red line (cavity), labels 0-250° every 50 drawn just BELOW their gridline, clock labels 20:00/23:00/02:00/"Now" drawn just RIGHT of their gridline, header "20 Jun 2026 - 17:40 to 03:52". The trace itself is right (plateaus at rows 735.6/638.7/510.7 = 79.8/110.0/149.9 °C). Findings:
1. Horizontal gridlines run under the y labels to x=30, so plot.left=30 (the axis line at 186.5 is ignored, rule only accepts end gridlines within 4 % of the width). y_label_boxes looks left of x=30, finds nothing -> no temperature labels -> manual mode with placeholders 100 (top gridline) / 0 -> every value x0.4 (80->32, 110->44, 150->60). Main cause of the wrong numbers.
2. Labels are offset from their gridlines (y: ~35 px below; x: text starts ~15 px right of the gridline). The app uses the text centre, so even with labels read: top 261 / bottom 11 instead of 250 / 0, and times 21-26 min early (17:19-03:26 instead of 17:40-03:52).
3. The 150° gridline is missing from h_lines: the line lies on it for 3.5 h and the row is rejected as a coloured flat line.
4. Header date read; start time not (the ' - ' between date and time is not accepted); end time 03:52 and 'Now' could also anchor the time axis.

## v1.7.2 (29 Oct 2026): new name
- App renamed "Chart-2-Data" (APP_NAME; title ":material/dashboard: Chart-2-Data", logo kept; browser tab title). Repository name BBQ_chart_to_data and the Streamlit app address unchanged.

## v1.7.1 (27 Oct 2026): two kinds of Weber chart
User's domain note: a Weber plot with FLAT, stepped lines is the Weber Smoque XL, whose cooker line is a setpoint using an averaged temperature reading; a Weber plot with a WIGGLY line is a gas BBQ or the Weber Connect probe and shows the instant temperature. (Same reason the Cook Profile Dashboard has a "setpoint" tick and the user puts a probe at grate level for the instant temperature.)
- vendors.py: Vendor.kind {role: 'setpoint' | 'instant'}; profiles 'weber_smoque' (words smoque + weber, min 2, ambient = setpoint) and 'weber' (gas grill / Weber Connect: weber, igrill, weber connect, genesis, spirit; ambient = instant).
- digitizer.stepped_share(trace): share of columns level with the next (|dy| < 0.3 px). Real Smoque screenshot 0.93; measured Meater lines 0.25-0.40. App: a plain "Weber" screen with stepped_share > 0.85 gets a hint to choose Weber Smoque XL. Step 5 shows an info box when the ambient values are a setpoint.

## v1.7.0 (27 Oct 2026): app profiles (vendors)
- vendors.py: Vendor(key, name, words, min_words, lines{role: rgb}, note); VENDORS = Meater, Typhur (the user's "21 June probe app"), Weber. detect(text) counts screen words; roles_for(vendor, candidates) gives each role the nearest candidate colour (any shade) within 75 RGB.
- chart_text: text is read above AND below the chart (_text_below_chart: from plot bottom + max(12 % of plot height, 40 px), phone status/navigation bars skipped). read_header -> Header(date, start, end, duration, text); end = start + duration when only those are given. parse_duration: 'Total Duration 01:25:20', 'Cooking Time' with '22hr 44min' on the next line, 'Elapsed 22hr45min'. Elapsed labels shown as '22m', '1h 6m'. _label_runs keeps words of one label together ('1h 6m') only where gaps are < 1 text height and < half the typical gap.
- app: Step 1 shows "Recognised: X" + "Chart app" select (Recognise automatically / Meater / Typhur / Weber / Other app). Line roles: profile first (a flat line named by the profile is still used), then legend, then "hotter at the start". Cross-check also compares duration with the table span (Typhur).
- Real screenshots: 3 Meater (one cook, three probes: peaks 81.6/82.3/83.6 vs app bubbles 82/83/84; 17:03-18:28 matches Cook Started + Total Duration), Weber and Typhur all recognised with correct roles. example_chart.make_meater_example + tests.
- Diff audit fixes before release: flat ambient line named by a profile was being dropped; a profile matching only the target colour blocked the fallback assignment; '1h 6m' merge rule could join crowded labels; note when a chosen profile's colours are not in the chart.

## v1.6.0 (16 Oct 2026): fixes from the Weber audit
- detect_layout: if a column of labels (_label_column: dark uncoloured text beside ≥3 gridlines) sits between where the gridlines start and the first vertical line, that line (the axis) is the plot's left edge (same on the right). Rows partly hidden at one end (value bubble) join the grid if one end matches and they span ≥ 50 % (this also brings in lighter minor gridlines).
- y_label_boxes: rows ≥ 60 % ink are gridlines, not text (they now run through the label strip).
- chart_text._align: label positions from their gridlines using the offset most labels share (centred, below/above, right of the line); a missing gridline uses label position minus the offset. Replaces per-label snapping for both axes.
- parse_start_time accepts '20 Jun 2026 - 17:40'; parse_end_time reads '17:40 to 03:52'; read_header -> (date, start, end). The app compares the screenshot's start/end with the table and shows a green check or a warning in Step 5.
- End markers: marker_centres(); a round marker just past either end of the traced line becomes its first/last point (the dot under a value bubble = latest reading; Weber: 145.4 °C, bubble says 145°).
- example_chart.make_weber_example + WeberStyleChart tests. Weber screenshot now: 250/0 °C, 17:44-03:53 (header 17:40-03:52), plateaus 79.7/110.0/149.9.

## v1.5.0 (16 Oct 2026)
- Title ":material/dashboard: BBQ Chart to Data" (logo first).
- Dark mode switch next to the title (theme_switch). Streamlit cannot change the theme from Python; the switch clicks Streamlit's own ⋮ menu items (stMainMenuItem-theme-Dark/Light), then the menu's Rerun so the HTML table follows. No page reload, so the uploaded screenshot stays. The switch follows st.context.theme when the theme is changed in the menu.
- Start time: chart_text.read_start / parse_start_time read a time on the date's line ('Jun 21, 2026 18:05', '21.06.2026, 6:05 PM') or after a start word ('Start: 18:05', 'Started 6:05 PM', 'Startzeit 07:30'). Status bar of full phone screenshots (top 4 %) is skipped so the phone clock is not taken. The user's app (21 June screenshot) shows only the date and the cooking time, so the start time still has to be set there.
- Export: "Columns to export" pills (Timestamp, Ambient, Meat, Filled when gaps were filled); the old Filled checkbox is now one of the pills.

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
- test_digitizer.py (21 tests) and test_chart_text.py (34 tests; skipped without Tesseract).

## Measured accuracy (v1.1.0)
Replica of the probe app, per-minute table vs true curves, excluding minutes where the curve jumps: mean 0.07-0.12 °C (1080 px PNG), 0.15-0.19 °C (582 px), 0.08-0.13 °C (JPEG q80). Rounded labels add up to ~0.3 °C at the top of the scale. Example chart: mean 0.03 °C.

## Open ideas
1. Second Y axis (separate calibration per line).
2. Click on the screenshot to place references (streamlit-image-coordinates) instead of choosing gridlines.
3. Hide line markers (peak triangle) from the trace.
