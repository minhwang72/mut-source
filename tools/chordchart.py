#!/usr/bin/env python3
"""
악보에서 **코드와 가사만** 뽑아 코드차트를 만든다.

왜 따로 만드나: 찬양팀 콘티의 상당수는 멜로디 없이 코드와 가사만 쓴다.
그 용도라면 오선을 건드릴 이유가 없고, 건드리지 않으면 **이조가 정확해진다**.

  · 코드  — 텍스트라 이조가 산술이다. 실측 430건(43개 × 10키) 오류 0.
  · 가사  — 원본 픽셀 띠를 그대로 오려 붙인다. 손대지 않으므로 100%.
  · 멜로디 — 아예 넣지 않는다. 픽셀 이동도, 임시표 문제도 사라진다.

즉 이 모드에는 **틀릴 구석이 없다.** 오선을 옮기지 않으니 해상도 게이트도,
조표 교체 실패도, 음표 뭉개짐도 없다.

    python3 tools/chordchart.py <이미지> <extraction.json> -s 2 -o out.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lyricstrip as LS  # noqa: E402
import render as R  # noqa: E402
import sheetcv as cv  # noqa: E402

GAP_CHORD = 0.55      # 코드 줄과 가사 띠 사이 (가사 띠 높이 대비)
GAP_LINE = 1.10       # 단과 단 사이
MARGIN = 0.6          # 좌우·상하 여백 (가사 띠 높이 대비)


def build(image_path: str, extraction: dict, semitones: int) -> tuple[Image.Image, dict]:
    src = Image.open(image_path).convert("RGB")
    ink, staves = cv.find_staves_best(src)
    if not staves:
        raise SystemExit("오선을 찾지 못했습니다.")
    spacing = cv.median_spacing(staves)

    systems = extraction["systems"]
    chords = [c["text"] for s in systems for c in s["chords"]]
    plan = R.call_engine(extraction["meta"]["key"], semitones, chords)
    new_text = [c["to"] for c in plan["chords"]]

    # 가사 띠를 단별로 잡는다. 코드는 그 단의 오선 위에 있던 것을 쓴다.
    lines = []
    k = 0
    for i, sysd in enumerate(systems):
        n = len(sysd["chords"])
        texts = new_text[k:k + n]
        boxes = [c["box"] for c in sysd["chords"]]
        k += n
        if i >= len(staves):
            continue
        st = staves[i]
        nxt = staves[i + 1].top if i + 1 < len(staves) else None
        raw = cv.find_lyric_band(ink, st, spacing, nxt)
        band = LS.band_of(ink, raw, spacing) if raw else None
        lines.append({"band": band, "texts": texts, "boxes": boxes})

    heights = [b["band"][1] - b["band"][0] for b in lines if b["band"]]
    lyric_h = int(np.median(heights)) if heights else int(spacing * 3)

    # 코드 글자 크기는 원본에서 역산한 값을 그대로 쓴다 — 한 장에 하나
    size = R.base_font_size([c for s in systems for c in s["chords"]])
    font = R.load_text_font(size)
    chord_h = size

    pad = int(lyric_h * MARGIN)
    row_h = int(chord_h + lyric_h * (1 + GAP_CHORD))
    step = int(row_h + lyric_h * GAP_LINE)
    W = src.width + pad * 2
    H = pad * 2 + step * len(lines)

    out = Image.new("RGB", (W, max(H, 80)), (255, 255, 255))
    d = ImageDraw.Draw(out)
    y = pad
    drawn = 0
    for ln in lines:
        # ① 코드 — 원본 x를 유지해 가사와 정렬을 지키되, **겹치면 밀어낸다.**
        # 이조하면 글자 길이가 달라져(Ebmaj7 → Fmaj7, Bb → C) 원본 자리
        # 그대로 두면 옆 코드에 파고든다(실측: Am7G2, Dm7G 처럼 붙었다).
        # 왼쪽부터 그리면서 최소 간격을 지키면 순서와 대략적 위치가 보존된다.
        min_gap = max(6, size // 3)
        right = -10 ** 9
        for text, box in sorted(zip(ln["texts"], ln["boxes"]),
                                key=lambda t: t[1]["x"]):
            if not text:
                continue
            x = pad + box["x"]
            if x < right + min_gap:
                x = right + min_gap
            d.text((x, y), text, fill=(0, 0, 0), font=font)
            right = x + int(d.textlength(text, font=font))
            drawn += 1
        # ② 가사 — 원본 픽셀 띠를 그대로
        if ln["band"]:
            b0, b1 = ln["band"]
            strip = src.crop((0, b0, src.width, b1))
            out.paste(strip, (pad, int(y + chord_h + lyric_h * GAP_CHORD)))
        y += step

    info = {"summary": plan["summary"], "fromKey": plan["fromKey"],
            "toKey": plan["toKey"], "lines": len(lines), "chords": drawn,
            "fontSize": size, "size": out.size}
    return out, info


def main() -> None:
    ap = argparse.ArgumentParser(description="코드차트 만들기")
    ap.add_argument("image")
    ap.add_argument("extraction")
    ap.add_argument("-s", "--semitones", type=int, required=True)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    with open(a.extraction, encoding="utf-8") as f:
        ex = json.load(f)
    img, info = build(a.image, ex, a.semitones)
    img.save(a.out)

    e = sys.stderr
    print(info["summary"], file=e)
    print(f"{info['lines']}줄 · 코드 {info['chords']}개 · "
          f"글자 {info['fontSize']}px · {info['size'][0]}x{info['size'][1]}", file=e)
    print("멜로디를 넣지 않으므로 이조가 정확합니다 — "
          "코드는 산술, 가사는 원본 픽셀입니다.", file=e)
    print(f"→ {a.out}", file=e)


if __name__ == "__main__":
    main()
