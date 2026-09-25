#!/usr/bin/env python3
"""Publish ONLY automated in-app ScoreLight jobs to short-lived public results.

Manual GitHub uploads keep the standard one-day Actions ZIP artifact.
Automated jobs are named pl-<32 hex>.pdf by the PuddleLoom Worker.
Publishing an output to this public repository does not make it private.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

JOB_FILE = re.compile(r"^(pl-[0-9a-f]{32})\.pdf$")
RESULTS = Path("scorelight/results")


def collect(output_root: Path, destination: Path) -> list[str]:
    report_file = output_root / "musicxml" / "conversion-report.json"
    if not report_file.is_file():
        return []
    manifest = json.loads(report_file.read_text(encoding="utf-8"))
    published = []
    for item in manifest.get("converted", []):
        match = JOB_FILE.fullmatch(item.get("pdf", ""))
        if not match:
            continue
        job_id = match.group(1)
        best = item.get("preferred_musicxml")
        if not isinstance(best, str) or Path(best).name != best:
            raise ValueError(f"Unsafe or missing preferred MusicXML filename for {job_id}")
        target = output_root / "musicxml" / best
        if not target.is_file() or target.is_symlink() or target.stat().st_size > 8_000_000:
            raise ValueError(f"Missing or invalid MusicXML for {job_id}")
        content = target.read_bytes()
        if ET.fromstring(content).tag.rsplit("}", 1)[-1] != "score-partwise":
            raise ValueError(f"Unsupported MusicXML for {job_id}")
        quality = item.get("quality", {})
        selected = quality.get("enhanced") or quality.get("baseline") or {}
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f"{job_id}.musicxml").write_bytes(content)
        public_report = {
            "jobId": job_id, "status": "ready",
            "method": quality.get("method", "Audiveris"),
            "enhanced": bool(quality.get("enhanced")),
            "measures": selected.get("measures"),
            "pitchedNotes": selected.get("pitched_notes"),
            "warnings": quality.get("warnings", []),
            "finishedAt": datetime.now(timezone.utc).isoformat(),
            "privacy": "PUBLIC_GITHUB_HISTORY",
        }
        (destination / f"{job_id}.json").write_text(
            json.dumps(public_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        published.append(job_id)
        print(f"Prepared GitHub-background ScoreLight result {job_id} ({len(content)} bytes)")
    return published


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("conversion_output", type=Path)
    parser.add_argument("--destination", type=Path, default=RESULTS)
    args = parser.parse_args()
    published = collect(args.conversion_output, args.destination)
    print(f"Ready to publish {len(published)} in-app result(s).")


if __name__ == "__main__":
    main()
