"""Tests for reading labels and legends, on charts with known values.

Run: python -m unittest test_chart_text   (needs Tesseract; skipped without it)
"""
import io
import unittest
from datetime import datetime, timedelta

import numpy as np

import chart_text as ct
import digitizer as dg
from example_chart import (AMBIENT_RGB, INTERNAL_RGB, PROBE_END, PROBE_HOURS, PROBE_TARGET, PROBE_YMAX,
                           TARGET_RGB, make_example, make_probe_example, probe_ambient, probe_internal)

T0 = datetime(2026, 6, 1, 18, 0)


def jpeg(image, quality=80):
    buf = io.BytesIO()
    image.save(buf, 'JPEG', quality=quality)
    return dg.load_image(buf.getvalue())


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** .5


def pipeline(img):
    """What the app does by default: labels, legend, trace, per-minute table."""
    lay = dg.detect_layout(img)
    y = ct.read_temperature_axis(img, lay)
    x = ct.read_time_axis(img, lay)
    legend = {e.role: e for e in ct.read_legend(img, lay)}
    area = dg.default_search_area(lay, img.shape[1], img.shape[0])
    cands = dg.colour_candidates(img, area)
    others = [c.rgb for c in cands]
    last = x.used[-1].value
    lo, hi = y.used[0], y.used[-1]
    cal = dg.Calibration(lo.pos, float(y.value(lo.pos)), hi.pos, float(y.value(hi.pos)),
                         float(x.pos(0)), T0, float(x.pos(last)), T0 + timedelta(hours=last))
    series = {}
    for role, label in (('ambient', 'Ambient temperature'), ('meat', 'Meat temperature')):
        c = min(cands, key=lambda c: dist(c.rgb, legend[role].rgb))
        series[label] = dg.series_in_units(dg.trace_line(img, area, c.rgb, lay.background, others=others), cal)
    return dg.build_table(series, cal, 60, anchor=T0, not_before=T0)


@unittest.skipUnless(ct.available(), 'Tesseract is not installed')
class ProbeAppChart(unittest.TestCase):
    """Replica of a phone probe app: rounded labels 0°..143°, elapsed hours, legend dots."""

    @classmethod
    def setUpClass(cls):
        cls.ex = make_probe_example()
        cls.img = np.asarray(cls.ex.image)
        cls.lay = dg.detect_layout(cls.img)

    def test_dashed_gridlines_and_target_line(self):
        self.assertEqual(len(self.lay.h_lines), 7, 'six dashed gridlines and the base line')
        self.assertFalse(any(abs(r - self.ex.y_px(PROBE_TARGET)) < 3 for r in self.lay.h_lines),
                         'the flat target line is not a gridline')

    def test_temperature_scale_from_labels(self):
        y = ct.read_temperature_axis(self.img, self.lay)
        self.assertTrue(y.ok)
        self.assertGreaterEqual(len(y.used), 5)
        # labels are rounded (143 for 143.3), so allow half a degree
        self.assertAlmostEqual(float(y.value(self.ex.y_top)), PROBE_YMAX, delta=0.5)
        self.assertAlmostEqual(float(y.value(self.ex.y_bottom)), 0, delta=0.5)

    def test_elapsed_time_labels(self):
        x = ct.read_time_axis(self.img, self.lay)
        self.assertEqual(x.kind, 'elapsed')
        self.assertEqual([l.text for l in x.used], ['4h', '8h', '12h', '16h', '20h', '24h'])
        self.assertAlmostEqual(float(x.value(self.ex.plot_left)), 0, delta=0.05)
        self.assertAlmostEqual(float(x.value(self.ex.plot_right)), PROBE_HOURS, delta=0.05)

    def test_legend_roles_and_colours(self):
        legend = {e.role: e for e in ct.read_legend(self.img, self.lay)}
        self.assertEqual(set(legend), {'meat', 'ambient', 'target'})
        self.assertLess(dist(legend['meat'].rgb, INTERNAL_RGB), 20)
        self.assertLess(dist(legend['ambient'].rgb, AMBIENT_RGB), 20)
        self.assertLess(dist(legend['target'].rgb, TARGET_RGB), 20)

    def test_pale_ambient_found_and_target_flat(self):
        area = dg.default_search_area(self.lay, self.img.shape[1], self.img.shape[0])
        cands = dg.colour_candidates(self.img, area)
        others = [c.rgb for c in cands]
        found = {}
        for name, rgb in (('ambient', AMBIENT_RGB), ('internal', INTERNAL_RGB), ('target', TARGET_RGB)):
            c = min(cands, key=lambda c: dist(c.rgb, rgb))
            self.assertLess(dist(c.rgb, rgb), 40, name)
            found[name] = dg.is_flat(dg.trace_line(self.img, area, c.rgb, self.lay.background, others=others),
                                     area.bottom - area.top)
        self.assertEqual(found, {'ambient': False, 'internal': False, 'target': True})

    def check_table(self, img):
        df = pipeline(img)
        self.assertEqual(df['Timestamp'].iloc[0], '01/06/2026 18:00')
        end = T0 + timedelta(hours=PROBE_END)
        last = datetime.strptime(df['Timestamp'].iloc[-1], dg.TIME_FORMAT)
        self.assertLess(abs((last - end).total_seconds()), 480, 'table ends when the cook ended (within ~3 columns)')
        h = np.arange(len(df)) / 60
        for col, fn in (('Ambient temperature (°C)', probe_ambient), ('Meat temperature (°C)', probe_internal)):
            v = df[col].to_numpy()
            # leave out minutes where the curve jumps (lid openings, steps): there the value
            # depends on which pixel column a minute falls in
            calm = ~np.isnan(v) & (h < PROBE_END - 0.1) & (np.abs(fn(h + 0.05) - fn(h - 0.05)) <= 1.5)
            err = np.abs(v[calm] - fn(h[calm]))
            self.assertGreater(calm.sum(), 900)
            self.assertLess(float(err.mean()), 0.3, col)
            self.assertLess(float(np.percentile(err, 95)), 0.8, col)

    def test_table_png(self):
        self.check_table(self.img)

    def test_table_jpeg(self):
        self.check_table(jpeg(self.ex.image))

    def test_table_small_screenshot(self):
        self.check_table(np.asarray(make_probe_example(582, 730).image))


@unittest.skipUnless(ct.available(), 'Tesseract is not installed')
class ClockChart(unittest.TestCase):
    def test_clock_labels_past_midnight(self):
        for dark in (False, True):
            ex = make_example(dark=dark)
            img = np.asarray(ex.image)
            lay = dg.detect_layout(img)
            x = ct.read_time_axis(img, lay)
            self.assertEqual(x.kind, 'clock')
            self.assertEqual(x.used[0].text, '18:00')
            self.assertAlmostEqual(x.used[-1].value, 28.0)           # 04:00 the next day
            self.assertAlmostEqual(float(x.value(ex.plot_left)), 18.0, delta=0.03)
            y = ct.read_temperature_axis(img, lay)
            self.assertAlmostEqual(float(y.value(ex.plot_top)), 150, delta=0.3)
            legend = {e.role for e in ct.read_legend(img, lay)}
            self.assertEqual(legend, {'ambient', 'meat'})


class Parsing(unittest.TestCase):
    def test_time_values(self):
        self.assertEqual(ct._time_value('4h'), ('elapsed', 4.0))
        self.assertEqual(ct._time_value('1h30'), ('elapsed', 1.5))
        self.assertEqual(ct._time_value('90m'), ('elapsed', 1.5))
        self.assertEqual(ct._time_value('18:00'), ('clock', 1080))
        self.assertEqual(ct._time_value('7'), ('number', 7.0))
        self.assertIsNone(ct._time_value('25:00'))

    def test_roles_tolerate_misreads(self):
        self.assertEqual(ct._role('Inlernal'), 'meat')
        self.assertEqual(ct._role('Targel'), 'target')
        self.assertEqual(ct._role('Ambient'), 'ambient')
        self.assertEqual(ct._role('Pit'), 'ambient')
        self.assertIsNone(ct._role('Elapsed'))
        self.assertIsNone(ct._role('Chart'))

    def test_fit_drops_misread_label(self):
        # rows 0..300, labels 150..0; the 100 is misread as 6
        cands = [(0, 150, 0), (50, 125, 1), (100, 6, 2), (150, 75, 3), (200, 50, 4), (250, 25, 5), (300, 0, 6)]
        slope, intercept, chosen, resid = ct._fit(cands, 7, 0.6)
        self.assertNotIn(2, chosen)
        self.assertAlmostEqual(slope, -0.5)
        self.assertAlmostEqual(intercept, 150)


if __name__ == '__main__':
    unittest.main()
