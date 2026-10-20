#!/usr/bin/env python3
"""
악보 이미지에서 오선과 코드 심볼 박스를 검출한다.

설계 의도: AI에게 좌표를 물어보지 않는다.
비전 모델은 바운딩 박스가 부정확하다. 반면 코드 심볼은 오선 위 여백에
떠 있는 고립된 검은 덩어리라서 고전적 영상처리로 픽셀 단위로 잡힌다.
AI에게는 잘라낸 작은 조각의 "글자"만 읽히면 된다 — 훨씬 싸고 정확하다.

    python3 tools/detect_chords.py <이미지> [--debug out.png] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sheetcv import Box, Staff, binarize, components, find_staves, merge_horizontal


# ---------------------------------------------------------------- 코드 밴드

def detect(path: str, debug_path: str | None = None) -> dict:
    """파일 경로용 진입점. 인메모리 처리는 detect_from_ink를 쓴다."""
    img = Image.open(path)
    # **파이프라인과 같은 오선 검출을 쓴다.** 예전엔 단순판 find_staves 를
    # 썼는데, 워터마크가 겹친 단을 통째로 놓쳤다(실측: 「지금 여기 우리」
    # 콘티에서 11단 중 1단이 빠져 그 단의 코드 6개가 사라졌다).
    # find_staves_best 는 여러 이진화를 시도해 가장 나은 것을 고른다.
    import sheetcv as _cv
    ink, staves = _cv.find_staves_best(img.convert("L"))
    if not staves:
        ink = binarize(img)
        staves = find_staves(ink)
    if not staves:
        raise SystemExit("오선을 찾지 못했습니다. 해상도나 대비를 확인하세요.")
    return detect_from_ink(img, ink, staves, debug_path)


def detect_from_ink(img, ink, staves, debug_path: str | None = None) -> dict:
    """
    이미 이진화·오선검출이 끝난 상태에서 코드 박스만 찾는다.

    서버는 전처리(prepare)에서 기울기 보정과 사진용 이진화를 이미 했으므로
    그 결과를 그대로 받아야 한다 — 여기서 다시 이진화하면 보정이 버려진다.
    """
    h, w = ink.shape
    spacing = float(np.median([s.lines[i + 1] - s.lines[i]
                              for s in staves for i in range(len(s.lines) - 1)]))
    # 박스 높이가 가장 강한 판별자다. 실측(오선간격 6px 악보):
    #   진짜 코드 심볼      h = 12~18  (대문자 높이 + 윗숫자/아래 m)
    #   음자리표 상단 갈고리 h = 8~9    (오선에 붙어 있고 밴드에서 잘림)
    #   빔·조표 잔여물       h = 3
    # 오선간격의 1.6배를 하한으로 두면 셋이 깔끔하게 갈린다.
    min_h = max(4, round(spacing * 1.6))
    min_w = max(3, round(spacing * 0.8))
    # 같은 코드로 볼 가로 간격 — 'Ebmaj7'은 E/b/maj/7 이 떨어져 잡힌다
    max_gap = max(2, int(spacing * 0.9))

    systems = []
    debug = ImageDraw.Draw(img.convert("RGB")) if debug_path else None
    canvas = img.convert("RGB") if debug_path else None
    if canvas is not None:
        debug = ImageDraw.Draw(canvas)

    for si, st in enumerate(staves):
        # 코드 밴드: 이 오선 위쪽 여백. 위 단의 가사와 겹치지 않게
        # 오선 사이 빈 공간의 아래쪽 절반만 본다.
        prev_bottom = staves[si - 1].bottom if si > 0 else 0
        gap = st.top - prev_bottom
        band_top = max(prev_bottom + int(gap * 0.45), st.top - int(spacing * 4.5))
        band_bottom = st.top - 1
        if band_bottom <= band_top:
            systems.append({"index": si, "staffTop": st.top, "staffBottom": st.bottom,
                            "chords": []})
            continue

        # 음자리표는 오선 위로 크게 뻗어 코드 밴드를 침범한다(실측: 오선 간격
        # 16px 악보에서 단마다 오검출 1개). 높은음자리표 폭은 오선 간격의
        # 약 3배이고, 실제 악보는 코드를 음자리표 위에 찍지 않으므로
        # 밴드의 왼쪽 시작을 그만큼 밀어 둔다.
        band_left = st.left + int(round(spacing * 3.2))
        if band_left >= st.right:
            band_left = st.left
        band = ink[band_top:band_bottom, band_left : st.right + 1]
        # 순서가 중요하다: 잡티만 걷어내고 **먼저 병합**한 뒤 크기로 판별한다.
        # 크기 필터를 먼저 걸면 'Ebmaj7'의 윗첨자(b·7)가 개별로는 작아서
        # 버려지고 대문자 E만 남아, 박스가 심볼 전체를 덮지 못한다.
        # 병합 **전에** 지나치게 넓은 덩어리를 버린다. 확대하면 오선 위
        # 흐릿한 띠가 밴드 폭 전체로 이어지는데(실측: 3배에서 1682px짜리
        # 덩어리), 이게 코드들과 세로로 겹쳐서 전부 한 덩어리로 삼킨다.
        # 실제 코드 심볼은 아무리 길어도 오선 간격의 8배를 넘지 않는다.
        max_w = spacing * 8
        speck = [b for b in components(band)
                 if b.h >= 2 and b.w >= 2 and b.w <= max_w]
        # 위첨자(⁷·²)는 세로로 안 겹쳐 따로 떨어진다 — stack_gap 으로 붙인다.
        merged = [b for b in merge_horizontal(speck, max_gap,
                                              stack_gap=max(1, round(spacing * 0.6)))
                  if b.h >= min_h and b.w >= min_w]

        chords = []
        for b in merged:
            # 밴드 좌표를 원본 좌표로 되돌린다
            gx = b.x + band_left
            gy = b.y + band_top
            # 너무 납작하거나 너무 넓은 건 늘임표·이음줄 잔여물
            if b.w > spacing * 12:
                continue
            chords.append({"x": int(gx), "y": int(gy), "w": int(b.w), "h": int(b.h)})
            if debug:
                debug.rectangle([gx - 1, gy - 1, gx + b.w, gy + b.h], outline=(220, 30, 30))

        if debug:
            debug.rectangle([st.left, band_top, st.right, band_bottom], outline=(40, 120, 220))
            debug.rectangle([st.left, st.top, st.right, st.bottom], outline=(30, 170, 90))

        systems.append({
            "index": si,
            "staffTop": int(st.top),
            "staffBottom": int(st.bottom),
            "chords": chords,
        })

    if debug_path and canvas is not None:
        canvas.save(debug_path)

    return {
        "imageSize": {"w": int(w), "h": int(h)},
        "staffSpacing": round(spacing, 2),
        "systems": systems,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="악보에서 오선·코드 박스 검출")
    ap.add_argument("image")
    ap.add_argument("--debug", help="검출 결과를 그린 이미지 저장 경로")
    ap.add_argument("--json", help="결과 JSON 저장 경로")
    args = ap.parse_args()

    result = detect(args.image, args.debug)

    total = sum(len(s["chords"]) for s in result["systems"])
    print(f"오선 {len(result['systems'])}단 · 오선 간격 {result['staffSpacing']}px "
          f"· 코드 박스 {total}개", file=sys.stderr)
    for s in result["systems"]:
        print(f"  단 {s['index']}: {len(s['chords'])}개", file=sys.stderr)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
