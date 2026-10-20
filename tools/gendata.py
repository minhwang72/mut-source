#!/usr/bin/env python3
"""
학습용 악보와 **정답 상자**를 함께 만든다.

착상: MusicXML을 Verovio로 그리면 우리가 **모든 기호의 위치와 종류를 이미
알고 있다.** 라벨링 노동이 0이고, 원하는 만큼 만들 수 있다.

왜 필요한가: 손으로 맞춘 문턱값은 조판을 넘으면 무너진다 — 실측으로
마커스 악보(머리 폭 2.21칸)에서 단당 7~18개 잡던 검출기가 위싱 콘티
(1.39칸)에서 0~1개로 전멸했다. 두 악보를 동시에 만족하는 고정 문턱은
찾지 못했다. 그래서 학습으로 대체한다.

핵심은 **조판을 흔드는 것**이다. 한 스타일로만 만들면 지금과 같은 이식성
문제를 그대로 반복한다. Verovio가 노출하는 손잡이를 무작위로 돌린다:
  · font        — Leipzig / Bravura / Petaluma / Gootville / Leland
                  (머리 모양과 크기 비율이 폰트마다 다르다 — 바로 그 변수)
  · unit        — 오선 간격
  · staffLineWidth · stemWidth · barLineWidth — 인쇄 굵기
  · lyricSize   — 가사 크기 비율
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import musicxml as M  # noqa: E402
from musicxml import DIVISIONS, DUR  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}"

# SMuFL 코드포인트 → 학습 클래스.
# 코드포인트로 라벨을 붙이면 사람이 판단할 여지가 없다.
# SMuFL 표준 코드포인트 → 학습 클래스.
# 코드포인트로 라벨을 붙이면 사람이 판단할 여지가 없다.
# ⚠️ 처음에 E4E5를 점(dot)으로, E4E6을 16분쉼표로 잘못 매핑했다. 표준은
#    E4E5=16분쉼표, E4E6=32분쉼표다. 라벨이 틀리면 학습이 오염되므로
#    실제 렌더에 나온 코드를 전부 뽑아 대조한 값이다.
GLYPH_CLASS = {
    # 머리
    "E0A2": "notehead_whole",
    "E0A3": "notehead_half",
    "E0A4": "notehead_filled",
    # 깃발 — 음가를 읽는 데 직접 쓰인다
    "E240": "flag_8th", "E241": "flag_8th",
    "E242": "flag_16th", "E243": "flag_16th",
    # 임시표
    "E260": "accidental_flat",
    "E261": "accidental_natural",
    "E262": "accidental_sharp",
    # 쉼표 — **실제 렌더로 대조한 값**이다. SMuFL 표를 기억으로 쓰면
    # 두 칸씩 어긋난다(처음에 E4E5를 16분쉼표로 잘못 넣었는데 4분쉼표였다).
    "E4E3": "rest_whole", "E4E4": "rest_half", "E4E5": "rest_quarter",
    "E4E6": "rest_8th", "E4E7": "rest_16th",
    # 음자리표 — 우리 제품은 높은음자리표 한 단짜리 악보만 다루므로
    # 낮은음자리표는 만들지도, 배우지도 않는다.
    "E050": "clef_g",
}

# 글리프가 아닌 **구조 요소**. Verovio가 도형으로 그리므로 코드포인트가 없고,
# bounding-box 사각형을 그대로 쓴다.
#   · barLine — 마디를 나누는 데 필요하다. MusicXML 조립의 전제다.
# (syl(가사 음절)은 상자에 rect가 없어 이 방법으로 못 딴다.)
#
# 빔은 여기서 다루지 않는다. bounding-box 를 그대로 쓰면 8분음표 한 겹과
# 16분음표 두 겹이 **같은 상자 하나**가 되어 겹수를 잃는다(실측: 실제 악보에서
# flag_16th·겹빔 검출 0개, 음가 정확도 84% 한계). beam_boxes()가 폴리곤을
# 직접 읽어 겹수별로 나눈다.
#   · dots    — 붙임점. 글리프가 아니라 도형이라 코드포인트가 없다.
#               점 하나가 음가를 1.5배로 바꾸므로 박자 검산에 반드시 필요하다.
#               상자가 아주 작다(오선 간격의 0.4배). 검출이 되는지는
#               학습 뒤 실측으로 확인해야 한다.
# tie·slur 는 같은 곡선이라 **한 클래스**로 배운다. 붙임줄인지
# 슬러인지는 판독할 때 양 끝 음높이가 같은가로 가른다.
STRUCT_CLASS: dict[str, str] = {"dots": "aug_dot", "tie": "tie",
                                "slur": "tie"}
# 박자표 숫자 E080~E089 는 한 클래스로 묶는다
for _d in range(10):
    GLYPH_CLASS[f"E08{_d}"] = "timesig"


def _transform_of(el) -> tuple[float, float, float, float]:
    """요소의 transform에서 (tx, ty, sx, sy)만 뽑는다. 회전은 쓰지 않는다."""
    t = el.get("transform") or ""
    tx = ty = 0.0
    sx = sy = 1.0
    m = re.search(r"translate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)", t)
    if m:
        tx, ty = float(m.group(1)), float(m.group(2))
    m = re.search(r"scale\(\s*(-?[\d.]+)(?:[ ,]+(-?[\d.]+))?", t)
    if m:
        sx = float(m.group(1))
        sy = float(m.group(2)) if m.group(2) else sx
    return tx, ty, sx, sy


def _poly_span(pts: str):
    """빔 폴리곤 한 장을 (x0, x1, 위모서리, 아래모서리) 선분으로 바꾼다."""
    xy = [tuple(map(float, q.split(","))) for q in pts.split() if "," in q]
    if len(xy) < 4:
        return None
    x0, x1 = min(p[0] for p in xy), max(p[0] for p in xy)
    if x1 - x0 < 1e-6:
        return None
    left = sorted(p[1] for p in xy if p[0] - x0 < (x1 - x0) * 0.5)
    right = sorted(p[1] for p in xy if p[0] - x0 >= (x1 - x0) * 0.5)
    if not left or not right:
        return None
    return x0, x1, (left[0], right[0]), (left[-1], right[-1])


def _at(x, x0, x1, ends):
    """기울어진 빔의 x 지점 y를 선형으로 구한다."""
    t = (x - x0) / (x1 - x0)
    return ends[0] + (ends[1] - ends[0]) * t


def beam_boxes(root, absolute) -> list[dict]:
    """
    빔을 **겹수별 구간**으로 라벨한다.

    Verovio는 겹빔을 폴리곤 여러 장으로 그린다 — 16분음표 네 개 묶음이면
    전체를 덮는 한 겹 + 짝마다 둘째 겹 세 조각. 그룹 전체를 상자 하나로
    잡으면 한 겹과 두 겹이 구별되지 않으므로, 폴리곤들의 x 경계로 잘라
    구간마다 **덮는 폴리곤 수 = 겹수**를 센다. 붙임점 8분 + 16분처럼 둘째
    겹이 반쪽만 있는 경우도 그 반쪽만 beam2 가 된다.

    y는 폴리곤의 전체 높이가 아니라 **그 구간의 y**를 선형으로 계산한다.
    기울어진 빔에서 전체 높이를 쓰면 좁은 구간에 세로로 긴 상자가 붙는다.
    """
    out: list[dict] = []
    for g in root.iter(f"{SVG}g"):
        if "beam" not in (g.get("class") or "").split():
            continue
        polys = []
        for poly in g.iter(f"{SVG}polygon"):
            sp = _poly_span(poly.get("points") or "")
            if not sp:
                continue
            x0, x1, top, bot = sp
            ax0, ay0, aw, ah = absolute(poly, x0, top[0], x1 - x0, 0.0)
            ax1 = ax0 + aw
            # y는 스케일·이동만 받으므로 두 끝을 따로 옮긴다
            _, at0, _, _ = absolute(poly, x0, top[0], 0.0, 0.0)
            _, at1, _, _ = absolute(poly, x1, top[1], 0.0, 0.0)
            _, ab0, _, _ = absolute(poly, x0, bot[0], 0.0, 0.0)
            _, ab1, _, _ = absolute(poly, x1, bot[1], 0.0, 0.0)
            polys.append((min(ax0, ax1), max(ax0, ax1), (at0, at1), (ab0, ab1)))
        if not polys:
            continue

        edges = sorted({e for p in polys for e in (p[0], p[1])})
        runs: list[tuple[float, float, int, float, float]] = []
        for a, b in zip(edges, edges[1:]):
            if b - a < 1e-6:
                continue
            mid = (a + b) / 2
            cov = [p for p in polys if p[0] - 1e-6 <= mid <= p[1] + 1e-6]
            if not cov:
                continue
            ys = []
            for x0, x1, top, bot in cov:
                ys += [_at(a, x0, x1, top), _at(b, x0, x1, top),
                       _at(a, x0, x1, bot), _at(b, x0, x1, bot)]
            runs.append((a, b, len(cov), min(ys), max(ys)))

        # 겹수가 같고 맞닿은 구간은 상자 하나로 합친다 (그룹 안에서만)
        merged: list[list] = []
        for a, b, lv, y0, y1 in runs:
            if merged and merged[-1][2] == lv and abs(merged[-1][1] - a) < 1e-6:
                m = merged[-1]
                m[1], m[3], m[4] = b, min(m[3], y0), max(m[4], y1)
                continue
            merged.append([a, b, lv, y0, y1])
        for a, b, lv, y0, y1 in merged:
            out.append({"class": f"beam{min(lv, 2)}", "glyph": "",
                        "x": a, "y": y0, "w": b - a, "h": y1 - y0})
    return out


def symbols(svg: str) -> list[dict]:
    """
    렌더된 SVG에서 기호 상자를 뽑는다. 좌표는 **viewBox 기준 절대값**.

    Verovio는 svgBoundingBoxes 옵션을 켜면 요소마다
    `<g class="note bounding-box"><rect .../></g>` 를 넣어 준다.
    글리프 종류는 `<use xlink:href="#E0A4-...">` 코드포인트로 알 수 있다.

    두 가지를 반드시 챙겨야 한다 — 둘 다 실측으로 드러났다:
      · **글리프마다 가장 가까운 조상의 상자**를 짝짓는다. 그룹의 첫 글리프만
        보면 조표의 ♭ 두 개, 박자표 숫자 두 개가 하나로 세어진다.
      · **조상의 transform을 누적**한다. Verovio는 내용을 page-margin
        그룹에 담고 translate(500, 500)을 건다. 안 더하면 상자가 통째로
        어긋난다(실측: 상자가 기호 위쪽으로 떠 있었다).
    """
    root = ET.fromstring(svg)
    parent = {c: p for p in root.iter() for c in p}
    box_of = {}
    for el in root.iter():
        for c in el:
            if "bounding-box" in c.get("class", ""):
                r = c.find(f"{SVG}rect")
                if r is not None:
                    box_of[el] = r
                break

    def absolute(el, x, y, w, h):
        node = parent.get(el)
        while node is not None:
            tx, ty, sx, sy = _transform_of(node)
            x, y = x * sx + tx, y * sy + ty
            w, h = w * sx, h * sy
            node = parent.get(node)
        return x, y, w, h

    out: list[dict] = beam_boxes(root, absolute)

    for el, r in box_of.items():
        name = STRUCT_CLASS.get((el.get("class") or "").split()[0]
                                if el.get("class") else "")
        if not name or r.get("width") is None:
            continue
        x, y, w, h = absolute(r, float(r.get("x")), float(r.get("y")),
                              float(r.get("width")), float(r.get("height")))
        out.append({"class": name, "glyph": "", "x": x, "y": y,
                    "w": abs(w), "h": abs(h)})

    for use in root.iter(f"{SVG}use"):
        href = use.get(f"{XLINK}href") or use.get("href") or ""
        m = re.match(r"#([0-9A-F]{4})-", href)
        if not m:
            continue
        name = GLYPH_CLASS.get(m.group(1))
        if not name:
            continue
        node = use
        holder = None
        while node is not None:
            if node in box_of:
                holder = node
                break
            node = parent.get(node)
        if holder is None:
            continue
        r = box_of[holder]
        x, y, w, h = absolute(r, float(r.get("x")), float(r.get("y")),
                              float(r.get("width")), float(r.get("height")))
        out.append({"class": name, "glyph": m.group(1),
                    "x": x, "y": y, "w": abs(w), "h": abs(h)})

    # 한 상자를 여러 글리프가 나눠 쓰는 경우가 있다 — 박자표는 숫자 두 개가
    # meterSig 그룹 하나에 들어가 같은 상자를 받는다(실측: 라벨이 그대로
    # 두 줄 중복됐다). 같은 상자는 하나로 친다.
    seen = set()
    uniq = []
    for b in out:
        key = (b["class"], round(b["x"], 1), round(b["y"], 1),
               round(b["w"], 1), round(b["h"], 1))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(b)
    return uniq


# ── 무작위 악보 만들기 ────────────────────────────────────────────
# 학습 데이터의 다양성은 두 축이다: **내용**(음높이·음가·조표·임시표)과
# **조판**(폰트·간격·굵기). 내용만 흔들면 조판 이식성 문제가 그대로 남는다.

DURATIONS = ["whole", "half", "quarter", "eighth", "16th"]
# **분포가 아니라 표본 수로 맞춘다.** 실제 악보 분포(8분음표 최다)를 그대로
# 쓰면 온음표는 마디를 혼자 채우므로 머리 1개, 8분음표는 8개가 나온다.
# 실측: 그렇게 만든 학습셋의 클래스 수가 꽉찬 155,854 · 흰 11,054 · 온 956개로
# **온음표가 163배 적었고**, 마커스 악보의 온음표 검출이 0개였다.
# 흰 머리·온음표 가중치를 올려 표본 수를 학습 가능한 수준으로 끌어올린다.
DUR_WEIGHT = [9, 13, 10, 14, 5]
PITCH_POOL = [f"{s}{o}" for o in (3, 4, 5) for s in "CDEFGAB"]
# 코드 글자는 검출 대상이 아니라 **오선 위 배경 잡음**으로만 쓴다.
# ♭·♯이 붙은 근음은 Verovio가 음악 폰트 글리프로 그리는데, 래스터라이저에
# 그 폰트가 없으면 두부 글자(□)가 되어 잘못된 모양을 배운다. 제자리음만 쓴다.
CHORD_ROOTS = ["C", "D", "E", "F", "G", "A", "B"]
CHORD_TAILS = ["", "m", "7", "m7", "maj7", "sus4", "2", "m7b5", "dim"]
# 실제 입력에는 **항상 가사가 있다.** 없이 학습하면 가사가 있는 진짜 악보에서
# 음표와 글자를 못 가른다. 찬양 가사에 흔한 음절을 쓴다.
SYLLABLES = list("주님사랑은혜찬양감사영광거룩능력믿음소망평강생명빛길진리"
                 "예수구원십자가부활성령아버지하늘땅새노래기쁨자유회복")


BEAMABLE = {"eighth": 1, "16th": 2}


# 빔 묶기는 musicxml.add_beams 를 쓴다 — 학습 데이터와 실제 변환이
# 같은 규칙이어야 그림이 어긋나지 않는다.
_beam = M.add_beams


def _stack(notes, rng, rate: float) -> None:
    """
    **화음을 쌓는다.** 콘티는 멜로디 한 줄이지만 간주·엔딩 스트립에는 2~3음이
    쌓인 마디가 있다(실측: 74장 중 15장). 학습 데이터가 멜로디뿐이라 검출기가
    화음 머리를 통째로 못 보고, 그래서 그 단의 리듬이 깨진다.

    빔·가사·곡선을 다 붙인 **뒤에** 끼운다 — 구성음은 기둥과 빔을 base 와
    나눠 쓰므로 자기 빔을 가지면 안 되고, 가사도 묶음당 하나여야 한다.
    """
    if rate <= 0:
        return
    for i in range(len(notes) - 1, -1, -1):
        n = notes[i]
        if n["pitch"] is None or n.get("chord") or rng.random() >= rate:
            continue
        # **곡선이 걸린 음은 건드리지 않는다.** 붙임줄·슬러는 _curves 에서
        # **인접한 두 음**으로 짝지어지는데, 그 사이에 구성음을 끼우면 짝이
        # 끊긴다(실측: "1 tie left open" 경고). 라벨이 틀린 표본을 만드느니
        # 그 음만 화음에서 뺀다.
        if any(n.get(k) for k in ("tie", "tie_stop", "slur", "slur_stop")):
            continue
        # 다음 음이 이 음에 걸려 있으면(붙임줄 끝·슬러 끝) 사이를 벌릴 수 없다
        if i + 1 < len(notes) and any(
                notes[i + 1].get(k) for k in ("tie_stop", "slur_stop")):
            continue
        try:
            base = PITCH_POOL.index(n["pitch"].replace("#", "").replace("b", ""))
        except ValueError:
            continue
        # 3도·5도 아래 — 실제 보이싱에 가깝게
        for step in rng.choice([[2], [4], [2, 4], [2, 5]]):
            j = base - step
            if j < 0:
                continue
            notes.insert(i + 1, {"pitch": PITCH_POOL[j],
                                 "duration": n["duration"],
                                 "dotted": n.get("dotted", False),
                                 "chord": True})


def random_score(rng, measures: int = 4,
                 chord_rate: float = 0.0) -> tuple[list[dict], int]:
    """마디 몇 개짜리 무작위 멜로디. (measures, fifths) 반환."""
    fifths = rng.randint(-5, 5)
    bar = DIVISIONS * 4
    out = []
    cur = rng.randrange(len(PITCH_POOL))
    for _ in range(measures):
        # 온쉼표는 **마디 전체가 빈 경우**에만 나온다. 음표로 마디를 채우는
        # 방식만 쓰면 표본이 하나도 안 생긴다.
        if rng.random() < 0.08:
            out.append({"notes": [{"pitch": None, "duration": "whole"}]})
            continue
        notes = []
        used = 0
        while used < bar:
            dur = rng.choices(DURATIONS, weights=DUR_WEIGHT)[0]
            d = DUR[dur]
            dotted = rng.random() < 0.12 and dur not in ("whole", "16th")
            if dotted:
                d = d * 3 // 2
            if used + d > bar:
                continue
            if rng.random() < 0.10:          # 쉼표
                notes.append({"pitch": None, "duration": dur, "dotted": dotted})
            else:
                # **순차 진행에 가깝게 움직인다.** 완전 무작위로 뽑으면 덧줄이
                # 과하게 많은 비현실적 조판이 되어, 실제 악보와 배치 분포가
                # 어긋난다.
                cur = max(0, min(len(PITCH_POOL) - 1,
                                 cur + rng.choice([-3, -2, -1, -1, 0, 1, 1, 2, 3])))
                p = PITCH_POOL[cur]
                # **임시표를 일부러 섞는다.** 조표만으로는 ♯·♭·♮ 표본이
                # 부족해 검출기가 그 글리프를 못 배운다.
                r = rng.random()
                if r < 0.12:
                    p = p[0] + rng.choice(["#", "b"]) + p[1:]
                notes.append({"pitch": p, "duration": dur, "dotted": dotted,
                              "tie": rng.random() < 0.10,
                              # ♮ 취소표도 배워야 한다
                              "natural": r >= 0.12 and r < 0.18,
                              "lyric": rng.choice(SYLLABLES)})
            used += d
        _beam(notes)
        _curves(notes, rng)
        _words(notes, rng)
        _stack(notes, rng, chord_rate)
        m = {"notes": notes}
        if rng.random() < 0.7:
            m["chords"] = [rng.choice(CHORD_ROOTS) + rng.choice(CHORD_TAILS)]
        out.append(m)
    return out, fifths


# ── 조판 흔들기 ──────────────────────────────────────────────────
# 폰트마다 머리 크기와 오선 간격의 비율이 다르다. 손으로 맞춘 문턱값이
# 조판을 넘어 무너진 원인이 정확히 이 비율이었으므로, 여기를 넓게 흔든다.
FONTS = ["Leipzig", "Bravura", "Petaluma", "Gootville", "Leland"]
# 가사에 쓸 한글 폰트 (렌더 환경에 있어야 한다)
TEXT_FONT = "AppleGothic"


def _curves(notes, rng) -> None:
    """
    **붙임줄은 같은 음높이를 잇는다.** 무작위로 tie를 켜면 다른 음끼리
    이어져 음악적으로 불가능한 표본이 되고, 판독 때 쓰는 "양 끝이 같은
    음높이면 붙임줄" 규칙을 배울 수 없다.

    슬러(다른 음을 잇는 곡선)도 같이 만든다. 검출기에는 **같은 클래스**로
    보이지만, 폭이 넓은 곡선 표본이 생겨야 실제 악보의 슬러에 안 흔들린다.
    """
    real = [i for i, n in enumerate(notes) if n.get("pitch")]
    # 마디 마지막 음의 붙임줄은 이을 상대가 이 마디에 없다 (이 함수는 마디
    # 단위로 돈다). 라벨을 정직하게 두려고 지운다.
    if real:
        notes[real[-1]].pop("tie", None)
    for a, b in zip(real, real[1:]):
        if not notes[a].get("tie"):
            continue
        if b != a + 1:                  # 사이에 쉼표가 있으면 붙임줄이 아니다
            notes[a].pop("tie", None)
            continue
        notes[b]["pitch"] = notes[a]["pitch"]
        notes[b]["tie_stop"] = True
        # 이어진 음에는 가사를 붙이지 않는다 (한 음절을 끄는 것이므로)
        notes[b].pop("lyric", None)
    # 슬러 — 2~4음을 덮는다
    i = 0
    while i < len(real) - 1:
        if rng.random() < 0.14:
            span = min(rng.choice([2, 2, 3, 4]), len(real) - i)
            a, b = real[i], real[i + span - 1]
            if b > a and not notes[a].get("tie"):
                notes[a]["slur"] = True
                notes[b]["slur_stop"] = True
                i += span
                continue
        i += 1


def _words(notes, rng) -> None:
    """
    가사를 **낱말로 묶는다.**

    음절마다 따로 두면 Verovio가 하이픈도 늘임줄도 그리지 않는다. 그런데
    실제 한글 악보는 "사 - 랑 - 하 -"처럼 가로 이음표가 줄줄이 있고,
    한 음절을 길게 끄는 곳에는 긴 가로줄(늘임줄)이 붙는다.

    **이 가로줄들이 빔과 똑같이 생겼다.** 학습 데이터에 없으면 검출기가
    겹빔으로 센다 — 실측: 위싱 악보에서 가사 위쪽 흐릿한 이음표 줄을
    beam2로 잡아(0.64·0.67) 8분음표 5개가 16분음표가 됐다.
    """
    idx = [i for i, n in enumerate(notes) if n.get("lyric")]
    i = 0
    while i < len(idx):
        n = rng.choices([1, 2, 3, 4], weights=[38, 34, 18, 10])[0]
        grp = idx[i:i + n]
        for k, j in enumerate(grp):
            if len(grp) == 1:
                notes[j]["syllabic"] = "single"
            elif k == 0:
                notes[j]["syllabic"] = "begin"
            elif k == len(grp) - 1:
                notes[j]["syllabic"] = "end"
            else:
                notes[j]["syllabic"] = "middle"
        i += n
        # **늘임줄을 만들려면 뒤 음에서 가사를 빼야 한다.** 모든 음에 가사가
        # 붙어 있으면 Verovio가 끌 자리가 없어 선을 안 그린다. 한 음절을
        # 다음 한두 음까지 끄는 형태로 만든다 — 그때 나오는 **긴 가로줄**이
        # 빔과 가장 닮았다.
        if grp and rng.random() < 0.25 and i < len(idx):
            hold = min(rng.choice([1, 1, 2]), len(idx) - i)
            notes[grp[-1]]["extend"] = True
            for j in idx[i:i + hold]:
                notes[j].pop("lyric", None)
                notes[j].pop("syllabic", None)
            i += hold


def random_style(rng) -> dict:
    return {
        "font": rng.choice(FONTS),
        "unit": rng.randint(6, 11),              # 오선 간격의 기본 단위
        # 실측: 위싱 콘티 0.22칸 / 마커스 0.33칸. 굵은 쪽까지 덮어야 한다
        # 실측 0.158~0.333칸이지만 **중앙이 0.169로 얇은 쪽에 몰려 있다.**
        # 균등분포로 뽑으면 합성 중앙이 0.229가 되어 실제보다 굵어진다.
        # 제곱으로 얇은 쪽에 치우치게 하고 굵은 꼬리는 남긴다.
        # Verovio 상한이 0.300이다. 넘기면 오류만 찍고 **기본값 0.150으로
        # 되돌아가서** 굵기 다양화가 조용히 절반만 작동한다(실측).
        "staffLineWidth": round(min(0.300, 0.13 + 0.22 * rng.random() ** 1.5), 3),
        "stemWidth": round(rng.uniform(0.13, 0.38), 3),
        "barLineWidth": round(rng.uniform(0.20, 0.40), 3),
        # 실측 가사 띠 2.50~6.67칸. Verovio 상한이 8.0이라 그 안에서 넓힌다.
        # (실측 상위값은 가사가 2절인 쪽에서 나온 것으로 보인다 — 여기서는
        #  1절만 만들므로 완전히 덮지는 못한다. 가사는 검출 대상이 아니라
        #  배경 잡음이므로 이 정도로 둔다.)
        "lyricSize": round(rng.uniform(3.2, 7.5), 2),
        # **가사를 오선에 바짝 붙여 본다.** 붙으면 이음표 줄이 빔 바로 옆에
        # 오는데, 그게 정확히 오검출이 나던 배치다
        "lyricTopMinMargin": round(rng.uniform(0.0, 3.5), 2),
        "spacingStaff": rng.randint(6, 14),
        "scale": rng.randint(30, 60),
    }


# ── 렌더 · 열화 · 내보내기 ─────────────────────────────────────────
# verovio·cairosvg·numpy는 **생성기 전용 의존성**이다. 배포되는 브라우저
# 코드에는 들어가지 않는다(코어는 여전히 의존성 0).

CLASSES = [
    "notehead_filled", "notehead_half", "notehead_whole",
    "flag_8th", "flag_16th",
    "accidental_sharp", "accidental_flat", "accidental_natural",
    "rest_whole", "rest_half", "rest_quarter", "rest_8th", "rest_16th",
    "clef_g", "timesig", "beam1", "beam2", "aug_dot", "tie",
]
# 마디선은 **일부러 뺐다.** 폭 27 : 높이 747의 극단적인 세로 막대라 960px로
# 줄면 1px가 되어 YOLO가 거의 못 찾는다(실측: mAP50 0.085, 재현율 0.044).
# 반면 고전적 영상처리는 "긴 세로 잉크 런"으로 안정적으로 찾는다
# (실측: find_fixed_objects가 단당 84~91개). 역할을 나눈다.


def render_sample(xml: str, style: dict, page_width: int = 2200):
    """MusicXML → (PNG 이미지, [기호 상자]). 상자는 **픽셀 좌표**."""
    import io
    import re as _re

    import cairosvg
    import verovio
    from PIL import Image

    base = {"pageWidth": page_width, "pageHeight": 2000,
            "adjustPageHeight": True, "header": "none", "footer": "none",
            **style}
    tk = verovio.toolkit()
    tk.setOptions({**base, "svgBoundingBoxes": True})
    if not tk.loadData(xml):
        return None, []
    syms = symbols(tk.renderToSVG(1))

    # 상자는 **라벨을 켠 렌더**에서, 그림은 **끈 렌더**에서 얻는다.
    # 켠 채로 그리면 투명 사각형이 그림에 섞인다.
    tk.setOptions({**base, "svgBoundingBoxes": False})
    svg = tk.renderToSVG(1)
    # Verovio는 글자 폰트를 "Times, serif"로 내보내는데, 그 폰트에는 한글이
    # 없어 가사가 두부 글자(□)로 그려진다. 실제 악보의 가사 모양과 달라
    # 배경 잡음을 잘못 배우게 되므로 한글 폰트로 바꿔 그린다.
    svg = svg.replace('font-family="Times, serif"',
                      f'font-family="{TEXT_FONT}"')
    vb = [float(v) for v in
          _re.search(r'viewBox="([\d\.\- ]+)"', svg).group(1).split()]
    png = cairosvg.svg2png(bytestring=svg.encode(), scale=1.0)
    im = Image.open(io.BytesIO(png))
    flat = Image.new("L", im.size, 255)
    flat.paste(im.convert("L"), mask=im.split()[-1] if im.mode == "RGBA" else None)

    k = flat.width / vb[2]
    boxes = [{"class": s["class"], "x": s["x"] * k, "y": s["y"] * k,
              "w": s["w"] * k, "h": s["h"] * k} for s in syms]
    return flat, boxes


# **사람이 더한 표시** — 실측으로 정체를 확인한 오검출원이다.
# 문턱 0.05 에서 걸러야 할 후보를 90개 잘라 보니 1/3이 음표가 아니라
# 글자·손글씨였다: 구역 표시 상자(A B A' A2 D), 코드 글자, 빨간 펜 표시,
# 주황 형광펜 띠. 지금 생성기는 코드 글자를 **오선 위에만** 그리는데,
# 실제 악보의 구역 표시는 오선을 물고 있고 형광펜은 오선을 통째로 덮는다 —
# 그 모양이 학습 데이터에 아예 없어서 검출기가 처음 본다.
#
# 이것들은 **음성 표본**이라 상자를 만들지 않는다. 머리를 지우면 양성 라벨이
# 틀려지므로, 형광펜은 곱하기(밝게)로만 덮고 획은 오선 밖을 지난다.
MARK_LETTERS = ["A", "B", "C", "A'", "B'", "A2", "1.", "2.", "D", "Intro"]
FONT_PATHS = ["/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"]


def _font(size: int):
    from PIL import ImageFont
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except Exception:                                   # noqa: BLE001
            continue
    return ImageFont.load_default()


def human_marks(img, boxes, rng):
    """오선 위에 사람이 더한 표시를 얹는다. 상자는 만들지 않는다(음성 표본)."""
    from PIL import ImageDraw

    import numpy as np

    heads = [b for b in boxes if b["class"].startswith("notehead")]
    if not heads:
        return img
    # **오선을 직접 찾는다.** 음표 높이로 잡으면 음이 높은 악보에서 띠가
    # 오선을 비껴 깔린다 — 그러면 가르칠 것이 없는 표본이 된다.
    a = np.asarray(img)
    dark = (a < 128).mean(axis=1)
    rows = np.where(dark > 0.35)[0]
    if rows.size >= 2:
        top, bot = float(rows[0]), float(rows[-1])
        sp = max(4.0, (bot - top) / 4.0)
        cols = np.where((a < 128).mean(axis=0) > 0.02)[0]
        right = float(cols[-1]) if cols.size else img.width
    else:
        top = min(b["y"] for b in heads)
        bot = max(b["y"] + b["h"] for b in heads)
        sp = max(6.0, (bot - top) / 8.0)
        right = img.width
    img = img.copy()
    d = ImageDraw.Draw(img)

    # ① 구역 표시 — 오선 왼쪽에 상자 친 글자. 오선을 물기도 한다.
    if rng.random() < 0.45:
        size = int(sp * rng.uniform(2.0, 3.2))
        f = _font(size)
        txt = rng.choice(MARK_LETTERS)
        x = rng.uniform(0, img.width * 0.10)
        y = rng.uniform(top - sp * 1.5, bot - sp * 2.0)
        pad = size * 0.25
        try:
            l, t_, r, b_ = d.textbbox((x, y), txt, font=f)
        except Exception:                                   # noqa: BLE001
            l, t_, r, b_ = x, y, x + size, y + size
        if rng.random() < 0.7:
            d.rectangle([l - pad, t_ - pad, r + pad, b_ + pad],
                        outline=rng.randint(0, 90), width=max(1, int(sp * 0.12)))
        d.text((x, y), txt, fill=rng.randint(0, 70), font=f)

    # ② 형광펜 — 오선을 통째로 덮는 옅은 띠. 곱하기라 잉크는 남는다.
    if rng.random() < 0.30:
        a = np.asarray(img).astype("float32")
        y0 = int(max(0, top - sp * rng.uniform(1.0, 3.0)))
        y1 = int(min(img.height, bot + sp * rng.uniform(1.0, 3.0)))
        x0 = int(rng.uniform(0, right * 0.3))
        x1 = int(min(img.width, rng.uniform(right * 0.6, right + sp * 2)))
        a[y0:y1, x0:x1] *= rng.uniform(0.70, 0.92)
        from PIL import Image as _I
        img = _I.fromarray(a.clip(0, 255).astype("uint8"), "L")
        d = ImageDraw.Draw(img)

    # ③ 손글씨 — 동그라미·사선·밑줄. 오선을 가로지른다.
    for _ in range(rng.choice([0, 0, 1, 1, 2])):
        ink = rng.randint(0, 110)
        w = max(1, int(sp * rng.uniform(0.15, 0.35)))
        cx = rng.uniform(right * 0.1, right * 0.95)
        cy = rng.uniform(top - sp, bot + sp)
        kind = rng.random()
        if kind < 0.4:
            rx, ry = sp * rng.uniform(1.2, 3.0), sp * rng.uniform(1.0, 2.2)
            d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=ink, width=w)
        elif kind < 0.7:
            dx, dy = sp * rng.uniform(1, 3), sp * rng.uniform(-2, 2)
            d.line([cx, cy, cx + dx, cy + dy], fill=ink, width=w)
        else:
            d.line([cx, bot + sp * 0.6, cx + sp * rng.uniform(3, 10),
                    bot + sp * 0.6], fill=ink, width=w)
    return img


def degrade(img, boxes, rng):
    """
    실제 입력을 흉내 낸다 — 웹에서 받은 저해상도 JPEG, 스캔 잡티.

    가장 중요한 건 **축소**다. 사용자가 넣는 악보는 오선 간격이 6~7px인
    경우가 흔한데, 검출기가 그 해상도를 못 보면 쓸모가 없다.
    """
    import io

    import numpy as np
    from PIL import Image, ImageFilter

    # 축소 한계는 **음표 머리 크기**로 정한다. 머리 높이가 한 칸이므로
    # 그게 5px 밑으로 내려가면 사람도 못 읽는 그림이 되고, 학습에 해가 된다
    # (실측: 무작정 0.28배로 줄였더니 201×60px짜리 표본이 나왔다).
    # **잉크 두껍게 — 축소보다 먼저.** 굵게 인쇄되거나 번진 악보는 머리가
    # 오선 간격 대비 넓어진다(실측: 마커스 2.21칸 vs 보통 1.3칸).
    #
    # 순서가 중요하다. 축소한 뒤에 3×3 최소값 필터를 걸면 필터가 머리에
    # 비해 너무 커서 **속 빈 머리의 구멍까지 메워버린다.** 그러면 모델이
    # "두꺼운 테두리 + 작은 구멍"이라는 중간 상태를 한 번도 못 본다 —
    # 마커스 악보의 2분음표가 정확히 그 모양인데 검출이 0개였다.
    # 원래 해상도에서 부풀린 뒤 축소하면 구멍이 비율대로 살아남는다.
    # **가로만 늘린다.** 실측(실제 악보 56쪽): 음표 머리 폭이 오선 간격의
    # 1.285~1.49칸인데, Verovio 폰트 5종은 전부 1.02~1.23칸이라 어떤 폰트를
    # 써도 실제 구간에 못 들어간다(합성 커버리지 38%). 오선 간격은 세로로
    # 정해지므로 가로만 늘리면 머리 폭 비율만 커진다 — 실제 조판도 가로
    # 여유가 곡마다 다르다.
    sx = rng.uniform(1.0, 1.28)
    if sx > 1.01:
        img = img.resize((max(8, int(img.width * sx)), img.height),
                         Image.LANCZOS)
        boxes = [{**b, "x": b["x"] * sx, "w": b["w"] * sx} for b in boxes]

    # 속 빈 머리(2분·온음표)가 있으면 조심해야 한다. 구멍이 메워지면
    # 그림은 꽉 찬 머리인데 라벨은 "속 빔"이 되어 **모순된 신호**가 된다
    # (실측: 그냥 두면 38%가 메워졌다). 부풀리기는 한 번만, 축소 하한은
    # 구멍이 2px 이상 남도록 높인다.
    has_hollow = any(b["class"] in ("notehead_half", "notehead_whole")
                     for b in boxes)

    # **부풀리기는 속 빈 머리를 전멸시킨다.** 실측(합성 105개 표본):
    #   축소만(6.5~12px) 76~80% · JPEG50 81%  → 무해
    #   블러 0.7          47%                  → 절반 죽음
    #   MinFilter(3)       7%                  → 거의 전멸
    # 확대→침식→축소로 "부분 픽셀"만 번지게 해도 23~42%로 마찬가지였다.
    # 머리 높이가 8px이면 구멍은 원래 2px이라, 어떤 침식도 메운다.
    # 그래서 구멍을 억지로 살리는 대신 **부풀린 장은 라벨을 그림에 맞춘다**
    # (아래 relabel_hollow). 다만 "구멍이 보이는 머리"라는 표본이 충분히
    # 남아야 하므로, 속 빈 머리가 있는 장은 70%를 순한 열화로 돌린다.
    gentle = has_hollow and rng.random() < 0.70

    if not gentle and rng.random() < 0.35:
        img = img.filter(ImageFilter.MinFilter(3))
        if not has_hollow and rng.random() < 0.4:   # 더 굵은 인쇄
            img = img.filter(ImageFilter.MinFilter(3))

    # 축소는 **목표 오선 간격**으로 정한다. 머리 높이가 대략 한 칸이므로
    # 그것으로 현재 간격을 가늠한다. 실측(실제 악보 70쪽): 원본 오선 간격이
    # 7.0~10.5px(중앙 9.0)인데, 예전 합성은 4.0~8.0(중앙 6.0)으로 **실제보다
    # 작게** 몰려 있었다. 학습이 본 적 없는 크기로 추론하게 되는 셈이다.
    heads = [b["h"] for b in boxes if b["class"].startswith("notehead")]
    space = sorted(heads)[len(heads) // 2] if heads else 12.0
    target = rng.uniform(6.5, 11.5)
    # **축소는 손대지 않는다.** 실측: 축소만 하면 6.5px에서도 76%, 12px에서
    # 80%로 사실상 차이가 없다. 구멍을 죽이는 건 부풀리기와 블러다.
    # 실제 악보(마커스)의 오선 간격이 정확히 6.50px이고 그 크기에서 구멍이
    # 눈에 보이므로, 순한 장을 크게 만들어 버리면 정작 실제 크기를 못 배운다.
    f = min(1.0, target / space) if space > 0 else 1.0
    if f < 0.99:
        w, h = max(64, int(img.width * f)), max(32, int(img.height * f))
        img = img.resize((w, h), Image.LANCZOS)
        boxes = [{**b, "x": b["x"] * f, "y": b["y"] * f,
                  "w": b["w"] * f, "h": b["h"] * f} for b in boxes]

    # 블러도 구멍을 죽인다 (실측 0.3→73% · 0.5→60% · 0.7→47% · 0.9→31%)
    if rng.random() < 0.5:
        hi = 0.35 if gentle else 1.1
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, hi)))

    a = np.asarray(img).astype(np.int16)
    if rng.random() < 0.6:
        a = a + rng.gauss(0, 1) * 0 + np.random.normal(
            0, rng.uniform(3, 14), a.shape)
    # 종이 밝기·인쇄 농도
    a = (a - 255) * rng.uniform(0.75, 1.0) + 255 * rng.uniform(0.92, 1.0)
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    if rng.random() < 0.7:
        buf = io.BytesIO()
        img.convert("L").save(buf, format="JPEG",
                              quality=rng.randint(35, 92))
        buf.seek(0)
        img = Image.open(buf).convert("L")
    return img, boxes


def relabel_hollow(img, boxes):
    """
    **라벨을 그림에 맞춘다.**

    속 빈 머리(2분·온음표)는 저해상도·굵은 인쇄에서 구멍이 메워져 꽉 찬
    머리와 구별이 안 된다. 그때 라벨을 "속 빔"으로 두면 그림과 라벨이
    **정반대인 신호**가 되고, 모델은 두 부류를 아예 못 가른다.
    실측: 그렇게 만든 학습셋에서 흰 머리 라벨의 46%가 그림상 꽉 찬 머리였고,
    실제 악보(마커스)에서 속 빈 머리 15개 중 1개만 잡혔다 — 오분류가 아니라
    **아예 검출이 안 됐다.** 배운 적 없는 모양이었기 때문이다.

    그래서 열화가 끝난 뒤 상자마다 구멍을 실제로 재보고, 사라졌으면
    `notehead_filled`로 바꾼다. 그림이 꽉 찬 머리면 라벨도 꽉 찬 머리다.
    이 함수는 표본을 버리지 않는다 — 부류만 옮긴다.

    반환: (boxes, 바뀐 개수)
    """
    import numpy as np

    a = np.asarray(img.convert("L")).astype(np.float32)
    out, moved = [], 0
    for b in boxes:
        if b["class"] not in ("notehead_half", "notehead_whole"):
            out.append(b)
            continue
        cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        bw, bh = b["w"], b["h"]
        # 안쪽 40%가 구멍, 상자 110%가 잉크·종이 기준
        core = a[max(0, int(cy - bh * .20)):int(cy + bh * .20) + 1,
                 max(0, int(cx - bw * .20)):int(cx + bw * .20) + 1]
        ring = a[max(0, int(cy - bh * .55)):int(cy + bh * .55) + 1,
                 max(0, int(cx - bw * .55)):int(cx + bw * .55) + 1]
        if core.size == 0 or ring.size == 0:
            out.append(b)
            continue
        ink = float(np.percentile(ring, 5))
        paper = float(np.percentile(ring, 95))
        if paper - ink < 20:          # 대비가 없으면 판단 보류
            out.append(b)
            continue
        if float(core.mean()) > ink + (paper - ink) * 0.45:
            out.append(b)            # 구멍 살아 있음 — 그대로
        else:
            out.append({**b, "class": "notehead_filled"})
            moved += 1
    return out, moved


def drop_faded_dots(img, boxes):
    """
    **지워진 붙임점의 라벨을 버린다.**

    붙임점 상자는 오선 간격의 0.40배다(실측). 열화 단계의 흐림·수축은
    이만한 점을 통째로 지울 수 있다. 그림에는 없는데 라벨만 남으면
    속 빈 머리 때와 같은 **정반대 신호**가 되어, 모델이 점을 배우는 대신
    "여기쯤에 뭔가 있다"를 외우게 된다.

    상자 안이 주변 종이보다 확실히 어두울 때만 라벨을 남긴다.
    반환: (boxes, 버린 개수)
    """
    import numpy as np

    a = np.asarray(img.convert("L")).astype(np.float32)
    out, dropped = [], 0
    for b in boxes:
        if b["class"] != "aug_dot":
            out.append(b)
            continue
        cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        r = max(1.0, b["w"] / 2)
        core = a[max(0, int(cy - r * .6)):int(cy + r * .6) + 1,
                 max(0, int(cx - r * .6)):int(cx + r * .6) + 1]
        # 점 좌우 바깥쪽을 종이 기준으로 쓴다 (위아래는 오선이 걸린다)
        ring = a[max(0, int(cy - r * .6)):int(cy + r * .6) + 1,
                 max(0, int(cx - r * 3.0)):int(cx + r * 3.0) + 1]
        if core.size == 0 or ring.size == 0:
            out.append(b)
            continue
        paper = float(np.percentile(ring, 95))
        if paper - float(core.min()) < 30:      # 점이 남아 있지 않다
            dropped += 1
            continue
        out.append(b)
    return out, dropped


def to_yolo(boxes, w: int, h: int) -> list[str]:
    """YOLO 라벨 한 줄씩: `클래스 중심x 중심y 폭 높이` (0~1 정규화)."""
    lines = []
    for b in boxes:
        if b["class"] not in CLASSES:
            continue
        if b["w"] <= 0 or b["h"] <= 0:
            continue
        cx = (b["x"] + b["w"] / 2) / w
        cy = (b["y"] + b["h"] / 2) / h
        bw, bh = b["w"] / w, b["h"] / h
        if not (0 < cx < 1 and 0 < cy < 1):
            continue
        lines.append(f"{CLASSES.index(b['class'])} "
                     f"{cx:.6f} {cy:.6f} {min(bw,1):.6f} {min(bh,1):.6f}")
    return lines


def main() -> None:
    import argparse
    import random

    import musicxml as M

    ap = argparse.ArgumentParser(description="YOLO 학습 데이터 생성")
    ap.add_argument("-n", "--count", type=int, default=50)
    ap.add_argument("-o", "--out", default="data/synth")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--measures", type=int, default=6)
    a = ap.parse_args()

    out = Path(a.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    (out / "classes.txt").write_text("\n".join(CLASSES) + "\n")

    rng = random.Random(a.seed)
    made = 0
    moved = 0
    faded = 0
    for i in range(a.count):
        # **화음 표본 비율.** 실측: 74장 중 15장(20%)에 화음 단이 있고, 그
        # 장 안에서도 보통 1~3단이다. 그래서 표본의 일부만 화음으로 만들되,
        # 그때는 간주 스트립처럼 **빽빽하게** 쌓는다 — 드문드문 섞으면
        # 검출기가 "쌓인 기둥"이라는 배치 자체를 못 배운다.
        chord_rate = (rng.uniform(0.4, 0.9) if rng.random() < 0.12 else 0.0)
        ms, fifths = random_score(rng, a.measures, chord_rate=chord_rate)
        xml = M.build(ms, fifths=fifths)
        img, boxes = render_sample(xml, random_style(rng))
        if img is None or not boxes:
            continue
        # **사람 표시는 열화보다 먼저.** 실제 악보도 인쇄 뒤에 사람이 긋고
        # 그걸 통째로 스캔한다 — 표시만 깨끗하면 학습이 쉬워져 버린다.
        img = human_marks(img, boxes, rng)
        img, boxes = degrade(img, boxes, rng)
        boxes, mv = relabel_hollow(img, boxes)
        moved += mv
        boxes, dd = drop_faded_dots(img, boxes)
        faded += dd
        lines = to_yolo(boxes, img.width, img.height)
        if not lines:
            continue
        img.save(out / "images" / f"{i:05d}.png")
        (out / "labels" / f"{i:05d}.txt").write_text("\n".join(lines) + "\n")
        made += 1
    print(f"{made}/{a.count}장 생성 → {out}")
    if moved:
        print(f"  구멍이 메워진 흰 머리 {moved}개는 notehead_filled로 정정")
    if faded:
        print(f"  열화로 지워진 붙임점 {faded}개는 라벨에서 제외")


if __name__ == "__main__":
    main()
