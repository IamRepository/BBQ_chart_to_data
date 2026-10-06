"""Pixel-level digitizing of line charts.

Pipeline
1. load_image: RGB array, transparency composited onto white.
2. detect_layout: background colour, horizontal and vertical gridlines, plot area.
3. colour_candidates: the saturated line colours inside the plot area.
4. trace_line: per pixel column, the sub-pixel centre of the line.
   Each pixel gets a coverage value (how much of it is line colour, from the
   anti-aliasing blend with the background); runs of covered pixels in a
   column are candidates; a dynamic-programming pass picks the one continuous
   path through the columns, so legend text, labels and the other line are
   skipped. Short gaps (where the other line is drawn on top) are bridged.
5. Calibration: pixel -> temperature and pixel -> time from two reference
   points on each axis.
6. build_table: resample onto a regular clock (e.g. every minute).
"""
from __future__ import annotations

import colorsys
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from PIL import Image


# --------------------------------------------------------------------------- image

def load_image(source) -> np.ndarray:
    """Return an HxWx3 uint8 array. Accepts a path, bytes or a file-like object."""
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    im = Image.open(source)
    im.load()
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        white = Image.new('RGBA', im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(white, im)
    return np.asarray(im.convert('RGB'), dtype=np.uint8).copy()


def background_colour(img: np.ndarray) -> np.ndarray:
    """Most common colour (quantised to 8 levels per channel, then averaged)."""
    q = (img // 32).reshape(-1, 3).astype(np.int32)
    keys = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
    top = np.bincount(keys).argmax()
    sel = img.reshape(-1, 3)[keys == top]
    return np.median(sel, axis=0)


def _saturation(img: np.ndarray) -> np.ndarray:
    f = img.astype(np.float32)
    mx = f.max(axis=2)
    mn = f.min(axis=2)
    return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)


def is_dark(bg) -> bool:
    return float(np.mean(bg)) < 110


# --------------------------------------------------------------------------- layout

@dataclass
class PlotArea:
    left: int
    top: int
    right: int
    bottom: int

    def clip(self, width: int, height: int) -> 'PlotArea':
        l = int(min(max(self.left, 0), width - 2))
        r = int(min(max(self.right, l + 1), width - 1))
        t = int(min(max(self.top, 0), height - 2))
        b = int(min(max(self.bottom, t + 1), height - 1))
        return PlotArea(l, t, r, b)


@dataclass
class Layout:
    background: np.ndarray
    h_lines: list = field(default_factory=list)   # sub-pixel row centres
    v_lines: list = field(default_factory=list)   # sub-pixel column centres
    plot: PlotArea | None = None


def _line_groups(frac: np.ndarray, threshold: float):
    """Contiguous indices where frac >= threshold -> (weighted centre, start, end)."""
    idx = np.flatnonzero(frac >= threshold)
    groups = []
    if idx.size == 0:
        return groups
    start = prev = idx[0]
    for i in list(idx[1:]) + [None]:
        if i is not None and i == prev + 1:
            prev = i
            continue
        rng = np.arange(start, prev + 1)
        w = frac[rng]
        groups.append((float((rng * w).sum() / w.sum()), int(start), int(prev)))
        if i is not None:
            start = prev = i
    return groups


def detect_layout(img: np.ndarray) -> Layout:
    """Find gridlines and the plot area.

    Gridlines are thin rows/columns of low-saturation pixels that differ from
    the background over a large share of the width. Several unrelated lines
    (UI dividers, headers) can match, so lines are grouped by their left/right
    extent and the largest consistent group is taken as the chart grid.
    """
    h, w, _ = img.shape
    bg = background_colour(img)
    sat = _saturation(img)
    # thin horizontal strokes: pixels that differ from the rows a few pixels
    # above and below, where those two agree (local background). This works
    # on any background, including a chart card on a different page colour.
    drawn = _thin_strokes(img, axis=0)     # data lines lying on a gridline count too
    grey = drawn & (sat < 0.22)

    rows = []
    grey_frac = grey.mean(axis=1)
    for centre, s, e in _line_groups(np.where(grey_frac >= 0.12, drawn.mean(axis=1), 0), 0.30):
        if e - s > 6:            # a band of text or a block, not a line
            continue
        # data lines crossing the gridline break the stroke test, so coloured
        # pixels count as part of the row too
        coloured = np.convolve((sat[max(0, s - 3):e + 4] > 0.25).any(axis=0), np.ones(7), 'same') > 0
        lo, hi = _longest_run(drawn[s:e + 1].any(axis=0) | coloured, w)
        if hi - lo > 0.2 * w:
            rows.append((centre, float(lo), float(hi)))

    layout = Layout(background=bg)
    if not rows:
        return layout

    # group rows sharing the same horizontal extent
    groups = []
    for r in rows:
        for g in groups:
            if abs(g[0][1] - r[1]) < 0.04 * w and abs(g[0][2] - r[2]) < 0.04 * w:
                g.append(r)
                break
        else:
            groups.append([r])
    groups.sort(key=lambda g: (len(g), g[-1][0] - g[0][0]), reverse=True)
    grid = groups[0]
    layout.h_lines = sorted(r[0] for r in grid)
    left = int(round(np.median([r[1] for r in grid])))
    right = int(round(np.median([r[2] for r in grid])))
    top = int(round(layout.h_lines[0]))
    bottom = int(round(layout.h_lines[-1]))

    if bottom - top > 10:
        band = (_thin_strokes(img, axis=1) & (sat < 0.22))[top:bottom + 1]
        for centre, s, e in _line_groups(band.mean(axis=0), 0.45):
            if e - s <= 6 and left - 0.02 * w <= centre <= right + 0.02 * w:
                layout.v_lines.append(centre)
    # vertical gridlines at the ends are the most precise plot edges
    if len(layout.v_lines) >= 2:
        if abs(layout.v_lines[0] - left) < 0.04 * w:
            left = int(np.floor(layout.v_lines[0]))
        if abs(layout.v_lines[-1] - right) < 0.04 * w:
            right = int(np.ceil(layout.v_lines[-1]))
    layout.plot = PlotArea(left, top, right, bottom).clip(w, h)
    layout.background = background_colour(img[layout.plot.top:layout.plot.bottom + 1,
                                              layout.plot.left:layout.plot.right + 1])
    return layout


def _thin_strokes(img: np.ndarray, axis: int, reach: int = 4) -> np.ndarray:
    """Pixels on a line up to 2*reach-1 px thick running across `axis`."""
    f = img.astype(np.int16)
    a = np.roll(f, reach, axis=axis)
    b = np.roll(f, -reach, axis=axis)
    agree = np.abs(a - b).sum(axis=2) < 30
    dev = np.abs(2 * f - a - b).sum(axis=2) // 2
    out = agree & (dev > 18)
    if axis == 0:
        out[:reach] = out[-reach:] = False
    else:
        out[:, :reach] = out[:, -reach:] = False
    return out


def _longest_run(mask: np.ndarray, width: int):
    """Start and end of the longest stretch of True, allowing small breaks.

    Breaks up to 6 px are bridged (dashes, anti-aliasing). If that leaves the
    line in many pieces (a dashed gridline), larger breaks are bridged too.
    Axis labels sit further away and stay separate."""
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return 0, 0
    for tol in (6, 16):
        best = (idx[0], idx[0]); start = prev = idx[0]
        for i in list(idx[1:]) + [None]:
            if i is not None and i - prev <= tol + 1:
                prev = i
                continue
            if prev - start > best[1] - best[0]:
                best = (start, prev)
            if i is not None:
                start = prev = i
        if best[1] - best[0] >= 0.6 * (idx[-1] - idx[0]) or tol == 16:
            return int(best[0]), int(best[1])
    return int(idx[0]), int(idx[-1])


def default_search_area(layout: Layout, width: int, height: int) -> PlotArea:
    """Plot area with a margin above the top gridline (lines may peak above it)."""
    if layout.plot is None:
        return PlotArea(int(width * .08), int(height * .1), int(width * .97), int(height * .9))
    p = layout.plot
    pad = max(2, int(0.04 * (p.bottom - p.top)))
    return PlotArea(p.left, p.top - pad, p.right, p.bottom + 2).clip(width, height)


# --------------------------------------------------------------------------- colours

@dataclass
class ColourCandidate:
    rgb: tuple
    pixels: int
    coverage: float   # share of plot columns that contain this colour

    @property
    def hex(self) -> str:
        return '#%02x%02x%02x' % self.rgb


def colour_candidates(img: np.ndarray, area: PlotArea, max_n: int = 6) -> list[ColourCandidate]:
    """Distinct saturated colours inside the area, ranked by column coverage."""
    reg = img[area.top:area.bottom + 1, area.left:area.right + 1].astype(np.float32) / 255
    mx = reg.max(axis=2)
    mn = reg.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    mask = (sat > 0.35) & (mx > 0.25)
    if mask.sum() < 20:
        return []
    r, g, b = reg[..., 0], reg[..., 1], reg[..., 2]
    d = np.maximum(mx - mn, 1e-6)
    hue = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    hues = hue[mask]
    nbins = 72
    hist = np.bincount((hues / 360 * nbins).astype(int) % nbins, minlength=nbins).astype(float)
    smooth = hist + 0.5 * np.roll(hist, 1) + 0.5 * np.roll(hist, -1)
    used = np.zeros(nbins, bool)
    out = []
    ncols = reg.shape[1]
    for peak in np.argsort(smooth)[::-1]:
        if used[peak] or smooth[peak] < max(10, 0.01 * mask.sum()):
            continue
        # take the hue window around the peak, stop at valleys
        lo = hi = peak
        while not used[(lo - 1) % nbins] and smooth[(lo - 1) % nbins] < smooth[lo % nbins] * 1.05 and smooth[(lo - 1) % nbins] > 0.05 * smooth[peak] and peak - lo < 6:
            lo -= 1
        while not used[(hi + 1) % nbins] and smooth[(hi + 1) % nbins] < smooth[hi % nbins] * 1.05 and smooth[(hi + 1) % nbins] > 0.05 * smooth[peak] and hi - peak < 6:
            hi += 1
        for k in range(lo, hi + 1):
            used[k % nbins] = True
        h0 = (lo / nbins * 360) % 360
        h1 = ((hi + 1) / nbins * 360) % 360
        in_win = (hue >= h0) & (hue < h1) if h0 < h1 else (hue >= h0) | (hue < h1)
        sel = mask & in_win
        if sel.sum() < 10:
            continue
        # the line core: the most saturated half of the pixels
        s_sel = sat[sel]
        core = reg[sel][s_sel >= np.median(s_sel)]
        rgb = tuple(int(round(v * 255)) for v in np.median(core, axis=0))
        out.append(ColourCandidate(rgb, int(sel.sum()), float(sel.any(axis=0).sum() / ncols)))
    out.sort(key=lambda c: (c.coverage, c.pixels), reverse=True)
    return out[:max_n]


def colour_name(rgb) -> str:
    r, g, b = (v / 255 for v in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.15 or l < 0.08 or l > 0.95:
        return 'black' if l < 0.25 else 'white' if l > 0.85 else 'grey'
    deg = h * 360
    names = [(15, 'red'), (40, 'orange'), (68, 'yellow'), (165, 'green'), (195, 'cyan'),
             (255, 'blue'), (290, 'purple'), (335, 'pink'), (361, 'red')]
    base = next(n for limit, n in names if deg < limit)
    if l < 0.3:
        base = 'dark ' + base
    elif l > 0.72:
        base = 'light ' + base
    return base


def parse_hex(text: str) -> tuple:
    text = text.lstrip('#')
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


# --------------------------------------------------------------------------- tracing

@dataclass
class Trace:
    x: np.ndarray            # pixel column (image coordinates)
    y: np.ndarray            # sub-pixel row centre, NaN where the line was not found
    found: np.ndarray        # True where measured, False where bridged or missing
    thickness: float
    columns_found: float     # share of columns between first and last point measured


def coverage_map(region: np.ndarray, rgb, bg, tolerance: float) -> np.ndarray:
    """0..1 per pixel: how much of the pixel is the line colour.

    An anti-aliased edge pixel is a blend of background and line colour. The
    pixel is projected onto the background->line colour segment; the position
    along it is the coverage, and the distance off it must stay within the
    tolerance (otherwise it is some other colour).
    """
    p = region.astype(np.float32)
    c = np.asarray(rgb, np.float32)
    b = np.asarray(bg, np.float32)
    v = c - b
    vv = float((v * v).sum())
    if vv < 300:                          # line colour too close to the background
        d = np.sqrt(((p - c) ** 2).sum(axis=2))
        return np.clip(1 - d / tolerance, 0, 1)
    a = ((p - b) * v).sum(axis=2) / vv
    a = np.clip(a, 0, 1)
    resid = np.sqrt(((p - (b + a[..., None] * v)) ** 2).sum(axis=2))
    cov = np.where(resid < tolerance * np.maximum(a, 0.25), a, 0.0)
    cov[cov < 0.12] = 0
    return cov


def _column_runs(col: np.ndarray, max_runs: int = 6):
    """Runs of covered pixels in one column -> list of (centroid, mass, top, bottom).

    Runs are seeded on well-covered pixels (the line core) and grown by up to
    two pixels into the faint anti-aliased edge on each side. Faint pixels on
    their own (a gridline tinted towards the line colour, JPEG noise) do not
    start a run and cannot stretch one.
    """
    strong = np.flatnonzero(col >= 0.35)
    if strong.size == 0:
        return []
    n = col.size
    runs = []
    start = prev = strong[0]
    for i in list(strong[1:]) + [None]:
        if i is not None and i <= prev + 3:
            prev = i
            continue
        lo, hi = start, prev
        for _ in range(2):
            if lo > 0 and col[lo - 1] > 0:
                lo -= 1
            if hi < n - 1 and col[hi + 1] > 0:
                hi += 1
        rng = np.arange(lo, hi + 1)
        w = col[rng]
        m = float(w.sum())
        if m >= 0.25:
            runs.append((float((rng * w).sum() / m), m, int(lo), int(hi)))
        if i is not None:
            start = prev = i
    runs.sort(key=lambda r: r[1], reverse=True)
    return runs[:max_runs]


def trace_line(img: np.ndarray, area: PlotArea, rgb, bg, tolerance: float = 70,
               max_bridge_px: int = 25, edge: str = 'centre', exclude: Trace | None = None) -> Trace:
    """Follow one coloured line through the search area, one value per pixel column."""
    reg = img[area.top:area.bottom + 1, area.left:area.right + 1]
    H, W = reg.shape[:2]
    cov = coverage_map(reg, rgb, bg, tolerance)

    cands = [_column_runs(cov[:, x]) for x in range(W)]
    masses = [r[1] for col in cands for r in col]
    thick = float(np.median(masses)) if masses else 1.0
    thick = max(thick, 1.0)

    # flatten candidates (sorted by column)
    X, C, M, T, B = [], [], [], [], []
    for x, col in enumerate(cands):
        for (c, m, t, b) in col:
            X.append(x); C.append(c); M.append(m); T.append(t); B.append(b)
    n = len(X)
    if n == 0:
        xs = np.arange(area.left, area.right + 1)
        return Trace(xs, np.full(W, np.nan), np.zeros(W, bool), thick, 0.0)
    X = np.array(X); C = np.array(C); M = np.array(M); T = np.array(T); B = np.array(B)
    reward = np.minimum(M / (0.6 * thick), 1.0)
    # a run much taller than the line is either a steep section (fine) or a
    # filled area / text block; keep it, but at a lower reward
    height = B - T + 1
    reward = np.where(height > 6 * thick + 4, reward * 0.6, reward)

    K = max(40, min(W // 3, 400))      # longest gap that can be bridged in the path
    SKIP, SKIP_CAP, BETA = 0.25, 4.0, 45.0 / H
    score = np.zeros(n)
    prev = np.full(n, -1)
    col_start = np.searchsorted(X, np.arange(W + 1))
    for x in range(W):
        i0, i1 = col_start[x], col_start[x + 1]
        if i0 == i1:
            continue
        j0 = col_start[max(0, x - K)]
        j1 = i0
        if j1 > j0:
            gap = x - X[j0:j1]
            ti = T[i0:i1, None]; bi = B[i0:i1, None]
            tj = T[None, j0:j1]; bj = B[None, j0:j1]
            dist = np.maximum(0, np.maximum(ti - bj, tj - bi) - 1)
            dist = np.maximum(0, dist - 2 * (gap[None, :] - 1))
            cost = np.minimum(SKIP * (gap - 1), SKIP_CAP)[None, :] + BETA * dist
            total = score[None, j0:j1] - cost
            best = total.argmax(axis=1)
            bestv = total[np.arange(i1 - i0), best]
            use = bestv > 0
            score[i0:i1] = reward[i0:i1] + np.where(use, bestv, 0)
            prev[i0:i1] = np.where(use, best + j0, -1)
        else:
            score[i0:i1] = reward[i0:i1]

    # back-track the best path
    k = int(score.argmax())
    path = []
    while k >= 0:
        path.append(k)
        k = int(prev[k])
    path = path[::-1]

    # drop short islands that sit far from their neighbours (legend text etc.)
    path = _prune_islands(path, X, T, B, C, thick, H)

    y = np.full(W, np.nan)
    found = np.zeros(W, bool)
    half = (thick - 1) / 2
    for n_, k in enumerate(path):
        x = X[k]
        if edge == 'top':
            y[x] = T[k] + half
        elif B[k] - T[k] + 1 > 2.5 * thick + 1 and 0 < n_ < len(path) - 1:
            # a tall run is a steep section; at a peak or a dip the value is
            # the far end of the run, on a steady slope it is the middle
            up, down = C[path[n_ - 1]], C[path[n_ + 1]]
            if up < C[k] and down < C[k]:
                y[x] = B[k] - half          # dip (rows grow downwards)
            elif up > C[k] and down > C[k]:
                y[x] = T[k] + half          # peak
            else:
                y[x] = C[k]
        else:
            y[x] = C[k]
        found[x] = True

    # bridge short gaps (other line drawn on top, dashed lines)
    idx = np.flatnonzero(found)
    if idx.size >= 2:
        for a, b in zip(idx[:-1], idx[1:]):
            if 1 < b - a <= max_bridge_px + 1:
                y[a + 1:b] = np.interp(np.arange(a + 1, b), [a, b], [y[a], y[b]])
    span = (idx[-1] - idx[0] + 1) if idx.size else 1
    xs = np.arange(area.left, area.right + 1)
    return Trace(xs, y + area.top, found, thick, float(found.sum() / span))


def _prune_islands(path, X, T, B, C, thick, H):
    """Split the path where it skips columns or jumps between runs that do not
    touch, then drop short pieces that sit far from their neighbours."""
    if len(path) < 3:
        return path
    jump = max(3 * thick, 0.03 * H)
    segs = [[path[0]]]
    for k in path[1:]:
        j = segs[-1][-1]
        apart = max(T[k] - B[j], T[j] - B[k])
        if X[k] - X[j] > 3 or apart > jump:
            segs.append([k])
        else:
            segs[-1].append(k)
    total = sum(len(s) for s in segs)
    keep = []
    for i, s in enumerate(segs):
        if len(s) < max(8, 0.05 * total) and len(segs) > 1:
            ys = [C[k] for k in s]
            neigh = []
            if i > 0:
                neigh.append(C[segs[i - 1][-1]])
            if i < len(segs) - 1:
                neigh.append(C[segs[i + 1][0]])
            if neigh and min(abs(np.median(ys) - v) for v in neigh) > 0.08 * H:
                continue
        keep.extend(s)
    return keep


def smooth(y: np.ndarray, window: int) -> np.ndarray:
    """Centred moving average that respects gaps (NaN)."""
    if window <= 1:
        return y
    s = pd.Series(y)
    out = s.rolling(window, center=True, min_periods=1).mean().to_numpy()
    out[np.isnan(y)] = np.nan
    return out


# --------------------------------------------------------------------------- calibration

@dataclass
class Calibration:
    y1_px: float
    y1_value: float
    y2_px: float
    y2_value: float
    x1_px: float
    x1_time: datetime
    x2_px: float
    x2_time: datetime

    def check(self) -> list[str]:
        problems = []
        if abs(self.y2_px - self.y1_px) < 5:
            problems.append('The two temperature reference rows are less than 5 pixels apart.')
        if self.y1_value == self.y2_value:
            problems.append('The two temperature reference values are the same.')
        if abs(self.x2_px - self.x1_px) < 5:
            problems.append('The two time reference columns are less than 5 pixels apart.')
        if self.x2_time <= self.x1_time:
            problems.append('The end time must be after the start time.')
        return problems

    def value(self, y_px):
        return self.y1_value + (np.asarray(y_px, float) - self.y1_px) * (self.y2_value - self.y1_value) / (self.y2_px - self.y1_px)

    def seconds(self, x_px):
        span = (self.x2_time - self.x1_time).total_seconds()
        return (np.asarray(x_px, float) - self.x1_px) * span / (self.x2_px - self.x1_px)

    @property
    def seconds_per_px(self) -> float:
        return abs((self.x2_time - self.x1_time).total_seconds() / (self.x2_px - self.x1_px))

    @property
    def degrees_per_px(self) -> float:
        return abs((self.y2_value - self.y1_value) / (self.y2_px - self.y1_px))


# --------------------------------------------------------------------------- table

TIME_FORMAT = '%d/%m/%Y %H:%M'


def series_in_units(trace: Trace, cal: Calibration, smoothing_px: int = 0):
    """(seconds after x1_time, temperature) for every column with a value."""
    y = smooth(trace.y, smoothing_px)
    ok = ~np.isnan(y)
    return cal.seconds(trace.x[ok]), cal.value(y[ok])


def _resample(sec: np.ndarray, val: np.ndarray, grid: np.ndarray, max_gap_s: float) -> np.ndarray:
    out = np.full(grid.shape, np.nan)
    if sec.size < 2:
        return out
    order = np.argsort(sec)
    sec, val = sec[order], val[order]
    out = np.interp(grid, sec, val, left=np.nan, right=np.nan)
    # a clock tick just outside the first or last pixel column takes its value
    step = np.median(np.diff(sec)) if sec.size > 1 else 0
    near_start = (grid < sec[0]) & (grid >= sec[0] - 0.6 * step)
    near_end = (grid > sec[-1]) & (grid <= sec[-1] + 0.6 * step)
    out[near_start] = val[0]
    out[near_end] = val[-1]
    # blank grid points that fall inside a gap in the data
    pos = np.searchsorted(sec, grid)
    pos = np.clip(pos, 1, sec.size - 1)
    gaps = (sec[pos] - sec[pos - 1]) > max_gap_s
    exact = np.isin(grid, sec)
    inside = (grid >= sec[0]) & (grid <= sec[-1])
    out[gaps & ~exact & inside] = np.nan
    return out


def build_table(series: dict, cal: Calibration, interval_s: float, unit: str = '°C',
                max_gap_s: float | None = None, decimals: int = 1) -> pd.DataFrame:
    """Resample every series onto one regular clock that starts at the start time.

    series: {column label: (seconds, values)}
    """
    starts = [s.min() for s, _ in series.values() if s.size]
    ends = [s.max() for s, _ in series.values() if s.size]
    if not starts:
        return pd.DataFrame(columns=['Timestamp'] + [f'{k} ({unit})' for k in series])
    reach = 0.6 * cal.seconds_per_px          # a tick within ~half a column of the ends is kept
    first = np.ceil((min(starts) - reach) / interval_s - 1e-9) * interval_s
    last = np.floor((max(ends) + reach) / interval_s + 1e-9) * interval_s
    grid = np.arange(first, last + interval_s / 2, interval_s)
    if max_gap_s is None:
        max_gap_s = max(3 * cal.seconds_per_px, 1.5 * interval_s)
    data = {'Timestamp': [(cal.x1_time + timedelta(seconds=float(s))).strftime(TIME_FORMAT) for s in grid]}
    for label, (sec, val) in series.items():
        data[f'{label} ({unit})'] = np.round(_resample(sec, val, grid, max_gap_s), decimals)
    df = pd.DataFrame(data)
    value_cols = df.columns[1:]
    return df.dropna(subset=value_cols, how='all').reset_index(drop=True)


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode('utf-8-sig')


def build_pixel_table(traces: dict, cal: Calibration, unit: str = '°C', smoothing_px: int = 0,
                      decimals: int = 2) -> pd.DataFrame:
    """One row per pixel column: the full resolution of the screenshot.

    traces: {column label: Trace or None}. Timestamps include seconds here,
    since columns are usually less than a minute apart.
    """
    xs = None
    cols = {}
    for label, tr in traces.items():
        if tr is None:
            continue
        xs = tr.x if xs is None else xs
        cols[label] = cal.value(smooth(tr.y, smoothing_px))
    if xs is None:
        return pd.DataFrame(columns=['Timestamp'] + [f'{k} ({unit})' for k in traces])
    sec = cal.seconds(xs)
    data = {'Timestamp': [(cal.x1_time + timedelta(seconds=float(s))).strftime(TIME_FORMAT + ':%S') for s in sec]}
    for label in traces:
        v = cols.get(label, np.full(xs.shape, np.nan))
        data[f'{label} ({unit})'] = np.round(v, decimals)
    df = pd.DataFrame(data)
    return df.dropna(subset=df.columns[1:], how='all').reset_index(drop=True)
