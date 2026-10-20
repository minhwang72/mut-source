#!/usr/bin/env python3
"""Rebuild a cached detector capture with current code: no inference or LLM call."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fifths", type=int, required=True)
    ap.add_argument("--time", required=True)
    a = ap.parse_args()
    from PIL import Image
    import numpy as np
    import probe as P
    import sheetcv as C
    import detstruct as D
    data = json.loads(Path(a.capture).read_text())
    source = Path(data["source"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != data["sourceSha256"]:
        raise SystemExit("Source changed; capture cannot be reused")
    big, scale = P.upscale(Image.open(source).convert("RGB"))
    if abs(scale - data["scale"]) > 1e-6:
        raise SystemExit("Image scale changed; capture cannot be reused")
    ink, staves = C.find_staves_best(big)
    counts = data["counts"] or [{} for _ in staves]
    counts = [dict(c) for c in counts]
    counts[0]["time_signature"] = a.time
    struct = D.build_from(data["boxes"], staves,
                         C.remove_staff_lines(ink, staves, protect_noteheads=True),
                         C.median_spacing(staves), np.asarray(big.convert("L")).astype("float32"),
                         counts, curves=data.get("curveBoxes"),
                         sections=[a.fifths] * len(staves), meta=data["detMeta"])
    struct["sourceFifths"] = a.fifths
    data["struct"] = struct
    data["knownInput"] = {"fifths": a.fifths, "timeSignature": a.time}
    data["apiCalls"] = 0
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(a.out)


if __name__ == "__main__":
    main()
