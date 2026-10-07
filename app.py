"""BBQ Chart to Data: turn a screenshot of a temperature chart into a table.

Steps: upload a screenshot; the app reads the axis labels and the legend;
give the start date and time; check the traced lines on top of the
screenshot; download the table as CSV. Every automatic choice can be
overridden by hand.
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

import chart_text as ct
import digitizer as dg
from example_chart import START as EX_START, make_example, make_probe_example
from version import VERSION

APP_NAME = 'BBQ Chart to Data'
SERIES = ('Ambient temperature', 'Meat temperature')
KEYS = ('amb', 'meat')
ROLE_OF = {'amb': 'ambient', 'meat': 'meat'}
REF_COLOUR = '#c026d3'      # axis references on the screenshot
CUSTOM = 'Custom colour…'
NONE = 'Not in this chart'
FROM_LABELS = 'From the axis labels'
Y_MANUAL = 'Two reference lines'
X_MANUAL = 'Two reference points'
INTERVALS = {
    'Every minute': 60, 'Every 2 minutes': 120, 'Every 5 minutes': 300,
    'Every 10 minutes': 600, 'Every 15 minutes': 900, 'Every 30 minutes': 1800,
    'Every pixel column (adds seconds)': 0,
}
# widget keys that belong to one image; cleared when a new image is loaded
IMAGE_KEYS = ('y_mode', 'y1_sel', 'y1_px', 'y1_val', 'y2_sel', 'y2_px', 'y2_val',
              'x_mode', 'x1_sel', 'x1_px', 'x1_date', 'x1_time', 'x2_sel', 'x2_px', 'x2_date', 'x2_time',
              'start_date', 'start_time', 'label_date', 'start_touched', 'manual_touched', 'date_applied',
              'amb_sel', 'amb_hex', 'meat_sel', 'meat_hex',
              'area_l', 'area_t', 'area_r', 'area_b', 'y_prefilled', 'assign_note')
EXAMPLES = {'probe': 'Example: probe app (elapsed hours)', 'clock': 'Example: clock times'}

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


@st.cache_data(show_spinner=False, max_entries=8)
def read_text(digest: str, _img, _layout):
    """Axis labels, legend and the cook date (slowest step: a few seconds)."""
    return (ct.read_temperature_axis(_img, _layout), ct.read_time_axis(_img, _layout),
            ct.read_legend(_img, _layout), ct.read_date(_img, _layout))


@st.cache_data(show_spinner=False, max_entries=4)
def example_png(which: str) -> bytes:
    buf = io.BytesIO()
    (make_probe_example() if which == 'probe' else make_example()).image.save(buf, 'PNG')
    return buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=16)
def find_colours(digest: str, _img, area: tuple):
    return dg.colour_candidates(_img, dg.PlotArea(*area))


@st.cache_data(show_spinner=False, max_entries=64)
def trace(digest: str, _img, area: tuple, rgb: tuple, bg: tuple, tolerance: float, bridge: int, edge: str,
          others: tuple = (), shades: tuple = ()):
    return dg.trace_line(_img, dg.PlotArea(*area), rgb, np.array(bg), tolerance, bridge, edge, others, shades)


@st.cache_data(show_spinner=False, max_entries=8)
def png_data_uri(data: bytes) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(dg.load_image(data)).save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- helpers

def contrast_colour(rgb) -> str:
    """A strong colour clearly different from the line, for drawing the trace on top."""
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    r, g, b = colorsys.hls_to_rgb((h + 0.5) % 1, 0.45, 0.95)
    return '#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))


def touched(flag: str):
    st.session_state[flag] = True


def ref_choice(label: str, key: str, options: list, default_index: int, custom_label: str,
               custom_default: float, limit: int) -> float:
    """Select a detected gridline or type a pixel position."""
    names = [o[0] for o in options] + [custom_label]
    if st.session_state.get(key + '_sel') not in names:
        st.session_state[key + '_sel'] = names[min(default_index, len(names) - 1)]
    choice = st.selectbox(label, names, key=key + '_sel')
    if choice == custom_label:
        if key + '_px' not in st.session_state:
            st.session_state[key + '_px'] = float(round(custom_default, 1))
        return st.number_input('Pixel position', 0.0, float(limit), step=0.5, key=key + '_px',
                               help='Hover over the screenshot to read pixel positions.')
    return dict(options)[choice]


def x_options(layout: dg.Layout) -> list:
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


def reset_for_new_image(digest: str, layout: dg.Layout, example: str | None, shape):
    for k in IMAGE_KEYS:
        st.session_state.pop(k, None)
    st.session_state.image_digest = digest
    h, w = shape[:2]
    area = dg.default_search_area(layout, w, h)
    st.session_state.area_l, st.session_state.area_t = area.left, area.top
    st.session_state.area_r, st.session_state.area_b = area.right, area.bottom
    start = EX_START if example else datetime.combine(date.today(), time(12, 0))
    st.session_state.start_date, st.session_state.start_time = start.date(), start.time()
    st.session_state.label_date = start.date()
    st.session_state.start_touched = bool(example)
    st.session_state.manual_touched = bool(example)
    st.session_state.y1_val, st.session_state.y2_val = 100.0, 0.0
    st.session_state.x1_date, st.session_state.x1_time = start.date(), start.time()
    end = start + timedelta(hours=8)
    st.session_state.x2_date, st.session_state.x2_time = end.date(), end.time()


def fmt_list(values: list, limit: int = 8) -> str:
    if len(values) <= limit:
        return ', '.join(values)
    return ', '.join(values[:3]) + ', …, ' + ', '.join(values[-2:])


def overlay_figure(data: bytes, img, area, y_refs, x_refs, traces, colours) -> go.Figure:
    """Screenshot with the search box, axis references and the traced lines."""
    h, w = img.shape[:2]
    fig = go.Figure(go.Image(source=png_data_uri(data), hovertemplate='column %{x}<br>row %{y}<extra></extra>'))
    fig.add_shape(type='rect', x0=area.left - .5, x1=area.right + .5, y0=area.top - .5, y1=area.bottom + .5,
                  line=dict(color='rgba(128,128,128,.9)', width=1, dash='dash'))
    for y, text in y_refs:
        fig.add_shape(type='line', x0=area.left, x1=area.right, y0=y, y1=y,
                      line=dict(color=REF_COLOUR, width=1, dash='dot'))
        fig.add_annotation(x=area.right, y=y, text=text, showarrow=False, xanchor='left', yanchor='middle',
                           font=dict(color=REF_COLOUR, size=11), bgcolor='rgba(255,255,255,.8)')
    for x, text in x_refs:
        fig.add_shape(type='line', x0=x, x1=x, y0=area.top, y1=area.bottom,
                      line=dict(color=REF_COLOUR, width=1, dash='dot'))
        fig.add_annotation(x=x, y=area.top, text=text, showarrow=False, yanchor='bottom',
                           font=dict(color=REF_COLOUR, size=11), bgcolor='rgba(255,255,255,.8)')
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
                                help='Use the original screenshot from your phone (PNG if possible). Cropping is '
                                     'fine; resizing or re-compressing loses detail.')
for which, label in EXAMPLES.items():
    if ex_col.button(label, width='stretch', key='ex_' + which):
        st.session_state.example = which
if uploaded is not None:
    st.session_state.example = None
    data = uploaded.getvalue()
elif st.session_state.get('example'):
    data = example_png(st.session_state.example)
else:
    st.info('Upload a screenshot to start, or try an example.')
    st.stop()
example = None if uploaded is not None else st.session_state.get('example')

digest = hashlib.sha1(data).hexdigest()
try:
    img, layout = analyse_image(data)
except Exception as exc:          # unreadable file
    st.error(f'The image could not be read ({exc}).')
    st.stop()
H, W = img.shape[:2]
if layout.plot is None:
    st.warning('No chart gridlines were found. Set the axes and the search area by hand.')
    layout.plot = dg.default_search_area(layout, W, H)
if st.session_state.get('image_digest') != digest:
    reset_for_new_image(digest, layout, example, img.shape)

text_ok = ct.available()
if text_ok:
    with st.spinner('Reading the axis labels and the legend…'):
        yfit, xfit, legend, cook_date = read_text(digest, img, layout)
else:
    yfit, xfit, legend, cook_date = ct.AxisFit(), ct.AxisFit(), [], None
if cook_date and not st.session_state.get('date_applied'):
    # the screenshot shows the date (e.g. 'Jun 21, 2026'): use it as the start date
    for key in ('start_date', 'label_date', 'x1_date', 'x2_date'):
        st.session_state[key] = cook_date
    st.session_state.date_applied = True

bg = tuple(float(v) for v in layout.background)
unit = st.session_state.get('unit', '°C')

left, right = st.columns([3, 2], gap='large')
figure_slot = left.empty()
left.caption('Drag on the picture to zoom in, double-click to zoom out. Hover to read pixel positions. '
             'Pink dotted lines are the axis values the app uses; the thin lines drawn over the curves are '
             'what it read.')

y_refs, x_refs = [], []
with right:
    if not text_ok:
        st.info('Text recognition is not installed here, so the axes are set by hand. On Streamlit Cloud, '
                'packages.txt installs it.')

    # ---- temperature axis
    st.subheader('2. Temperature axis')
    y_modes = [FROM_LABELS, Y_MANUAL] if yfit.ok else [Y_MANUAL]
    if st.session_state.get('y_mode') not in y_modes:
        st.session_state.y_mode = y_modes[0]
    y_mode = st.segmented_control('Scale', y_modes, key='y_mode') or y_modes[0]
    if y_mode == FROM_LABELS:
        used = yfit.used
        rejected = [l for l in yfit.labels if not l.used]
        top_v, bot_v = float(yfit.value(layout.plot.top)), float(yfit.value(layout.plot.bottom))
        st.caption(f'Read {len(used)} labels: **{fmt_list([l.text + "°" for l in sorted(used, key=lambda l: -l.value)])}**. '
                   f'Top gridline = {top_v:.1f}°, bottom = {bot_v:.1f}°; '
                   f'{abs(yfit.slope):.2f}° per pixel.'
                   + (f' All labels fit one straight scale within {yfit.residual:.1f}°.'
                      if yfit.residual >= 0.05 else '')
                   + (f' Not used (unreadable): {len(rejected)}.' if rejected else ''))
        lo, hi = min(used, key=lambda l: l.pos), max(used, key=lambda l: l.pos)
        y1, v1, y2, v2 = lo.pos, float(yfit.value(lo.pos)), hi.pos, float(yfit.value(hi.pos))
        y_refs = [(l.pos, f'{l.value:g}°') for l in used]
    else:
        if text_ok and not yfit.ok:
            st.caption('The temperature labels could not be read. Pick two gridlines that have a label and type it.')
        else:
            st.caption(f'{len(layout.h_lines)} horizontal gridlines found. Pick two that have a label and type it.')
        y_opts = [(f'{"Top gridline" if i == 0 else "Bottom gridline" if i == len(layout.h_lines) - 1 else f"Gridline {i + 1}"}'
                   f' (row {r:.1f})', r) for i, r in enumerate(layout.h_lines)]
        if yfit.ok and 'y_prefilled' not in st.session_state:
            st.session_state.y1_val = round(float(yfit.value(layout.h_lines[0])), 1) if layout.h_lines else 100.0
            st.session_state.y2_val = round(float(yfit.value(layout.h_lines[-1])), 1) if layout.h_lines else 0.0
            st.session_state.y_prefilled = True
        c1, c2 = st.columns([3, 2])
        with c1:
            y1 = ref_choice('Upper reference', 'y1', y_opts, 0, 'Custom row', H * 0.2, H - 1)
        c2.number_input(f'Temperature ({unit})', step=5.0, key='y1_val', format='%g',
                        on_change=touched, args=('manual_touched',))
        c1, c2 = st.columns([3, 2])
        with c1:
            y2 = ref_choice('Lower reference', 'y2', y_opts, len(y_opts) - 1, 'Custom row', H * 0.8, H - 1)
        c2.number_input(f'Temperature ({unit}) ', step=5.0, key='y2_val', format='%g',
                        on_change=touched, args=('manual_touched',))
        v1, v2 = float(st.session_state.y1_val), float(st.session_state.y2_val)
        y_refs = [(y1, f'{v1:g}°'), (y2, f'{v2:g}°')]

    # ---- time axis
    st.subheader('3. Time axis')
    x_modes = [FROM_LABELS, X_MANUAL] if xfit.ok else [X_MANUAL]
    if st.session_state.get('x_mode') not in x_modes:
        st.session_state.x_mode = x_modes[0]
    x_mode = st.segmented_control('Times', x_modes, key='x_mode') or x_modes[0]
    anchor = None
    start_needed = False
    if x_mode == FROM_LABELS and xfit.kind == 'elapsed':
        used = sorted(xfit.used, key=lambda l: l.pos)
        zero = float(xfit.pos(0))
        st.caption(f'Read elapsed-time labels: **{fmt_list([l.text for l in used])}**. '
                   f'0 h is at column {zero:.1f}; {abs(1 / xfit.slope) * 1:.1f} pixels per hour.')
        c1, c2 = st.columns(2)
        c1.date_input('Start date', key='start_date', format='DD/MM/YYYY',
                      on_change=touched, args=('start_touched',))
        c2.time_input('Start time (at 0 h)', key='start_time', step=60,
                      on_change=touched, args=('start_touched',))
        if cook_date:
            st.caption(f'Start date read from the screenshot: {cook_date:%d/%m/%Y}. Set the start time.')
        t0 = datetime.combine(st.session_state.start_date, st.session_state.start_time)
        last = used[-1].value
        x1, t1, x2, t2 = zero, t0, float(xfit.pos(last)), t0 + timedelta(hours=last)
        anchor = t0
        start_needed = not st.session_state.start_touched
        x_refs = [(l.pos, l.text) for l in used]
    elif x_mode == FROM_LABELS:                       # clock times
        used = sorted(xfit.used, key=lambda l: l.pos)
        st.caption(f'Read clock-time labels: **{fmt_list([l.text for l in used])}**'
                   + (' (the chart runs past midnight)' if used[-1].value >= 24 else '') + '.')
        st.date_input(f'Date at {used[0].text}', key='label_date', format='DD/MM/YYYY',
                      on_change=touched, args=('start_touched',))
        midnight = datetime.combine(st.session_state.label_date, time(0, 0))
        x1, t1 = used[0].pos, midnight + timedelta(hours=used[0].value)
        x2, t2 = used[-1].pos, midnight + timedelta(hours=used[-1].value)
        anchor = midnight
        start_needed = not (st.session_state.start_touched or cook_date)
        x_refs = [(l.pos, l.text) for l in used]
    else:
        if text_ok and not xfit.ok:
            st.caption('The time labels could not be read. Give the date and time at two points on the time axis.')
        else:
            st.caption('Give the date and time at two points on the time axis, usually the start and end of the chart.')
        x_opts = x_options(layout)
        c1, c2, c3 = st.columns([3, 2, 2])
        with c1:
            x1 = ref_choice('Start reference', 'x1', x_opts, 0, 'Custom column', W * 0.1, W - 1)
        c2.date_input('Start date', key='x1_date', format='DD/MM/YYYY', on_change=touched, args=('manual_touched',))
        c3.time_input('Start time', key='x1_time', step=60, on_change=touched, args=('manual_touched',))
        c1, c2, c3 = st.columns([3, 2, 2])
        with c1:
            x2 = ref_choice('End reference', 'x2', x_opts, len(x_opts) - 1, 'Custom column', W * 0.9, W - 1)
        c2.date_input('End date', key='x2_date', format='DD/MM/YYYY', on_change=touched, args=('manual_touched',))
        c3.time_input('End time', key='x2_time', step=60, on_change=touched, args=('manual_touched',))
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
        start_needed = not st.session_state.manual_touched
        x_refs = [(x1, t1.strftime('%H:%M')), (x2, t2.strftime('%H:%M'))]

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
    cands = list(find_colours(digest, img, area_t))

    # legend colours: match each to a line colour; add it if no line colour is close
    role_of_cand = {}
    for entry in legend:
        dists = [min(sum((a - b) ** 2 for a, b in zip(sh, entry.rgb)) ** .5 for sh in c.shades) for c in cands]
        if dists and min(dists) < 90:
            role_of_cand.setdefault(int(np.argmin(dists)), entry)
        elif entry.role != 'target':
            cands.append(dg.ColourCandidate(entry.rgb, 0, 0.0))
            role_of_cand[len(cands) - 1] = entry
    others = tuple(tuple(int(v) for v in sh) for c in cands for sh in c.shades)
    flat = {}
    medians = {}
    pre = {}
    for i, c in enumerate(cands):
        tr = pre[i] = trace(digest, img, area_t, c.rgb, bg, 70.0, 25, 'centre', others, c.variants)
        flat[i] = dg.is_flat(tr, area.bottom - area.top)
        medians[i] = np.nanmedian(tr.y) if np.isfinite(tr.y).any() else np.inf

    def cand_name(i, c):
        bits = [f'Colour {i + 1}: {dg.colour_name(c.rgb)} ({c.hex})']
        if i in role_of_cand:
            bits.append(f'legend “{role_of_cand[i].word}”')
        if c.variants:
            bits.append(f'+{len(c.variants)} shade' + ('s' if len(c.variants) > 1 else ''))
        if flat[i]:
            bits.append('flat line')
        return ' · '.join(bits)

    names = [cand_name(i, c) for i, c in enumerate(cands)] + [CUSTOM, NONE]
    if cands:
        chips = ''.join(f'<span class="bcd-chip"><span class="sw" style="background:{c.hex}"></span>'
                        f'{i + 1}: {role_of_cand[i].word if i in role_of_cand else dg.colour_name(c.rgb)}'
                        f'{" (flat)" if flat[i] else ""}</span>' for i, c in enumerate(cands))
        st.markdown(f'<div>{chips}</div>', unsafe_allow_html=True)
    else:
        st.caption('No coloured lines found in the search area. Use Custom colour.')

    if 'amb_sel' not in st.session_state:
        chosen = {}
        notes = []
        for key in KEYS:                                   # 1. the legend says which is which
            for i, entry in role_of_cand.items():
                if entry.role == ROLE_OF[key] and not flat[i]:
                    chosen[key] = i
        if len(chosen) == 2:
            notes.append('Lines assigned from the legend.')
        free = [i for i in range(len(cands)) if not flat[i] and i not in chosen.values()
                and role_of_cand.get(i, None) is None]
        free.sort(key=lambda i: -cands[i].coverage)
        if 'amb' not in chosen and 'meat' not in chosen and len(free) >= 2:
            a, b = free[:2]                                     # 2. ambient is hotter at the start
            if not dg.hotter_early(pre[a], pre[b]):
                a, b = b, a
            chosen['amb'], chosen['meat'] = a, b
            notes.append('No legend was read, so ambient is taken as the line that is hotter at the start. '
                         'Check the choice.')
        for key in KEYS:
            if key not in chosen and free:
                rest = [i for i in free if i not in chosen.values()]
                if rest:
                    chosen[key] = rest[0]
        for key in KEYS:
            st.session_state[key + '_sel'] = names[chosen[key]] if key in chosen else NONE
        ignored = [i for i in range(len(cands)) if flat[i] or (i in role_of_cand and role_of_cand[i].role == 'target')]
        if ignored:
            notes.append('Ignored: ' + ', '.join(
                (f'“{role_of_cand[i].word}”' if i in role_of_cand else f'colour {i + 1}')
                + (f' (flat line at {float(dg.Calibration(y1, v1, y2, v2, 0, t1, 1, t2).value(medians[i])):.0f}°)'
                   if flat[i] and np.isfinite(medians[i]) else '')
                for i in ignored) + '.')
        st.session_state.assign_note = ' '.join(notes)
    if st.session_state.get('assign_note'):
        st.caption(st.session_state.assign_note)

    picked = {}
    picked_shades = {}
    for key in KEYS:                      # colours change when the search area changes
        if st.session_state.get(key + '_sel') not in names:
            st.session_state[key + '_sel'] = NONE
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
            picked_shades[label] = cands[names.index(choice)].variants
            c2.markdown(f'<span class="bcd-chip"><span class="sw" style="background:{"#%02x%02x%02x" % rgb};'
                        f'width:34px;height:34px"></span></span>', unsafe_allow_html=True)
            picked[label] = rgb

    st.radio('Temperature unit on the chart', ['°C', '°F'], horizontal=True, key='unit')

# --------------------------------------------------------------------------- trace and calibrate

cal = dg.Calibration(y1, v1, y2, v2, x1, t1, x2, t2)
traces = {}
for label in SERIES:
    rgb = picked[label]
    traces[label] = None if rgb is None else trace(digest, img, area_t, tuple(int(v) for v in rgb), bg,
                                                   float(tolerance), int(bridge), edge.lower().replace(' edge', ''),
                                                   others, picked_shades.get(label, ()))
colours = [contrast_colour(picked[l]) if picked[l] is not None else '#888' for l in SERIES]
figure_slot.plotly_chart(overlay_figure(data, img, area, y_refs, x_refs, traces, colours),
                         width='stretch', config={'displaylogo': False, 'scrollZoom': False})

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
if start_needed:
    st.warning((f'Set the start time (step 3). The date {cook_date:%d/%m/%Y} was read from the screenshot; the '
                'time is a placeholder until you set it.' if cook_date else
                'Set the start date and time (step 3); the timestamps below use a placeholder date and time.')
               if x_mode == FROM_LABELS else
               'Check the axis values and times in steps 2 and 3; they are still at their starting values.')
m = st.columns(4)
m[0].metric('Time per pixel column', f'{cal.seconds_per_px:.0f} s')
m[1].metric('Temperature per pixel', f'{cal.degrees_per_px:.2f} {unit}')
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
                             help='Values are interpolated between pixel columns onto a regular clock that '
                                  'starts at the start time.')
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
    table = dg.build_table(series, cal, interval, unit, max_gap_s=max_gap, anchor=anchor,
                           not_before=anchor if x_mode == FROM_LABELS and xfit.kind == 'elapsed' else None)
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
