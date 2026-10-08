"""A synthetic phone-app style temperature chart with known values.

Used by the "Try the example chart" button and by the tests, which compare
the digitized values against the curves the chart was drawn from.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from PIL import Image, ImageDraw, ImageFont

START = datetime(2026, 6, 1, 18, 0)
HOURS = 10.0
Y_MIN, Y_MAX, Y_STEP = 0, 150, 25


def ambient(h):
    h = np.asarray(h, float)
    base = 20 + (110 - 20) * (1 - np.exp(-h / 0.35))
    wobble = 3.0 * np.sin(h * 2.3) + 1.5 * np.sin(h * 7.1)
    lid = -55 * np.exp(-((h - 4.0) / 0.06) ** 2)          # lid opened at 22:00
    return base + wobble + lid


def meat(h):
    h = np.asarray(h, float)
    rise = 5 + (68 - 5) * (1 - np.exp(-h / 1.6))
    stall = np.clip((h - 5.2) / 3.5, 0, 1) ** 1.6 * 27     # stall, then push to ~95
    return rise + stall


@dataclass
class ExampleChart:
    image: Image.Image
    plot_left: int
    plot_right: int
    plot_top: int       # row of the Y_MAX gridline
    plot_bottom: int    # row of the Y_MIN gridline
    dark: bool

    def y_px(self, value):
        return self.plot_bottom + (np.asarray(value, float) - Y_MIN) * (self.plot_top - self.plot_bottom) / (Y_MAX - Y_MIN)

    def hours(self, x_px):
        return (np.asarray(x_px, float) - self.plot_left) * HOURS / (self.plot_right - self.plot_left)


def _font(size):
    for name in ('DejaVuSans.ttf', 'Arial.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def make_example(width: int = 1080, height: int = 760, dark: bool = False, scale: int = 4,
                 ambient_colour=(240, 140, 30), meat_colour=(220, 45, 60)) -> ExampleChart:
    """Draw the chart at `scale` times the size, then downsample (anti-aliased like a screenshot)."""
    W, H = width * scale, height * scale
    bg = (24, 26, 30) if dark else (255, 255, 255)
    grid = (70, 74, 82) if dark else (222, 224, 228)
    text = (200, 204, 210) if dark else (90, 94, 100)
    im = Image.new('RGB', (W, H), bg)
    d = ImageDraw.Draw(im)
    f = _font(15 * scale)
    ft = _font(22 * scale)

    pl, pr = int(0.10 * width) * scale, int(0.95 * width) * scale
    pt, pb = int(0.16 * height) * scale, int(0.86 * height) * scale
    d.text((pl, int(0.04 * height) * scale), 'Brisket - temperature', fill=text, font=ft)
    d.line([(0, int(0.12 * height) * scale), (W, int(0.12 * height) * scale)], fill=grid, width=scale)  # UI divider

    gw = max(1, scale)
    for v in range(Y_MIN, Y_MAX + 1, Y_STEP):
        y = pb + (v - Y_MIN) * (pt - pb) / (Y_MAX - Y_MIN)
        d.line([(pl, y), (pr, y)], fill=grid, width=gw)
        d.text((pl - 12 * scale, y), f'{v}°', fill=text, font=f, anchor='rm')
    for k in range(0, int(HOURS) + 1, 2):
        x = pl + k * (pr - pl) / HOURS
        d.line([(x, pt), (x, pb)], fill=grid, width=gw)
        t = START + timedelta(hours=k)
        d.text((x, pb + 10 * scale), t.strftime('%H:%M'), fill=text, font=f, anchor='mt')

    # legend inside the plot area, in the line colours
    lx, ly = pl + 20 * scale, pt + 14 * scale
    for label, colour in (('Ambient', ambient_colour), ('Meat', meat_colour)):
        d.rectangle([lx, ly, lx + 14 * scale, ly + 14 * scale], fill=colour)
        d.text((lx + 20 * scale, ly - 2 * scale), label, fill=colour, font=f)
        lx += 110 * scale

    xs = np.linspace(pl, pr, 2400)
    hrs = (xs - pl) / (pr - pl) * HOURS
    ypx = lambda v: pb + (v - Y_MIN) * (pt - pb) / (Y_MAX - Y_MIN)
    lw = int(2.5 * scale)
    d.line(list(zip(xs, ypx(ambient(hrs)))), fill=ambient_colour, width=lw, joint='curve')
    meat_h = hrs[hrs >= 0.25]                          # probe inserted 15 minutes in
    d.line(list(zip(xs[hrs >= 0.25], ypx(meat(meat_h)))), fill=meat_colour, width=lw, joint='curve')

    small = im.resize((width, height), Image.LANCZOS)
    # pixel coordinates in the small image (pixel centres)
    s = lambda v: (v + 0.5) / scale - 0.5
    return ExampleChart(small, s(pl), s(pr), s(pt), s(pb), dark)


if __name__ == '__main__':
    make_example().image.save('example_chart.png')


# --------------------------------------------------------------------------- probe-app style replica
# Modelled on a phone probe app: legend dots with grey words, a flat target
# line, a pale (lavender) ambient line, a red internal line with a pink fill,
# dashed gridlines, rounded axis labels (0°, 24°, ... 143°) and elapsed-hour
# time labels (4h ... 24h), plus a red button under the chart.

PROBE_YMAX = 143.3           # the app's scale; labels are rounded to whole degrees
PROBE_HOURS = 24.0
PROBE_END = 22.75            # the cook ended at 22 h 45 min
PROBE_TARGET = 100.0

AMBIENT_RGB = (155, 165, 250)
INTERNAL_RGB = (250, 58, 55)
TARGET_RGB = (221, 85, 253)


def probe_ambient(h):
    h = np.asarray(h, float)
    v = 22 + 58 * (1 - np.exp(-h / 0.6)) + 4 * np.sin(h * 5.0)        # warming to ~80
    v = np.where(h > 3.4, 108 + 3 * np.sin(h * 6.0), v)                # raised to ~108
    for c, a in ((5.0, -14), (5.9, -16), (7.3, 25), (7.9, 30), (8.6, 22), (9.2, 15)):
        v = v + a * np.exp(-((h - c) / 0.12) ** 2)                     # lid openings and spikes
    v = np.where(h > 10.0, 72 - 0.6 * (h - 10.0), v)                   # wrapped, smoker turned down
    v = np.where(h > 22.5, 64 - 120 * (h - 22.5), v)                   # taken off
    return v


def probe_internal(h):
    h = np.asarray(h, float)
    v = 10 + 82.4 * (1 - np.exp(-h / 2.6)) / (1 - np.exp(-10 / 2.6))   # 10 -> 92.4 at 10 h
    v = np.where(h > 10.0, 92.4 - 0.75 * (h - 10.0), v)                # slow decline in the hold
    v = np.where(h > 22.5, v - 70 * (h - 22.5), v)
    return v


@dataclass
class ProbeChart:
    image: Image.Image
    plot_left: float
    plot_right: float
    y_top: float         # row of the 143° gridline
    y_bottom: float      # row of the 0° gridline

    def y_px(self, value):
        return self.y_bottom + np.asarray(value, float) * (self.y_top - self.y_bottom) / PROBE_YMAX

    def hours(self, x_px):
        return (np.asarray(x_px, float) - self.plot_left) * PROBE_HOURS / (self.plot_right - self.plot_left)


def _dashed_h(d, x0, x1, y, fill, width, dash, gap):
    x = x0
    while x < x1:
        d.line([(x, y), (min(x + dash, x1), y)], fill=fill, width=width)
        x += dash + gap


def _dashed_v(d, x, y0, y1, fill, width, dash, gap):
    y = y0
    while y < y1:
        d.line([(x, y), (x, min(y + dash, y1))], fill=fill, width=width)
        y += dash + gap


def make_probe_example(width: int = 1080, height: int = 1350, scale: int = 3, gap=None) -> ProbeChart:
    """gap: (start h, end h) with no recorded data; the app joins it with grey dotted lines."""
    W, H = width * scale, height * scale
    u = width / 582 * scale                     # layout unit: 1 = one pixel of a 582 px wide screen
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    grey_text, grid = (40, 40, 40), (205, 205, 205)
    d.text((92 * u, 10 * u), '92.4°C', fill=(10, 10, 10), font=_font(int(20 * u)))
    d.line([(92 * u, 65 * u), (487 * u, 65 * u)], fill=(238, 238, 238), width=max(1, int(u)))
    d.text((92 * u, 96 * u), 'Chart', fill=grey_text, font=_font(int(15 * u)))
    f = _font(int(11 * u))
    for x, label, colour in ((107, 'Internal', INTERNAL_RGB), (175, 'Target', TARGET_RGB), (236, 'Ambient', AMBIENT_RGB)):
        d.ellipse([x * u, 138 * u, (x + 7) * u, 145 * u], fill=colour)
        d.text(((x + 13) * u, 135 * u), label, fill=grey_text, font=f)

    pl, pr, pt, pb = 139 * u, 446 * u, 173 * u, 432 * u
    lw = max(1, int(1.2 * u))
    for k in range(7):
        y = pb + k * (pt - pb) / 6
        if k == 0:
            d.line([(pl, y), (pr, y)], fill=grid, width=lw)
        else:
            _dashed_h(d, pl, pr, y, grid, lw, 3 * u, 2.5 * u)
        d.text((131 * u, y), f'{round(PROBE_YMAX * k / 6)}°', fill=grey_text, font=f, anchor='rm')
    d.line([(pl, pt), (pl, pb)], fill=grid, width=lw)
    for k in range(1, 7):
        x = pl + k * (pr - pl) / 6
        _dashed_v(d, x, pt, pb, grid, lw, 3 * u, 2.5 * u)
        d.text((x, 440 * u), f'{4 * k}h', fill=grey_text, font=f, anchor='mt')

    hrs = np.linspace(0, PROBE_END, 4000)
    xs = pl + hrs / PROBE_HOURS * (pr - pl)
    ypx = lambda v: pb + np.asarray(v) * (pt - pb) / PROBE_YMAX
    yi = ypx(probe_internal(hrs))
    xh = lambda h: pl + h / PROBE_HOURS * (pr - pl)
    if gap:
        parts = [hrs <= gap[0], hrs >= gap[1]]
        # dotted connectors across the gap, as the app draws them
        dots = [((xh(gap[0]), ypx(fn(gap[0]))), (xh(gap[1]), ypx(fn(gap[1]))))
                for fn in (probe_internal, probe_ambient)]
    else:
        parts = [np.ones(hrs.size, bool)]
        dots = [((xh(10), ypx(92.4)), (xh(21.5), ypx(v))) for v in (75, 62)]   # prediction lines
    peak = (pl + 10 / PROBE_HOURS * (pr - pl), ypx(92.4))
    for (x0, y0), (x1, y1) in dots:
        for t in np.arange(0, 1, 0.02):
            d.ellipse([x0 + (x1 - x0) * t - u * .5, y0 + (y1 - y0) * t - u * .5,
                       x0 + (x1 - x0) * t + u * .5, y0 + (y1 - y0) * t + u * .5], fill=(185, 185, 185))
    line_w = max(1, int(1.6 * u))
    yt = ypx(PROBE_TARGET)
    d.line([(pl, yt), (pr, yt)], fill=TARGET_RGB, width=line_w)
    d.polygon([(pl - 3 * u, yt - 4 * u), (pl - 3 * u, yt + 4 * u), (pl + 4 * u, yt)], fill=(40, 200, 40))
    for part in parts:
        d.line(list(zip(xs[part], ypx(probe_ambient(hrs[part])))), fill=AMBIENT_RGB, width=line_w, joint='curve')
    # translucent red shading under the internal line, drawn over everything
    # beneath it (as the app does): the ambient line inside it turns from
    # #9ba5fa to about #a49ee7
    alpha = np.zeros((H, W), np.float32)
    alpha[int(pt):int(pb)] = np.linspace(0.16, 0.03, int(pb) - int(pt))[:, None]
    mask = Image.new('L', (W, H), 0)
    for part in parts:
        ImageDraw.Draw(mask).polygon(list(zip(xs[part], yi[part])) + [(xs[part][-1], pb), (xs[part][0], pb)], fill=255)
    a_map = (alpha * (np.asarray(mask, np.float32) / 255))[..., None]
    arr = np.asarray(im, np.float32)
    arr = arr * (1 - a_map) + np.array(INTERNAL_RGB, np.float32) * a_map
    im = Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    for part in parts:
        d.line(list(zip(xs[part], yi[part])), fill=INTERNAL_RGB, width=line_w, joint='curve')
    d.polygon([(peak[0] - 4 * u, peak[1] - 6 * u), (peak[0] + 4 * u, peak[1] - 6 * u), (peak[0], peak[1])], fill=INTERNAL_RGB)

    ft = _font(int(14 * u))
    for x, a, b in ((175, 'Target', '100°C'), (289, 'Peak', '92.4°C'), (388, 'Elapsed', '22hr45min')):
        d.text((x * u, 507 * u), a, fill=(20, 20, 20), font=ft, anchor='mm')
        d.text((x * u, 530 * u), b, fill=(20, 20, 20), font=_font(int(17 * u)), anchor='mm')
    d.rounded_rectangle([92 * u, 551 * u, 487 * u, 604 * u], radius=26 * u, fill=(219, 79, 78))
    d.text((290 * u, 577 * u), 'Cook Again', fill=(255, 255, 255), font=_font(int(17 * u)), anchor='mm')

    small = im.resize((width, height), Image.LANCZOS)
    s = lambda v: (v + 0.5) / scale - 0.5
    return ProbeChart(small, s(pl), s(pr), s(pt), s(pb))
