#!/usr/bin/env python3
"""Detect and crop complete two-staff score systems, never individual staves."""
from pathlib import Path
import json, sys, subprocess, zipfile, xml.etree.ElementTree as ET
import numpy as np
from PIL import Image

def locate(gray):
    height,width=gray.shape
    start,end=int(width*.11),int(width*.89)
    candidates=[]
    for y in range(int(height*.055),int(height*.91)):
        dark=gray[y,start:end]<135
        diff=np.diff(np.r_[False,dark,False].astype(np.int8))
        lengths=np.flatnonzero(diff==-1)-np.flatnonzero(diff==1)
        if lengths.size and lengths.max()>max(250,(end-start)*.25):
            candidates.append(y)
    runs=[]
    for y in candidates:
        if runs and y<=runs[-1][-1]+2:runs[-1].append(y)
        else:runs.append([y])
    lines=[round(np.mean(run)) for run in runs if len(run)<=5]
    groups=[];i=0
    while i<len(lines):
        block=lines[i:i+5]
        if len(block)==5 and all(11<=block[k+1]-block[k]<=24 for k in range(4)):
            groups.append(block);i+=5
        else:i+=1
    if len(groups)<2 or len(groups)%2:
        raise ValueError(f"Unexpected {len(groups)} staves: no safe grand-staff pairs")
    pairs=[]
    for g in range(0,len(groups),2):
        upper,lower=groups[g],groups[g+1]
        if not 55<=lower[0]-upper[-1]<=190:
            raise ValueError("The two staves do not form an identifiable piano system")
        pairs.append((upper[0],lower[-1]))
    return pairs

def score_summary(raw):
    root=ET.fromstring(raw)
    parts=root.findall("./part")
    return {"measures":max((len(p.findall("measure")) for p in parts),default=0),
            "notes":sum(len(p.findall(".//note/pitch")) for p in parts),
            "parts":len(parts)}

def uncompress(path):
    with zipfile.ZipFile(path) as z:
        name=next((n for n in z.namelist()
                   if n.endswith((".musicxml",".xml")) and not n.startswith("META-INF/")),None)
        if name is None:raise ValueError("Audiveris exported empty .mxl")
        return z.read(name)

def main(pdf,exe,out,page_number):
    pdf=Path(pdf).resolve();exe=Path(exe).resolve();out=Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True);images=out/"pages";images.mkdir(exist_ok=True)
    command=["pdftoppm","-f",str(page_number),"-l",str(page_number),
             "-r","200","-gray","-png",str(pdf),str(images/"page")]
    subprocess.run(command,check=True,timeout=90,stdout=subprocess.DEVNULL)
    imagefiles=sorted(images.glob("*.png"))
    if len(imagefiles)!=1:raise RuntimeError("Expected exactly one selected page")
    gray=np.array(Image.open(imagefiles[0]).convert("L"))
    systems=locate(gray)
    print(f"Page {page_number}: {len(systems)} complete grand-staff systems found",flush=True)
    report={"page":page_number,"systems":[]}
    for i,(top,bottom) in enumerate(systems):
        y0=max(0,top-82);y1=min(gray.shape[0],bottom+66)
        if i:y0=max(y0,systems[i-1][1]+38)
        if i<len(systems)-1:y1=min(y1,systems[i+1][0]-37)
        png=out/"cropped"/f"system-{i+1:02d}.png";png.parent.mkdir(parents=True,exist_ok=True)
        Image.fromarray(gray[y0:y1,:]).save(png,dpi=(200,200))
        native=out/"native"/f"system-{i+1:02d}";native.mkdir(parents=True,exist_ok=True)
        p=subprocess.run([str(exe),"-batch","-transcribe","-export","-output",
                          str(native),"--",str(png)],
                         capture_output=True,text=True,errors="replace",timeout=260)
        if p.returncode:row={"system":i+1,"error":p.stdout[-1800:]}
        else:
            candidates=sorted(native.rglob("*.mxl"))
            if candidates:
                xml=uncompress(candidates[0])
                target=out/"raw-systems"/f"system-{i+1:02d}.musicxml"
                target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(xml)
                row={"system":i+1,**score_summary(xml)}
            else:row={"system":i+1,"error":"No .mxl"}
        report["systems"].append(row);print(json.dumps(row),flush=True)
    report["measures"]=sum(r.get("measures",0) for r in report["systems"])
    report["notes"]=sum(r.get("notes",0) for r in report["systems"])
    (out/"system-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("SYSTEM TOTAL:",report["measures"],"measures,",report["notes"],"notes",flush=True)

if __name__=="__main__":main(sys.argv[1],sys.argv[2],sys.argv[3],int(sys.argv[4]))
