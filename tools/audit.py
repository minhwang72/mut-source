#!/usr/bin/env python3
"""
렌더 감사 — 모든 키로 변환해 화소 단위로 검증한다.

눈으로 보면 놓친다. 무엇이 **변해야 하고** 무엇이 **변하면 안 되는지**를
숫자로 확인한다.

  변하면 안 되는 것: 가사 · 마디선 · 쉼표 · 오선 · 제목/저작권 표기
  변해야 하는 것:   코드 심볼 · 음표 위치(짝수 단) · 조표(고해상도)

    python3 tools/audit.py <이미지> <extraction.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render as R
import lyricstrip as LS
import sheetcv as cv


def ink(arr: np.ndarray) -> np.ndarray:
    return arr < 128


def region_match(a: np.ndarray, b: np.ndarray, y0, y1, x0, x1) -> float:
    """두 이미지의 한 구역이 화소 단위로 얼마나 같은가 (0~1)"""
    y0, x0 = max(0, y0), max(0, x0)
    y1 = min(a.shape[0], y1)
    x1 = min(a.shape[1], x1)
    if y1 <= y0 or x1 <= x0:
        return 1.0
    return float((a[y0:y1, x0:x1] == b[y0:y1, x0:x1]).mean())


def head_box_ink(m: np.ndarray, st, step: float, x: int, spacing: float) -> int:
    """음표 머리 한 개가 차지하는 상자의 잉크 화소 수"""
    cy = st.top + step * (spacing / 2.0)
    y0 = max(0, int(cy - spacing * 0.45))
    y1 = int(cy + spacing * 0.45) + 1
    x0 = max(0, x - int(spacing * 0.5))
    x1 = x + int(spacing * 0.5) + 1
    return int(m[y0:y1, x0:x1].sum())


def lyric_bands(ink: np.ndarray, staves, spacing: float) -> list[tuple[int, int]]:
    """
    가사 띠 — 렌더러와 **같은 검출 함수**를 쓴다.

    처음엔 "오선 아래 2칸부터"로 하드코딩했는데, 조판이 바뀌자(가사를 3.2칸
    아래로 내림) 띠가 음표 영역을 덮어 가사 일치율이 92%로 떨어졌다.
    검증 기준이 구현과 어긋나면 검증이 거짓말을 한다.
    """
    out = []
    for i, st in enumerate(staves):
        nxt = staves[i + 1].top if i + 1 < len(staves) else None
        b = cv.find_lyric_band(ink, st, spacing, nxt)
        if b:
            out.append(b)
    return out


def audit(image_path: str, extraction: dict, keys: list[int]) -> list[dict]:
    src = Image.open(image_path).convert("RGB")
    # 렌더러는 오선 간격이 좁으면 확대해서 그린다. 기준 이미지도 **같은
    # 배율로** 키워야 화소 비교가 성립한다. 확대 없이 비교하면 크기가 달라
    # 가사·고정 객체 일치율이 0%로 나온다.
    _ink0, _st0 = cv.find_staves_best(src)
    _sp0 = cv.median_spacing(_st0) if _st0 else 0.0
    scale = 1.0
    if _sp0 > 0:
        f = min(R.MAX_UPSCALE, R.TARGET_SPACING / _sp0)
        if f >= 1.3:
            scale = f
            src = src.resize((int(src.width * f), int(src.height * f)),
                             Image.LANCZOS)
            extraction = R._scale_boxes(extraction, f)
    orig = np.asarray(src.convert("L")).astype(int)
    ink0 = ink(orig)
    ink_src, staves = cv.find_staves_best(src)
    spacing = cv.median_spacing(staves)
    strict = cv.remove_staff_lines(ink_src, staves, protect_noteheads=False)

    truth_notes = extraction.get("_truthNotes")
    # 머리 구간 기준은 렌더러와 **같은 함수**로 구한다. 고정 배수를 쓰면
    # 머리 구간 안에 든 첫 음표를 검사에서 빼먹는다(실측: 단1의 첫 음표가
    # 뭉개졌는데 감사는 통과로 보고했다).
    src_fifths = R.call_engine(extraction["meta"]["key"], 0, [])["fifthsFrom"]

    lyrics = lyric_bands(ink_src, staves, spacing)
    fixed = []
    for st in staves:
        he = R.head_end_for(strict, st, spacing, src_fifths)
        fixed += [o for o in cv.find_fixed_objects(strict, st, spacing) if o["x"] >= he]

    scaled_path = image_path
    if scale != 1.0:
        scaled_path = "/tmp/mut_audit_src.png"
        src.save(scaled_path)

    rows = []
    for n in keys:
        out_path = f"/tmp/mut_audit_{n}.png"
        # 위에서 이미 확대해 뒀으므로 렌더러가 또 키우면 안 된다
        info = R.render(scaled_path, json.loads(json.dumps(extraction)), n,
                        out_path, upscale=False)
        got = np.asarray(Image.open(out_path).convert("L")).astype(int)
        head_ends = info.get("headEnds", {})

        # 가사 — 변하면 안 된다
        ly = min((region_match(orig, got, y0, y1, 0, orig.shape[1])
                  for (y0, y1) in lyrics), default=1.0)

        # 고정 객체 — 변하면 안 된다
        fx = min((region_match(orig, got, o["y"], o["y"] + o["h"],
                               o["x"], o["x"] + o["w"]) for o in fixed), default=1.0)

        # 오선 — **끊기지 않았는지**만 본다. 잉크가 늘어난 것은 정상이다:
        # 그 줄 자리로 옮겨온 음표 머리가 더해진 것이고, 오선이 음표 위를
        # 지나는 것은 원래 조판이다(실측: 웹 다운로드급에서 +19~23px).
        # 절대차로 재면 정상적인 증가를 결함으로 잡는다.
        worst_line = 0
        for st in staves:
            for (a, b) in st.spans:
                for y in range(a, b + 1):
                    lost = int(ink0[y].sum()) - int(ink(got)[y].sum())
                    worst_line = max(worst_line, lost)

        # 음표 머리 보존율 — "기대 위치에 잉크가 있나"만 보는 적중률은 너무
        # 관대해서, 머리가 부서지고 조각만 남아도 통과시킨다(실측: 코드 지우기
        # 사각형이 머리를 먹었는데 적중률은 96%였다). 원본 머리의 잉크량과
        # 비교해 **얼마나 남았는지**를 본다.
        head_min = None
        if info["melody"]["shifted"] and truth_notes:
            hes = info.get("headEnds", {})
            gi = ink(got)
            ratios = []
            for nt in truth_notes:
                si, x, step = nt["system"], int(nt["x"]), nt["step"]
                if si >= len(staves) or x < hes.get(si, 0):
                    continue
                st = staves[si]
                a = head_box_ink(ink0, st, step, x, spacing)
                b = head_box_ink(gi, st, step - info["steps"], x, spacing)
                if a:
                    ratios.append(b / a)
            if ratios:
                head_min = round(min(ratios) * 100, 1)

        # 음표 검증 — 창 기반 중심점은 가사·코드가 섞여 불안정하다
        # (실측: 창을 넓히니 가사가 들어와 이동량이 0으로 측정됐다).
        # 정답 음표 데이터가 있으면 **기대 위치에 잉크가 있는지**를 직접 본다.
        moved = None
        hit = None
        if info["melody"]["shifted"]:
            steps = info["steps"]
            if truth_notes:
                found = tot = 0
                for nt in truth_notes:
                    si, x, step = nt["system"], int(nt["x"]), nt["step"]
                    if si >= len(staves):
                        continue
                    st = staves[si]
                    if x < head_ends.get(si, st.left + spacing * 12):
                        continue
                    # 위로 k단 이조하면 음표는 k단 위로 = step 감소
                    ny = st.top + (step - steps) * (spacing / 2.0)
                    lo = int(ny - spacing * 0.35)
                    hi = int(ny + spacing * 0.35) + 1
                    seg = ink(got)[max(0, lo):hi, max(0, x - 3):x + 4]
                    tot += 1
                    if seg.sum() >= 3:
                        found += 1
                hit = round(found / tot * 100, 1) if tot else None
            else:
                # 정답이 없으면 오선 밴드 안에서만 중심점을 본다
                # (가사는 오선 아래 1.8칸이므로 +1.0칸까지만 본다)
                st = staves[0]
                he = head_ends.get(0, st.left + int(spacing * 12))
                STAFF = {y for (a, b) in st.spans for y in range(a - 1, b + 2)}
                frozen = set()
                for o in fixed:
                    c = o["y"] + o["h"] / 2
                    if st.top <= c <= st.bottom:
                        frozen.update(range(o["x"] - 2, o["x"] + o["w"] + 3))
                lo = max(0, st.top - int(spacing * 2.2))
                hi = min(orig.shape[0], st.bottom + int(spacing * 1.0))
                deltas = []
                for x in range(he, min(st.right, orig.shape[1]), 6):
                    if x in frozen:
                        continue
                    ra = [y for y in range(lo, hi) if ink0[y, x] and y not in STAFF]
                    rb = [y for y in range(lo, hi)
                          if ink(got)[y, x] and y not in STAFF]
                    if len(ra) >= 2 and len(rb) >= 2:
                        deltas.append(sum(rb) / len(rb) - sum(ra) / len(ra))
                if deltas:
                    deltas.sort()
                    moved = round(deltas[len(deltas) // 2], 1)

        rows.append({
            "semitones": n,
            "toKey": info["toKey"],
            "chords": info["chords"],
            "lyricMatch": round(ly * 100, 1),
            "fixedMatch": round(fx * 100, 1),
            "staffInkDelta": worst_line,
            "melodyShift": moved,
            "noteHit": hit,
            "headMin": head_min,
            "expectShift": info["melody"]["dy"] if info["melody"]["shifted"] else None,
            "keysig": info["keySignatures"],
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("extraction")
    ap.add_argument("--keys", default="-5,-4,-3,-2,-1,1,2,3,4,5")
    args = ap.parse_args()

    with open(args.extraction, encoding="utf-8") as f:
        ex = json.load(f)
    keys = [int(k) for k in args.keys.split(",")]

    rows = audit(args.image, ex, keys)

    print(f"\n{'반음':>4} {'키':>5} {'코드':>4} {'가사':>7} {'고정':>7} "
          f"{'오선Δ':>6} {'음표':>9} {'머리':>6} {'조표':>4}")
    print("-" * 70)
    ok = True
    no_truth = all(r["noteHit"] is None for r in rows)
    for r in rows:
        exp = r["expectShift"]
        got = r["melodyShift"]
        if r["noteHit"] is not None:
            shift = f"{r['noteHit']:.0f}%"
        else:
            shift = "—" if exp is None else f"{got}/{exp}"
        flag = ""
        if r["noteHit"] is not None and r["noteHit"] < 90:
            flag = "  ← 음표 위치 불일치"
            ok = False
        if r["lyricMatch"] < 99.9 or r["fixedMatch"] < 99.9 or r["staffInkDelta"] > 20:
            flag = "  ← 확인"
            ok = False
        # 정답 음표(_truthNotes)가 없으면 이동량은 **대체 측정**이다 — 오선
        # 밴드 안 잉크 중심점이라 빔·이음줄·쉼표가 섞여 실제보다 작게 나온다
        # (실측: 독립적으로 머리 좌표를 재면 +2는 -10.4/-9.5, +5는
        # -28.2/-28.5로 맞는데 이 지표는 각각 -7.5, -24.6을 냈다).
        # 근거 없는 지표가 합불을 가르면 안 되므로 참고로만 표시한다.
        if (r["noteHit"] is None and exp is not None and got is not None
                and abs(got - exp) > 2.0):
            flag = "  · 이동량 참고치"
        if r["headMin"] is not None and r["headMin"] < 75:
            flag = "  ← 음표 머리 손상"
            ok = False
        hm = "—" if r["headMin"] is None else f"{r['headMin']:.0f}%"
        print(f"{r['semitones']:+4d} {r['toKey']:>5} {r['chords']:4d} "
              f"{r['lyricMatch']:6.1f}% {r['fixedMatch']:6.1f}% "
              f"{r['staffInkDelta']:6d} {shift:>9} {hm:>6} {r['keysig']:4d}{flag}")
    print("-" * 70)
    if no_truth:
        print("※ 정답 음표(_truthNotes)가 없어 음표 위치는 검증되지 않았습니다 "
              "— '이동량 참고치'는 대체 측정입니다.")
    print("전부 통과 ✅" if ok else "문제 있음 ❌")


if __name__ == "__main__":
    main()
