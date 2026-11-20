#!/usr/bin/env python3
"""
Extract one captured item (by index) from the Burp XML and write its decoded
request + response into research/02_endpoints/<idx>/ for study.

Usage: python3 research/extract_item.py <idx> [idx2 idx3 ...]
"""
import xml.etree.ElementTree as ET
import base64
import sys
import os

SRC = "requests"

def localname(tag):
    return tag.split('}', 1)[-1]

def extract(idx_target, out_dir):
    context = ET.iterparse(SRC, events=("end",))
    found = False
    cur = {"_idx": 0}
    for event, elem in context:
        if event == "end" and localname(elem.tag) == "item":
            # track running index to match the one from parse_index
            cur["_idx"] += 1  # not reliable; instead we recompute below
            pass
    # iterparse index counting is messy; redo a clean pass tracking count
    return None

# Simpler: stream and count items 0..N, dump when we hit target set.
def run(targets):
    targets = set(int(t) for t in targets)
    os.makedirs("research/02_endpoints", exist_ok=True)
    context = ET.iterparse(SRC, events=("end",))
    count = -1
    for event, elem in context:
        if event == "end" and localname(elem.tag) == "item":
            count += 1
            if count not in targets:
                elem.clear()
                continue
            d = {"raw": {}}
            for child in elem:
                n = localname(child.tag)
                txt = child.text or ""
                if n in ("request", "response"):
                    b64 = child.attrib.get("base64") == "true"
                    raw = base64.b64decode(txt) if b64 else txt.encode()
                    d["raw"][n] = raw
                else:
                    d[n] = (txt or "").strip()
            folder = f"research/02_endpoints/{count:04d}"
            os.makedirs(folder, exist_ok=True)
            # write text fields
            with open(f"{folder}/meta.txt", "w") as f:
                for k, v in d.items():
                    if k == "raw":
                        continue
                    f.write(f"{k}: {v}\n")
            for bn in ("request", "response"):
                if bn in d["raw"]:
                    raw = d["raw"][bn]
                    # try to write as text
                    try:
                        txt = raw.decode("utf-8")
                        ext = "txt"
                    except Exception:
                        txt = None
                        ext = "bin"
                    with open(f"{folder}/{bn}.{ext}", "wb" if ext == "bin" else "w") as f:
                        if ext == "bin":
                            f.write(raw)
                        else:
                            f.write(txt)
            print(f"Wrote item {count} -> {folder} (req {len(d['raw'].get('request',b''))}B, resp {len(d['raw'].get('response',b''))}B)")
            elem.clear()
            if count >= max(targets):
                break

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: extract_item.py <idx> ...")
        sys.exit(1)
    run(sys.argv[1:])
