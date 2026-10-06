# BBQ Chart to Data: code notes

Last updated 7 October 2026 for v1.0.0. Repo: github.com/IamRepository/BBQ_chart_to_data (public). Streamlit app on Streamlit Community Cloud; files are uploaded to GitHub manually through the web interface.

## Conventions
- Release zip: "BBQ Chart to Data vX.Y.Z.zip", inner folder named the same.
- Every release zip includes this file, updated for that release.
- Keep files at the top level (subfolders did not survive manual upload in the other projects).
- After uploading a release that changes more than app.py, reboot the app (Manage app, ⋮, Reboot app).
- Output: Timestamp in "%d/%m/%Y %H:%M" (day first), then "Ambient temperature (unit)", "Meat temperature (unit)". CSV is UTF-8 with BOM (Excel shows °C correctly). The Cook Profile Dashboard's profile_loader imports it as two profiles (checked for v1.0.0).

## Files
- app.py: page in five steps (screenshot, temperature axis, time axis, lines, data). Overlay figure is a plotly go.Image (PNG data URI) with the search box, reference lines (#c026d3) and traced lines in a contrasting colour. Widget state for one image lives in IMAGE_KEYS and is cleared when a new image arrives (sha1 digest). The example chart prefills 150/0 °C and 01/06/2026 18:00 to 02/06/2026 04:00. Uploads start at 100/0 and 12:00-20:00, and a warning shows while those are unchanged.
- digitizer.py:
  - detect_layout: thin strokes against local background (_thin_strokes compares with pixels 4 px either side), rows grouped by extent; largest group = grid. Extent = longest run (breaks up to 6 px, then 16 px for dashed), with coloured pixels counted so data lines crossing a gridline do not cut it. Vertical gridlines at the ends refine left/right. Background for tracing = most common colour inside the plot.
  - colour_candidates: hue histogram (72 bins) of saturated pixels, ranked by share of columns covered.
  - coverage_map: projection of each pixel on the background->line colour segment; coverage = position, accepted if the residual < tolerance x max(coverage, 0.25).
  - _column_runs: runs seeded on coverage >= 0.35, grown 2 px into faint edges.
  - trace_line: dynamic programming over column runs (reward up to 1 per column; skip 0.25 per column capped at 4; jump cost 45/H per pixel of separation; lookback up to W/3 columns). Then islands short and far from neighbours are dropped. Tall runs at a peak/dip take the far end. Gaps up to max_bridge_px are interpolated.
  - Calibration: linear, two references per axis.
  - build_table: regular clock from the start reference; ticks within 0.6 column of the ends keep the end value; gaps longer than max_gap_s stay empty. build_pixel_table: one row per column with seconds.
- example_chart.py: drawn at 4x and downsampled with LANCZOS. Ambient with a lid-open dip at 22:00 that crosses the meat line; meat from 18:15; legend inside the plot in line colours.
- test_digitizer.py: 16 tests (layout light/dark, phone card, dashed gridlines, colours, accuracy light/dark/JPEG/half-size/blue-green, crossing, legend, table values, pixel table, gaps, CSV, calibration).

## Measured accuracy (v1.0.0, example chart)
Mean error 0.03 °C, max 0.3 °C (0.1 px mean) for light, dark, phone screenshot; JPEG q75 0.04 °C mean. The lid-open spike is excluded from these numbers: it is narrower than the line width and is read within a few pixels.

## Open ideas
1. Second Y axis (separate calibration per line).
2. Text recognition of axis labels (would need tesseract via packages.txt).
3. Click on the screenshot to place references (streamlit-image-coordinates) instead of choosing gridlines.
4. Test with real screenshots from the user's apps.
