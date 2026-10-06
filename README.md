# BBQ Chart to Data

Turn a screenshot of a temperature chart (from a probe or smoker app) into a table with three columns, and download it as CSV:

| Timestamp | Ambient temperature (°C) | Meat temperature (°C) |
|---|---|---|
| 01/06/2026 18:00 | 108.4 | 21.3 |

Timestamps are day/month/year. The CSV imports straight into the Cook Profile Dashboard (BBQ_temp_dashboard).

## How to use

1. **Screenshot**: upload the original screenshot (PNG is best). Or press *Try the example chart*.
2. **Temperature axis**: the app finds the horizontal gridlines. Pick two that have a label (for example the top and bottom ones) and type their temperatures.
3. **Time axis**: give the date and time at two points, usually the left and right edge of the chart. If the end time is earlier than the start time on the same date, the chart is taken to run past midnight.
4. **Lines**: the app lists the line colours it found and guesses which is ambient (the hotter one) and which is meat. Change them if needed, or pick *Custom colour*.
5. **Data**: check that the thin traced lines sit on the curves in the screenshot, choose the row interval (every minute by default) and download the CSV.

Hover over the screenshot to read pixel positions; drag to zoom in. *Search area and tracing settings* has the box the lines are searched in, the colour tolerance, gap bridging, a top-edge option for charts with a filled area under the line, and optional smoothing.

## How it reads the chart

- **Gridlines** are thin grey strokes found against their own local background, so a chart on a card inside a phone screenshot works. Dashed gridlines and lines drawn over gridlines are handled.
- **Lines** are traced one pixel column at a time. Anti-aliased edge pixels are a blend of the line colour and the background; how much of each pixel is line colour gives the centre of the line to a fraction of a pixel.
- **One continuous path** is chosen through the columns, so legend text, labels and the other line are skipped. Where the other line is drawn on top (crossings) or a line is dashed, short gaps are bridged; longer gaps stay empty.
- **Peaks and dips** that are steeper than one column (a lid opening) are read at their tip, not the middle.
- **Calibration** is linear, from the two temperature references and the two time references.
- **Rows** are interpolated onto a regular clock starting at the start time. *Every pixel column* gives the raw resolution with seconds in the timestamp.

On the test charts, values are within about 0.03 °C of the drawn line on average (a tenth of a pixel), and within 0.3 °C at worst, for light and dark charts, JPEG screenshots and half-size screenshots.

## Limits

- Axes must be linear. A chart with a separate scale for each line (two Y axes) is not supported yet.
- The temperature labels and times are typed in; there is no text recognition.
- Lines must have different colours from each other. Grey or black lines can be picked with *Custom colour*.

## Files

- `app.py`: the Streamlit interface.
- `digitizer.py`: image analysis, tracing, calibration and the table.
- `example_chart.py`: the example chart, drawn from known curves (also used by the tests).
- `test_digitizer.py`: accuracy tests. Run `python -m unittest test_digitizer`.
- `version.py`, `requirements.txt` (exact versions tested), `.gitignore`.
- `bbq-chart-to-data-notes.md`: development notes.

## Deploying on Streamlit Community Cloud

New app → this repository → main file `app.py`. Under *Advanced settings* choose Python 3.12 or newer (numpy 2.5 needs it).
