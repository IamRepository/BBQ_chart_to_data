"""BBQ Chart to Data: turn a screenshot of a temperature chart into a table.

Steps: upload a screenshot, tell the app what two gridlines on each axis mean,
pick the ambient and meat line colours, check the traced lines on top of the
screenshot, then download the table as CSV.
"""
from __future__ import annotations

import base64
import colorsys
import hashlib
import io
from datetime import date, datetime, time, timedelta

import numpy as np
import plotly.graph_objects as go
import streamlit as st

import digitizer as dg
from example_chart import HOURS as EX_HOURS, START as EX_START, Y_MAX as EX_YMAX, Y_MIN as EX_YMIN, make_example
from version import VERSION

APP_NAME = 'BBQ Chart to Data'
SERIES = ('Ambient temperature', 'Meat temperature')
KEYS = ('amb', 'meat')
REF_COLOUR = '#c026d3'      # reference lines on the screenshot
CUSTOM = 'Custom colour…'
NONE = 'Not in this chart'
INTERVALS = {
    'Every minute': 60, 'Every 2 minutes': 120, 'Every 5 minutes': 300,
    'Every 10 minutes': 600, 'Every 15 minutes': 900, 'Every 30 minutes': 1800,
    'Every pixel column (adds seconds)': 0,
}
# widget keys that belong to one image; cleared when a new image is loaded
IMAGE_KEYS = ('y1_sel', 'y1_px', 'y1_val', 'y2_sel', 'y2_px', 'y2_val',
              'x1_sel', 'x1_px', 'x1_date', 'x1_time', 'x2_sel', 'x2_px', 'x2_date', 'x2_time',
              'amb_sel', 'amb_hex', 'meat_sel', 'meat_hex',
              'area_l', 'area_t', 'area_r', 'area_b')

st.set_page_config(page_title=APP_NAME, page_icon='📈', layout='wide')
st.markdown("""<style>
.bcd-chip{display:inline-flex;align-items:center;gap:6px;margin:0 14px 6px 0;font-size:.9rem}
.bcd-chip span.sw{width:16px;height:16px;border-radius:3px;border:1px solid rgba(128,128,128,.5);display:inline-block}
</style>""", unsafe_allow_html=True)


# --------------------------------------------------------------------------- cached work

@st.cache_data(show_spinner=False, max_entries=8)
def analyse_image(data: bytes):
    img = dg.load_image(data)
    return img, dg.detect_layout(img)


@st.cache_data(show_spinner=False, max_entries=2)
def example_png() -> bytes:
    buf = io.BytesIO()
    make_example().image.save(buf, 'PNG')
    return buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=16)
def find_colours(digest: str, _img, area: tuple):
    return dg.colour_candidates(_img, dg.PlotArea(*area))


@st.cache_data(show_spinner=False, max_entries=64)
def trace(digest: str, _img, area: tuple, rgb: tuple, bg: tuple, tolerance: float, bridge: int, edge: str):
    return dg.trace_line(_img, dg.PlotArea(*area), rgb, np.array(bg), tolerance, bridge, edge)


@st.cache_data(show_spinner=False, max_entries=8)
def png_data_uri(data: bytes) -> str:
    img = dg.load_image(data)
    buf = io.BytesIO()
    from PIL import Image
    Image.fromarray(img).save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- helpers

def contrast_colour(rgb) -> str:
    """A strong colour clearly different from the line, for drawing the trace on top."""
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    r, g, b = colorsys.hls_to_rgb((h + 0.5) % 1, 0.45, 0.95)
    return '#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))


def ref_choice(label: str, key: str, options: list, default_index: int, custom_label: str,
               custom_default: float, limit: int) -> float:
    """Select a detected gridline or type a pixel position."""
    names = [o[0] for o in options] + [custom_label]
    if key + '_sel' not in st.session_state:
        st.session_state[key + '_sel'] = names[min(default_index, len(names) - 1)]
    choice = st.selectbox(label, names, key=key + '_sel')
    if choice == custom_label:
        if key + '_px' not in st.session_state:
            st.session_state[key + '_px'] = float(round(custom_default, 1))
        return st.number_input('Pixel position', 0.0, float(limit), step=0.5, key=key + '_px',
                               help='Hover over the screenshot to read pixel positions.')
    return dict(options)[choice]


def x_options(layout: dg.Layout, area: dg.PlotArea) -> list:
    if layout.plot is None:
        return []
    xs = sorted(set([float(layout.plot.left)] + list(layout.v_lines) + [float(layout.plot.right)]))
    merged = []
    for x in xs:
        if merged and x - merged[-1] < 3:
            merged[-1] = x if x % 1 else merged[-1]          # prefer sub-pixel gridline centres
        else:
            merged.append(x)
    out = []
    for i, x in enumerate(merged):
        name = 'Left edge' if i == 0 else 'Right edge' if i == len(merged) - 1 else f'Gridline {i}'
        out.append((f'{name} (column {x:.1f})', x))
    return out


def reset_for_new_image(digest: str, layout: dg.Layout, is_example: bool, shape):
    for k in IMAGE_KEYS:
        st.session_state.pop(k, None)
    st.session_state.image_digest = digest
    h, w = shape[:2]
    area = dg.default_search_area(layout, w, h)
    st.session_state.area_l, st.session_state.area_t = area.left, area.top
    st.session_state.area_r, st.session_state.area_b = area.right, area.bottom
    if is_example:
        st.session_state.y1_val, st.session_state.y2_val = float(EX_YMAX), float(EX_YMIN)
        st.session_state.x1_date, st.session_state.x1_time = EX_START.date(), EX_START.time()
        end = EX_START + timedelta(hours=EX_HOURS)
        st.session_state.x2_date, st.session_state.x2_time = end.date(), end.time()
    else:
        st.session_state.y1_val, st.session_state.y2_val = 100.0, 0.0
        st.session_state.x1_date, st.session_state.x1_time = date.today(), time(12, 0)
        st.session_state.x2_date, st.session_state.x2_time = date.today(), time(20, 0)


def overlay_figure(data: bytes, img, area, cal_parts, traces, colours) -> go.Figure:
    h, w = img.shape[:2]
    fig = go.Figure(go.Image(source=png_data_uri(data), hovertemplate='column %{x}<br>row %{y}<extra></extra>'))
    fig.add_shape(type='rect', x0=area.left - .5, x1=area.right + .5, y0=area.top - .5, y1=area.bottom + .5,
                  line=dict(color='rgba(128,128,128,.9)', width=1, dash='dash'))
    (y1, v1), (y2, v2), (x1, t1), (x2, t2), unit = cal_parts
    for y, v in ((y1, v1), (y2, v2)):
        fig.add_shape(type='line', x0=0, x1=w - 1, y0=y, y1=y, line=dict(color=REF_COLOUR, width=1))
        fig.add_annotation(x=w - 1, y=y, text=f'{v:g} {unit}', showarrow=False, xanchor='right', yanchor='bottom',
                           font=dict(color=REF_COLOUR, size=12), bgcolor='rgba(255,255,255,.75)')
    for x, t in ((x1, t1), (x2, t2)):
        fig.add_shape(type='line', x0=x, x1=x, y0=0, y1=h - 1, line=dict(color=REF_COLOUR, width=1))
        fig.add_annotation(x=x, y=0, text=t.strftime('%d/%m %H:%M'), showarrow=False, yanchor='top',
                           font=dict(color=REF_COLOUR, size=12), bgcolor='rgba(255,255,255,.75)')
    for (label, tr), colour in zip(traces.items(), colours):
        if tr is None:
            continue
        fig.add_trace(go.Scattergl(x=tr.x, y=tr.y, mode='lines', name=f'{label} (traced)',
                                   line=dict(color=colour, width=1.6),
                                   hovertemplate='column %{x}<br>row %{y:.2f}<extra>' + label + '</extra>'))
    fig.update_layout(height=int(min(820, max(360, 900 * h / w))), margin=dict(l=0, r=0, t=10, b=0),
                      legend=dict(orientation='h', yanchor='bottom', y=1.0, x=0),
                      xaxis=dict(visible=False), yaxis=dict(visible=False), dragmode='zoom')
    return fig


# --------------------------------------------------------------------------- page

st.title(APP_NAME)
st.caption(f'Version {VERSION} · Screenshot of a temperature chart → table of ambient and meat temperatures → CSV')

st.subheader('1. Screenshot')
up_col, ex_col = st.columns([3, 1], vertical_alignment='bottom')
uploaded = up_col.file_uploader('Upload a screenshot of the chart', type=['png', 'jpg', 'jpeg', 'webp'],
                                help='Use the original screenshot (PNG if possible). Cropping is fine; resizing or '
                                     're-compressing loses detail.')
if ex_col.button('Try the example chart', width='stretch'):
    st.session_state.use_example = True
if uploaded is not None:
    st.session_state.use_example = False
    data = uploaded.getvalue()
elif st.session_state.get('use_example'):
    data = example_png()
else:
    st.info('Upload a screenshot to start, or try the example chart.')
    st.stop()

digest = hashlib.sha1(data).hexdigest()
try:
    img, layout = analyse_image(data)
except Exception as exc:          # unreadable file
    st.error(f'The image could not be read ({exc}).')
    st.stop()
H, W = img.shape[:2]
if st.session_state.get('image_digest') != digest:
    reset_for_new_image(digest, layout, uploaded is None, img.shape)

bg = tuple(float(v) for v in layout.background)
unit = st.session_state.get('unit', '°C')

left, right = st.columns([3, 2], gap='large')
figure_slot = left.empty()
left.caption('Drag on the picture to zoom in, double-click to zoom out. Hover to read pixel positions. '
             'The pink lines are your axis references; the thin lines drawn over the curves are what the app read.')

with right:
    # ---- temperature axis
    st.subheader('2. Temperature axis')
    st.caption(f'{len(layout.h_lines)} horizontal gridlines found. Pick two that have a label and type the label.')
    y_opts = [(f'{"Top gridline" if i == 0 else "Bottom gridline" if i == len(layout.h_lines) - 1 else f"Gridline {i + 1}"} (row {r:.1f})', r)
              for i, r in enumerate(layout.h_lines)]
    c1, c2 = st.columns([3, 2])
    with c1:
        y1 = ref_choice('Upper reference', 'y1', y_opts, 0, 'Custom row', H * 0.2, H - 1)
    c2.number_input(f'Temperature ({unit})', step=5.0, key='y1_val', format='%g')
    c1, c2 = st.columns([3, 2])
    with c1:
        y2 = ref_choice('Lower reference', 'y2', y_opts, len(y_opts) - 1, 'Custom row', H * 0.8, H - 1)
    c2.number_input(f'Temperature ({unit}) ', step=5.0, key='y2_val', format='%g')

    # ---- time axis
    st.subheader('3. Time axis')
    st.caption('Give the date and time at two points on the time axis, usually the start and end of the chart.')
    x_opts = x_options(layout, dg.PlotArea(0, 0, W - 1, H - 1))
    c1, c2, c3 = st.columns([3, 2, 2])
    with c1:
        x1 = ref_choice('Start reference', 'x1', x_opts, 0, 'Custom column', W * 0.1, W - 1)
    c2.date_input('Start date', key='x1_date', format='DD/MM/YYYY')
    c3.time_input('Start time', key='x1_time', step=60)
    c1, c2, c3 = st.columns([3, 2, 2])
    with c1:
        x2 = ref_choice('End reference', 'x2', x_opts, len(x_opts) - 1, 'Custom column', W * 0.9, W - 1)
    c2.date_input('End date', key='x2_date', format='DD/MM/YYYY')
    c3.time_input('End time', key='x2_time', step=60)
    t1 = datetime.combine(st.session_state.x1_date, st.session_state.x1_time)
    t2 = datetime.combine(st.session_state.x2_date, st.session_state.x2_time)
    rolled = False
    if t2 <= t1 and st.session_state.x2_date == st.session_state.x1_date:
        t2 += timedelta(days=1)          # chart runs past midnight
        rolled = True
    span = t2 - t1
    hours, minutes = divmod(int(span.total_seconds() // 60), 60)
    st.caption(f'Time between the references: **{hours} h {minutes:02d} min**'
               + (f' (end time is earlier than the start time, so it is read as {t2:%d/%m/%Y})' if rolled else ''))

    # ---- lines
    st.subheader('4. Lines')
    with st.expander('Search area and tracing settings'):
        st.caption('The dashed box on the picture is where lines are searched for. Keep titles and legends '
                   'outside it if they use the same colours as the lines.')
        a1, a2, a3, a4 = st.columns(4)
        a1.number_input('Left', 0, W - 2, step=1, key='area_l')
        a2.number_input('Top', 0, H - 2, step=1, key='area_t')
        a3.number_input('Right', 1, W - 1, step=1, key='area_r')
        a4.number_input('Bottom', 1, H - 1, step=1, key='area_b')
        tolerance = st.slider('Colour tolerance', 20, 140, 70, 5, key='tol',
                              help='How far a pixel may be from the line colour. Raise it for blurry or JPEG '
                                   'screenshots; lower it if the trace jumps onto another line.')
        bridge = st.slider('Bridge gaps up to (pixels)', 0, 100, 25, 1, key='bridge',
                           help='Where the other line is drawn on top, or the line is dashed, short gaps are '
                                'filled with a straight line. Longer gaps stay empty in the table.')
        edge = st.segmented_control('Read the line at', ['Centre', 'Top edge'], default='Centre', key='edge',
                                    help='Use Top edge if the area under the line is filled with the line colour.') or 'Centre'
        smoothing = st.slider('Smoothing (pixels)', 0, 15, 0, 1, key='smooth',
                              help='Moving average across neighbouring pixel columns. 0 keeps the full detail.')

    area = dg.PlotArea(st.session_state.area_l, st.session_state.area_t,
                       st.session_state.area_r, st.session_state.area_b).clip(W, H)
    area_t = (area.left, area.top, area.right, area.bottom)
    cands = find_colours(digest, img, area_t)
    if cands:
        chips = ''.join(f'<span class="bcd-chip"><span class="sw" style="background:{c.hex}"></span>'
                        f'Colour {i + 1}: {dg.colour_name(c.rgb)}</span>' for i, c in enumerate(cands))
        st.markdown(f'<div>{chips}</div>', unsafe_allow_html=True)
    else:
        st.caption('No coloured lines found in the search area. Use Custom colour.')
    names = [f'Colour {i + 1}: {dg.colour_name(c.rgb)} ({c.hex})' for i, c in enumerate(cands)] + [CUSTOM, NONE]

    if 'amb_sel' not in st.session_state:
        # the ambient line is normally the hotter of the two most widespread colours
        if len(cands) >= 2:
            meds = [np.nanmedian(trace(digest, img, area_t, c.rgb, bg, 70, 25, 'Centre').y) for c in cands[:2]]
            order = np.argsort(meds)          # smaller row = higher temperature
            st.session_state.amb_sel, st.session_state.meat_sel = names[order[0]], names[order[1]]
        else:
            st.session_state.amb_sel = names[0]
            st.session_state.meat_sel = names[1] if len(cands) == 1 else NONE

    picked = {}
    for key in KEYS:                      # colours change when the search area changes
        if st.session_state.get(key + '_sel') not in names:
            st.session_state[key + '_sel'] = names[0] if cands else CUSTOM
    for label, key in zip(SERIES, KEYS):
        c1, c2 = st.columns([4, 1], vertical_alignment='bottom')
        choice = c1.selectbox(label + ' line', names, key=key + '_sel')
        if choice == CUSTOM:
            other = picked.get(SERIES[0]) if key == 'meat' else None
            spare = [c.hex for c in cands if c.rgb != other]
            default = spare[KEYS.index(key) % len(spare)] if spare else '#e03030'
            picked[label] = dg.parse_hex(c2.color_picker('Colour', st.session_state.get(key + '_hex', default),
                                                         key=key + '_hex'))
        elif choice == NONE:
            picked[label] = None
        else:
            rgb = cands[names.index(choice)].rgb
            c2.markdown(f'<span class="bcd-chip"><span class="sw" style="background:{"#%02x%02x%02x" % rgb};'
                        f'width:34px;height:34px"></span></span>', unsafe_allow_html=True)
            picked[label] = rgb

    st.radio('Temperature unit on the chart', ['°C', '°F'], horizontal=True, key='unit')

# --------------------------------------------------------------------------- trace and calibrate

cal = dg.Calibration(y1, float(st.session_state.y1_val), y2, float(st.session_state.y2_val), x1, t1, x2, t2)
traces = {}
for label in SERIES:
    rgb = picked[label]
    traces[label] = None if rgb is None else trace(digest, img, area_t, tuple(int(v) for v in rgb), bg,
                                                   float(tolerance), int(bridge), edge.lower().replace(' edge', ''))
colours = [contrast_colour(picked[l]) if picked[l] is not None else '#888' for l in SERIES]
figure_slot.plotly_chart(
    overlay_figure(data, img, area, ((y1, cal.y1_value), (y2, cal.y2_value), (x1, t1), (x2, t2), unit), traces, colours),
    width='stretch', config={'displaylogo': False, 'scrollZoom': False})

defaults_left = uploaded is not None and (
    (st.session_state.y1_val, st.session_state.y2_val) == (100.0, 0.0)
    or (st.session_state.x1_time, st.session_state.x2_time) == (time(12, 0), time(20, 0)))
problems = cal.check()
if picked[SERIES[0]] is not None and picked[SERIES[0]] == picked[SERIES[1]]:
    problems.append('Ambient and meat use the same colour.')
if problems:
    st.divider()
    for p in problems:
        st.error(p)
    st.stop()

# --------------------------------------------------------------------------- results

st.divider()
st.subheader('5. Data')
if defaults_left:
    st.warning('The temperature labels or the times are still at their starting values '
               '(100 / 0 and 12:00 to 20:00). Set them from your chart, or the numbers below will be wrong.')
m = st.columns(4)
m[0].metric('Time per pixel column', f'{cal.seconds_per_px:.0f} s')
m[1].metric(f'Temperature per pixel', f'{cal.degrees_per_px:.2f} {unit}')
for i, label in enumerate(SERIES):
    tr = traces[label]
    m[2 + i].metric(label.replace(' temperature', ' line found'),
                    '—' if tr is None else f'{100 * tr.columns_found:.0f} % of columns',
                    help='Share of pixel columns, between the first and last point of the line, where the line '
                         'colour was found. The rest is bridged or left empty.')
st.caption(f'Lines are read to a fraction of a pixel from the anti-aliased edges, so on a clean screenshot each '
           f'value is typically within ±{max(0.3 * cal.degrees_per_px, 0.05):.1f} {unit} of the drawn line.')

o1, o2 = st.columns([2, 3])
interval_name = o1.selectbox('Rows', list(INTERVALS), index=0, key='interval',
                             help='Values are interpolated between pixel columns onto a regular clock.')
interval = INTERVALS[interval_name]
if interval and cal.seconds_per_px > 3 * interval:
    o2.caption(f'The screenshot has one column every {cal.seconds_per_px:.0f} s, so rows this close together '
               'are interpolated between columns.')

series = {}
for label in SERIES:
    tr = traces[label]
    series[label] = (np.array([]), np.array([])) if tr is None else dg.series_in_units(tr, cal, smoothing)
if interval:
    max_gap = max(cal.seconds_per_px * (bridge + 2), 1.5 * interval)
    table = dg.build_table(series, cal, interval, unit, max_gap_s=max_gap)
else:
    table = dg.build_pixel_table(traces, cal, unit, smoothing)

if table.empty:
    st.warning('No values were found. Check the line colours and the search area.')
    st.stop()

chart = go.Figure()
times = [datetime.strptime(t[:16], dg.TIME_FORMAT) + timedelta(seconds=int(t[17:19]) if len(t) > 16 else 0)
         for t in table['Timestamp']]
for label, rgb in zip(SERIES, (picked[s] for s in SERIES)):
    col = f'{label} ({unit})'
    if rgb is None or table[col].isna().all():
        continue
    chart.add_trace(go.Scatter(x=times, y=table[col], mode='lines', name=label, connectgaps=False,
                               line=dict(color='#%02x%02x%02x' % tuple(int(v) for v in rgb), width=2),
                               hovertemplate='%{x|%d/%m/%Y %H:%M}<br>%{y:.1f} ' + unit + '<extra>' + label + '</extra>'))
chart.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10), hovermode='x unified',
                    legend=dict(orientation='h', yanchor='bottom', y=1.02, x=0),
                    yaxis_title=f'Temperature ({unit})', xaxis=dict(tickformat='%H:%M\n%d/%m'))
st.plotly_chart(chart, width='stretch', config={'displaylogo': False})

st.dataframe(table, width='stretch', hide_index=True, height=320)
first = times[0]
st.download_button('Download CSV', dg.to_csv_bytes(table), file_name=f'chart_data_{first:%Y-%m-%d_%H%M}.csv',
                   mime='text/csv', type='primary', icon=':material/download:')
st.caption(f'{len(table)} rows from {table["Timestamp"].iloc[0]} to {table["Timestamp"].iloc[-1]}. '
           'Timestamps are day/month/year. Empty cells are gaps where the line was not visible.')
