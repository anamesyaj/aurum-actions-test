#!/usr/bin/env python3
"""PuddleLoom ScoreLight: public GitHub Actions PDF to MusicXML conversion."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "scorelight" / "input"
MAX_PDF_BYTES = 15 * 1024 * 1024


def pdf_path(name: str) -> Path:
    if "\n" in name or "\r" in name:
        raise ValueError("A PDF filename cannot include line breaks.")
    selected = (ROOT / name).resolve()
    if selected.parent != INPUT.resolve():
        raise ValueError("Select a PDF directly inside scorelight/input/.")
    if selected.suffix.lower() != ".pdf" or not selected.is_file():
        raise ValueError("The requested PDF was not found in scorelight/input/.")
    if not 50 <= selected.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("PDF must be between 50 bytes and 15 MB.")
    with selected.open("rb") as stream:
        if not stream.read(1024).lstrip().startswith(b"%PDF-"):
            raise ValueError("The uploaded file has no valid PDF header.")
    return selected


def new_pdfs(before: str, after: str) -> list[Path]:
    if not re.fullmatch("[a-f0-9]{40}", before or ""):
        return []
    if not re.fullmatch("[a-f0-9]{40}", after or ""):
        return []
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AM", "-z",
         before, after, "--", "scorelight/input/"],
        cwd=ROOT, capture_output=True, check=True,
    )
    paths = []
    for encoded in result.stdout.split(b"\0"):
        if encoded and os.fsdecode(encoded).lower().endswith(".pdf"):
            paths.append(pdf_path(os.fsdecode(encoded)))
    return paths


def extract_musicxml(path: Path) -> bytes:
    if path.suffix.lower() != ".mxl":
        return path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        target = None
        if "META-INF/container.xml" in names:
            root = ET.fromstring(archive.read("META-INF/container.xml"))
            target = next((elem.attrib.get("full-path") for elem in root.iter()
                           if elem.tag.endswith("rootfile")), None)
        if not target or target not in names:
            target = next((n for n in names
                           if n.lower().endswith((".musicxml", ".xml"))
                           and not n.startswith("META-INF/")), None)
        if not target:
            raise ValueError("Audiveris's .mxl archive does not include MusicXML.")
        if archive.getinfo(target).file_size > 8_000_000:
            raise ValueError("The recognized score is larger than 8 MB.")
        return archive.read(target)


def convert_pdf(source: Path, audiveris: Path, out: Path) -> list[str]:
    internal = out / "temporary" / source.stem
    internal.mkdir(parents=True, exist_ok=True)
    command = [
        str(audiveris), "-batch", "-transcribe", "-export",
        "-output", str(internal), "--", str(source),
    ]
    print("Recognizing: " + source.name, flush=True)
    try:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True,
            errors="replace", timeout=900,
            env={**os.environ, "JAVA_TOOL_OPTIONS": "-Djava.awt.headless=true"},
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Audiveris exceeded the 15-minute conversion limit.")
    if result.returncode:
        print(result.stdout[-6000:], flush=True)
        print(result.stderr[-2000:], flush=True)
        raise RuntimeError("Audiveris could not transcribe this PDF.")
    print(result.stdout[-1200:], flush=True)
    candidates = (
        sorted(internal.rglob("*.mxl")) +
        sorted(internal.rglob("*.musicxml")) +
        sorted(internal.rglob("*.xml"))
    )
    if not candidates:
        raise RuntimeError("Audiveris did not export a MusicXML file.")
    results = []
    for i, file in enumerate(candidates, start=1):
        if "META-INF" in file.parts:
            continue
        raw = extract_musicxml(file)
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            continue
        if root.tag.rsplit("}", 1)[-1] != "score-partwise":
            continue
        safe = re.sub("[^a-zA-Z0-9_-]+", "-", source.stem).strip("-")[:60] or "score"
        if len(candidates) > 1:
            safe += "-part-" + str(i)
        name = safe + ".musicxml"
        destination = out / "musicxml" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        results.append(name)
        print("Ready for ScoreLight: " + name, flush=True)
    if not results:
        raise RuntimeError("The exported file did not contain readable partwise MusicXML.")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Public-runner sheet-music converter")
    parser.add_argument("--audiveris", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--event", choices=["push", "manual"], required=True)
    parser.add_argument("--path", default="")
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="")
    parser.add_argument("--test-install", action="store_true")
    args = parser.parse_args()
    if not args.audiveris.is_file():
        raise RuntimeError("The official Audiveris launcher is missing.")
    print("Checking installed Audiveris…", flush=True)
    check = subprocess.run(
        [str(args.audiveris), "-help"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        errors="replace", timeout=75,
        env={**os.environ, "JAVA_TOOL_OPTIONS": "-Djava.awt.headless=true"},
    )
    if check.returncode:
        print(check.stdout[-5000:])
        raise RuntimeError("Audiveris could not launch.")
    if args.test_install:
        print("Audiveris installed and launched successfully.")
        return 0
    if args.path:
        selected = [pdf_path(args.path)]
    elif args.event == "push":
        selected = new_pdfs(args.before, args.after)
    else:
        raise ValueError(
            "Manual run: enter the existing PDF path or select test_install."
        )
    if not selected:
        if args.event == "push":
            print("No new PDFs; installation smoke test passed.")
            return 0
        raise ValueError("No PDF selected.")
    if len(selected) > 4:
        raise ValueError("Convert at most four PDFs per workflow run.")
    manifest = {
        "converted": [],
        "warning": (
            "Recognition is fallible. Verify pitch, chords, tuplets, tempo, "
            "repeats and rhythm against the original PDF before rendering."
        ),
    }
    for source in selected:
        manifest["converted"].append({
            "pdf": source.name,
            "musicxml": convert_pdf(source, args.audiveris, args.output),
        })
    report = args.output / "musicxml" / "conversion-report.json"
    report.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Conversion complete. Download the MusicXML artifact from this run.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, subprocess.CalledProcessError,
            zipfile.BadZipFile) as exc:
        print("::error::" + str(exc), file=sys.stderr)
        sys.exit(1)
