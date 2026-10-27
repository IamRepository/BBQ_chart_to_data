"""Tests for reading labels and legends, on charts with known values.

Run: python -m unittest test_chart_text   (needs Tesseract; skipped without it)
"""
import io
import unittest
from datetime import datetime, timedelta

import numpy as np

import chart_text as ct
import digitizer as dg
import vendors
from example_chart import (MEATER_AMBIENT_RGB, MEATER_DURATION, MEATER_MEAT_RGB, MEATER_START, make_meater_example,
                           meater_ambient, meater_meat, WEBER_END, WEBER_RGB, WEBER_START, make_weber_example, weber_temp, AMBIENT_RGB, INTERNAL_RGB, PROBE_END, PROBE_HOURS, PROBE_TARGET, PROBE_YMAX,
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
    others = [sh for c in cands for sh in c.shades]
    last = x.used[-1].value
    lo, hi = y.used[0], y.used[-1]
    cal = dg.Calibration(lo.pos, float(y.value(lo.pos)), hi.pos, float(y.value(hi.pos)),
                         float(x.pos(0)), T0, float(x.pos(last)), T0 + timedelta(hours=last))
    series = {}
    for role, label in (('ambient', 'Ambient temperature'), ('meat', 'Meat temperature')):
        c = min(cands, key=lambda c: min(dist(sh, legend[role].rgb) for sh in c.shades))
        series[label] = dg.series_in_units(dg.trace_line(img, area, c.rgb, lay.background, others=others,
                                                         shades=c.variants), cal)
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
        others = [sh for c in cands for sh in c.shades]
        found = {}
        for name, rgb in (('ambient', AMBIENT_RGB), ('internal', INTERNAL_RGB), ('target', TARGET_RGB)):
            c = min(cands, key=lambda c: dist(c.rgb, rgb))
            self.assertLess(dist(c.rgb, rgb), 40, name)
            found[name] = dg.is_flat(dg.trace_line(self.img, area, c.rgb, self.lay.background, others=others,
                                                   shades=c.variants), area.bottom - area.top)
        self.assertEqual(found, {'ambient': False, 'internal': False, 'target': True})

    def test_ambient_shaded_part_is_one_line(self):
        """Inside the translucent shading under the meat line the ambient line looks a
        different colour; it must still be traced as the same line, to the end of the cook."""
        area = dg.default_search_area(self.lay, self.img.shape[1], self.img.shape[0])
        cands = dg.colour_candidates(self.img, area)
        amb = min(cands, key=lambda c: dist(c.rgb, AMBIENT_RGB))
        self.assertGreaterEqual(len(amb.variants), 1, 'the tinted shade is joined to the ambient line')
        self.assertEqual(sum(min(dist(sh, AMBIENT_RGB) for sh in c.shades) < 40 for c in cands), 1)
        tr = dg.trace_line(self.img, area, amb.rgb, self.lay.background,
                           others=[sh for c in cands for sh in c.shades], shades=amb.variants)
        h = self.ex.hours(tr.x[~np.isnan(tr.y)])
        self.assertLess(h.min(), 0.1)
        self.assertGreater(h.max(), PROBE_END - 0.1)
        self.assertGreater(tr.columns_found, 0.97)

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
            self.assertGreater(np.isfinite(v[h > 12]).mean(), 0.97, col + ': values after the 10 h drop')
            self.assertLess(float(err.mean()), 0.3, col)
            self.assertLess(float(np.percentile(err, 95)), 0.8, col)

    def test_table_png(self):
        self.check_table(self.img)

    def test_peak_marker_not_read_as_temperature(self):
        """The red triangle on the meat line at its peak must not raise the peak."""
        df = pipeline(self.img)
        self.assertLess(df['Meat temperature (°C)'].max(), 92.4 + 0.6)
        self.assertGreater(df['Meat temperature (°C)'].max(), 92.4 - 0.6)

    def test_no_date_on_replica(self):
        self.assertIsNone(ct.read_date(self.img, self.lay))
        self.assertEqual(ct.read_start(self.img, self.lay), (None, None))

    def test_start_date_and_time_read_when_shown(self):
        from datetime import date, time
        for title, expected in (('Jun 21, 2026 18:05', (date(2026, 6, 21), time(18, 5))),
                                ('Start time 6:05 PM', (None, time(18, 5)))):
            for size in ((1080, 1350), (582, 730)):
                img = np.asarray(make_probe_example(*size, title=title).image)
                self.assertEqual(ct.read_start(img, dg.detect_layout(img)), expected, (title, size))

    def test_table_jpeg(self):
        self.check_table(jpeg(self.ex.image))

    def test_table_small_screenshot(self):
        self.check_table(np.asarray(make_probe_example(582, 730).image))


@unittest.skipUnless(ct.available(), 'Tesseract is not installed')
class ChartWithDataGap(unittest.TestCase):
    """The app recorded nothing from 10 h to 22.35 h and joins the gap with dotted lines;
    a short stretch of both lines follows at the end of the cook."""

    def test_gap_filled_on_a_straight_line(self):
        start, end = 10.0, 22.35
        ex = make_probe_example(gap=(start, end))
        df = pipeline(np.asarray(ex.image))
        last = datetime.strptime(df['Timestamp'].iloc[-1], dg.TIME_FORMAT)
        self.assertLess(abs((last - (T0 + timedelta(hours=PROBE_END))).total_seconds()), 480,
                        'the short stretch after the gap is traced')
        h = np.arange(len(df)) / 60
        gap = (h > start + 0.1) & (h < end - 0.1)
        for col, fn in (('Ambient temperature (°C)', probe_ambient), ('Meat temperature (°C)', probe_internal)):
            self.assertTrue(df[col][gap].isna().all(), 'nothing is read inside the gap')
            filled, mask = dg.fill_gaps(df)
            v = filled[col].to_numpy()
            self.assertTrue(np.isfinite(v[gap]).all(), col + ': gap filled')
            # on the straight line between the values either side of the gap
            line = np.interp(h[gap], [start, end], [fn(start), fn(end)])
            self.assertLess(float(np.abs(v[gap] - line).max()), 2.0, col)
            self.assertTrue(mask[col][gap].all())


@unittest.skipUnless(ct.available(), 'Tesseract is not installed')
class WeberStyleChart(unittest.TestCase):
    """Gridlines run under the temperature labels, labels sit below their gridline
    (temperature) or right of it (time), header '20 Jun 2026 - 17:40 to 03:52',
    one stepped line and a value bubble over the end of the 150° gridline."""

    @classmethod
    def setUpClass(cls):
        cls.ex = make_weber_example()
        cls.img = np.asarray(cls.ex.image)
        cls.lay = dg.detect_layout(cls.img)

    def test_plot_starts_at_the_axis_not_under_the_labels(self):
        self.assertAlmostEqual(self.lay.plot.left, 186, delta=2)
        self.assertTrue(any(abs(r - self.ex.y_of_temp(150)) < 1.5 for r in self.lay.h_lines),
                        'the 150° gridline under the line and the bubble is found')

    def test_temperature_scale(self):
        y = ct.read_temperature_axis(self.img, self.lay)
        self.assertGreaterEqual(len(y.used), 5)
        self.assertAlmostEqual(float(y.value(self.ex.y_of_temp(250))), 250, delta=0.6)
        self.assertAlmostEqual(float(y.value(self.ex.y_of_temp(0))), 0, delta=0.6)

    def test_time_labels_right_of_their_gridline(self):
        x = ct.read_time_axis(self.img, self.lay)
        self.assertEqual(x.kind, 'clock')
        self.assertEqual([l.text for l in x.used], ['20:00', '23:00', '02:00'])
        self.assertAlmostEqual(float(x.value(self.ex.x_of_hour(0))), 17 + 40 / 60, delta=2 / 60)

    def test_header_date_and_times(self):
        from datetime import date, time
        self.assertEqual(tuple(ct.read_header(self.img, self.lay)), (date(2026, 6, 20), time(17, 40), time(3, 52)))

    def test_table(self):
        lay, img = self.lay, self.img
        y, x = ct.read_temperature_axis(img, lay), ct.read_time_axis(img, lay)
        area = dg.default_search_area(lay, img.shape[1], img.shape[0])
        cands = dg.colour_candidates(img, area)
        c = min(cands, key=lambda c: dist(c.rgb, WEBER_RGB))
        tr = dg.trace_line(img, area, c.rgb, lay.background, others=[k.rgb for k in cands])
        midnight = datetime(2026, 6, 20)
        u = x.used
        cal = dg.Calibration(y.used[0].pos, float(y.value(y.used[0].pos)), y.used[-1].pos, float(y.value(y.used[-1].pos)),
                             u[0].pos, midnight + timedelta(hours=u[0].value), u[-1].pos, midnight + timedelta(hours=u[-1].value))
        df = dg.build_table({'Ambient temperature': dg.series_in_units(tr, cal)}, cal, 60, anchor=midnight)
        first = datetime.strptime(df['Timestamp'].iloc[0], dg.TIME_FORMAT)
        last = datetime.strptime(df['Timestamp'].iloc[-1], dg.TIME_FORMAT)
        self.assertLess(abs((first - WEBER_START).total_seconds()), 300)
        self.assertLess(abs((last - WEBER_END).total_seconds()), 300)
        rows = dict(zip(df['Timestamp'], df['Ambient temperature (°C)']))
        for stamp, value in (('20/06/2026 19:00', 80), ('20/06/2026 22:00', 110), ('21/06/2026 01:00', 150),
                             ('21/06/2026 03:00', 150)):
            self.assertAlmostEqual(rows[stamp], value, delta=0.6, msg=stamp)


@unittest.skipUnless(ct.available(), 'Tesseract is not installed')
class MeaterStyleChart(unittest.TestCase):
    """No legend; elapsed labels '22m' ... '1h 28m'; cook start and duration printed UNDER the chart."""

    @classmethod
    def setUpClass(cls):
        cls.ex = make_meater_example()
        cls.img = np.asarray(cls.ex.image)
        cls.lay = dg.detect_layout(cls.img)
        cls.header = ct.read_header(cls.img, cls.lay)

    def test_details_under_the_chart(self):
        from datetime import time
        h = self.header
        self.assertEqual((h.date, h.start, h.duration), (MEATER_START.date(), MEATER_START.time(), MEATER_DURATION))
        self.assertEqual(h.end, time(18, 28, 20), 'end = start + duration')

    def test_recognised_and_lines_assigned(self):
        vendor = vendors.detect(self.header.text)
        self.assertIsNotNone(vendor)
        self.assertEqual(vendor.key, 'meater')
        area = dg.default_search_area(self.lay, self.img.shape[1], self.img.shape[0])
        cands = dg.colour_candidates(self.img, area)
        roles = {r: cands[i].rgb for i, r in vendors.roles_for(vendor, cands).items()}
        self.assertLess(dist(roles['ambient'], MEATER_AMBIENT_RGB), 40)
        self.assertLess(dist(roles['meat'], MEATER_MEAT_RGB), 40)
        self.assertIn('target', roles)

    def test_elapsed_labels_with_two_words(self):
        x = ct.read_time_axis(self.img, self.lay)
        self.assertEqual([l.text for l in x.used], ['22m', '44m', '1h 6m', '1h 28m'])
        self.assertAlmostEqual(float(x.value(self.ex.x_of_hour(0))), 0, delta=0.02)

    def test_table(self):
        img, lay = self.img, self.lay
        y, x = ct.read_temperature_axis(img, lay), ct.read_time_axis(img, lay)
        self.assertAlmostEqual(float(y.value(self.ex.y_of_temp(240))), 240, delta=0.6)
        area = dg.default_search_area(lay, img.shape[1], img.shape[0])
        cands = dg.colour_candidates(img, area)
        roles = {r: i for i, r in vendors.roles_for(vendors.BY_KEY['meater'], cands).items()}
        others = [sh for c in cands for sh in c.shades]
        t0 = MEATER_START
        last = x.used[-1].value
        cal = dg.Calibration(y.used[0].pos, float(y.value(y.used[0].pos)), y.used[-1].pos, float(y.value(y.used[-1].pos)),
                             float(x.pos(0)), t0, float(x.pos(last)), t0 + timedelta(hours=last))
        series = {}
        for role, label in (('ambient', 'Ambient temperature'), ('meat', 'Meat temperature')):
            c = cands[roles[role]]
            series[label] = dg.series_in_units(dg.trace_line(img, area, c.rgb, lay.background, others=others,
                                                             shades=c.variants), cal)
        df = dg.build_table(series, cal, 60, anchor=t0, not_before=t0)
        self.assertEqual(df['Timestamp'].iloc[0], '22/11/2025 17:03')
        last_t = datetime.strptime(df['Timestamp'].iloc[-1], dg.TIME_FORMAT)
        self.assertLess(abs((last_t - (MEATER_START + MEATER_DURATION)).total_seconds()), 180)
        h = np.arange(len(df)) / 60
        for col, fn in (('Ambient temperature (°C)', meater_ambient), ('Meat temperature (°C)', meater_meat)):
            v = df[col].to_numpy()
            calm = ~np.isnan(v) & (h > 0.05) & (h < 1.35) & (np.abs(fn(h + 0.03) - fn(h - 0.03)) <= 8)
            self.assertGreater(calm.sum(), 40, col)
            self.assertLess(float(np.abs(v[calm] - fn(h[calm])).mean()), 0.8, col)


class Vendors(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(vendors.detect('Cook Summary\nRate your cook\n82° Peak').key, 'meater')
        self.assertEqual(vendors.detect('Weber Smoque XL 20 Jun 2026').key, 'weber_smoque')
        self.assertEqual(vendors.BY_KEY['weber_smoque'].kind['ambient'], 'setpoint')
        self.assertEqual(vendors.detect('Weber Genesis EX-335').key, 'weber')
        self.assertEqual(vendors.BY_KEY['weber'].kind['ambient'], 'instant')
        self.assertEqual(vendors.detect('Target Temp Cooking Time\nCook Again').key, 'typhur')
        self.assertIsNone(vendors.detect('Chart 18:00 20:00'))
        self.assertIsNone(vendors.detect('Elapsed 4h'), 'one Typhur word is not enough')

    def test_roles_by_nearest_colour(self):
        from digitizer import ColourCandidate
        cands = [ColourCandidate((200, 12, 200), 100, .9), ColourCandidate((14, 200, 70), 100, .9),
                 ColourCandidate((90, 160, 190), 50, .5), ColourCandidate((120, 120, 120), 10, .1)]
        roles = vendors.roles_for(vendors.BY_KEY['meater'], cands)
        self.assertEqual(roles, {0: 'meat', 1: 'ambient', 2: 'target'})
        self.assertEqual(vendors.roles_for(None, cands), {})


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
    def test_dates(self):
        from datetime import date
        for text in ('Jun 21, 2026', '21 June 2026', '21.06.2026', '21/06/2026', '2026-06-21', 'Sun, Jun 21, 2026'):
            self.assertEqual(ct.parse_date(text), date(2026, 6, 21), text)
        self.assertIsNone(ct.parse_date('23:39  57%'))

    def test_start_times(self):
        from datetime import time
        for text in ('Jun 21, 2026 18:05', '21.06.2026, 6:05 PM', 'Jun 21, 2026 at 6:05 pm', 'Start: 18:05',
                     'Started 6:05 PM', 'Start time 18:05'):
            self.assertEqual(ct.parse_start_time(text), time(18, 5), text)
        for text in ('Jun 21, 2026', 'Cooking Time 22hr 44min', '23:39 57%', 'Target 100°C', 'Elapsed 22hr44min'):
            self.assertIsNone(ct.parse_start_time(text), text)
        self.assertIsNone(ct.parse_date('Target Temp 100°C'))

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

    def test_align_labels_offset_from_gridlines(self):
        lines = [100.0, 200.0, 300.0, 400.0]
        # labels drawn 35 px below their gridline, one gridline missing (300)
        out = ct._align([135.0, 235.0, 335.0, 435.0], [30] * 4, [100.0, 200.0, 400.0])
        self.assertEqual(out, [100.0, 200.0, 300.0, 400.0])
        # labels centred on their gridlines stay where they are
        self.assertEqual(ct._align([100.5, 199.6, 300.2], [20] * 3, lines), [100.0, 200.0, 300.0])

    def test_label_words_joined_but_crowded_labels_kept_apart(self):
        row = np.zeros(400, bool)
        for a in (0, 58, 116, 174):                       # labels 8 px apart, text height 10
            row[a:a + 50] = True
        self.assertEqual(len(ct._label_runs(row, 10)), 4)
        row = np.zeros(600, bool)
        for a, b in ((0, 30), (150, 180), (300, 318), (330, 350), (470, 488), (500, 530)):
            row[a:b] = True                               # '22m', '44m', '1h 6m', '1h 28m'
        self.assertEqual(ct._label_runs(row, 20), [(0, 29), (150, 179), (300, 349), (470, 529)])

    def test_durations(self):
        from datetime import timedelta as td
        self.assertEqual(ct.parse_duration('Total Duration 01:25:20'), td(hours=1, minutes=25, seconds=20))
        self.assertEqual(ct.parse_duration('Target Temp Cooking Time\n100°C 22hr 44min'), td(hours=22, minutes=44))
        self.assertEqual(ct.parse_duration('Elapsed 22hr45min'), td(hours=22, minutes=45))
        self.assertIsNone(ct.parse_duration('Target 100°C Peak 85.6°C'))
        self.assertEqual(ct._elapsed_text(0.3667), '22m')
        self.assertEqual(ct._elapsed_text(1.1), '1h 6m')
        self.assertEqual(ct._elapsed_text(4.0), '4h')

    def test_time_range(self):
        from datetime import time
        self.assertEqual(ct.parse_start_time('20 Jun 2026 - 17:40 to 03:52'), time(17, 40))
        self.assertEqual(ct.parse_end_time('20 Jun 2026 - 17:40 to 03:52'), time(3, 52))
        self.assertIsNone(ct.parse_end_time('Jun 21, 2026 18:05'))

    def test_fit_drops_misread_label(self):
        # rows 0..300, labels 150..0; the 100 is misread as 6
        cands = [(0, 150, 0), (50, 125, 1), (100, 6, 2), (150, 75, 3), (200, 50, 4), (250, 25, 5), (300, 0, 6)]
        slope, intercept, chosen, resid = ct._fit(cands, 7, 0.6)
        self.assertNotIn(2, chosen)
        self.assertAlmostEqual(slope, -0.5)
        self.assertAlmostEqual(intercept, 150)


if __name__ == '__main__':
    unittest.main()
