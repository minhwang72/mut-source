#!/usr/bin/env python3
"""
이동 후 음표 머리가 놓일 상자를 계산해 JSON으로 낸다.

렌더러가 가사 띠를 원본으로 되돌릴 때 **이 자리는 비켜가야** 한다. 가사 띠는
오선 바로 아래부터 잡히므로 아래로 이조하면 덧줄 음표가 그 안으로 내려오고,
띠를 통째로 덮으면 그 음표가 지워진다(실측: 머리 115개 중 36개가 잉크 절반
이하로 떨어졌고, 그중 92%가 이 띠 안이었다. 비켜가면 4개).

검출기(ultralytics)가 필요하므로 렌더러 본체와 분리해 별도 프로세스로 둔다 —
코어 도구들은 의존성 0을 유지한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> None:
    import evaldet as E

    ap = argparse.ArgumentParser(description="음표 보호 상자 계산")
    ap.add_argument("image")
    ap.add_argument("extraction")
    ap.add_argument("-s", "--semitones", type=int, required=True)
    ap.add_argument("--model", default="models/omr.pt")
    ap.add_argument("--conf", type=float, default=0.50)
    ap.add_argument("--target", type=float, default=E.INPUT_SPACING)
    a = ap.parse_args()

    from PIL import Image
    from ultralytics import YOLO

    import probe as P
    import render as R
    import sheetcv as cv

    with open(a.extraction, encoding="utf-8") as f:
        ex = json.load(f)

    big, _f = P.upscale(Image.open(a.image).convert("RGB"))
    _ink, staves = cv.find_staves_best(big)
    if not staves:
        print("[]")
        return
    sp = cv.median_spacing(staves)
    steps = R.call_engine(ex["meta"]["key"], a.semitones, [])["steps"]
    dy = int(round(-steps * (sp / 2.0)))

    boxes, _names = E.detect_by_staff(YOLO(a.model), big, a.conf, a.target)
    pad = max(2, int(sp * 0.15))
    out = [{"x": int(b["x"] - pad), "y": int(b["y"] + dy - pad),
            "w": int(b["w"] + pad * 2), "h": int(b["h"] + pad * 2)}
           for b in boxes if b["class"].startswith("notehead")]
    print(json.dumps(out))


if __name__ == "__main__":
    main()
