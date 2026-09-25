"""Automated result publication only includes validated, server-named jobs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_result.py"
SPEC = importlib.util.spec_from_file_location("publish_result", SCRIPT)
PUBLISH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLISH)
IDENTIFIER = "pl-" + "a" * 32

def fixture(root, pdfname=IDENTIFIER+".pdf", best="correct.musicxml"):
    music = root/"musicxml"
    music.mkdir(parents=True)
    (music/"correct.musicxml").write_bytes(b'<?xml version="1.0"?><score-partwise><part-list/></score-partwise>')
    (music/"conversion-report.json").write_text(json.dumps({
        "converted":[{
            "pdf":pdfname,
            "musicxml":["correct.musicxml"],
            "preferred_musicxml":best,
            "quality":{"method":"system-wise two-staff reconstruction",
                       "enhanced":{"measures":68,"pitched_notes":1129},
                       "warnings":["Compare against the original PDF."]},
        }]
    }),encoding="utf-8")

class PublisherTests(unittest.TestCase):
    def test_only_automated_id_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root)
            got=PUBLISH.collect(root,root/"public")
            self.assertEqual(got,[IDENTIFIER])
            data=json.loads((root/"public"/(IDENTIFIER+".json")).read_text())
            self.assertEqual(data["pitchedNotes"],1129)
            self.assertTrue(data["enhanced"])
            self.assertTrue((root/"public"/(IDENTIFIER+".musicxml")).is_file())
    def test_manual_pdf_never_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root,pdfname="my-sheet.pdf")
            self.assertEqual(PUBLISH.collect(root,root/"public"),[])
            self.assertFalse((root/"public").exists())
    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            fixture(root,best="../bad.musicxml")
            with self.assertRaises(ValueError):
                PUBLISH.collect(root,root/"public")
if __name__=="__main__":
    unittest.main()
