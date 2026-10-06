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
