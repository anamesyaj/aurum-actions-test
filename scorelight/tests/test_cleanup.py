"""Test the two-hour ScoreLight PDF retention cutoff without deleting data."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "maintenance" / "cleanup.py"
SPEC = importlib.util.spec_from_file_location("scorelight_cleanup", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
NOW = 1_700_000_000

def git(root, *args, age=None):
    env = os.environ.copy()
    if age is not None:
        env["GIT_AUTHOR_DATE"] = f"@{NOW-age} +0000"
        env["GIT_COMMITTER_DATE"] = f"@{NOW-age} +0000"
    subprocess.run(["git", *args], cwd=root, env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

class RetentionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="scorelight-cleanup-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.name", "ScoreLight Test")
        git(self.root, "config", "user.email", "test@example.invalid")
        self.folder = self.root / "scorelight" / "input"
        self.folder.mkdir(parents=True)
        (self.folder / "README.md").write_text("Keep this file.")
        (self.folder / "old score.pdf").write_bytes(b"%PDF-1.4 older")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "old file", age=7200)
        (self.folder / "fresh.pdf").write_bytes(b"%PDF-1.4 new")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "fresh file", age=7199)
        (self.folder / "not-tracked.pdf").write_bytes(b"%PDF-1.4 untracked")

    def test_two_hour_threshold_and_scope(self):
        found = MODULE.expired_pdfs(self.root, now=NOW)
        self.assertEqual([item["path"] for item in found],
                         ["scorelight/input/old score.pdf"])

    def test_no_file_deleted_before_two_hours(self):
        self.assertEqual(MODULE.expired_pdfs(self.root, now=NOW-1), [])

    def test_cannot_shorten_retention(self):
        with self.assertRaises(ValueError):
            MODULE.expired_pdfs(self.root, now=NOW, min_age=7199)

    def test_result_pair_cleaned_only_after_24_hours(self):
        folder=self.root / "scorelight" / "results"
        folder.mkdir(parents=True)
        uid="pl-"+"a"*32
        (folder/(uid+".musicxml")).write_text("<score-partwise/>")
        (folder/(uid+".json")).write_text('{"status":"ready"}')
        (folder/"README.md").write_text("Keep this")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "old published results", age=86400)
        self.assertEqual(len(MODULE.expired_results(self.root,now=NOW-1)),0)
        found=MODULE.expired_results(self.root,now=NOW)
        self.assertEqual([e["path"] for e in found],[
            "scorelight/results/"+uid+".json",
            "scorelight/results/"+uid+".musicxml",
        ])

    def test_updated_pdf_gets_fresh_retention(self):
        (self.folder / "old score.pdf").write_bytes(b"%PDF-1.4 updated")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "update old file", age=100)
        self.assertEqual(MODULE.expired_pdfs(self.root, now=NOW), [])

if __name__ == "__main__":
    unittest.main()
