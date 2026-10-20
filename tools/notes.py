#!/usr/bin/env python3
"""
음표 머리 검출 — 빔으로 묶인 음표를 개별 머리로 분리한다.

왜 필요한가: 8분음표들이 빔으로 이어지면 **연결요소 하나**가 된다. 그래서
연결요소만 세면 여러 음이 한 덩어리로 잡혀 음높이를 뽑을 수 없다.

방법: 음표 머리 크기의 타원으로 **침식(erosion)** 한다.
  · 빔  → 가로로 길지만 세로로 얇다  → 세로로 깎이면 사라진다
  · 기둥 → 세로로 길지만 가로로 얇다  → 가로로 깎이면 사라진다
  · 오선 → 세로로 아주 얇다          → 사라진다
  · 머리 → 타원이라 살아남는다
남은 씨앗의 연결요소가 곧 머리다.

속 빈 머리(2분·온음표)는 침식으로 지워지므로 **구멍**으로 따로 찾는다.
"""

from __future__ import annotations

import numpy as np


def _ellipse(rw: int, rh: int) -> np.ndarray:
    """반지름 (rw, rh)인 타원 구조요소"""
    ys, xs = np.mgrid[-rh:rh + 1, -rw:rw + 1]
    return ((xs / max(1, rw)) ** 2 + (ys / max(1, rh)) ** 2) <= 1.0


def erode(mask: np.ndarray, se: np.ndarray) -> np.ndarray:
    """구조요소 se로 침식. se가 전부 들어가는 자리만 남는다."""
    h, w = mask.shape
    sh, sw = se.shape
    ry, rx = sh // 2, sw // 2
    pad = np.zeros((h + 2 * ry, w + 2 * rx), dtype=bool)
    pad[ry:ry + h, rx:rx + w] = mask
    out = np.ones((h, w), dtype=bool)
    for dy in range(sh):
        for dx in range(sw):
            if not se[dy, dx]:
                continue
            out &= pad[dy:dy + h, dx:dx + w]
    return out


def _label(mask: np.ndarray):
    """연결요소 라벨링 (4방향). (라벨수, 라벨배열) 반환."""
    h, w = mask.shape
    lab = np.zeros((h, w), dtype=np.int32)
    n = 0
    stack: list[tuple[int, int]] = []
    for y in range(h):
        row = mask[y]
        for x in range(w):
            if not row[x] or lab[y, x]:
                continue
            n += 1
            stack.append((y, x))
            lab[y, x] = n
            while stack:
                cy, cx = stack.pop()
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                        lab[ny, nx] = n
                        stack.append((ny, nx))
    return n, lab


def find_filled_heads(ink: np.ndarray, spacing: float) -> list[dict]:
    """꽉 찬 머리(4분·8분·16분)를 침식으로 찾는다."""
    # 머리는 가로 약 1.2칸, 세로 약 1칸. 그보다 조금 작은 타원으로 깎는다.
    rw = max(1, int(round(spacing * 0.34)))
    rh = max(1, int(round(spacing * 0.24)))
    seeds = erode(ink, _ellipse(rw, rh))
    n, lab = _label(seeds)
    out = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        if ys.size < 3:
            continue
        out.append({"x": float(xs.mean()), "y": float(ys.mean()),
                    "filled": True, "px": int(ys.size)})
    return out


def find_hollow_heads(ink: np.ndarray, spacing: float) -> list[dict]:
    """
    속 빈 머리(2분·온음표)는 침식으로 지워진다. **구멍**으로 찾는다.

    배경(잉크 아님) 중에서 이미지 테두리와 이어지지 않은 영역이 구멍이고,
    그 크기가 머리 속만 한 것이 속 빈 머리다.
    """
    h, w = ink.shape
    bg = ~ink
    n, lab = _label(bg)
    # 테두리에 닿은 라벨은 바깥 배경이다
    outer = set(lab[0].tolist()) | set(lab[-1].tolist())
    outer |= set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    lo = (spacing * 0.18) ** 2 * 3.14
    hi = (spacing * 0.62) ** 2 * 3.14
    out = []
    for i in range(1, n + 1):
        if i in outer:
            continue
        ys, xs = np.nonzero(lab == i)
        area = ys.size
        if not (lo <= area <= hi):
            continue
        bh = ys.max() - ys.min() + 1
        bw = xs.max() - xs.min() + 1
        if bh > spacing * 1.1 or bw > spacing * 1.4:
            continue
        # 진짜 머리 속은 옆으로 누운 타원이다. 빔·기둥·이음줄 사이에 생기는
        # 흰 구멍은 세로로 서 있거나 들쭉날쭉해서 여기서 걸린다.
        aspect = bw / max(1.0, bh)
        solid = area / max(1.0, bw * bh)
        if not (1.15 <= aspect <= 2.6 and solid >= 0.62):
            continue
        out.append({"x": float(xs.mean()), "y": float(ys.mean()),
                    "filled": False, "px": int(area),
                    "aspect": float(aspect), "solid": float(solid)})
    return out


def find_heads(ink: np.ndarray, spacing: float) -> list[dict]:
    """머리 전부 (꽉 찬 것 + 속 빈 것), x순 정렬"""
    heads = find_filled_heads(ink, spacing) + find_hollow_heads(ink, spacing)
    heads.sort(key=lambda d: d["x"])
    return heads


def heads_of_staff(ink: np.ndarray, st, spacing: float,
                   exclude: list[dict] | None = None,
                   lyric_band: tuple[int, int] | None = None,
                   head_end: int | None = None,
                   chord_bottom: float | None = None,
                   strict: np.ndarray | None = None) -> list[dict]:
    """
    한 단의 음표 머리만 찾는다.

    침식은 머리를 정확히 집어내지만 **쉼표·마디선·글자 구멍**도 같이 잡는다
    (실측: 단0에서 46개 중 실제 음표는 7개). 그것들은 우리가 이미 따로
    검출하고 있으니 잉크에서 지우고 시작한다:
      · 마디선·쉼표 → find_fixed_objects 결과
      · 코드 글자   → 오선 위쪽 밴드를 아예 안 본다
      · 가사        → find_lyric_band 결과
    """
    h, w = ink.shape
    top = max(0, int(st.top - spacing * 3.0))
    bot = min(h, int(st.bottom + spacing * 3.0))
    if chord_bottom is not None:
        # 코드 글자는 오선 위에 뜬다. 그 아래부터 본다 — 글자 속 구멍(‘B’의
        # 눈, 윗첨자 ‘o’)이 속 빈 머리로 잡히는 걸 막는다.
        top = max(top, int(chord_bottom) + 1)
    if lyric_band:
        # 멜로디는 덧줄로 오선 아래 두 칸까지 내려간다(실측: 단0 첫 음 C4).
        # 가사 띠가 바로 붙어 있어도 그만큼은 반드시 본다 — 가사 글자는
        # 아래 폭·채움률 검사에서 떨어진다.
        bot = min(bot, max(int(st.bottom + spacing * 2.2), lyric_band[0] - 1))
    left = int(head_end) if head_end is not None else int(st.left + spacing * 10)
    right = min(w, int(st.right) + 1)
    if right <= left or bot <= top:
        return []

    work = ink[top:bot, left:right].copy()
    # 마디선은 얇아서 상자만 지우면 침식 씨앗이 가장자리에 남는다. 넉넉히 지운다.
    pad = max(2, int(round(spacing * 0.35)))
    for o in (exclude or []):
        y0 = max(top, o["y"] - pad) - top
        y1 = min(bot, o["y"] + o["h"] + pad) - top
        x0 = max(left, o["x"] - pad) - left
        x1 = min(right, o["x"] + o["w"] + pad) - left
        if y1 > y0 and x1 > x0:
            work[y0:y1, x0:x1] = False

    raw = [{"x": hd["x"] + left, "y": hd["y"] + top,
            "filled": hd["filled"], "px": hd["px"]}
           for hd in find_heads(work, spacing)]

    # 가까운 씨앗 병합. 8분음표 깃발처럼 두툼한 곡선이 머리 옆에 씨앗을
    # 하나 더 남긴다(실측: 한 음표에 3개까지 잡혔다). 실제 머리끼리는
    # 가로로 최소 0.7칸은 떨어져 있다.
    # **가로 폭으로 거른다.** 머리는 한 칸 남짓 넓고 마디선·기둥은 얇다.
    # 오선 행 위에서 재면 줄 전체가 한 덩어리로 이어지므로 그 행은 건너뛰고,
    # 머리 높이 안 여러 행의 중앙값을 쓴다.
    line_rows = set()
    for a, b in st.spans:
        for y in range(int(a) - 1, int(b) + 2):
            line_rows.add(y)
    half = max(1, int(round(spacing * 0.30)))
    wide = []
    for hd in raw:
        cy = int(round(hd["y"]))
        cx = int(round(hd["x"] - left))
        runs = []
        for y in range(cy - half, cy + half + 1):
            if y in line_rows:
                continue
            ry = y - top
            if not (0 <= ry < work.shape[0] and 0 <= cx < work.shape[1]):
                continue
            row = work[ry]
            if not row[cx]:
                continue
            x0 = cx
            while x0 - 1 >= 0 and row[x0 - 1]:
                x0 -= 1
            x1 = cx
            while x1 + 1 < row.size and row[x1 + 1]:
                x1 += 1
            runs.append(x1 - x0 + 1)
        if not runs:
            continue
        runs.sort()
        run = runs[len(runs) // 2]
        # 실측 분포(3배 확대, spacing 19): 진짜 머리 2.2칸 / 마디선·기둥 0.4칸.
        # 상한은 두지 않는다 — 빔으로 붙은 머리는 옆 머리까지 런이 이어져
        # 3칸을 넘는데(실측: Dm7 묶음 전체가 상한 2.6칸에 걸려 빠졌다),
        # 그런 잔여물은 아래 채움률에서 걸린다.
        # 표본이 몇 줄 안 되면 오선 사이에 낀 잡티다.
        # 줄 위에 놓인 머리는 오선 행을 빼고 나면 표본이 5줄까지 준다
        # (실측: Dm7 묶음 머리 전부 표본 5로 기준 6에 걸려 빠졌다).
        # 하한도 조판마다 다르다 — 실측: 마커스 인쇄본 머리 2.21칸,
        # 위싱 콘티 1.39칸. 마디선·기둥(0.4칸)만 떨궈내면 된다.
        if not (len(runs) >= 4 and run >= spacing * 0.80):
            continue
        # **채움률.** 꽉 찬 머리는 머리 크기 상자가 통째로 잉크다. 꼬리(깃발)·
        # 빔·이음줄 잔여는 굽은 획이라 상자에 빈 곳이 남는다. 실측(단0, 3배):
        # 진짜 머리 6개 전부 1.00 / 나머지 25개 전부 0.95 이하로 딱 갈린다.
        # 오선을 지운 그림에서 재면 줄 위 머리가 잘려 값이 떨어지므로 잉크로 잰다.
        # ⚠️ 이 상자 크기가 **조판 사이 이식성의 벽**이다.
        # 칸(spacing) 기준으로 고정하면 머리가 작은 조판에서 전멸한다
        # (실측: 위싱 콘티, 머리 1.39칸 → 씨앗 30개 전부 0.97 미만, 검출 0개).
        # 그렇다고 방금 잰 run 기준으로 바꾸면 빔으로 이어진 머리는 run이
        # 옆 머리까지 이어져 상자가 과대해진다 (실측: 마커스 단당 7~18개
        # → 2~7개로 후퇴). run은 머리 폭이 아니라 '이어진 잉크 폭'이다.
        # 두 악보를 동시에 만족하는 고정 문턱을 찾지 못했다. 학습 기반
        # 검출기로 대체할 지점.
        rw = int(round(spacing * 0.80))
        rh = int(round(spacing * 0.55))
        cyy = int(round(hd["y"]))
        cxx = int(round(hd["x"]))
        box = ink[max(0, cyy - rh):cyy + rh + 1, max(0, cxx - rw):cxx + rw + 1]
        if box.size == 0:
            continue
        fill = float(box.mean())
        # 속 빈 머리(2분·온음표)는 정의상 가운데가 비어 있으니 이 검사를 면제한다.
        if hd["filled"] and fill < 0.97:
            continue
        hd["fill"] = fill
        hd["run"] = run
        wide.append(hd)
    raw = wide

    raw.sort(key=lambda d: -d["px"])
    kept: list[dict] = []
    for hd in raw:
        near = False
        for k in kept:
            if (abs(hd["x"] - k["x"]) < spacing * 0.7
                    and abs(hd["y"] - k["y"]) < spacing * 0.6):
                near = True
                break
        if not near:
            kept.append(hd)
    kept.sort(key=lambda d: d["x"])
    return kept


def pitch_step(y: float, st, spacing: float) -> int:
    """머리 y좌표 → 맨 윗줄(F5)을 0으로 한 반칸 단위 계단값. **뺄셈이다.**"""
    top_mid = (st.spans[0][0] + st.spans[0][1]) / 2.0
    return int(round((y - top_mid) / (spacing / 2.0)))


STEP_NAMES = ["F5", "E5", "D5", "C5", "B4", "A4", "G4", "F4", "E4",
              "D4", "C4", "B3", "A3", "G3", "F3"]

_LETTERS = "CDEFGAB"


def step_name(step: int) -> str:
    """
    반칸 계단값 → 음이름. 맨 윗줄이 0(F5)이고 아래로 갈수록 커진다.

    표를 찾는 대신 **계산한다.** 표는 F5~F3까지만 있어서 오선 위 덧줄
    음표(G5·A5 — 흔하다)가 "step-1" 같은 문자열이 되고, 그게 MusicXML
    음높이 파서로 들어가 깨졌다. 계산식은 범위 제한이 없다.
    """
    f5 = _LETTERS.index("F") + 5 * 7      # 절대 음도
    a = f5 - step
    return _LETTERS[a % 7] + str(a // 7)

