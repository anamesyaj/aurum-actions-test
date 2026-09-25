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
import urllib.request
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



def official_public_test_pdf() -> Path:
    """Download Audiveris's own public example onto the ephemeral runner only."""
    url = ("https://raw.githubusercontent.com/Audiveris/audiveris/master/"
           "data/examples/Dichterliebe01.pdf")
    destination = INPUT / "audiveris-public-demo.pdf"
    print("Downloading official Audiveris example for an end-to-end test…")
    with urllib.request.urlopen(url, timeout=40) as response:
        data = response.read(700_000)
    if not data.lstrip().startswith(b"%PDF-") or len(data) > 600_000:
        raise RuntimeError("Audiveris example download is not a small valid PDF.")
    destination.write_bytes(data)
    return pdf_path("scorelight/input/audiveris-public-demo.pdf")


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


def musicxml_coverage(raw: bytes) -> dict[str, int]:
    """Diagnostic coverage only; note counts are NOT an accuracy percentage."""
    root = ET.fromstring(raw)
    if root.tag.rsplit("}", 1)[-1] != "score-partwise":
        raise ValueError("Not partwise MusicXML")
    parts = root.findall("part")
    return {
        "parts": len(parts),
        "measures": max((len(p.findall("measure")) for p in parts), default=0),
        "pitched_notes": sum(len(p.findall(".//note/pitch")) for p in parts),
    }


def enhanced_covers_baseline(baseline: dict, enhanced: dict) -> bool:
    """Reject any proposed reconstruction that loses recognized coverage."""
    return (
        enhanced["parts"] == 1
        and enhanced["measures"] >= baseline["measures"]
        and enhanced["pitched_notes"] >= baseline["pitched_notes"]
        and enhanced["measures"] > 0
    )


def convert_pdf(
    source: Path, audiveris: Path, out: Path, enhance: bool = True
) -> tuple[list[str], dict]:

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
    baseline_xml = []
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
        baseline_xml.append(raw)
        results.append(name)
        print("Ready for ScoreLight: " + name, flush=True)
    if not results:
        raise RuntimeError("The exported file did not contain readable partwise MusicXML.")
    baseline = {
        "parts": sum(musicxml_coverage(xml)["parts"] for xml in baseline_xml),
        "measures": max((musicxml_coverage(xml)["measures"] for xml in baseline_xml), default=0),
        "pitched_notes": sum(musicxml_coverage(xml)["pitched_notes"] for xml in baseline_xml),
    }
    quality = {
        "method": "standard Audiveris",
        "baseline": baseline,
        "preferred_musicxml": results[0],
        "enhanced": None,
        "warnings": [
            "Automatic optical music recognition is not note-accurate by guarantee; "
            "compare every page with the PDF."
        ],
    }
    if enhance:
        try:
            from recognize_systems import process
            improved_dir = out / "enhancement" / source.stem
            improved_report = process(source, audiveris, improved_dir)
            candidate = improved_dir / "enhanced.musicxml"
            enhanced = musicxml_coverage(candidate.read_bytes())
            # Refuse to silently make things worse even when the advanced OCR succeeded.
            if not enhanced_covers_baseline(baseline, enhanced):
                raise ValueError(
                    f"Enhanced scan failed coverage gate: {enhanced} vs {baseline}."
                )
            safe = re.sub("[^a-zA-Z0-9_-]+", "-", source.stem).strip("-")[:60] or "score"
            better_name = safe + "-ENHANCED-REVIEW.musicxml"
            (out / "musicxml" / better_name).write_bytes(candidate.read_bytes())
            quality.update({
                "method": "system-wise two-staff reconstruction",
                "enhanced": enhanced,
                "preferred_musicxml": better_name,
                "system_report": {
                    "source_pages": improved_report["source_pages"],
                    "detected_systems": improved_report["detected_systems"],
                },
            })
            quality["warnings"].extend(improved_report["warnings"])
            results.insert(0, better_name)
            print(
                f"ENHANCED PDF RESULT: {enhanced['measures']} measures, "
                f"{enhanced['pitched_notes']} pitches. Still requires note review.",
                flush=True,
            )
        except (ImportError, OSError, ValueError, RuntimeError,
                subprocess.TimeoutExpired) as exc:
            quality["warnings"].append(
                "Enhanced piano recognition unavailable or failed validation: "
                + str(exc)[:320] + "; standard Audiveris output preserved."
            )
            print("Enhanced piano mode skipped; baseline MusicXML retained: "
                  + str(exc)[:300], flush=True)
    return results, quality


def main() -> int:
    parser = argparse.ArgumentParser(description="Public-runner sheet-music converter")
    parser.add_argument("--audiveris", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--event", choices=["push", "manual"], required=True)
    parser.add_argument("--path", default="")
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="")
    parser.add_argument("--test-install", action="store_true")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--test-conversion", action="store_true")
    parser.add_argument("--test-conversion-if-empty", action="store_true")
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
    if args.test_conversion:
        selected = [official_public_test_pdf()]
    elif args.path:
        selected = [pdf_path(args.path)]
    elif args.event == "push":
        selected = new_pdfs(args.before, args.after)
        if not selected and args.test_conversion_if_empty:
            selected = [official_public_test_pdf()]
    else:
        raise ValueError("Manual run: provide pdf_path or select a test.")
    if not selected:
        if args.event == "push":
            print("No changed PDFs; Audiveris installation check passed.")
            return 0
        raise ValueError("No score PDF selected.")
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
        outputs, quality = convert_pdf(
            source, args.audiveris, args.output, enhance=not args.baseline_only,
        )
        manifest["converted"].append({
            "pdf": source.name,
            "musicxml": outputs,
            "preferred_musicxml": quality["preferred_musicxml"],
            "quality": quality,
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
