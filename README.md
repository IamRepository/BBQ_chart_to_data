# BBQ Chart to Data

Turn a screenshot of a temperature chart (from a probe or smoker app) into a table with three columns, and download it as CSV:

| Timestamp | Ambient temperature (°C) | Meat temperature (°C) |
|---|---|---|
| 01/06/2026 18:00 | 25.4 | 11.1 |

Timestamps are day/month/year. The CSV imports straight into the Cook Profile Dashboard (BBQ_temp_dashboard).

## How to use

1. **Screenshot**: upload the original screenshot from your phone (PNG is best). Or try one of the examples. The app recognises known thermometer apps (Meater, Typhur, Weber Smoque XL, Weber gas grill / Connect) from the words on their screen and shows "Recognised: …"; the *Chart app* list changes it, or reads the chart without a profile.
2. **Temperature axis**: the app reads the labels on the temperature axis (for example 0°, 24°, … 143°) and fits one straight scale through all of them. Labels it cannot read are left out. You can switch to *Two reference lines* and type values yourself.
3. **Time axis**: the app reads the time labels.
   - Elapsed hours (4h, 8h, …): give the **start date and start time** of the cook (the time at 0 h). If the screenshot shows the date (for example "Jun 21, 2026") or the start time ("Jun 21, 2026 18:05", "Start: 18:05"), they are filled in for you.
   - Clock times (18:00, 20:00, …): give the date of the first label; charts that run past midnight are handled.
   - Or switch to *Two reference points* and give the date and time at two places on the axis.
4. **Lines**: a recognised app's profile decides which colour is which (Meater: green ambient, magenta meat; Typhur: lavender ambient, red internal; Weber: the cooker line, which on the Weber Smoque XL is a setpoint (averaged reading, flat steps) and on a Weber gas grill or Weber Connect probe the instant temperature (wiggly)); otherwise the legend words decide (Internal/Meat/Probe → meat, Ambient/Pit/Grill/Smoker → ambient). A flat line, such as a target or setpoint, is never used. Without a legend, ambient is the line that is hotter at the start of the cook. You can change either line, or pick *Custom colour*.
5. **Data**: check that the thin traced lines sit on the curves in the screenshot and choose the time step between rows (every minute by default). Where the app recorded nothing (a gap, often drawn dotted), *Join gaps with straight lines* fills the values on a straight line across the gap; filled stretches are dotted in the chart.
6. **Export**: the file name starts as the screenshot's name; change it if you like and press *Download CSV*. In Chrome and Edge the browser asks where to save the file; other browsers save to the Downloads folder unless "Ask where to save each file" is on in their settings. Choose which columns go into the file (Timestamp, Ambient, Meat, and Filled, which marks values filled across gaps).

The *Dark mode* switch next to the title changes the look (the same choice is in the ⋮ menu). Hover over the screenshot to read pixel positions; drag to zoom in. *Search area and tracing settings* has the box the lines are searched in, the colour tolerance, gap bridging, a top-edge option for charts with a filled area under the line, and optional smoothing.

## How it reads the chart

- **Gridlines** (solid or dashed) are thin grey strokes found against their own local background, so a chart on a card inside a phone screenshot works. A flat coloured line (target) is not taken for a gridline.
- **Plot edges**: when gridlines run underneath the temperature labels, the axis line next to the labels is taken as the chart's edge.
- **Axis labels** are cut out one by one and read with Tesseract several times at different sizes. The degree sign is removed first. The readings that fit one straight line across all labels win, so a misread label is dropped instead of bending the scale. Labels use the exact position of their gridline, whether the chart centres them on it or draws them just below or beside it.
- **Legend**: words near the chart are read, matched to known names, and the colour of the dot or line next to each word is taken.
- **Lines** are traced one pixel column at a time. Anti-aliased edge pixels are a blend of the line colour and the background; how much of each pixel is line colour gives the centre of the line to a fraction of a pixel. Pale lines (such as lavender) are found too. Each pixel is given to the line colour that explains it best, so similar colours (a pale ambient line next to a purple target line) and grey gridlines do not mix. Where an app shades the area under one line translucently, a line running inside that shading changes shade; the two shades are recognised as one line and traced throughout.
- **Markers** drawn on a line in its colour (a peak triangle, dots) are removed before tracing; the line is bridged across them.
- **One continuous path** is chosen through the columns, so legend text, labels and other lines are skipped. Short gaps are bridged; longer gaps stay empty.
- **Check against the screenshot**: when the screenshot prints the cook's start and end time ("17:40 to 03:52"), Step 5 compares them with the table.
- **Rows** are interpolated onto a regular clock that starts at the start time. Where the app recorded nothing (a gap in the chart), the rows stay, and are either filled on a straight line across the gap (default) or left empty. Pieces of a line after a long gap are traced too. *Every pixel column* gives the raw resolution with seconds in the timestamp.

Accuracy on the test charts, per minute, against the curves they were drawn from: mean error 0.07–0.2 °C for a replica of a phone probe app (1080 px wide, 582 px wide, and JPEG). Errors are larger only where the curve jumps within one pixel column (lid openings) or under markers drawn on the line. Rounded axis labels (143 for 143.3) add up to about 0.3 °C.

## Limits

- Axes must be linear. A chart with a separate scale for each line (two Y axes) is not supported yet.
- Lines must have different colours from each other. Grey or black lines can be picked with *Custom colour*.

## Adding another thermometer app

Open `vendors.py`, copy one entry and change it: a few words that are always on the app's screen (lower case), how many of them must be found, and the colours of its lines (`ambient`, `meat`, `target`). Everything else (axes, dates, gaps) is read the same way for every app.

## Files

- `app.py`: the Streamlit interface.
- `digitizer.py`: gridlines, line colours, tracing, calibration and the table.
- `chart_text.py`: reading axis labels, the legend and the cook details above and below the chart (Tesseract).
- `vendors.py`: known apps (Meater, Typhur, Weber): how to recognise them and their line colours.
- `example_chart.py`: the example charts, drawn from known curves (also used by the tests).
- `test_digitizer.py`, `test_chart_text.py`: tests. Run `python -m unittest test_digitizer test_chart_text`.
- `version.py`, `requirements.txt` (exact versions tested), `packages.txt` (Tesseract, installed by Streamlit Cloud), `.gitignore`.
- `bbq-chart-to-data-notes.md`: development notes.

## Deploying on Streamlit Community Cloud

New app → this repository → main file `app.py`. Under *Advanced settings* choose Python 3.12 or newer (numpy 2.5 needs it). `packages.txt` makes Streamlit Cloud install Tesseract; without it the app still works, with the axes set by hand.
