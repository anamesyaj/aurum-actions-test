"""Verify ScoreLight enhanced-vs-baseline gate and MusicXML coverage."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "convert.py"
SPEC = importlib.util.spec_from_file_location("scorelight_convert", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

def musicxml(parts: list[list[int]]) -> bytes:
    out = ['<?xml version="1.0"?><score-partwise version="4.0">',
           '<part-list>']
    for i in range(len(parts)):
        out.append(f'<score-part id="P{i+1}"><part-name>Piano</part-name></score-part>')
    out.append('</part-list>')
    for i, pitches in enumerate(parts):
        out.append(f'<part id="P{i+1}"><measure number="1">')
        for j, pitch in enumerate(pitches):
            out.append(
                f'<note><pitch><step>C</step><octave>{pitch}</octave></pitch>'
                '<duration>1</duration></note>'
            )
        out.append('</measure></part>')
    out.append('</score-partwise>')
    return ''.join(out).encode()

class ScoreQualityTests(unittest.TestCase):
    def test_coverage_baseline(self):
        self.assertEqual(
            MODULE.musicxml_coverage(musicxml([[4,4],[3]])),
            {"parts":2,"measures":1,"pitched_notes":3},
        )

    def test_enhanced_gate_requires_single_part_and_no_lost_notes(self):
        base={"parts":3,"measures":42,"pitched_notes":757}
        good={"parts":1,"measures":68,"pitched_notes":1129}
        self.assertTrue(MODULE.enhanced_covers_baseline(base,good))
        self.assertFalse(MODULE.enhanced_covers_baseline(base,{"parts":1,"measures":68,"pitched_notes":750}))
        self.assertFalse(MODULE.enhanced_covers_baseline(base,{"parts":1,"measures":41,"pitched_notes":1129}))
        self.assertFalse(MODULE.enhanced_covers_baseline(base,{"parts":2,"measures":68,"pitched_notes":1129}))
if __name__ == "__main__":
    unittest.main()
