#!/usr/bin/env python3
"""
원본 악보에서 **가사 음절 조각**을 오려낸다.

왜 픽셀을 쓰나: 한글 가사는 LLM이 지어내고(실측: "주 이름 찬양"을
"즐거운 찬란한"으로 판독) OCR도 손글씨체에서 불안정하다. 원본 조각을
그대로 붙이면 100%다. 조각을 어느 음표 아래에 붙일지만 정하면 된다.

세 단계로 자른다 — 각각 실측으로 필요성이 확인됐다:
  ① 띠 좁히기   : 이음줄이 가사까지 내려온 단은 find_lyric_band가 음표까지
                  물고 온다. 띠 위쪽 60% 안에서 가장 깊은 골짜기 아래를 쓴다.
  ② 얇은 획 제거 : 가사 위를 지나는 이음줄 곡선이 음절들을 하나로 이어 붙인다.
                  열의 잉크 높이가 띠 높이의 0.22배를 넘어야 가사로 본다.
                  붙임표(－)도 여기서 빠지는데, 조판 엔진이 직접 그리므로 맞다.
  ③ 두 번 나누기 : 바짝 붙여 쓴 음절(통치·께순)은 0.45칸 간격으로 안 갈린다.
                  4칸을 넘는 덩어리만 0.12칸 간격으로 다시 나눈다.
실측(마커스 「내 마음 다해」 9단): 음절 125개, 붙은 것 0개.
"""

from __future__ import annotations

import numpy as np


def _runs(on: np.ndarray, gap: int, min_w: float) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = None
    blank = 0
    for x, v in enumerate(on):
        if v:
            if start is None:
                start = x
            blank = 0
        elif start is not None:
            blank += 1
            if blank >= gap:
                out.append((start, x - blank))
                start = None
    if start is not None:
        out.append((start, len(on) - 1))
    return [(a, b) for a, b in out if b - a >= min_w]


def tighten(ink: np.ndarray, band: tuple[int, int],
            spacing: float) -> tuple[int, int]:
    """띠 위쪽 60%에서 가장 깊은 골짜기를 찾아 그 아래만 남긴다."""
    y0, y1 = band
    rows = ink[y0:y1, :].sum(axis=1).astype(int)
    if rows.max() <= 0:
        return band
    limit = max(1, int(len(rows) * 0.60))
    m = int(np.argmin(rows[:limit]))
    if rows[m] < rows.max() * 0.25 and (y1 - (y0 + m)) > spacing * 2.0:
        return y0 + m + 1, y1
    return band


def syllables(ink: np.ndarray, band: tuple[int, int],
              spacing: float) -> list[tuple[int, int]]:
    """
    좁힌 띠에서 음절 x구간 목록을 낸다.

    붙어 있는 음절을 가르는 게 어려운 부분이다. 처음엔 **더 작은 간격으로
    다시 훑는** 방식이었는데, 한글에서 실패했다 — 초성·중성·종성 사이에도
    1px 틈이 생겨 "난"이 "ㄴ"으로, "에"가 "ㅣㅣ"로 쪼개졌다(실측: 위싱 콘티
    재조판에서 가사가 자모 조각으로 나왔다).

    그래서 **간격이 아니라 음절 폭으로 나눈다.** 한 줄 안의 한글 음절 폭은
    거의 일정하므로, 혼자 떨어져 있는 덩어리에서 대표 폭을 구하고 붙어 있는
    덩어리를 그 폭으로 등분한다. 자모 틈에 걸리지 않는다.
    """
    y0, y1 = tighten(ink, band, spacing)
    col = ink[y0:y1, :].sum(axis=0)
    # **잉크가 있으면 켠다.** 예전엔 "열의 22%가 잉크"를 조건으로 썼는데
    # 한글에서 실패했다 — 가로 획은 한두 줄만 차지하므로 세로 획만 남고,
    # 오려낸 조각이 음절의 3분의 2만 담겼다(실측: 위싱 콘티에서 폭 8px,
    # 실제 음절 14px). 붙어 있는 음절은 아래 폭 기준 분할이 가른다.
    on = col > 1
    runs = _runs(on, max(2, int(spacing * 0.45)), spacing * 0.25)
    if not runs:
        return []

    # 대표 음절 폭 — 한 음절짜리로 보이는 덩어리들의 중앙값.
    # `-` 연장선은 낮고 좁아서 제외해야 하는데, 폭 하한으로 걸러진다.
    singles = [b - a for a, b in runs
               if spacing * 0.8 <= (b - a) <= spacing * 2.3]
    if singles:
        singles.sort()
        w1 = singles[len(singles) // 2]
    else:
        w1 = spacing * 1.6

    out: list[tuple[int, int]] = []
    for a, b in runs:
        w = b - a
        n = int(round(w / w1)) if w1 > 0 else 1
        if n <= 1 or w < w1 * 1.6:
            out.append((a, b))
            continue
        step = w / n
        for i in range(n):
            out.append((a + int(round(i * step)),
                        a + int(round((i + 1) * step))))
    return out


def band_of(ink: np.ndarray, band: tuple[int, int], spacing: float,
            pad_below: bool = True) -> tuple[int, int]:
    """
    좁힌 띠. pad_below면 **글자 아래가 잘리지 않도록** 잉크가 끝날 때까지
    아래로 늘린다 — find_lyric_band 는 두 단 사이 중간에서 끊으므로
    받침이 있는 음절(삶·옵·붙)의 아래가 잘리는 경우가 있다.
    """
    # **tighten 을 더 쓰지 않는다.** 원래는 띠 위쪽의 가사 아닌 줄을 떼려고
    # "위 60% 에서 가장 깊은 골짜기 아래만 남기기"를 했는데, `find_lyric_band`
    # 가 이제 덩어리 단위로 가사만 골라 주므로 필요 없고, **1·2절 두 줄
    # 가사에서는 줄 사이 골짜기를 잘라 2절을 통째로 버린다**(실측
    # now0918-1 단2: 6.8칸 → 3.8칸).
    y0, y1 = band
    if not pad_below:
        return y0, y1
    h = ink.shape[0]
    limit = min(h, y1 + int(spacing * 1.2))
    y = y1
    while y < limit and ink[y].any():
        y += 1
    # 잉크가 끊긴 뒤 한 줄 여유
    return y0, min(h, y + 1)
