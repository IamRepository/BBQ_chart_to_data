"""Reading the text on a chart: axis labels and legend.

Uses Tesseract (installed on Streamlit Cloud through packages.txt). Every
label is cut out on its own and read several times at different sizes; the
readings that fit one straight scale across all labels win, so a single
misread label is dropped rather than bending the axis.
"""
from __future__ import annotations

import difflib
import re
import shutil
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
from PIL import Image, ImageOps

try:
    import pytesseract
except ImportError:            # the app still works with manual axes
    pytesseract = None

from digitizer import Layout, _saturation


def available() -> bool:
    return pytesseract is not None and shutil.which('tesseract') is not None


# --------------------------------------------------------------------------- results

@dataclass
class Label:
    text: str          # what was used, e.g. '143' or '4h'
    pos: float         # pixel row (temperature axis) or column (time axis)
    value: float       # degrees, or hours
    used: bool = True


@dataclass
class AxisFit:
    labels: list = field(default_factory=list)     # Label, used and rejected
    slope: float = 0.0                              # value per pixel
    intercept: float = 0.0
    kind: str = ''                                  # 'temperature', 'elapsed' or 'clock'
    residual: float = 0.0                           # largest misfit of a used label, in value units

    @property
    def ok(self) -> bool:
        return sum(l.used for l in self.labels) >= 2 and self.slope != 0

    def value(self, pos):
        return self.intercept + self.slope * np.asarray(pos, float)

    def pos(self, value):
        return (np.asarray(value, float) - self.intercept) / self.slope

    @property
    def used(self):
        return [l for l in self.labels if l.used]


@dataclass
class LegendEntry:
    role: str          # 'meat', 'ambient' or 'target'
    word: str
    rgb: tuple
    box: tuple         # left, top, right, bottom


# --------------------------------------------------------------------------- segmentation

def _ink(region: np.ndarray, threshold: int = 90) -> np.ndarray:
    """Text pixels: far from the region's most common colour."""
    q = (region // 16).reshape(-1, 3).astype(np.int32)
    keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    bg = region.reshape(-1, 3)[keys == np.bincount(keys).argmax()].mean(axis=0)
    return np.abs(region.astype(np.int16) - bg).sum(axis=2) > threshold


def _runs(mask: np.ndarray, gap: int = 0):
    """(start, end) of True stretches, merging breaks up to `gap`."""
    idx = np.flatnonzero(mask)
    out = []
    if idx.size == 0:
        return out
    s = p = idx[0]
    for i in list(idx[1:]) + [None]:
        if i is not None and i - p <= gap + 1:
            p = i
            continue
        out.append((int(s), int(p)))
        if i is not None:
            s = p = i
    return out


def _glyph_extent(ink: np.ndarray):
    """Rows of the main glyphs, ignoring raised small marks such as °."""
    keep = _drop_superscripts(ink)
    rows = np.flatnonzero(ink[:, keep].any(axis=1)) if keep.any() else np.flatnonzero(ink.any(axis=1))
    return rows[0], rows[-1], keep


def _drop_superscripts(ink: np.ndarray) -> np.ndarray:
    """Columns to keep: glyphs that are small and sit high (°, ') are dropped."""
    keep = np.ones(ink.shape[1], bool)
    rows_all = np.flatnonzero(ink.any(axis=1))
    if rows_all.size == 0:
        return keep
    top, bot = rows_all[0], rows_all[-1]
    height = bot - top + 1
    for s, e in _runs(ink.any(axis=0)):
        r = np.flatnonzero(ink[:, s:e + 1].any(axis=1))
        if (r[-1] - r[0] + 1) < 0.55 * height and r[-1] < top + 0.6 * height:
            keep[s:e + 1] = False
    return keep


def _remove_long_lines(ink: np.ndarray, axis: int, share: float = 0.5) -> np.ndarray:
    """Blank rows (axis=1) or columns (axis=0) that are mostly ink: axis lines, not text."""
    ink = ink.copy()
    frac = ink.mean(axis=axis)
    if axis == 0:
        ink[:, frac > share] = False
    else:
        ink[frac > share, :] = False
    return ink


@dataclass
class _Box:
    top: int
    bottom: int
    left: int
    right: int
    centre_row: float
    centre_col: float


def y_label_boxes(img: np.ndarray, layout: Layout, side: str = 'left') -> list:
    """Text boxes beside the plot, one per text line, nearest to the plot."""
    p = layout.plot
    H, W = img.shape[:2]
    ph = p.bottom - p.top
    r0, r1 = max(0, int(p.top - 0.12 * ph)), min(H, int(p.bottom + 0.12 * ph))
    if side == 'left':
        c0, c1 = max(0, int(p.left - 0.3 * W)), max(0, p.left - 2)
    else:
        c0, c1 = min(W, p.right + 3), min(W, int(p.right + 0.3 * W))
    if c1 - c0 < 4:
        return []
    ink = _ink(img[r0:r1, c0:c1])
    ink = _remove_long_lines(ink, axis=0)
    ink = _remove_long_lines(ink, axis=1, share=0.85)
    lines = [(a, b) for a, b in _runs(ink.any(axis=1)) if 3 <= b - a + 1 <= 0.2 * ph]
    if not lines:
        return []
    heights = np.array([b - a + 1 for a, b in lines])
    typical = np.median(heights)
    boxes = []
    for a, b in lines:
        if b - a + 1 > 2.2 * typical:
            continue
        clusters = _runs(ink[a:b + 1].any(axis=0), gap=max(2, int(0.5 * typical)))
        if not clusters:
            continue
        # the text block nearest the plot; tick marks (very flat) are skipped
        order = clusters[::-1] if side == 'left' else clusters
        for s, e in order:
            sub = ink[a:b + 1, s:e + 1]
            rr = np.flatnonzero(sub.any(axis=1))
            if rr[-1] - rr[0] + 1 >= 0.5 * typical and e - s + 1 >= 2:
                top, bot, _ = _glyph_extent(sub)
                boxes.append(_Box(r0 + a + rr[0], r0 + a + rr[-1], c0 + s, c0 + e,
                                  r0 + a + (top + bot) / 2, c0 + (s + e) / 2))
                break
    return boxes


def x_label_boxes(img: np.ndarray, layout: Layout) -> list:
    """Label boxes in the first text line under the plot."""
    p = layout.plot
    H, W = img.shape[:2]
    ph = p.bottom - p.top
    r0, r1 = min(H, p.bottom + 2), min(H, int(p.bottom + 0.25 * ph) + 4)
    c0, c1 = max(0, int(p.left - 0.08 * W)), min(W, int(p.right + 0.08 * W))
    if r1 - r0 < 4:
        return []
    ink = _ink(img[r0:r1, c0:c1])
    ink = _remove_long_lines(ink, axis=1)
    ink = _remove_long_lines(ink, axis=0, share=0.9)
    lines = [(a, b) for a, b in _runs(ink.any(axis=1)) if b - a + 1 >= 3]
    lo_col, hi_col = p.left - 0.03 * W, p.right + 0.03 * W
    for a, b in lines[:4]:
        if a > 0.15 * ph + 6:             # too far below the plot to be the axis
            break
        h = b - a + 1
        boxes = []
        for s, e in _runs(ink[a:b + 1].any(axis=0), gap=max(2, int(0.45 * h))):
            centre = c0 + (s + e) / 2
            if not lo_col <= centre <= hi_col:
                continue                  # e.g. the bottom of the 0° label beside the plot
            sub = ink[a:b + 1, s:e + 1]
            rr = np.flatnonzero(sub.any(axis=1))
            if rr[-1] - rr[0] + 1 < 0.5 * h:
                continue
            boxes.append(_Box(r0 + a + rr[0], r0 + a + rr[-1], c0 + s, c0 + e,
                              r0 + a + (rr[0] + rr[-1]) / 2, centre))
        if len(boxes) >= 2:
            return boxes
    return []


# --------------------------------------------------------------------------- reading

def _prepare(img: np.ndarray, box: _Box, target_h: int, strip_superscripts: bool):
    pad = 2
    t, b = max(0, box.top - pad), min(img.shape[0], box.bottom + pad + 1)
    l, r = max(0, box.left - pad), min(img.shape[1], box.right + pad + 1)
    crop = img[t:b, l:r].copy()
    ink = _ink(crop)
    if strip_superscripts:
        keep = _drop_superscripts(ink)
        crop[:, ~keep] = np.median(crop[~ink], axis=0) if (~ink).any() else 255
    grey = Image.fromarray(crop).convert('L')
    arr = np.asarray(grey)
    if (~ink).any() and arr[~ink].mean() < 128:        # light text on dark: invert
        grey = ImageOps.invert(grey)
    f = target_h / max(1, box.bottom - box.top + 1)
    grey = grey.resize((max(1, round(grey.width * f)), max(1, round(grey.height * f))), Image.LANCZOS)
    return ImageOps.expand(grey, border=max(10, target_h // 2), fill=255)


def _ocr(im: Image.Image, whitelist: str | None) -> str:
    cfg = '--psm 7'
    if whitelist:
        cfg += f' -c tessedit_char_whitelist={whitelist}'
    try:
        return pytesseract.image_to_string(im, config=cfg).strip()
    except Exception:
        return ''


def _readings(img, box, whitelist, strip=True, sizes=(32, 48, 64)):
    out = []
    for size in sizes:
        t = _ocr(_prepare(img, box, size, strip), whitelist)
        if t:
            out.append(t)
    return out


NUM = re.compile(r'-?\d+(?:[.,]\d+)?')


def _temperature_value(text: str):
    m = NUM.fullmatch(text.replace(' ', '').rstrip('.'))
    if not m:
        return None
    v = float(m.group().replace(',', '.'))
    return v if -60 <= v <= 700 else None


def _time_value(text: str):
    """('elapsed', hours) or ('clock', minutes after midnight) or ('number', n) or None."""
    t = text.lower().replace(' ', '').replace('o', '0').strip('.')
    m = re.fullmatch(r'(\d{1,2})[:.](\d{2})', t)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return 'clock', int(m.group(1)) * 60 + int(m.group(2))
    m = re.fullmatch(r'(\d+(?:\.\d+)?)h(?:(\d{1,2})m?)?', t)
    if m:
        return 'elapsed', float(m.group(1)) + (int(m.group(2)) / 60 if m.group(2) else 0)
    m = re.fullmatch(r'(\d+)m(?:in)?', t)
    if m:
        return 'elapsed', int(m.group(1)) / 60
    m = re.fullmatch(r'\d+', t)
    if m:
        return 'number', float(t)
    return None


def _fit(candidates: list, n_labels: int, min_tol: float):
    """Robust straight line through (pos, value, label index) candidates.

    Tries every pair of candidates from different labels; keeps the line that
    explains the most labels, then refits by least squares on those.
    """
    best = None
    for (p1, v1, i1), (p2, v2, i2) in combinations(candidates, 2):
        if i1 == i2 or abs(p2 - p1) < 3 or v1 == v2:
            continue
        slope = (v2 - v1) / (p2 - p1)
        tol = max(min_tol, 1.5 * abs(slope))
        chosen = {}
        for p, v, i in candidates:
            r = abs(v - (v1 + slope * (p - p1)))
            if r <= tol and (i not in chosen or r < chosen[i][0]):
                chosen[i] = (r, p, v)
        key = (len(chosen), -sum(r for r, _, _ in chosen.values()))
        if best is None or key > best[0]:
            best = (key, chosen)
    if best is None or len(best[1]) < 2:
        return None
    chosen = best[1]
    P = np.array([c[1] for c in chosen.values()])
    V = np.array([c[2] for c in chosen.values()])
    slope, intercept = np.polyfit(P, V, 1)
    return slope, intercept, chosen, float(np.abs(V - (intercept + slope * P)).max())


def _snap(pos: float, lines: list, tolerance: float) -> float:
    """Use a gridline position when a label is centred on it (more exact than the text)."""
    if not lines:
        return pos
    near = min(lines, key=lambda g: abs(g - pos))
    return float(near) if abs(near - pos) <= tolerance else pos


def read_temperature_axis(img: np.ndarray, layout: Layout) -> AxisFit:
    if layout.plot is None or not available():
        return AxisFit(kind='temperature')
    for side in ('left', 'right'):
        boxes = y_label_boxes(img, layout, side)
        cands, texts = [], {}
        for i, box in enumerate(boxes):
            pos = _snap(box.centre_row, layout.h_lines, max(1.5, 0.35 * (box.bottom - box.top + 1)))
            reads = _readings(img, box, '0123456789-.,')
            texts[i] = (pos, reads)
            for t in dict.fromkeys(reads):
                v = _temperature_value(t)
                if v is not None:
                    cands.append((pos, v, i))
        fit = _fit(cands, len(boxes), min_tol=0.6)
        if fit:
            break
    if not fit:
        return AxisFit(kind='temperature')
    slope, intercept, chosen, resid = fit
    labels = []
    for i, (pos, reads) in texts.items():
        if i in chosen:
            v = chosen[i][2]
            labels.append(Label(f'{v:g}', pos, v, True))
        else:
            labels.append(Label(reads[0] if reads else '?', pos, float('nan'), False))
    labels.sort(key=lambda l: l.pos)
    return AxisFit(labels, slope, intercept, 'temperature', resid)


def read_time_axis(img: np.ndarray, layout: Layout) -> AxisFit:
    if layout.plot is None or not available():
        return AxisFit()
    boxes = x_label_boxes(img, layout)
    per_label = []
    for i, box in enumerate(boxes):
        pos = _snap(box.centre_col, layout.v_lines, max(1.5, 0.2 * (box.right - box.left + 1)))
        reads = _readings(img, box, '0123456789hm:.', strip=False)
        parsed = [r for r in (_time_value(t) for t in reads) if r]
        per_label.append((i, pos, reads, parsed))
    kinds = [k for _, _, _, parsed in per_label for k, _ in parsed]
    if not kinds:
        return AxisFit()
    kind = max(('clock', 'elapsed', 'number'), key=kinds.count)
    cands = []
    if kind == 'clock':
        # one reading per label (the most common), then unwrap past midnight
        seq = []
        for i, pos, _, parsed in per_label:
            vals = [v for k, v in parsed if k == 'clock']
            if vals:
                seq.append((pos, max(set(vals), key=vals.count), i))
        seq.sort()
        day = 0
        prev = None
        for pos, v, i in seq:
            if prev is not None and v + day * 1440 < prev - 60:
                day += 1
            cands.append((pos, (v + day * 1440) / 60, i))
            prev = v + day * 1440
    else:
        for i, pos, _, parsed in per_label:
            for k, v in dict.fromkeys(parsed):
                if k == kind:
                    cands.append((pos, v, i))
    fit = _fit(cands, len(boxes), min_tol=0.05)
    if not fit:
        return AxisFit()
    slope, intercept, chosen, resid = fit
    labels = []
    for i, pos, reads, parsed in per_label:
        if i in chosen:
            v = chosen[i][2]
            if kind == 'clock':
                m = int(round(v * 60)) % 1440
                text = f'{m // 60:02d}:{m % 60:02d}'
            else:
                text = f'{v:g}h'
            labels.append(Label(text, pos, v, True))
        else:
            labels.append(Label(reads[0] if reads else '?', pos, float('nan'), False))
    return AxisFit(labels, slope, intercept, 'elapsed' if kind == 'number' else kind, resid)


# --------------------------------------------------------------------------- legend

ROLE_WORDS = {
    'meat': ('internal', 'meat', 'food', 'probe', 'core', 'inner', 'inside', 'tip', 'brisket', 'pork', 'beef'),
    'ambient': ('ambient', 'pit', 'grill', 'smoker', 'oven', 'cooker', 'chamber', 'air', 'cavity', 'dome',
                'grate', 'bbq', 'surface', 'external'),
    'target': ('target', 'setpoint', 'set', 'goal', 'alarm', 'limit'),
}


def _role(word: str):
    w = re.sub(r'[^a-z]', '', word.lower())
    if len(w) < 3:
        return None
    best = (0.0, None)
    for role, words in ROLE_WORDS.items():
        for k in words:
            r = difflib.SequenceMatcher(None, w, k).ratio()
            if w.startswith(k) or (len(k) >= 4 and k.startswith(w) and len(w) >= 4):
                r = max(r, 0.9)
            if r > best[0]:
                best = (r, role)
    return best[1] if best[0] >= 0.72 else None


def _marker_colour(img: np.ndarray, box) -> tuple | None:
    """Colour of the legend marker left of a word, or of the word itself."""
    l, t, r, b = box
    h = b - t + 1
    regions = [img[max(0, t - h // 2):b + h // 2 + 1, max(0, int(l - 3 * h)):max(0, l - 1)],
               img[t:b + 1, l:r + 1]]
    for reg in regions:
        if reg.size == 0:
            continue
        flat = reg.reshape(-1, 3)
        chroma = flat.max(axis=1).astype(int) - flat.min(axis=1)
        sel = flat[chroma > 45]
        if len(sel) >= 3:
            c = sel[(sel.max(axis=1).astype(int) - sel.min(axis=1)) >= np.median(sel.max(axis=1).astype(int) - sel.min(axis=1))]
            return tuple(int(v) for v in np.median(c, axis=0))
    return None


def read_legend(img: np.ndarray, layout: Layout) -> list:
    """Legend words with known meanings (Internal, Ambient, Target…) and their colours."""
    if layout.plot is None or not available():
        return []
    p = layout.plot
    ph = p.bottom - p.top
    H, W = img.shape[:2]
    r0, r1 = max(0, int(p.top - 0.6 * ph)), min(H, int(p.bottom + 0.35 * ph))
    region = img[r0:r1]
    scale = 3 if W < 900 else 2
    im = Image.fromarray(region).convert('L')
    if np.asarray(im).mean() < 110:
        im = ImageOps.invert(im)
    im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
    try:
        d = pytesseract.image_to_data(im, config='--psm 11', output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    found = {}
    for i, word in enumerate(d['text']):
        role = _role(word or '')
        if not role or role in found:
            continue
        box = (d['left'][i] // scale, r0 + d['top'][i] // scale,
               (d['left'][i] + d['width'][i]) // scale, r0 + (d['top'][i] + d['height'][i]) // scale)
        rgb = _marker_colour(img, box)
        if rgb is not None:
            found[role] = LegendEntry(role, word, rgb, box)
    return list(found.values())
