#!/usr/bin/env python3
"""Page-level OMR comparison, never include PDF bytes in public artifacts."""
from __future__ import annotations
import json, subprocess, sys, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

def run(args, timeout=250):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                     text=True,errors="replace",timeout=timeout)
    if p.returncode:
        print(p.stdout[-5000:])
        raise RuntimeError(f"{args[0]} returned {p.returncode}")
    return p.stdout

def read_mxl(path):
    with zipfile.ZipFile(path) as z:
        name=next((name for name in z.namelist()
                   if name.endswith((".musicxml",".xml"))
                   and not name.startswith("META-INF/")),None)
        if not name:raise ValueError("No XML inside .mxl")
        return z.read(name)

def report(xml):
    root=ET.fromstring(xml)
    names={p.get("id"):p.findtext("part-name")
           for p in root.findall("./part-list/score-part")}
    parts=root.findall("part")
    return {"measures":max((len(p.findall("measure")) for p in parts),default=0),
            "pitched_notes":sum(len(p.findall(".//note/pitch")) for p in parts),
            "parts":[{"name":names.get(p.get("id")),
                      "notes":len(p.findall(".//note/pitch")),
                      "measures":len(p.findall("measure"))} for p in parts]}

def main(pdf,exe,out):
    pdf=Path(pdf).resolve();exe=Path(exe).resolve();out=Path(out).resolve()
    pages=out/"pages";pages.mkdir(parents=True,exist_ok=True)
    run(["pdfseparate",str(pdf),str(pages/"page-%02d.pdf")],timeout=90)
    sources=sorted(pages.glob("page-*.pdf"))
    if not 1<=len(sources)<=15:raise ValueError("Unexpected PDF page count")
    results={"input":pdf.name,"pages":[]}
    for index,source in enumerate(sources,start=1):
        destination=out/"native"/f"page-{index:02d}";destination.mkdir(parents=True,exist_ok=True)
        print(f"Page {index} of {len(sources)}",flush=True)
        try:
            run([str(exe),"-batch","-transcribe","-export","-output",
                 str(destination),"--",str(source)],timeout=290)
            candidates=sorted(destination.rglob("*.mxl"))
            if not candidates:raise ValueError("No .mxl exported")
            xml=read_mxl(candidates[0]);stats=report(xml)
            artifact=out/"raw-pages"/f"page-{index:02d}.musicxml"
            artifact.parent.mkdir(parents=True,exist_ok=True)
            artifact.write_bytes(xml)
            row={"page":index,**stats}
        except (RuntimeError,ValueError,subprocess.TimeoutExpired) as e:
            row={"page":index,"error":str(e)}
        results["pages"].append(row);print(json.dumps(row),flush=True)
    results["total_measures"]=sum(p.get("measures",0) for p in results["pages"])
    results["total_pitched_notes"]=sum(p.get("pitched_notes",0) for p in results["pages"])
    (out/"page-coverage-report.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    print("PAGE-LEVEL RESULT:",results["total_measures"],"measures,",
          results["total_pitched_notes"],"notes",flush=True)

if __name__=="__main__":main(*sys.argv[1:4])
