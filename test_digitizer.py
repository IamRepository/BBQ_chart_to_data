"""Accuracy tests on synthetic charts with known values.

Run: python -m unittest test_digitizer
"""
import io
import re
import unittest
from datetime import datetime, timedelta

import numpy as np
from PIL import Image

import digitizer as dg
from example_chart import HOURS, START, Y_MAX, Y_MIN, ambient, make_example, meat

DIP = (3.8, 4.2)          # the lid-open spike: steeper than one pixel column can hold


def run(ex, image=None):
    img = np.asarray(image if image is not None else ex.image)
    lay = dg.detect_layout(img)
    area = dg.default_search_area(lay, img.shape[1], img.shape[0])
    cands = dg.colour_candidates(img, area)
    return img, lay, area, cands


def pick(cands, rgb):
    return min(cands, key=lambda c: sum((a - b) ** 2 for a, b in zip(c.rgb, rgb)))


def errors(ex, trace, fn, skip_dip=True, scale=1.0):
    h = ex.hours(trace.x * scale) if scale == 1 else ex.hours(trace.x * scale)
    ok = ~np.isnan(trace.y) & (h >= 0.3) & (h <= HOURS)
    if skip_dip:
        ok &= ~((h > DIP[0]) & (h < DIP[1]))
    return trace.y[ok] * scale - ex.y_px(fn(h[ok]))


class Layout(unittest.TestCase):
    def test_gridlines_light_and_dark(self):
        for dark in (False, True):
            ex = make_example(dark=dark)
            _, lay, _, _ = run(ex)
            self.assertEqual(len(lay.h_lines), (Y_MAX - Y_MIN) // 25 + 1)
            self.assertAlmostEqual(lay.h_lines[0], ex.plot_top, delta=0.6)
            self.assertAlmostEqual(lay.h_lines[-1], ex.plot_bottom, delta=0.6)
            self.assertAlmostEqual(lay.v_lines[0], ex.plot_left, delta=0.6)
            self.assertAlmostEqual(lay.v_lines[-1], ex.plot_right, delta=0.6)
            self.assertLess(abs(lay.plot.left - ex.plot_left), 1.5, 'axis labels must not widen the plot')

    def test_line_colours_found(self):
        ex = make_example()
        _, _, _, cands = run(ex)
        self.assertGreaterEqual(len(cands), 2)
        names = {dg.colour_name(c.rgb) for c in cands[:2]}
        self.assertEqual(names, {'orange', 'red'})


    def test_chart_card_inside_phone_screenshot(self):
        """Dark chart on its own card, inside a taller page with UI around it."""
        ex = make_example(dark=True)
        page = Image.new('RGB', (1170, 2532), (16, 16, 18))
        from PIL import ImageDraw
        d = ImageDraw.Draw(page)
        d.rounded_rectangle([60, 2100, 1110, 2240], 30, fill=(240, 140, 30))   # orange button
        for y in (1700, 1820):
            d.line([(40, y), (1130, y)], fill=(60, 60, 64), width=2)
        page.paste(ex.image, (45, 500))
        img = np.asarray(page)
        lay = dg.detect_layout(img)
        self.assertEqual(len(lay.h_lines), 7)
        self.assertAlmostEqual(lay.h_lines[0], ex.plot_top + 500, delta=0.6)
        self.assertAlmostEqual(lay.v_lines[0], ex.plot_left + 45, delta=0.6)
        area = dg.default_search_area(lay, img.shape[1], img.shape[0])
        self.assertLess(area.bottom, 2100, 'the orange button must stay outside the search area')

    def test_dashed_gridlines(self):
        ex = make_example()
        img = np.asarray(ex.image).copy()
        for x in range(0, img.shape[1], 12):          # cut every gridline into 8 px dashes
            img[:, x + 8:x + 12][(img[:, x + 8:x + 12] < 240).all(axis=2) & (img[:, x + 8:x + 12] > 200).all(axis=2)] = 255
        lay = dg.detect_layout(img)
        self.assertEqual(len(lay.h_lines), 7)
        self.assertAlmostEqual(lay.h_lines[-1], ex.plot_bottom, delta=0.6)


class Accuracy(unittest.TestCase):
    def check(self, ex, image=None, limit_px=0.35, scale=1.0, meat_rgb=(220, 45, 60), amb_rgb=(240, 140, 30)):
        img, lay, area, cands = run(ex, image)
        for rgb, fn in ((amb_rgb, ambient), (meat_rgb, meat)):
            tr = dg.trace_line(img, area, pick(cands, rgb).rgb, lay.background)
            err = errors(ex, tr, fn, scale=scale)
            rmse = float(np.sqrt(np.mean(err ** 2)))
            self.assertLess(rmse, limit_px, f'{fn.__name__}: rmse {rmse:.3f} px')
            self.assertLess(float(np.abs(err).max()), 8 * limit_px + 1.5, f'{fn.__name__}: max {np.abs(err).max():.2f}')
            self.assertGreater(tr.columns_found, 0.97)

    def test_light(self):
        self.check(make_example())

    def test_dark(self):
        self.check(make_example(dark=True))

    def test_jpeg(self):
        ex = make_example()
        buf = io.BytesIO()
        ex.image.save(buf, 'JPEG', quality=75)
        self.check(ex, dg.load_image(buf.getvalue()), limit_px=0.5)

    def test_downscaled_screenshot(self):
        ex = make_example()
        small = ex.image.resize((ex.image.width // 2, ex.image.height // 2), Image.LANCZOS)
        # pixel centres: big = 2 * small + 0.5
        img, lay, area, cands = run(ex, small)
        for rgb, fn in (((240, 140, 30), ambient), ((220, 45, 60), meat)):
            tr = dg.trace_line(img, area, pick(cands, rgb).rgb, lay.background)
            h = ex.hours(tr.x * 2 + 0.5)
            ok = ~np.isnan(tr.y) & (h >= 0.3) & ~((h > DIP[0]) & (h < DIP[1]))
            err = (tr.y[ok] * 2 + 0.5) - ex.y_px(fn(h[ok]))
            self.assertLess(float(np.sqrt(np.mean(err ** 2))), 0.8)

    def test_other_colours(self):
        ex = make_example(ambient_colour=(40, 120, 220), meat_colour=(30, 170, 90))
        self.check(ex, amb_rgb=(40, 120, 220), meat_rgb=(30, 170, 90))

    def test_meat_line_survives_crossing(self):
        """At the lid-open dip the ambient line crosses the meat line twice."""
        ex = make_example()
        img, lay, area, cands = run(ex)
        tr = dg.trace_line(img, area, pick(cands, (220, 45, 60)).rgb, lay.background)
        h = ex.hours(tr.x)
        near = (h > 3.7) & (h < 4.3)
        self.assertFalse(np.isnan(tr.y[near]).any())
        err = tr.y[near] - ex.y_px(meat(h[near]))
        self.assertLess(float(np.abs(err).max()), 3.5)

    def test_legend_not_traced(self):
        """The legend text uses the line colours but must not appear in the trace."""
        ex = make_example()
        img, lay, area, cands = run(ex)
        tr = dg.trace_line(img, area, pick(cands, (220, 45, 60)).rgb, lay.background)
        h = ex.hours(tr.x)
        early = h < 0.2           # meat probe not in yet: nothing to trace there
        self.assertTrue(np.isnan(tr.y[early]).all())


class Markers(unittest.TestCase):
    def test_solid_marker_removed_line_kept(self):
        cov = np.zeros((80, 200))
        cov[40:43, :] = 1.0                      # a 3 px line
        cov[25:42, 90:110] = 1.0                 # a solid marker on it
        out = dg.remove_markers(cov, 3.0)
        self.assertEqual(out[30, 100], 0)
        self.assertTrue((out[40:43, :80] == 1).all() and (out[40:43, 120:] == 1).all())

    def test_nothing_to_remove(self):
        cov = np.zeros((80, 200))
        cov[40:43, :] = 1.0
        self.assertIs(dg.remove_markers(cov, 3.0), cov)


class GapFill(unittest.TestCase):
    def test_straight_line_inside_gaps_only(self):
        import pandas as pd
        stamps = [(datetime(2026, 6, 21, 18, 0) + timedelta(minutes=k)).strftime(dg.TIME_FORMAT) for k in range(8)]
        df = pd.DataFrame({'Timestamp': stamps,
                           'Ambient temperature (°C)': [np.nan, 100, np.nan, np.nan, np.nan, 60, 61, np.nan],
                           'Meat temperature (°C)': [10, 11, 12, 13, 14, 15, 16, 17]})
        out, filled = dg.fill_gaps(df)
        amb = out['Ambient temperature (°C)'].tolist()
        self.assertTrue(np.isnan(amb[0]) and np.isnan(amb[7]), 'nothing added before the first or after the last value')
        self.assertEqual(amb[1:7], [100, 90, 80, 70, 60, 61])
        self.assertEqual(filled['Ambient temperature (°C)'].tolist(), [False, False, True, True, True, False, False, False])
        self.assertFalse(filled['Meat temperature (°C)'].any())
        self.assertTrue(np.isnan(df['Ambient temperature (°C)'][2]), 'the input table is not changed')


class Roles(unittest.TestCase):
    def test_ambient_is_hotter_at_the_start(self):
        from example_chart import make_probe_example, AMBIENT_RGB, INTERNAL_RGB
        for ex, amb, meat_ in ((make_example(), (240, 140, 30), (220, 45, 60)),
                               (make_probe_example(), AMBIENT_RGB, INTERNAL_RGB)):
            img, lay, area, cands = run(ex)
            others = [c.rgb for c in cands]
            ta = dg.trace_line(img, area, pick(cands, amb).rgb, lay.background, others=others)
            tm = dg.trace_line(img, area, pick(cands, meat_).rgb, lay.background, others=others)
            self.assertTrue(dg.hotter_early(ta, tm))
            self.assertFalse(dg.hotter_early(tm, ta))


class Table(unittest.TestCase):
    def setUp(self):
        self.ex = make_example()
        img, lay, area, cands = run(self.ex)
        self.cal = dg.Calibration(lay.h_lines[0], Y_MAX, lay.h_lines[-1], Y_MIN,
                                  lay.v_lines[0], START, lay.v_lines[-1], START + timedelta(hours=HOURS))
        self.traces = {
            'Ambient temperature': dg.trace_line(img, area, pick(cands, (240, 140, 30)).rgb, lay.background),
            'Meat temperature': dg.trace_line(img, area, pick(cands, (220, 45, 60)).rgb, lay.background),
        }

    def test_values_per_minute(self):
        series = {k: dg.series_in_units(t, self.cal) for k, t in self.traces.items()}
        df = dg.build_table(series, self.cal, 60)
        self.assertEqual(list(df.columns), ['Timestamp', 'Ambient temperature (°C)', 'Meat temperature (°C)'])
        self.assertEqual(df['Timestamp'].iloc[0], '01/06/2026 18:00')
        self.assertEqual(df['Timestamp'].iloc[-1], '02/06/2026 04:00')
        self.assertEqual(len(df), 601)
        self.assertTrue(df['Timestamp'].str.fullmatch(r'\d\d/\d\d/\d{4} \d\d:\d\d').all())
        h = np.arange(len(df)) / 60
        for col, fn in (('Ambient temperature (°C)', ambient), ('Meat temperature (°C)', meat)):
            ok = df[col].notna().to_numpy() & (h >= 0.3) & ~((h > DIP[0]) & (h < DIP[1]))
            err = df[col].to_numpy()[ok] - fn(h[ok])
            self.assertLess(float(np.abs(err).mean()), 0.15, col)
            self.assertLess(float(np.abs(err).max()), 1.0, col)
        # meat probe goes in at 18:15: no meat value before that
        self.assertTrue(df['Meat temperature (°C)'].iloc[:13].isna().all())

    def test_pixel_table(self):
        df = dg.build_pixel_table(self.traces, self.cal)
        self.assertTrue(df['Timestamp'].str.fullmatch(r'\d\d/\d\d/\d{4} \d\d:\d\d:\d\d').all())
        self.assertGreater(len(df), 900)

    def test_gap_stays_empty(self):
        sec = np.r_[np.arange(0, 3600, 40.0), np.arange(7200, 9000, 40.0)]
        val = np.full(sec.shape, 100.0)
        df = dg.build_table({'Ambient temperature': (sec, val)}, self.cal, 60, max_gap_s=120)
        row = dict(zip(df['Timestamp'], df['Ambient temperature (°C)']))
        self.assertTrue(np.isnan(row['01/06/2026 19:30']), 'the gap is kept as an empty row')
        self.assertEqual(row['01/06/2026 18:30'], 100.0)
        self.assertEqual(row['01/06/2026 20:29'], 100.0)
        self.assertEqual(len(df), len(set(df['Timestamp'])))
        steps = np.diff([datetime.strptime(t, dg.TIME_FORMAT) for t in df['Timestamp']])
        self.assertTrue(all(s == timedelta(minutes=1) for s in steps), 'one row every minute, gaps included')

    def test_csv(self):
        series = {k: dg.series_in_units(t, self.cal) for k, t in self.traces.items()}
        text = dg.to_csv_bytes(dg.build_table(series, self.cal, 300)).decode('utf-8-sig')
        first = text.splitlines()[0]
        self.assertEqual(first, 'Timestamp,Ambient temperature (°C),Meat temperature (°C)')
        self.assertTrue(re.match(r'01/06/2026 18:00,\d', text.splitlines()[1]))


class Calibration(unittest.TestCase):
    def test_linear_maps_and_checks(self):
        t = datetime(2026, 6, 1, 18, 0)
        cal = dg.Calibration(100, 150, 600, 0, 100, t, 1100, t + timedelta(hours=10))
        self.assertAlmostEqual(float(cal.value(350)), 75)
        self.assertAlmostEqual(float(cal.seconds(600)), 5 * 3600)
        self.assertAlmostEqual(cal.seconds_per_px, 36)
        self.assertAlmostEqual(cal.degrees_per_px, 0.3)
        self.assertEqual(cal.check(), [])
        bad = dg.Calibration(100, 50, 102, 50, 100, t, 100, t)
        self.assertEqual(len(bad.check()), 4)


if __name__ == '__main__':
    unittest.main()
