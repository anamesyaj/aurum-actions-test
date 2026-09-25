#!/usr/bin/env python3
"""List Git-tracked ScoreLight PDF uploads aged at least two hours.

A GitHub Actions workflow uses this list to remove files from main.
Public Git history is unaffected by removal from the current branch.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import subprocess
import sys
import time

INPUT = Path("scorelight/input")
MIN_AGE_SECONDS = 7200

def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True).stdout

def expired_pdfs(repo: Path, now: int | None = None,
                 min_age: int = MIN_AGE_SECONDS) -> list[dict]:
    if min_age < MIN_AGE_SECONDS:
        raise ValueError("Cleanup cannot remove files younger than two hours.")
    repo = repo.resolve()
    input_dir = (repo / INPUT).resolve()
    now = int(time.time()) if now is None else int(now)
    tracked = git(repo, "ls-files", "-z", "--", str(INPUT) + "/")
    result = []
    for raw in tracked.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8", "surrogateescape")
        relative = Path(name)
        file = repo / relative
        if (relative.parent != INPUT or relative.suffix.lower() != ".pdf"
                or file.is_symlink() or not file.is_file()
                or file.resolve().parent != input_dir):
            continue
        timestamp = git(repo, "log", "-1", "--format=%ct", "--", name).strip()
        if not timestamp:
            continue
        age = now - int(timestamp)
        if age >= min_age:
            result.append({"path": name, "age_seconds": age})
    return sorted(result, key=lambda item: item["path"])

def expired_results(repo: Path, now: int | None = None) -> list[dict]:
    """Remove temporary public branch files after 24h; Git history stays public."""
    root = repo.resolve()
    directory = root / "scorelight" / "results"
    now = int(time.time()) if now is None else int(now)
    retained_seconds = 24 * 60 * 60
    tracked = git(root, "ls-files", "-z", "--", "scorelight/results/")
    found = []
    for raw in tracked.split(b"\\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8", "surrogateescape"))
        if relative.parent != Path("scorelight/results") or not re.fullmatch(
            r"pl-[0-9a-f]{32}\\.(musicxml|json)", relative.name
        ):
            continue
        file = root / relative
        if file.is_symlink() or not file.is_file() or file.resolve().parent != directory:
            continue
        stamp = git(root, "log", "-1", "--format=%ct", "--", str(relative)).strip()
        if stamp and now-int(stamp) >= retained_seconds:
            found.append({"path": str(relative), "age_seconds": now-int(stamp)})
    return sorted(found, key=lambda item: item["path"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pdfs = expired_pdfs(args.repo)
    results = expired_results(args.repo)
    found = pdfs + results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
    print(f"Eligible ScoreLight PDFs >=2h: {len(pdfs)}; temporary MusicXML/report files >=24h: {len(results)}")
    for item in found:
        print("  " + item["path"])
    print("Git history is still public after files are removed from main.")

if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
