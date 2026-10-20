#!/usr/bin/env python3
"""
고해상도 합성 악보 + 정답을 **웹 다운로드급**으로 축소한다.

`make_test_sheet.py --spacing 6` 은 선을 1~2px로 또렷하게 그린다. 그런데
사용자가 실제로 올리는 이미지는 큰 악보를 축소하고 JPEG로 압축한 것이라
안티에일리어싱과 압축 잡티가 있다. 또렷한 픽스처로 검증하면 품질을
과대평가한다(실측: 홀수 단 머리 보존이 합성 83%인데 실제 악보에서는
머리가 번지고 빔이 조각났다).

    python3 tools/downscale_fixture.py <원본png> <원본truth> --scale 0.42 \
        -o out.jpg --truth out.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def scale_extraction(ex: dict, s: float) -> dict:
    out = json.loads(json.dumps(ex))
    r = lambda v: int(round(v * s))
    out["imageSize"] = {"w": r(ex["imageSize"]["w"]), "h": r(ex["imageSize"]["h"])}
    for sysd in out["systems"]:
        for key in ("staffTop", "staffBottom", "headEnd"):
            if key in sysd:
                sysd[key] = r(sysd[key])
        for c in sysd["chords"]:
            b = c["box"]
            b["x"], b["y"] = r(b["x"]), r(b["y"])
            b["w"], b["h"] = max(1, r(b["w"])), max(1, r(b["h"]))
    for nt in out.get("_truthNotes", []):
        nt["x"] = r(nt["x"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("truth")
    ap.add_argument("--scale", type=float, required=True)
    ap.add_argument("--quality", type=int, default=82, help="JPEG 품질")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--truth-out", required=True)
    args = ap.parse_args()

    src = Image.open(args.image).convert("RGB")
    w = int(round(src.width * args.scale))
    h = int(round(src.height * args.scale))
    small = src.resize((w, h), Image.LANCZOS)
    if args.out.lower().endswith((".jpg", ".jpeg")):
        small.save(args.out, quality=args.quality)
    else:
        small.save(args.out)

    with open(args.truth, encoding="utf-8") as f:
        ex = json.load(f)
    ex2 = scale_extraction(ex, args.scale)
    Path(args.truth_out).write_text(json.dumps(ex2, ensure_ascii=False),
                                    encoding="utf-8")
    print(f"{args.out}  {w}x{h}  (배율 {args.scale}, JPEG q{args.quality})")


if __name__ == "__main__":
    main()
