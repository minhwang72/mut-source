#!/usr/bin/env python3
"""
실제 악보에서 **조판 수치**를 재서 생성기 범위에 반영한다.

왜 필요한가: 합성 데이터의 다양성은 지금 **내가 흔들 생각을 한 만큼**이다.
그 한계가 실제로 물렸다 — 오선 굵기를 0.10~0.30칸으로 잡았는데 마커스
악보가 0.333칸이라 검출기가 그 악보에서만 무너졌다. 눈대중 대신 실제
분포를 재서 범위를 정한다.

**그림은 재기만 하고 학습에 넣지 않는다.** 뽑아내는 것은 숫자뿐이므로
저작권 방어선(개인적 이용)이 유지된다.

    python3 tools/measure_style.py 악보들/*.jpg [--model best.pt]

model을 주면 음표 머리 크기까지 잰다 — 머리 검출이 문턱값으로는 조판을
넘어 안 되기 때문에, 학습된 검출기가 있어야 이 항목을 잴 수 있다.
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lyricstrip as LS  # noqa: E402
import probe as P  # noqa: E402
import sheetcv as cv  # noqa: E402


def measure(path: str, model=None) -> dict | None:
    """악보 한 장의 조판 수치. 모든 길이는 **오선 간격(칸) 단위**로 낸다."""
    img = Image.open(path).convert("RGB")
    ink0, staves0 = cv.find_staves_best(img)
    if not staves0:
        return None
    raw_spacing = cv.median_spacing(staves0)

    # 잰다: 확대본에서. 실제 파이프라인이 확대해서 처리하기 때문이다.
    big, factor = P.upscale(img)
    ink, staves = cv.find_staves_best(big)
    if not staves:
        return None
    sp = cv.median_spacing(staves)
    if sp <= 0:
        return None

    line_w = [b - a + 1 for s in staves for (a, b) in s.spans]

    # 가사 띠 높이 = 가사 글자 크기의 대용치
    bands = []
    for i, s in enumerate(staves):
        nxt = staves[i + 1].top if i + 1 < len(staves) else None
        b = cv.find_lyric_band(ink, s, sp, nxt)
        if b:
            y0, y1 = LS.band_of(ink, b, sp)
            if y1 > y0:
                bands.append((y1 - y0) / sp)

    # 단 사이 간격
    gaps = [(staves[i + 1].top - staves[i].bottom) / sp
            for i in range(len(staves) - 1)]

    out = {
        "file": Path(path).name,
        "원본간격": round(raw_spacing, 1),
        "확대": round(factor, 2),
        "단수": len(staves),
        "오선굵기": round(float(np.median(line_w)) / sp, 3),
        "가사띠": round(st.median(bands), 2) if bands else None,
        "단간격": round(st.median(gaps), 2) if gaps else None,
        "머리폭": None, "머리높이": None,
    }

    if model is not None:
        r = model.predict(big, imgsz=960, conf=0.35, verbose=False)[0]
        ws, hs = [], []
        for b, c in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist()):
            if r.names[int(c)].startswith("notehead"):
                ws.append((b[2] - b[0]) / sp)
                hs.append((b[3] - b[1]) / sp)
        if ws:
            out["머리폭"] = round(st.median(ws), 2)
            out["머리높이"] = round(st.median(hs), 2)
            out["머리수"] = len(ws)
    return out


def summarize(rows: list[dict]) -> None:
    """생성기 범위로 바로 옮길 수 있게 5~95 백분위로 낸다."""
    print("\n── 생성기에 넣을 범위 (5~95 백분위) ──")
    for key, gen in (("오선굵기", "staffLineWidth"),
                     ("가사띠", "lyricSize 대용"),
                     ("단간격", "spacingStaff 대용"),
                     ("머리폭", "(폰트가 정함)"),
                     ("원본간격", "축소 목표")):
        vals = sorted(r[key] for r in rows if r.get(key) is not None)
        if len(vals) < 2:
            continue
        lo = vals[max(0, int(len(vals) * 0.05))]
        hi = vals[min(len(vals) - 1, int(len(vals) * 0.95))]
        print(f"  {key:8s} {lo:6.3f} ~ {hi:6.3f}   중앙 {st.median(vals):6.3f}"
              f"   → {gen}")


def main() -> None:
    ap = argparse.ArgumentParser(description="실제 악보 조판 수치 측정")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--model", help="학습된 가중치 (머리 크기까지 재려면)")
    # 표지·가사만 있는 쪽은 오선이 한둘뿐이라 분포를 흐린다
    # (실측: 콘티 1쪽이 24px 2단, 5쪽이 51px 2단으로 잡혀 중앙값을 밀었다).
    ap.add_argument("--min-staves", type=int, default=3)
    a = ap.parse_args()

    model = None
    if a.model:
        from ultralytics import YOLO
        model = YOLO(a.model)

    rows = []
    print(f"{'파일':<28} {'원본간격':>7} {'단수':>4} {'오선굵기':>7} "
          f"{'가사띠':>6} {'단간격':>6} {'머리폭':>6}")
    print("-" * 74)
    for p in a.images:
        r = measure(p, model)
        if not r:
            print(f"{Path(p).name[:27]:<28} 오선 못 찾음")
            continue
        if r["단수"] < a.min_staves:
            print(f"{r['file'][:27]:<28} 단 {r['단수']}개 — 건너뜀 (표지로 보임)")
            continue
        rows.append(r)
        print(f"{r['file'][:27]:<28} {r['원본간격']:>7.1f} {r['단수']:>4} "
              f"{r['오선굵기']:>7.3f} "
              f"{(r['가사띠'] if r['가사띠'] is not None else 0):>6.2f} "
              f"{(r['단간격'] if r['단간격'] is not None else 0):>6.2f} "
              f"{(r['머리폭'] if r['머리폭'] is not None else 0):>6.2f}")
    if len(rows) >= 2:
        summarize(rows)


if __name__ == "__main__":
    main()
