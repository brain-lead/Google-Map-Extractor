#!/usr/bin/env python3
"""
Parse the BurpSuite XML export (requests) and build a summary index of every
captured item. Streams the file with iterparse so we never hold the whole
34MB document in memory at once.

For each item we record: index, time, host, method, path, status,
mimetype, declared response length, decoded request size, decoded response size.

Output: research/01_index/index.csv  and  research/01_index/index.json
"""
import xml.etree.ElementTree as ET
import base64
import csv
import json
import sys

SRC = "requests"
OUT_CSV = "research/01_index/index.csv"
OUT_JSON = "research/01_index/index.json"

# Fields we care about inside each <item>
TEXT_FIELDS = ["time", "url", "host", "port", "protocol",
               "method", "path", "extension", "status",
               "responselength", "mimetype", "comment"]
BIN_FIELDS = ["request", "response"]  # may be base64

records = []

def localname(tag):
    return tag.split('}', 1)[-1]

context = ET.iterparse(SRC, events=("end",))
idx = 0
for event, elem in context:
    if event == "end" and localname(elem.tag) == "item":
        rec = {}
        req_b64 = False
        resp_b64 = False
        for child in elem:
            name = localname(child.tag)
            if name in TEXT_FIELDS:
                rec[name] = (child.text or "").strip()
            elif name == "request":
                req_b64 = (child.attrib.get("base64") == "true")
                txt = child.text or ""
                try:
                    raw = base64.b64decode(txt) if req_b64 else txt.encode()
                except Exception:
                    raw = txt.encode()
                rec["request_len"] = len(raw)
            elif name == "response":
                resp_b64 = (child.attrib.get("base64") == "true")
                txt = child.text or ""
                try:
                    raw = base64.b64decode(txt) if resp_b64 else txt.encode()
                except Exception:
                    raw = txt.encode()
                rec["response_len"] = len(raw)
        rec["_idx"] = idx
        records.append(rec)
        idx += 1
        # Free memory
        elem.clear()
        if idx % 50 == 0:
            print(f"  parsed {idx} items...", file=sys.stderr)

print(f"Total items: {len(records)}", file=sys.stderr)

# Write CSV
cols = ["_idx", "time", "host", "method", "path", "status",
        "mimetype", "responselength", "request_len", "response_len", "url"]
with open(OUT_CSV, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in records:
        w.writerow(r)

with open(OUT_JSON, "w") as f:
    json.dump(records, f, indent=1)

print(f"Wrote {OUT_CSV} and {OUT_JSON}", file=sys.stderr)
