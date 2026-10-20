#!/usr/bin/env python3
"""
**검출기로 구조를 읽는다** — LLM에게는 개수만 묻는다.

왜 바꾸는가(실측): 장당 $2.84~4.5의 82%가 구조 판독 출력 토큰이고, 그 출력의
94%가 Opus의 사고 과정이다. 그런데 음가·붙임점·마디는 검출기와 그림만으로
나온다:

  · 음가   96.9% (마커스) · 99.5% (DAY2) · 96.5% (위싱)
  · 붙임점 99.2% · 100% · 97.5%
  · 마디   97.4% · 97.9% · 87.2%   ← 그림 줄막대로 나눈 마디의 4박 검산

LLM에 남는 일은 **단별 음표 수·쉼표 수**뿐이다. 그 두 숫자는 검출기의
문턱을 정하는 데 쓰인다(`evaldet.detect_guided`) — 속 빈 머리와 2분쉼표는
점수가 낮아 개수 없이는 빠진다.

읽지 못하는 것(LLM 경로에서 후퇴하는 부분):
  · **도돌이표·볼타** — counts 에 실려 오면 그대로 쓰고, 없으면 비운다.
  · **붙임줄** — 절반쯤만 잡는다(마커스 8/16 · 위싱 8/40 · DAY2 2/14).
    합성 검증셋에서는 mAP50 0.946인데 실제 악보로 잘 옮겨오지 않는다.

붙임줄은 곡선 클래스(`tie`)로 검출하고, 슬러와는 **양 끝 음높이가 같은가**로
가른다 — 붙임줄의 정의다. 슬러를 붙임줄로 읽으면 리듬이 바뀌므로 놓치는
쪽으로 기울여 둔다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import durations as D  # noqa: E402
import fitdur as F  # noqa: E402
import repeats as R  # noqa: E402
import layout as L  # noqa: E402
import sheetcv as cv  # noqa: E402

BEATS = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}
REST_DUR = {"rest_whole": "whole", "rest_half": "half",
            "rest_quarter": "quarter", "rest_8th": "eighth",
            "rest_16th": "16th"}


_LOOSE: dict[int, bool] = {}


def _worst_measure(edges, notes, boxes) -> float:
    """이 마디선 배치에서 가장 큰 마디의 박수."""
    worst = 0.0
    for a, b in zip(edges, edges[1:]):
        v = sum(BEATS[n["duration"]] * (1.5 if n.get("dotted") else 1.0)
                for n in notes
                if not n.get("chord") and a <= n["x"] + n["w"] / 2.0 < b)
        v += sum(BEATS[REST_DUR[r["class"]]] for r in boxes
                 if r["class"] in REST_DUR and a <= r["x"] + r["w"] / 2.0 < b)
        worst = max(worst, v)
    return worst


def _measure_edges(strict, st, spacing: float, boxes,
                   loose: bool = False) -> list[float]:
    """
    한 단의 마디 경계 x. `layout.systems_of` 와 같은 기준을 쓴다.

    음자리표·조표 뒤(첫 음표/쉼표 앞)부터 보고, 겹마디선(도돌이표)은
    2.4칸 안이면 하나로 합친다 — 안 합치면 사이에 0박짜리 가짜 마디가 생긴다
    (실측: 위싱 단3, DAY2 단3·단7).
    """
    heads = [b for b in boxes if b["class"].startswith("notehead")]
    firsts = [b["x"] for b in boxes
              if b["class"].startswith("notehead")
              or b["class"].startswith("rest")]
    x_from = (min(firsts) - spacing * 0.6) if firsts else None
    merged: list[float] = []
    for b in sorted(L.barlines_of(strict, st, spacing, heads, x_from, loose)):
        if merged and b - merged[-1] < spacing * 2.4:
            merged[-1] = (merged[-1] + b) / 2.0
        else:
            merged.append(b)
    inner = [b for b in merged
             if st.left + spacing * 3 < b < st.right - spacing * 0.8]
    return [float(st.left)] + inner + [float(st.right)]


TIE_SAME_Y = 0.30      # 붙임줄로 볼 두 머리의 y 차이 (칸)
# **붙임줄은 두 머리 사이에 그려진다** — 머리 중심까지 닿지 않는다.
# 이전 조건은 곡선이 머리 중심에서 0.6칸 안까지 들어오기를 요구했는데, 조판에
# 따라 곡선이 머리에서 한 칸쯤 떨어져 시작한다. 캡처 세 장의 붙임줄 상자를 재
# 보니 머리 중심에서 안쪽으로 0.10~1.59칸 들어가 있었고(6개), 길이는 두 머리
# 간격의 0.57~0.97배였다. 여백이 넓은 쪽(wish3 단0)은 통째로 놓쳤다 — 3개 전부.
#
# 그래서 "닿는가" 대신 **"사이에 있고 그 사이를 대부분 덮는가"** 로 묻는다.
# 이쪽이 더 엄하기도 하다: 여러 음을 지나가는 긴 이음줄은 두 머리 바깥으로
# 삐져나오므로 이제 걸러진다(이전 조건은 걸러내지 못했다).
TIE_OUTSIDE = 0.5      # 머리 중심 바깥으로 봐줄 곡선 끝 (칸) — 상자 흔들림
TIE_SPAN = 0.5         # 두 머리 간격 중 곡선이 덮어야 할 최소 비율


def _ties(heads, curves, spacing: float) -> set[int]:
    """
    **붙임줄인 곡선만 고른다.**

    붙임줄과 슬러는 같은 곡선으로 그려져 검출기가 구별하지 못한다(그래서 한
    클래스로 배운다). 가르는 건 정의다 — **붙임줄은 같은 음높이를 잇는다.**
    그래서 곡선이 걸친 두 이웃 머리의 y가 거의 같을 때만 붙임줄로 본다.

    슬러를 붙임줄로 잘못 읽으면 다른 음 두 개가 한 음처럼 이어져 리듬이
    바뀐다. 반대로 놓치면 곡선만 안 그려진다 — 놓치는 쪽이 안전하다.

    반환: 붙임줄이 시작하는 머리 인덱스 집합
    """
    out: set[int] = set()
    slop = spacing * TIE_OUTSIDE
    for i, (a, b) in enumerate(zip(heads, heads[1:])):
        ay = a["y"] + a["h"] / 2.0
        by = b["y"] + b["h"] / 2.0
        if abs(ay - by) > spacing * TIE_SAME_Y:
            continue
        ax = a["x"] + a["w"] / 2.0
        bx = b["x"] + b["w"] / 2.0
        for c in curves:
            cx0, cx1 = c["x"], c["x"] + c["w"]
            if (cx0 >= ax - slop and cx1 <= bx + slop
                    and cx1 - cx0 >= (bx - ax) * TIE_SPAN):
                out.add(i)
                break
    return out


SLUR_MIN_SPAN = 1.2    # 슬러로 볼 곡선의 최소 가로폭 (칸)


def _slurs(heads, curves, spacing: float,
           tie_at: set[int]) -> list[tuple[int, int]]:
    """
    **붙임줄이 아닌 곡선은 슬러다** — 어느 음표에서 시작해 어느 음표에서
    끝나는지 돌려준다.

    왜 필요한가: 지금까지 검출한 곡선 중 붙임줄로 쓰이지 않은 것은 통째로
    버렸다(7장 실측: 곡선 160개 중 40개). 그래서 "Pra——ise" 같은 긴 슬러가
    변환본에서 사라진다 — 원본과 그림이 달라 보이는 가장 큰 차이였다.

    붙임줄과 달리 슬러는 **여러 음표를 건너뛴다.** 그래서 이웃 쌍만 보지
    않고 곡선이 덮는 머리를 전부 모아 처음과 끝을 쓴다.

    이미 붙임줄로 쓴 쌍은 건너뛴다 — 같은 곡선을 두 번 그리게 된다.
    """
    out: list[tuple[int, int]] = []
    slop = spacing * TIE_OUTSIDE
    seen: set[tuple[int, int]] = set()
    for c in curves:
        if c["w"] < spacing * SLUR_MIN_SPAN:
            continue
        cx0, cx1 = c["x"] - slop, c["x"] + c["w"] + slop
        idx = [i for i, h in enumerate(heads)
               if cx0 <= h["x"] + h["w"] / 2.0 <= cx1]
        if len(idx) < 2:
            continue
        a, b = idx[0], idx[-1]
        # 이웃 둘뿐이고 그게 붙임줄이면 이미 그려진다
        if b == a + 1 and a in tie_at:
            continue
        if (a, b) in seen:
            continue
        seen.add((a, b))
        out.append((a, b))
    # **겹치는 슬러는 하나만 남긴다.** 구조에는 시작·끝을 참/거짓으로
    # 싣고 MusicXML 도 번호 하나로 적으므로, 겹치거나 품으면 짝이 어긋나
    # Verovio 가 열린 슬러를 끝까지 끌고 간다. 리드시트에서 슬러가 겹치는
    # 일은 드물다 — 먼저 시작한 것을 쓰고, 짧은 쪽을 버린다.
    out.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    kept: list[tuple[int, int]] = []
    for a, b in out:
        if kept and a <= kept[-1][1]:
            continue
        kept.append((a, b))
    return kept


# 모델을 매 호출마다 새로 올리지 않는다 — 서버에서 로드가 추론보다 비싸다.
_MODELS: dict[str, object] = {}


def _load(path: str):
    m = _MODELS.get(path)
    if m is None:
        from ultralytics import YOLO
        m = _MODELS[path] = YOLO(path)
    return m


def detect_curves(big, model_path: str, expect, expect_rests) -> list[dict]:
    """
    **곡선만 다른 모델로 검출한다.**

    왜 나누는가(실측): 곡선 클래스를 넣어 재학습한 모델은 붙임줄을 얻는
    대신 마디 정확도를 잃었다 — 마커스 97.4% → 92.3%, DAY2 97.9% → 95.8%.
    마디는 배치를 결정하므로 그쪽을 지키는 게 낫다.

    그런데 **두 모델을 따로 돌리면 둘 다 얻는다.** 구조는 곡선 없는 모델이,
    곡선은 곡선 있는 모델이 낸다. 붙임줄 수는 한 모델로 돌린 것과 같았고
    (8·8·2개) 구조 수치는 그대로였다. 검출을 한 번 더 하는 값(약 10초)만 든다.
    """
    import evaldet as E

    boxes, _ = E.detect_guided(_load(model_path), big, expect,
                               expect_rests=expect_rests)
    return [b for b in boxes if b["class"] == "tie"]


# 한 마디의 박수 후보 (4분음표 몇 개분). 콘티에서 실제로 본 것들이다 —
# 4/4·2/2(4박), 3/4·6/8(3박), 2/4(2박).
BEAT_CANDIDATES = (4.0, 3.0, 2.0)


def _three_or_six(pages) -> str:
    """
    3.0박 악보가 6/8 인지 3/4 인지 **빔 묶음 크기**로 가른다.

    6/8 은 8분음표를 3개씩, 3/4 는 2개씩 묶는 것이 조판 관행이다. 마디 합은
    둘 다 3.0박이라 합만으로는 영영 못 가른다 — 틀리면 박자표가 잘못 그려진다
    (실측 wish0830-8 은 6/8 인데 판독이 없으면 3/4 로 그려진다).
    근거가 약하면(빔이 적으면) 3/4 로 둔다 — 기존 동작이다.
    """
    from collections import Counter
    sizes: Counter = Counter()
    for ms in pages:
        for m in ms:
            groups: Counter = Counter()
            for it in m.get("items", []):
                g = it.get("beamGroup", -1)
                if it["duration"] == "eighth" and g is not None and g >= 0:
                    groups[g] += 1
            for v in groups.values():
                if v >= 2:
                    sizes[v] += 1
    if sum(sizes.values()) < 3:
        return ""
    threes = sizes.get(3, 0) + sizes.get(6, 0)
    twos = sizes.get(2, 0) + sizes.get(4, 0)
    return "6/8" if threes > twos else ""


def _broken(pages, beats: float) -> int:
    """이 박자로 보면 합이 안 맞는 마디가 몇 개인가 (박자표 검증용)."""
    n = 0
    for ms in pages:
        for m in ms:
            v = sum(BEATS[i["duration"]] * (1.5 if i["dotted"] else 1.0)
                    for i in m["items"])
            if v > 0 and abs(v - beats) > 1e-6:
                n += 1
    return n


def guess_beats(pages) -> float:
    """
    마디 합의 **최빈값**으로 한 마디의 박수를 정한다.

    파이프라인은 오래 4/4를 전제했는데, 실제 콘티 73쪽을 재 보니 13쪽(18%)이
    4박이 아니었다 — 6/8 「교회여 일어나라」는 한 마디가 3박이라 맞는 마디를
    전부 "미달"로 표시했다.

    후보 중에서 고르고, 어느 것도 뚜렷하지 않으면 4박으로 둔다 — 근거 없이
    바꾸면 4/4 악보의 검산이 무너진다.
    """
    from collections import Counter

    sums = []
    for ms in pages:
        for m in ms:
            t = sum(BEATS[i["duration"]] * (1.5 if i["dotted"] else 1.0)
                    for i in m["items"])
            if t > 0:
                sums.append(round(t, 2))
    if len(sums) < 6:
        return 4.0
    c = Counter(sums)
    best, share = 4.0, 0.0
    for cand in BEAT_CANDIDATES:
        r = c.get(cand, 0) / len(sums)
        if r > share:
            best, share = cand, r
    # 최빈이라도 너무 드물면 믿지 않는다
    return best if share >= 0.25 else 4.0


def _split_merged(pages, beats: float = 4.0) -> int:
    """
    정확히 한 마디의 배수인 마디를 **박자 경계에서 나눈다.**

    줄막대를 놓치면 두 마디가 하나로 붙는다. 합이 4박의 정수배이고 그 경계에
    음표 사이 자리가 있으면 원래 두 마디였다고 보는 게 맞다 — 나머지가 남는
    경우(못갖춘마디·쪼개진 마디)는 배수가 아니므로 손대지 않는다.

    반환: 나눈 횟수
    """
    n = 0
    for ms in pages:
        out = []
        for m in ms:
            items = m["items"]
            # **화음 구성음은 박을 차지하지 않는다.** 기둥 하나를 나눠 쓰므로
            # checkbeats 도 fitdur._beats 도 빼고 센다. 이 함수만 세고 있었고,
            # 그래서 화음이 많은 장에서 4박 마디를 8박으로 착각해 두 동강
            # 냈다 — 양쪽 다 깨진다(실측: now0918-8 이 12 -> 29).
            paid = [i for i in items if not i.get("chord")]
            total = sum(BEATS[i["duration"]] * (1.5 if i["dotted"] else 1.0)
                        for i in paid)
            k = round(total / beats) if beats else 0
            if k < 2 or abs(total - k * beats) > 1e-6 or len(paid) < 2:
                out.append(m)
                continue
            # 4박 경계마다 자른다. 경계가 음표 중간이면 나누지 않는다
            # 박을 먹는 음표의 자리만 본다. 화음 구성음은 앞 음표에 딸린
            # 것이므로 경계를 만들지 않고, 잘릴 때도 앞 음표를 따라간다.
            at = [i for i, it in enumerate(items) if not it.get("chord")]
            cuts, acc = [], 0.0
            for k2, idx in enumerate(at):
                it = items[idx]
                acc += BEATS[it["duration"]] * (1.5 if it["dotted"] else 1.0)
                # **마지막 음표 뒤에서는 자르지 않는다.** 그 뒤에 화음
                # 구성음이 붙어 있으면 idx+1 이 아직 목록 안이라, 순진하게
                # 재면 끝에서 한 번 더 자른다.
                if abs(acc % beats) < 1e-6 and k2 + 1 < len(at):
                    cuts.append(at[k2 + 1])
            if len(cuts) != k - 1:
                out.append(m)
                continue
            prev = 0
            for c in cuts + [len(items)]:
                part = items[prev:c]
                out.append({
                    "notes": [x for x in part if not x["rest"]],
                    "rest": sum(BEATS[x["duration"]] for x in part if x["rest"]),
                    "items": part,
                })
                prev = c
            n += k - 1
        ms[:] = out
    return n


# **화음으로 묶는 기준.** 화음 구성음은 기둥 하나를 나눠 쓰므로 x 가 거의
# 같다. 빠른 연속 음표는 최소 한 칸 이상 떨어진다. 세로로도 떨어져야
# 화음이다 — 같은 자리 중복 검출과 구분된다.
CHORD_DX = 0.5      # 중심 거리가 이 안(오선간격 배수)이면 같은 기둥
# **2도(인접 음)도 화음이다.** 0.8 칸이면 반 칸 떨어진 2도가 "같은 음
# 중복"으로 걸러져 둘 다 박을 차지한다 — 실측 now0918-8 단9 에서 그 마디가
# 4박 대신 6박이 됐다. 겹친 머리 쌍 224개의 세로거리를 재 보니 **0.5칸
# 미만은 하나도 없었다**(중복 검출은 detect_guided 의 _overlaps 가 이미
# 걸러낸다). 그래서 0.45 로 내려도 새로 삼키는 게 없다.
CHORD_DY = 0.45     # 이보다 떨어져야 다른 음 (0.5칸 = 2도를 살린다)
# **가로 겹침 기준.** 중심 거리만 보면 **머리가 넓은 온음표·2분음표**를
# 놓친다 — 실측 now0918-8 단11: 온음표 화음 두 개가 폭 30·36px(오선간격
# 18)인데 중심이 13.9px 떨어져 한계 9.0px 를 넘었다. 안 묶이니 4+4=8박이
# 되어 그 마디가 통째로 깨졌다. 같은 기둥이면 **가로로 크게 겹친다.**
# 0.55 인 이유: 빔으로 이어진 16분음표는 가로로 한 칸 정도 떨어져 있어
# 겹침이 폭의 20%대다 — 그쪽은 안 걸린다.
CHORD_OVERLAP = 0.55


def mark_chords(notes, spacing: float) -> int:
    """같은 기둥에 쌓인 머리를 화음으로 묶는다. 둘째부터 chord=True.

    화음은 **한 번만** 박을 차지한다 — 가로로 펴면 마디가 두세 배로
    부풀어 그 단의 리듬이 통째로 깨진다(실측: set0802-7 단1이 11.5박).
    """
    if not notes:
        return 0
    order = sorted(range(len(notes)), key=lambda i: notes[i]["x"])
    n = 0
    base = order[0]
    for i in order[1:]:
        a, b = notes[base], notes[i]
        ax = a["x"] + a["w"] / 2.0
        bx = b["x"] + b["w"] / 2.0
        ay = a["y"] + a["h"] / 2.0
        by = b["y"] + b["h"] / 2.0
        # 가로: 중심이 가깝거나(좁은 머리) 크게 겹치거나(넓은 머리)
        ov = (min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
        same_stem = (abs(bx - ax) <= spacing * CHORD_DX
                     or ov >= CHORD_OVERLAP * min(a["w"], b["w"]))
        if same_stem and abs(by - ay) > spacing * CHORD_DY:
            b["chord"] = True          # 구성음 — 박을 차지하지 않는다
            n += 1
        else:
            base = i
    return n


# 박자 검산으로 되살릴 수 있는 머리의 최소 점수. 이보다 낮으면 잉크가 아니라
# 잡음일 확률이 높다 — 실측한 진짜 누락 머리는 0.059 였다.
SPARE_MIN_CONF = 0.03


def promote_heads(grp, got, spares, strict, st, spacing: float, gray,
                  cur, beats: float | None) -> tuple[list, list, int]:
    """
    **모자란 마디에서만** 버려진 머리·쉼표를 되살린다.

    왜: `detect_guided` 는 LLM 이 준 개수까지만 채운다. 그 개수가 하나 모자라면
    고신뢰 검출로 이미 다 차 버려서 **진짜 음표가 버려진다**(실측:
    camp0814a-1 단8 점2분음표, 점수 0.059 → 그 마디가 4박에서 1박이 됐다).
    전수 점검에서 어긋난 마디 165개 중 96개(58%)가 이 '모자람'이다.

    문턱을 그냥 낮추면 오검출이 는다. 그래서 `promote_dots` 와 같은 원리를
    쓴다 — **박자를 심판으로.** 합이 모자란 마디에 후보를 하나 넣어 보고,
    합이 **정확히** 맞아떨어질 때만 받는다. 이미 맞는 마디는 건드리지 않으므로
    맞던 게 틀려지지 않는다.

    반환: (grp, got, 되살린 개수)
    """
    if not spares or not beats:
        return grp, got, 0
    full = float(beats)
    cands = sorted((c for c in spares if c.get("conf", 0) >= SPARE_MIN_CONF),
                   key=lambda c: -c.get("conf", 0))
    if not cands:
        return grp, got, 0

    def sums(g, notes):
        edges = _measure_edges(strict, st, spacing, g)
        out = []
        for a, b in zip(edges, edges[1:]):
            v = sum(BEATS[n["duration"]] * (1.5 if n.get("dotted") else 1.0)
                    for n in notes
                    if not n.get("chord") and a <= n["x"] + n["w"] / 2.0 < b)
            v += sum(BEATS[REST_DUR[r["class"]]] for r in g
                     if r["class"] in REST_DUR and a <= r["x"] + r["w"] / 2.0 < b)
            out.append((a, b, v))
        return out

    n = 0
    for _ in range(len(cands)):
        short = [(a, b) for a, b, v in sums(grp, got) if v < full - 1e-6]
        if not short:
            break
        picked = None
        for c in cands:
            cx = c["x"] + c["w"] / 2.0
            if not any(a <= cx < b for a, b in short):
                continue
            trial_grp = grp + [c]
            trial_got = D.read_durations(trial_grp, spacing, gray=gray,
                                         mask_extra=cur, nostaff=strict,
                               lines=getattr(st, "spans", None))
            mark_chords(trial_got, spacing)
            # **그 마디만 정확히 맞아야 한다.** 다른 마디를 망가뜨리면 버린다.
            before = {(a, b): v for a, b, v in sums(grp, got)}
            after = sums(trial_grp, trial_got)
            ok = True
            fixed_one = False
            for a, b, v in after:
                was = before.get((a, b))
                if was is None:
                    ok = False
                    break
                if abs(v - full) < 1e-6 and abs(was - full) > 1e-6:
                    fixed_one = True
                elif abs(v - was) > 1e-6 and abs(was - full) < 1e-6:
                    ok = False          # 맞던 마디가 틀어졌다
                    break
            if ok and fixed_one:
                picked = c
                grp, got = trial_grp, trial_got
                if c["class"] in REST_DUR:
                    # 쉼표는 got(머리 목록)에 없다 — 상자에 직접 표시한다
                    c["restPromoted"] = True
                for x in got:
                    if abs(x["x"] - c["x"]) < 1e-6 and abs(x["y"] - c["y"]) < 1e-6:
                        x["headPromoted"] = True
                        x["fitted"] = True
                n += 1
                break
        if picked is None:
            break
        cands = [c for c in cands if c is not picked]
    return grp, got, n


def staff_pos(head: dict, st) -> str:
    """높은음자리표 오선 위 머리 자리 → 'F5' 같은 음이름(임시표 전). 맨 아래 줄 = E4."""
    half = (st.bottom - st.top) / 8.0
    k = 30 + int(round((st.bottom - (head["y"] + head["h"] / 2.0)) / half))
    return "CDEFGAB"[k % 7] + str(k // 7)


ALTER = {"accidental_sharp": 1, "accidental_flat": -1, "accidental_natural": 0}


def link_accidentals(accs: list[dict], notes: list[dict], spacing: float) -> bool:
    """
    임시표를 바로 오른쪽 머리에 붙인다(note["accidental"] / note["natural"]).
    전부 붙였거나 단 끝 예고 조표뿐이면 True — 하나라도 못 붙이면 False.

    실측 105장: 이 연결이 없어 임시표 있는 단은 전부 막혔다 — 그것만으로
    막힌 장이 4장(camp0814b-02 · c-02 · now0918-3 · set0802-2).
    ♯·♮ 는 상자 가운데, ♭ 는 아래 볼록한 데(하단에서 반 칸 위)가 머리 높이다.
    옆에 다른 임시표가 붙어 있으면 곡 중간 조표라 붙이지 않는다.
    """
    heads = [n for n in notes if not n["rest"] and n.get("head")]
    ok = True
    for a in accs:
        ax1 = a["x"] + a["w"]
        if not any(n["head"]["x"] > ax1 for n in heads):
            continue                                  # 단 끝 예고 조표
        if any(b is not a and abs(b["x"] - a["x"]) < spacing * 1.2 for b in accs):
            ok = False                                # 곡 중간 조표 무더기
            continue
        ay = (a["y"] + a["h"] - spacing * 0.5 if a["class"] == "accidental_flat"
              else a["y"] + a["h"] / 2)
        cand = [n for n in heads
                if -spacing * 0.5 <= n["head"]["x"] - ax1 <= spacing * 1.5
                and abs(n["head"]["y"] + n["head"]["h"] / 2 - ay) <= spacing * 0.6]
        if not cand:
            ok = False
            continue
        n = min(cand, key=lambda n: (n["head"]["x"],
                                     abs(n["head"]["y"] + n["head"]["h"] / 2 - ay)))
        alter = ALTER.get(a["class"])
        if alter is None:
            ok = False
        elif alter == 0:
            n["natural"] = True
        else:
            n["accidental"] = alter
    return ok


def build_from(boxes, staves, strict, spacing: float, gray,
               counts: list[dict], curves: list[dict] | None = None,
               sections: list[int] | None = None,
               beats: float | None = None,
               meta: dict | None = None, repair: bool = True,
               dots: bool | None = None,
               repeats: bool | None = None,
               merged: bool | None = None,
               fit: bool | None = None,
               head_ends: list[int] | None = None,
               rgb=None) -> dict:
    """
    이미 검출된 상자로 struct 모양을 만든다. rebuild 가 검출을 두 번
    하지 않도록 build() 에서 떼어 놓았다.

    curves 를 주면 붙임줄은 그것에서 읽는다 (detect_curves 참고).
    sections 를 주면 단별 원조 fifths 로 실어 보낸다 (전조용).
    """
    import numpy as _np
    _NS = (strict if hasattr(strict, "shape") else _np.asarray(strict))
    mids = [(s.top + s.bottom) / 2.0 for s in staves]
    bysys: list[list[dict]] = [[] for _ in staves]
    for b in boxes:
        cy = b["y"] + b["h"] / 2.0
        bysys[min(range(len(mids)), key=lambda i: abs(mids[i] - cy))].append(b)
    cbysys: list[list[dict]] = [[] for _ in staves]
    for b in (curves if curves is not None else
              [b for b in boxes if b["class"] == "tie"]):
        cy = b["y"] + b["h"] / 2.0
        cbysys[min(range(len(mids)), key=lambda i: abs(mids[i] - cy))].append(b)

    pages: list[list[dict]] = []
    n_chord = 0
    chord_per_sys: list[int] = []
    spares = (meta or {}).get("spare") or []
    n_promoted = 0

    # **머리 승격은 한 마디가 몇 박인지 알아야 한다** — 박자가 심판이기
    # 때문이다. 그런데 기존 코드는 마디를 다 만든 뒤에야 박자를 정한다.
    # 그래서 여기서 먼저 정한다: 판독이 읽어 온 박자표가 있으면 그것,
    # 없으면 **가벼운 예비 패스**로 마디 합만 뽑아 추정한다.
    ts_txt = next((str(c.get("time_signature")) for c in counts
                   if c.get("time_signature")), "")
    prov = beats
    if prov is None and "/" in ts_txt:
        try:
            a_, b_ = ts_txt.split("/")[:2]
            prov = int(a_) * 4.0 / int(b_)
        except Exception:
            prov = None
    if prov is None and spares:
        rough = []
        for grp_, cur_, st_ in zip(bysys, cbysys, staves):
            g2 = D.fix_rest_class(list(grp_), st_.top, spacing)
            got2 = D.read_durations(g2, spacing, gray=gray, mask_extra=cur_,
                                    nostaff=strict,
                                    lines=getattr(st_, "spans", None))
            mark_chords(got2, spacing)
            edges = _measure_edges(strict, st_, spacing, g2)
            ms_ = []
            for a_, b_ in zip(edges, edges[1:]):
                ns_ = [n for n in got2 if not n.get("chord")
                       and a_ <= n["x"] + n["w"] / 2.0 < b_]
                rs_ = [r for r in g2 if r["class"] in REST_DUR
                       and a_ <= r["x"] + r["w"] / 2.0 < b_]
                items_ = [{"duration": n["duration"],
                           "dotted": bool(n["dotted"])} for n in ns_]
                items_ += [{"duration": REST_DUR[r["class"]], "dotted": False}
                           for r in rs_]
                ms_.append({"items": items_})
            rough.append(ms_)
        prov = guess_beats(rough)
    for si_, (grp, cur, st) in enumerate(zip(bysys, cbysys, staves)):
        # **음자리표·조표 구간의 검출은 버린다.** 조표의 ♭ 는 8분쉼표와
        # 글리프가 닮아 자주 뒤바뀐다 — 실측 camp0814b-07 단7: 조표 ♭ 가
        # rest_8th(0.57)로 잡혀 **0.5박짜리 유령 마디**가 생겼고, 그
        # 위치 때문에 도돌이표까지 마디선으로 읽혔다.
        # head_ends 는 렌더러와 같은 함수(render.head_end_for)가 낸 값이다.
        # **쉼표만** 버린다. 음표까지 버리면 머리 구간을 조금만 길게
        # 잡아도 진짜 첫 음을 잃는다(실측 105장: 9장 개선 · 8장 후퇴로
        # 무승부). 조표 자리의 '쉼표'는 거의 확실히 임시표 오독이다.
        if head_ends and si_ < len(head_ends) and head_ends[si_]:
            he = head_ends[si_]
            grp[:] = [b for b in grp
                      if not b["class"].startswith("rest")
                      or b["x"] + b["w"] / 2.0 >= he]
        grp[:] = D.fix_rest_class(grp, st.top, spacing)
        got = D.read_durations(grp, spacing, gray=gray, mask_extra=cur,
                               nostaff=strict,
                               lines=getattr(st, "spans", None))
        if repair and si_ < len(spares):
            grp, got, np_ = promote_heads(grp, got, spares[si_], strict, st,
                                          spacing, gray, cur, prov)
            n_promoted += np_
        got_chords = mark_chords(got, spacing)
        # **마디가 말이 안 되게 크면 마디선을 놓친 것이다.** 엄격한 기준은
        # 빽빽한 단에서 마디선을 통째로 잃는다(실측 now0918-1 단4: 단 전체가
        # 17박 한 마디). 느슨한 기준은 기둥까지 받으므로 **여기서만** 쓴다 —
        # 기본으로 깔면 멀쩡하던 장이 0개에서 5개로 깨졌다(105장 실측).
        if repair and prov:
            edges0 = _measure_edges(strict, st, spacing, grp)
            w0 = _worst_measure(edges0, got, grp)
            if w0 >= prov * 1.8:
                edges1 = _measure_edges(strict, st, spacing, grp, loose=True)
                # **가장 큰 마디가 작아지면** 받는다. 마디 수가 늘어야
                # 한다고 걸면 안 된다 — 같은 개수인데 **자리만 맞는** 경우가
                # 있다(실측 now0918-1 단4: 엄격 5마디 worst 9.0 ·
                # 느슨 5마디 worst 4.0 인데 개수 조건에 반려됐다).
                # 마디 수가 줄면 마디가 커지므로 worst 가 알아서 막는다.
                if _worst_measure(edges1, got, grp) < w0:
                    _LOOSE[id(st)] = True
        chord_per_sys.append(got_chords)
        n_chord += got_chords
        tie_at = _ties(got, cur, spacing)
        slur_at = _slurs(got, cur, spacing, tie_at)
        starts = {a for a, _ in slur_at}
        stops = {b for _, b in slur_at}
        for i, n in enumerate(got):
            n["tie"] = i in tie_at
            n["slurStart"] = i in starts
            n["slurStop"] = i in stops
        edges = _measure_edges(strict, st, spacing, grp,
                               loose=_LOOSE.pop(id(st), False))
        ms = []
        for a, b in zip(edges, edges[1:]):
            ns = [{"duration": n["duration"], "dotted": bool(n["dotted"]),
                   "rest": False, "tie": bool(n.get("tie")),
                   "slurStart": bool(n.get("slurStart")),
                   "slurStop": bool(n.get("slurStop")),
                   "chord": bool(n.get("chord")),
                   # **원본의 빔 묶음.** 같은 값이면 한 빔에 묶여 있었다 —
                   # 재조판할 때 묶음을 지어내면 "키만 바뀐 같은 악보"가
                   # 아니라 다른 악보로 보인다.
                   "beamGroup": int(n.get("beamGroup", -1)),
                   # 빔·꼬리 겹수 — 2면 2차 빔(또는 16분 꼬리)이 실제로 보였다
                   "level": int(n.get("level") or 0),
                   # 박자 검산으로 되살린 자리 — 화면이 짚어 준다
                   "headPromoted": bool(n.get("headPromoted")),
                   "dotScore": n.get("dotScore", 0.0),
                   "dotRun": n.get("dotRun", 0.0),
                   "hollow": n.get("hollow"),
                   "head": {k: float(n[k]) for k in ("x", "y", "w", "h")},
                   "x": n["x"] + n["w"] / 2.0}
                  for n in got if a <= n["x"] + n["w"] / 2.0 < b]
            # **쉼표에도 붙임점이 붙는다.** 지금까지 쉼표는 점 판정이
            # 아예 없어서 𝄼. 를 𝄼 로 읽었고, 그 마디가 1박 모자란 채
            # fit_page 로 갔다(실측 set0802-1 단0 마디4·단2 마디7).
            rs = [{"duration": REST_DUR[r["class"]], "dotted": False,
                   "rest": True, "tie": False,
                   # 검출 확신 — 또렷한 쉼표 글리프는 박자로 바꾸지 않는다
                   "conf": float(r.get("conf") or 0.0),
                   "dotScore": D.rest_dot_score(_NS, r, spacing, rgb,
                                                getattr(st, "spans", None)),
                   "restPromoted": bool(r.get("restPromoted")),
                   "x": r["x"] + r["w"] / 2.0}
                  for r in grp
                  if r["class"] in REST_DUR and a <= r["x"] + r["w"] / 2.0 < b]
            items = sorted(ns + rs, key=lambda n: n["x"])
            ms.append({"notes": [n for n in items if not n["rest"]],
                       "rest": sum(BEATS[r["duration"]] for r in rs),
                       "items": items})
        pages.append(ms)

    # **놓친 줄막대를 되살린다.** 한 마디가 정확히 4박의 배수면 줄막대를
    # 하나 놓쳐 두 마디가 합쳐진 것이다 — 나눌 자리가 박자로 정해지므로
    # 추측이 아니다(실측: 「지금 여기 우리」 마지막 단이 15음 8박이었다).
    # **한 마디가 몇 박인가.**
    # 판독이 박자표를 읽어 왔으면 그것이 우선이다 — 6/8 과 3/4 는 마디 합이
    # 같아 추정으로는 못 가른다. 없으면 마디 합에서 추정한다.
    # `beats` 는 **4분음표 환산**(검산·역산이 쓰는 단위)이고,
    # `timeSignature` 는 악보에 적히는 숫자다. 6/8 은 3.0박이지만 3/8 이
    # 아니다 — 둘을 섞으면 박자표가 틀리게 그려진다.
    if beats is None and "/" in ts_txt:
        try:
            a, b = ts_txt.split("/")[:2]
            beats = int(a) * 4.0 / int(b)
        except Exception:
            beats = None
        # **판독한 박자표를 마디 합이 정면으로 반박하면 버린다.**
        # 실측: camp0814c-09 는 악보에 4/4 라 찍혀 있는데 판독이 2/4 로 읽었고,
        # 그대로 쓰면 깨진 마디가 2개에서 18개가 됐다. 반대로 wish0830-8 은
        # 판독이 6/8 로 맞았고 마디 합만으로는 절대 못 가른다(6/8 과 3/4 는
        # 합이 같다). 그래서 **크게 틀렸을 때만** 뒤집는다.
        if beats is not None:
            alt = guess_beats(pages)
            if alt and abs(alt - beats) > 1e-6:
                b_llm, b_alt = _broken(pages, beats), _broken(pages, alt)
                if b_llm >= b_alt * 2 and b_llm - b_alt >= 4:
                    beats, ts_txt = alt, ""
    if beats is None:
        beats = guess_beats(pages)
        ts_txt = ""
    # **6/8 인가 3/4 인가.** 마디 합은 둘 다 3.0박이라 절대 못 가른다. 그런데
    # **빔 묶음이 말해 준다** — 6/8 은 8분음표를 3개씩, 3/4 는 2개씩 묶는다.
    # 판독이 박자표를 못 읽은 장에서만 쓴다(실측 105장 중 4장이 여기 해당).
    if not ts_txt and abs(beats - 3.0) < 1e-6:
        ts_txt = _three_or_six(pages)
    # **박자 역산은 기본으로 켠다.** 끄면 마디의 43%가 깨진 채 나가고
    # (실측 7장 217마디: 깨짐 94개, 장당 13.4개), 사용자가 그걸 다 고쳐야
    # 한다. 켜면 깨짐 18개(8%), 장당 2.6개다.
    # "합이 맞는다고 원본과 같다는 증거는 아니다"는 맞는 지적이라, 고친
    # 자리를 fitted/guessed 로 남겨 화면이 짚어 준다 — 증거를 지우는 게
    # 아니라 표시하는 쪽으로 푼다.
    # 흐린 붙임점 먼저. 음가를 비틀기 전에 점부터 심판해야, fitdur 가
    # 붙임점 자리를 다른 음가로 덮어쓰지 않는다.
    # **붙임점 승격은 "찍기"가 아니다.** 화소에서 점의 흔적을 이미 본
    # 음표(회색지대 점수)에 한해, 마디 합이 정확히 채워질 때만 인정한다 —
    # 잉크라는 증거가 있고 박자가 그것을 확인해 주는 구조다. 그런데 "없던
    # 것을 만들지 말자"는 repair 플래그에 묶여 함께 꺼져 있었다(실측: 놓친
    # 붙임점의 45%가 회색지대 안에 있는데 승격되지 않았다). 따로 켤 수 있게
    # 가른다. 기본값은 예전과 같다.
    # **가장자리의 유령 마디를 지운다.**
    #
    # 단의 맨 끝(또는 맨 앞) 마디에 음표도 쉼표도 하나 없는 경우가 있다.
    # 끝 줄막대·겹세로줄을 마디 경계로 세어 생긴 빈 칸이다. 그대로 두면
    # rebuild.js 가 "읽은 음표·쉼표가 없어 원본 확인 필요"로 차단한다.
    #
    # 실측 25장: 빈 마디 24개 중 46%가 단의 끝, 8%가 단의 앞이었고, 그
    # 단들은 LLM 개수와 검출 개수가 **일치**했다(17/17 · 13/13 · 10/10) —
    # 음표를 놓친 게 아니라 칸이 하나 더 생긴 것이다.
    #
    # **가운데 빈 마디는 건드리지 않는다.** 거기는 진짜로 못 읽었을 수
    # 있고, 지우면 박자가 밀린다.
    ghosts = 0
    for ms in pages:
        while len(ms) > 1 and not (ms[-1].get("items") or []):
            ms.pop(); ghosts += 1
        while len(ms) > 1 and not (ms[0].get("items") or []):
            ms.pop(0); ghosts += 1

    want_dots = repair if dots is None else dots
    dots = F.promote_dots(pages, beats) if want_dots else 0
    # 거울상 — 넘치는 마디에서는 화소로 찍은 점을 거둔다. 같은 스위치로 묶는다.
    undots = F.demote_dots(pages, beats) if want_dots else 0
    # 점이 옆 빔 묶음으로 잘못 붙었으면 옮긴다 — 합은 그대로, 묶음이 맞을 때만
    if want_dots:
        F.regroup_dots(pages, beats)
    # 속 빈 머리도 같은 틀이다 — 모자란 마디에서 한 단계 올리면 딱 맞을 때만.
    hollows = F.promote_hollow(pages, beats) if want_dots else 0
    # 거울상 — 넘치는 마디에서 꽉 찬 머리를 한 단계 내린다
    unhollow = F.demote_hollow(pages, beats) if want_dots else 0

    # **쪼개기는 붙임점 뒤에 둔다.** 앞에 두면 마디 개수가 바뀌고,
    # promote_dots 의 "단 첫·끝 마디는 건너뛴다" 가드가 다른 마디에 걸린다 —
    # 붙임점이 벌어 주는 몫이 커서 그 어긋남이 쪼개기의 이득을 잡아먹는다
    # (실측: 순서를 앞에 뒀을 때 wish0809-4 가 6 -> 11 로 나빠졌다).
    # 쪼개기 자체는 "찍기"가 아니다 — 합이 기준의 정확한 배수이고 자를
    # 자리가 음표 경계에 딱 떨어질 때만 나눈다. 맞는 마디는 배수가 1 이라
    # 애초에 후보가 아니다.
    want_split = repair if merged is None else merged
    split = _split_merged(pages, beats) if want_split else 0

    # **박자로 역산한다.** 단 안쪽 마디는 편차와 무관하게, 단 가장자리는
    # 4박에서 1박 안쪽일 때만, 줄바꿈에서 쪼개진 마디는 앞뒤를 합쳐서.
    # **이건 "찍기"가 맞다.** 앞의 셋(붙임점·쪼개기·반복 비교)은 화소나
    # 반복이라는 증거가 있었지만, 이것은 합이 맞을 때까지 음가를 비튼다.
    # 그래서 깨진 마디 수로는 판단할 수 없다 — 정의상 줄어든다(순환논법).
    # 찍은 자리는 guessed/fitted 로 남겨 화면이 짚어 준다.
    want_fit = repair if fit is None else fit
    fixed = F.fit_page(pages, beats) if want_fit else {}

    # **반복 구간끼리 다르게 읽은 마디를 고친다.** 박자 검산은 "합이 4박인가"
    # 만 보므로, 쉼표를 음표로 잘못 읽고 음가를 비틀어 4박을 맞춘 마디를
    # 통과시킨다. 같은 그림을 두 번 다르게 읽었다면 정답을 몰라도 한쪽이
    # 틀린 건 안다 — 박자 규칙이 손대지 않은 쪽을 믿는다.
    # 실측 103장: 검산이 통과시킨 마디 36개가 여기서 걸린다.
    # **이것도 "찍기"가 아니다.** 같은 그림을 두 번 다르게 읽었다는 사실은
    # 정답 없이도 확인되고, 고칠 때는 박자 규칙이 손대지 않은 쪽을 믿는다.
    # promote_dots 와 같은 이유로 repair 에서 따로 뗀다.
    want_rep = repair if repeats is None else repeats
    rep_fix = R.repair(pages, strict, staves, spacing, beats) if want_rep else 0
    if rep_fix:
        fixed["repeatFixed"] = rep_fix
    if split:
        fixed["splitMerged"] = split
    if dots:
        fixed["dotsPromoted"] = dots
    if undots:
        fixed["dotsDemoted"] = undots
    if hollows:
        fixed["hollowPromoted"] = hollows
    if unhollow:
        fixed["hollowDemoted"] = unhollow
    if n_chord:
        fixed["chordNotes"] = n_chord
    if ghosts:
        fixed["ghostBars"] = ghosts

    # 게이트(web/rebuild.js)는 이 표시가 있는 마디만 짧아도 봐 준다.
    # 아무도 안 채우고 있어서 못갖춘마디로 시작한 곡은 전부 막혔다.
    pickups = F.pickup_pair(pages, beats)
    systems = []
    for si, ms in enumerate(pages):
        notes = []
        for mi, m in enumerate(ms, start=1):
            for it in m["items"]:
                notes.append({"measure": mi, "duration": it["duration"],
                              "dotted": bool(it["dotted"]),
                              "rest": bool(it["rest"]),
                              "tie": bool(it.get("tie")),
                              # **슬러.** 붙임줄이 아닌 곡선 — 여러 음표를
                              # 건너뛰므로 시작·끝을 따로 싣는다.
                              "slurStart": bool(it.get("slurStart")),
                              "slurStop": bool(it.get("slurStop")),
                              **({"head": it["head"]} if "head" in it else {}),
                              # 오선 위치의 음이름(임시표 전) — homr 와 음높이 대조용
                              **({"pos": staff_pos(it["head"], staves[si])}
                                 if "head" in it and len(staves[si].lines) == 5 else {}),
                              # 박자로 승격한 흐린 붙임점 — 검출이 아니라
                              # 추론이므로 표시해 둔다.
                              "chord": bool(it.get("chord")),
                              "beamGroup": int(it.get("beamGroup", -1)),
                              "dotPromoted": bool(it.get("dotPromoted")),
                              "dotDemoted": bool(it.get("dotDemoted")),
                              "hollowPromoted": bool(it.get("hollowPromoted")),
                              "hollowDemoted": bool(it.get("hollowDemoted")),
                              # 박자가 모자라 되살린 쉼표 — 검출은 했는데
                              # 개수 안내에 밀려 버렸던 것이다.
                              "restPromoted": bool(it.get("restPromoted")),
                              # **점수를 함께 내보낸다.** 붙임점을 놓치는 게
                              # 깨진 마디의 1위 원인인데, 점수가 없으면
                              # "문턱이 높아서인지 점이 안 보여서인지"를
                              # 가릴 수가 없다. 화면은 안 쓰고 측정이 쓴다.
                              "dotScore": float(it.get("dotScore") or 0.0),
                              # 머리 속이 얼마나 비었나 — 2분·온음표를
                              # 4분으로 잘못 읽었는지 가리는 독립 증거다.
                              # 잴 수 없었으면 None 그대로 — 0 은 "꽉 찼다"는 뜻이다
                              "hollow": it.get("hollow"),
                              "dotRun": float(it.get("dotRun") or 0.0),
                              # 박자 검산으로 되살린 머리 — 검출이 버렸던 것이라
                              # 반드시 짚어 준다
                              "headPromoted": bool(it.get("headPromoted")),
                              # 박자 역산이 **찍은** 자리 — 수정 패널이 짚는다
                              "guessed": bool(it.get("guessed")),
                              # 반복 비교로 고친 자리 / 못 고치고 표시만 한 자리
                              "repeatFixed": bool(it.get("repeatFixed")),
                              "repeatDiff": bool(it.get("repeatDiff")),
                              "fitted": bool(it.get("fitted"))})
        entry = {
            "system": si, "measures": max(1, len(ms)), "notes": notes,
            "marks": (counts[si].get("marks") or []) if si < len(counts) else [],
        }
        pk = sorted(mi + 1 for s_, mi in pickups if s_ == si)   # 마디 번호는 1부터
        if pk:
            entry["pickups"] = pk
        # 조표 구간 뒤의 임시표는 바로 오른쪽 머리에 붙인다. 하나라도 못 붙이면
        # 조표 기본값으로 조용히 넘기지 않고 막는다.
        grp = bysys[si]
        clefs = [b for b in grp if b["class"] == "clef_g"]
        if clefs:
            edge = max(b["x"] + b["w"] for b in clefs) + spacing * 4.5
            accs = [b for b in grp if b["class"].startswith("accidental_")
                    and b["x"] + b["w"] / 2 > edge]
            if accs and not link_accidentals(accs, notes, spacing):
                entry.setdefault("review", []).append("멜로디 임시표와 음표의 연결 확인 필요")
        # Preserve discrepancies even when geometry and durations came from
        # the same detector (and therefore trivially agree with one another).
        if si < len(counts):
            expected = counts[si].get("notes")
            got_n = sum(1 for n in notes if not n["rest"])
            # **화음 있는 단에서는 이 비교를 하지 않는다.** LLM 은 화음을
            # 머리로도 기둥으로도 일관되게 못 센다(실측 17단: 머리일치 3 ·
            # 기둥일치 1). 그대로 두면 화음 악보가 전부 needs_review 로
            # 잠겨 저장이 영영 안 된다 — 근거 없는 경고로 막는 셈이다.
            has_chord = any(n.get("chord") for n in notes)
            # **박자가 동의할 때만 경고한다.**
            #
            # 개수가 다르다는 것만으로는 누가 틀렸는지 모른다. 그런데 검출이
            # 읽은 대로 **마디 합이 전부 맞으면** 그 읽기는 자체적으로
            # 일관된다 — 음표를 놓쳤거나 더 찾았다면 합이 틀어졌을 것이다.
            # 그때 다른 쪽은 LLM 의 개수다.
            #
            # 실측 25장 108단: 합이 정확한데 개수만 다른 경우가 101개(93%)
            # 였고, 진짜 검출 오류는 7개뿐이었다. 차이는 +1(38) · +2(29) 가
            # 대부분 — LLM 이 조금씩 덜 센다. 그대로 두면 25장 전부가
            # needs_review 로 잠긴다(차단 사유 108개 중 56%가 이것이었다).
            #
            # 화음 단을 뺀 것과 같은 이유다 — 근거 없는 경고로 막지 않는다.
            beats_ok = True
            if expected is not None and not has_chord and int(expected) != got_n:
                full_u = int(round(beats * 8))
                per_m: dict = {}
                for n in notes:
                    if n.get("chord"):
                        continue
                    v = BEATS.get(n["duration"], 0) * (1.5 if n.get("dotted") else 1.0)
                    per_m[n.get("measure")] = per_m.get(n.get("measure"), 0.0) + v * 8
                # 단의 첫·끝 마디가 짧은 건 쪼개진 짝·못갖춘마디일 수 있다 —
                # 그걸로 개수 경고를 띄우면 정상 단이 막힌다(짝은 게이트가 본다)
                ks_ = sorted(per_m)
                beats_ok = all(abs(v - full_u) < 1e-6
                               or (k in (ks_[0], ks_[-1]) and v < full_u)
                               for k, v in per_m.items())
            if (expected is not None and not has_chord
                    and int(expected) != got_n and not beats_ok):
                entry.setdefault("review", []).append(
                    f"기존 개수 판독 {expected}개와 검출 {got_n}개 불일치")
        # **단별 원조 조표.** 곡 중간에 키가 바뀌는 악보가 있어서 하나로
        # 뭉치면 그 구간이 임시표투성이가 된다(guesskey.keysig_sections).
        if sections is not None and si < len(sections):
            entry["srcFifths"] = int(sections[si])
        systems.append(entry)
    out = {"systems": systems, "source": "detector", "fitted": fixed,
           "beats": beats, "timeSignature": ts_txt, "rhythmRepair": repair,
           "headsPromoted": n_promoted}
    # **못 읽는 단은 조용히 넘기지 않는다.** × 머리(리듬 슬래시)는 아직
    # 지원하지 않는데, 그냥 두면 리듬이 틀린 마디를 말없이 내준다.
    # 어느 단인지 실어 보내 화면에서 알린다.
    if meta:
        # 화음은 이제 묶어서 <chord/> 로 낸다. **실제로 묶은 단은 빼야
        # 한다** — 안 그러면 화음 악보가 전부 needs_review 로 잠겨
        # 저장 버튼이 영영 안 열린다. 쌓인 걸 봤는데 묶지 못한 단만 남긴다.
        stacked = [i for i in (meta.get("stacked") or [])
                   if i >= len(chord_per_sys) or not chord_per_sys[i]]
        bad = {k: v for k, v in
               (("stacked", stacked),
                ("slashOnly", meta.get("slashOnly"))) if v}
        if bad:
            out["unreliable"] = bad
    return out


def expects(counts: list[dict]) -> tuple[list[int], list[int]]:
    """detect_guided 에 줄 (음표 수, 쉼표 수)."""
    return ([int(c.get("notes") or 0) for c in counts],
            [int(c.get("rests") or 0) for c in counts])


def counts_from_struct(struct: dict) -> list[dict]:
    """LLM struct 에서 개수만 뽑는다 — 교체를 API 없이 검증하려고 둔다."""
    return [{"notes": sum(1 for n in s.get("notes", []) if not n.get("rest")),
             "rests": sum(1 for n in s.get("notes", []) if n.get("rest")),
             "marks": s.get("marks") or []}
            for s in struct.get("systems", [])]


def build(big, model_path: str, counts: list[dict],
          conf: float = 0.50) -> dict:
    """확대된 그림 한 장에서 struct 모양을 만든다 (단독 실행용)."""
    import numpy as np
    from ultralytics import YOLO

    import evaldet as E

    gray = np.asarray(big.convert("L")).astype("float32")
    ink, staves = cv.find_staves_best(big.convert("L"))
    if not staves:
        raise ValueError("오선을 찾지 못했습니다.")
    sp = cv.median_spacing(staves)
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=True)
    ex, exr = expects(counts)
    boxes, meta = E.detect_guided(YOLO(model_path), big, ex,
                                  conf_hi=conf, expect_rests=exr)
    out = build_from(boxes, staves, strict, sp, gray, counts)
    out["detMeta"] = {k: v for k, v in meta.items() if k != "names"}
    return out
