#!/usr/bin/env python3
"""
검출된 기호 상자 → **음높이가 붙은 음표 목록**.

여기가 CV와 학습 검출기가 만나는 지점이다:
  · 검출기(YOLO)는 **무엇이 어디 있는지**를 준다 — 조판이 달라도 견딘다.
  · 오선 검출(CV)은 **줄이 정확히 어디인지**를 준다 — 픽셀 단위로 정확하다.
  · 음높이는 그 둘의 **뺄셈**이다: (머리 y − 첫 줄 y) ÷ 반칸. 원가 0.

왜 음높이를 AI에게 묻지 않나: 실측으로 Opus 5가 6배 확대본에서 7음 중
평균 5.75개만 맞췄다(82%). 100음 곡이면 18음이 틀린다. 좌표는 뺄셈이므로
틀릴 수가 없다 — 상자만 제자리에 오면 된다.

임시표는 **머리 왼쪽에 붙은 상자**로 잇는다. 조표에 있는 것과 구별해야
하므로 머리 구간(조표가 끝나는 x) 오른쪽만 본다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import notes as N  # noqa: E402
import sheetcv as cv  # noqa: E402

HEADS = {"notehead_filled": "filled",
         "notehead_half": "half",
         "notehead_whole": "whole"}
ACCIDENTALS = {"accidental_sharp": "#",
               "accidental_flat": "b",
               "accidental_natural": "n"}


def _center(b: dict) -> tuple[float, float]:
    return b["x"] + b["w"] / 2.0, b["y"] + b["h"] / 2.0


def assign(boxes: list[dict], staves, spacing: float) -> list[list[dict]]:
    """
    상자를 단별로 나눈다. 판정은 **세로 중심이 어느 단에 가장 가까운가**다.

    덧줄로 오선 밖 두 칸까지 나가는 음표가 있으므로 단 경계로 자르면 안 된다
    (실측: 단0의 첫 음 C4가 오선 아래 1.5칸에 있었다).
    """
    out: list[list[dict]] = [[] for _ in staves]
    if not staves:
        return out
    mids = [(st.top + st.bottom) / 2.0 for st in staves]
    for b in boxes:
        _, cy = _center(b)
        i = min(range(len(mids)), key=lambda k: abs(mids[k] - cy))
        # 단 높이의 두 배를 넘게 떨어져 있으면 그 단의 것이 아니다
        span = staves[i].bottom - staves[i].top
        if abs(mids[i] - cy) <= span * 1.6:
            out[i].append(b)
    return out


def read_staff(boxes: list[dict], st, spacing: float,
               head_end: float | None = None) -> list[dict]:
    """한 단의 상자에서 음표를 x 순으로 읽는다."""
    heads = [b for b in boxes if b["class"] in HEADS]
    accs = [b for b in boxes if b["class"] in ACCIDENTALS]
    if head_end is not None:
        heads = [b for b in heads if _center(b)[0] >= head_end]
        accs = [b for b in accs if _center(b)[0] >= head_end]

    out = []
    for b in sorted(heads, key=lambda d: _center(d)[0]):
        hx, hy = _center(b)
        step = N.pitch_step(hy, st, spacing)
        # 임시표는 머리 **바로 왼쪽**, 같은 높이에 붙는다
        acc = None
        best = None
        for a in accs:
            ax, ay = _center(a)
            dx = hx - ax
            if 0 < dx < spacing * 2.2 and abs(ay - hy) < spacing * 0.8:
                if best is None or dx < best:
                    best, acc = dx, ACCIDENTALS[a["class"]]
        out.append({
            "x": round(hx, 1), "y": round(hy, 1),
            "kind": HEADS[b["class"]],
            "step": step,
            "name": N.step_name(step),
            "accidental": acc,
            "conf": round(b.get("conf", 1.0), 3),
        })
    return out


def read_image(img, boxes: list[dict]) -> dict:
    """이미지와 검출 상자로 단별 음표 목록을 만든다."""
    ink, staves = cv.find_staves_best(img)
    if not staves:
        return {"staves": 0, "systems": []}
    spacing = cv.median_spacing(staves)
    per = assign(boxes, staves, spacing)
    systems = []
    for i, (st, bs) in enumerate(zip(staves, per)):
        # 조표·음자리표 오른쪽부터 본다. 검출된 음자리표·박자표 중
        # 가장 오른쪽 끝을 머리 구간의 시작으로 삼는다.
        marks = [b for b in bs if b["class"] in ("clef_g", "timesig")]
        he = max((b["x"] + b["w"] for b in marks), default=st.left)
        systems.append({
            "staff": i,
            "spacing": round(spacing, 1),
            "notes": read_staff(bs, st, spacing, he + spacing * 0.3),
        })
    return {"staves": len(staves), "spacing": round(spacing, 1),
            "systems": systems}
