#!/usr/bin/env python3
"""Capture local detector evidence without importing or calling an LLM client.

Outputs contain structural data only. Existing LLM counts may be reused explicitly;
they are evidence, never ground truth. Source images are not copied.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

os.environ["YOLO_OFFLINE"] = "true"
os.environ["YOLO_AUTOINSTALL"] = "false"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image")
    ap.add_argument("--model", default="models/omr.pt")
    ap.add_argument("--counts", help="Existing readcounts JSON; no API fallback")
    ap.add_argument("--tie-model", default="models/omr_tie.pt")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    from PIL import Image
    from ultralytics import YOLO
    import evaldet as E
    import probe as P
    import sheetcv as C
    import detstruct as D
    import numpy as np

    model_path = Path(a.model).resolve()
    if not model_path.is_file():
        raise SystemExit("Local model missing; downloads are disabled")
    src = Path(a.image).resolve()
    big, scale = P.upscale(Image.open(src).convert("RGB"))
    ink, staves = C.find_staves_best(big)
    if not staves:
        raise SystemExit("No staves found")
    model = YOLO(str(model_path))
    counts = json.loads(Path(a.counts).read_text())["systems"] if a.counts else []
    if counts:
        ex, exr = D.expects(counts)
        boxes, meta = E.detect_guided(model, big, ex, conf_hi=0.50, expect_rests=exr)
    else:
        boxes, meta = E.detect_by_staff(model, big, 0.50)
    spacing = C.median_spacing(staves)
    strict = C.remove_staff_lines(ink, staves, protect_noteheads=True)
    curves = []
    tie_path = Path(a.tie_model).resolve()
    if tie_path.is_file():
        if counts:
            expected, expected_rests = D.expects(counts)
        else:
            mids = [(s.top + s.bottom) / 2 for s in staves]
            expected, expected_rests = [0] * len(staves), [0] * len(staves)
            for box in boxes:
                i = min(range(len(mids)), key=lambda i: abs(mids[i] - box["y"] - box["h"] / 2))
                if box["class"].startswith("notehead"):
                    expected[i] += 1
                if box["class"].startswith("rest_"):
                    expected_rests[i] += 1
        curve_boxes, _ = E.detect_guided(YOLO(str(tie_path)), big, expected, expect_rests=expected_rests)
        curves = [b for b in curve_boxes if b["class"] == "tie"]
    struct = D.build_from(boxes, staves, strict, spacing,
                          np.asarray(big.convert("L")).astype("float32"),
                          counts, curves=curves, meta=meta)
    systems = [{"staffTop": int(s.top), "staffBottom": int(s.bottom),
                "lineSpans": [[int(x), int(y)] for x, y in s.spans],
                "spacing": float(s.spacing), "left": int(s.left), "right": int(s.right)}
               for s in staves]
    heads = [{"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"],
              "cls": b["class"]} for b in boxes if b["class"].startswith("notehead")]
    out = {"source": str(src), "sourceSha256": hashlib.sha256(src.read_bytes()).hexdigest(),
           "modelSha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
           "apiCalls": 0, "countsSource": str(Path(a.counts).resolve()) if a.counts else None,
           "scale": scale, "boxes": boxes, "curveBoxes": curves,
           "tieModelSha256": hashlib.sha256(tie_path.read_bytes()).hexdigest() if tie_path.is_file() else None,
           "detMeta": meta, "counts": counts,
           "struct": struct, "geometry": {"systems": systems, "heads": heads},
           "imageSize": {"w": big.width, "h": big.height}}
    target = Path(a.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"output": str(target), "systems": len(staves), "heads": len(heads), "apiCalls": 0}))


if __name__ == "__main__":
    main()
