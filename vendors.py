"""Known thermometer apps ("vendors") and what the general chart reading cannot know.

The app reads any chart without a profile. A profile only adds what the
general reading cannot be sure of: which line colour is which (ambient,
meat, target), and how to recognise the app from the words on its screen.

To add an app: copy one entry, list a few words that are always on its
screen (in lower case) and the colours of its lines.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Vendor:
    key: str
    name: str
    words: tuple            # words or phrases always on the app's screen (lower case)
    min_words: int          # how many of them must be found to recognise the app
    lines: dict = field(default_factory=dict)   # role ('ambient', 'meat', 'target') -> line colour (r, g, b)
    note: str = ''          # shown in the app once the vendor is recognised
    kind: dict = field(default_factory=dict)    # role -> 'setpoint' (averaged/set value) or 'instant' reading


VENDORS = (
    Vendor('meater', 'Meater',
           words=('cook summary', 'rate your cook', 'cook started', 'total duration', 'meater', 'usda'),
           min_words=2,
           lines={'ambient': (15, 205, 69),      # green
                  'meat': (201, 11, 201),        # magenta
                  'target': (84, 166, 193)},     # blue dotted target line
           note='Start date and time are read from "Cook Started" under the chart; "Total Duration" '
                'checks the end.'),
    Vendor('typhur', 'Typhur',
           words=('cook again', 'target temp', 'cooking time', 'peak temp', 'elapsed', 'typhur'),
           min_words=2,
           lines={'meat': (250, 58, 55),         # red "Internal"
                  'ambient': (155, 165, 250),    # lavender "Ambient"
                  'target': (221, 85, 253)},     # purple flat "Target"
           note='The screen shows the date and the cooking time but no start time: set the start time.'),
    # Smoque before the general Weber entry: its screen also says "Weber", so it scores higher
    Vendor('weber_smoque', 'Weber Smoque XL',
           words=('smoque', 'weber'),
           min_words=2,
           lines={'ambient': (234, 54, 14)},     # the cooker line
           kind={'ambient': 'setpoint'},
           note='The flat, stepped line is the Smoque\'s setpoint, an averaged cooker reading, not the '
                'instant temperature. Date, start and end time are read from the header.'),
    Vendor('weber', 'Weber (gas grill / Weber Connect)',
           words=('weber', 'igrill', 'weber connect', 'genesis', 'spirit'),
           min_words=1,
           lines={'ambient': (234, 54, 14)},     # the cooker or probe line
           kind={'ambient': 'instant'},
           note='The wiggly line is the instant temperature from the grill or the Weber Connect probe.'),
)

BY_KEY = {v.key: v for v in VENDORS}


def detect(text: str) -> Vendor | None:
    """The app whose screen words appear in the text (None if no app is clearly recognised)."""
    t = re.sub(r'\s+', ' ', text.lower())
    best, best_hits = None, 0
    for v in VENDORS:
        hits = sum(1 for w in v.words if w in t)
        if hits >= v.min_words and hits > best_hits:
            best, best_hits = v, hits
    return best


def _dist(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** .5


def roles_for(vendor: Vendor | None, candidates, max_dist: float = 75) -> dict:
    """{candidate index: role} for the line colours found in the chart.

    Each role takes the closest candidate colour (any of its shades), if it is
    close enough; a candidate gets at most one role.
    """
    if vendor is None:
        return {}
    pairs = []
    for role, ref in vendor.lines.items():
        for i, c in enumerate(candidates):
            d = min(_dist(ref, shade) for shade in getattr(c, 'shades', (c.rgb,)))
            if d <= max_dist:
                pairs.append((d, i, role))
    out, used = {}, set()
    for d, i, role in sorted(pairs):
        if i not in out and role not in used:
            out[i] = role
            used.add(role)
    return out
