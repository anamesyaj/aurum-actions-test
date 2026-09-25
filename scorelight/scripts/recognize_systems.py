#!/usr/bin/env python3
"""Scan each complete piano grand-staff system separately, stitch complete MusicXML.

Unlike naive whole-document OMR, each system preserves its own brace/staff
relationship. This only emits a combined score if every system passes checks.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from PIL import Image
from evaluate_systems import locate, uncompress

def command(argv,timeout):
    p=subprocess.run(argv,capture_output=True,text=True,errors="replace",timeout=timeout)
    if p.returncode:
        print(p.stdout[-2200:]+"\n"+p.stderr[-500:],flush=True)
        raise RuntimeError(f"{argv[0]} returned {p.returncode}")

def parts_and_notes(xml):
    root=ET.fromstring(xml)
    parts=root.findall("part")
    return root,parts,sum(len(p.findall(".//note/pitch")) for p in parts)

def insert_metadata(root,title,composer,bpm):
    if title:
        work=root.find("work")
        if work is None:
            work=ET.Element("work");root.insert(0,work)
        t=work.find("work-title")
        if t is None:t=ET.SubElement(work,"work-title")
        t.text=title
        movement=root.find("movement-title")
        if movement is None:
            movement=ET.Element("movement-title")
            root.insert(list(root).index(work)+1,movement)
        movement.text=title
    if composer:
        identification=root.find("identification")
        if identification is None:
            identification=ET.Element("identification")
            listing=root.find("part-list")
            root.insert(list(root).index(listing) if listing is not None else 0,identification)
        creator=next((c for c in identification.findall("creator")
                      if c.get("type")=="composer"),None)
        if creator is None:creator=ET.SubElement(identification,"creator",{"type":"composer"})
        creator.text=composer
    if bpm is not None:
        if not 20<=bpm<=250:raise ValueError("Tempo must be 20–250 BPM")
        if not root.findall(".//direction/sound[@tempo]"):
            first=root.find("./part/measure")
            if first is not None:
                direction=ET.Element("direction",{"placement":"above"})
                dt=ET.SubElement(direction,"direction-type")
                mark=ET.SubElement(dt,"metronome")
                ET.SubElement(mark,"beat-unit").text="quarter"
                ET.SubElement(mark,"per-minute").text=str(bpm)
                ET.SubElement(direction,"sound",{"tempo":str(bpm)})
                attrs=first.find("attributes")
                first.insert(list(first).index(attrs)+1 if attrs is not None else 0,direction)

def process(pdf,exe,out,title="",composer="",bpm=None,min_measures=0):
    pdf=pdf.resolve();exe=exe.resolve();out=out.resolve()
    raster=out/"raster";raster.mkdir(parents=True,exist_ok=True)
    command(["pdftoppm","-r","200","-gray","-png",str(pdf),str(raster/"page")],150)
    pages=sorted(raster.glob("page-*.png"),
                 key=lambda p:int(re.findall(r"\d+",p.stem)[-1]))
    if not 1<=len(pages)<=15:raise ValueError("Only 1–15 scanned pages are supported")
    systems=[]
    for pi,page in enumerate(pages,start=1):
        gray=np.array(Image.open(page).convert("L"))
        paired=locate(gray)
        if not 1<=len(paired)<=7:raise ValueError("Ambiguous system count")
        for si,(upper,lower) in enumerate(paired,start=1):
            top=max(0,upper-82);bottom=min(gray.shape[0],lower+66)
            if si>1:top=max(top,paired[si-2][1]+38)
            if si<len(paired):bottom=min(bottom,paired[si][0]-37)
            if bottom-top<190:raise ValueError("Staff crop too short")
            crop=out/"crops"/f"page-{pi:02d}-system-{si:02d}.png"
            crop.parent.mkdir(parents=True,exist_ok=True)
            Image.fromarray(gray[top:bottom,:]).save(crop,dpi=(200,200))
            systems.append((pi,si,crop))
    if len(systems)>65:raise ValueError("Too many systems for one run")
    report={
        "method":"grand-staff-system-crop-v1",
        "source_pages":len(pages),"detected_systems":len(systems),
        "systems":[],
        "warnings":[
            "Not guaranteed note-accurate: review all pitches, rests, durations and key signatures against the original PDF.",
            "Ties and slurs across isolated system boundaries may require manual correction."
        ]
    }
    combined=None;target_part=None;count=0;notes=0
    for index,(pi,si,crop) in enumerate(systems,start=1):
        native=out/"native"/f"p{pi:02d}s{si:02d}";native.mkdir(parents=True,exist_ok=True)
        command([str(exe),"-batch","-transcribe","-export",
                 "-output",str(native),"--",str(crop)],230)
        candidates=sorted(native.rglob("*.mxl"))
        if len(candidates)!=1:
            raise ValueError(f"Page {pi}, system {si}: cannot locate unique Audiveris export")
        root,parts,pitches=parts_and_notes(uncompress(candidates[0]))
        if len(parts)!=1 or pitches<1:
            raise ValueError(f"Page {pi}, system {si}: score has {len(parts)} parts and {pitches} notes")
        staves=parts[0].findtext("./measure/attributes/staves")
        if staves!="2":
            clefs={c.get("number") for c in parts[0].findall("./measure/attributes/clef")}
            note_staves={v.text for v in parts[0].findall(".//note/staff")}
            if not ({"1","2"}<=clefs or {"1","2"}<=note_staves):
                raise ValueError(f"Page {pi}, system {si}: two-staff piano was not identified")
        measures=parts[0].findall("measure")
        if not measures:raise ValueError(f"Page {pi}, system {si}: missing measures")
        if combined is None:
            combined=root;target_part=parts[0]
        for m in measures:
            count+=1
            m.set("number",str(count))
            if index>1:
                m.attrib.pop("implicit",None)
                target_part.append(m)
        notes+=pitches
        record={"page":pi,"system":si,"measures":len(measures),"notes":pitches}
        report["systems"].append(record)
        print(f"System {index}/{len(systems)}: page {pi}, system {si}, {len(measures)} bars, {pitches} notes",flush=True)
    if combined is None or target_part is None:raise ValueError("No recognized systems")
    insert_metadata(combined,title,composer,bpm)
    content=ET.tostring(combined,encoding="utf-8",xml_declaration=True)
    _,parts,actual=parts_and_notes(content)
    if len(parts)!=1 or len(parts[0].findall("measure"))!=count or actual!=notes:
        raise RuntimeError("MusicXML stitching changed the number of recognized notes or measures")
    if count<min_measures:
        raise ValueError(f"Only {count} bars recognized, below requested minimum {min_measures}")
    output=out/"enhanced.musicxml";output.write_bytes(content)
    report.update({"completed":True,"enhanced_measures":count,"enhanced_pitched_notes":notes,"tempo_override":bpm})
    (out/"system-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(f"ENHANCED COMPLETE: {count} measures, {notes} recognized pitches",flush=True)
    return report

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("pdf",type=Path);ap.add_argument("audiveris",type=Path);ap.add_argument("output",type=Path)
    ap.add_argument("--title",default="");ap.add_argument("--composer",default="")
    ap.add_argument("--tempo",type=int);ap.add_argument("--min-measures",type=int,default=0)
    args=ap.parse_args()
    process(args.pdf,args.audiveris,args.output,title=args.title,composer=args.composer,
            bpm=args.tempo,min_measures=args.min_measures)
