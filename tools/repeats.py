#!/usr/bin/env python3
"""
**같은 그림을 두 번 다르게 읽었으면 둘 중 하나는 틀렸다.**

찬양 악보는 절·후렴이 반복된다. 그래서 어떤 두 단은 가사만 다르고 음표는
똑같다. 그 둘을 다르게 읽었다면 정답을 몰라도 오류가 있다는 건 안다 —
박자 검산과 같은 원리인데, **박자 검산이 못 보는 것을 본다.**

박자 검산은 "합이 4박인가"만 본다. 그래서 쉼표를 음표로 잘못 읽고 음가를
비틀어 4박을 맞춘 마디는 통과시킨다(실측: now0918-12 단3 마디1 — 단1과
같은 그림인데 `[4분쉼표] 8 16 16 점4 16 16` 을 `4분 8 8 점4 16 16` 로 읽고
박자 규칙이 음가 셋을 고쳐 4박을 맞췄다. 검산은 통과했다).

**반복을 그림으로 찾는다.** 읽은 결과로 찾으면 순환논리가 된다 — 틀리게
읽은 두 단이 우연히 같으면 "일치"로 보고 넘어간다.
"""
from __future__ import annotations

import numpy as np

# 단을 비교할 때 오선 위아래로 얼마나 더 볼 것인가 (칸 단위).
# 기둥·빔·꼬리가 오선 밖으로 나가므로 넉넉히 보되, 가사까지 들어가면
# 가사가 다른 반복 구간을 다른 단으로 판정한다.
BAND_UP = 3.2
BAND_DOWN = 2.6
# 같은 음악으로 보는 문턱. 절대값과 **상대 배수**를 둘 다 넘겨야 한다 —
# 절대값만 쓰면 인쇄가 흐린 악보에서 반복을 통째로 놓친다.
#
# **오선을 지우고 재야 갈린다.** 오선 5줄은 모든 단에 똑같이 있어서 겹침을
# 통째로 부풀린다. 그대로 재면 진짜 반복(1.49)과 오탐(1.55)의 배수가 뒤집혀
# 문턱으로 못 가른다. 지우고 나면 실측이 이렇게 벌어진다:
#   now0918-12  진짜 0.361·0.540  vs  오탐 ≤0.18
#   camp0814a-1 진짜 0.531        vs  오탐 ≤0.21
SAME = 0.30
RATIO = 1.8
WIDTH = 900          # 비교용으로 맞출 너비


def band(ink: np.ndarray, st, spacing: float) -> np.ndarray:
    """한 단의 **오선 띠**만 잘라 낸다. 가사는 뺀다."""
    y0 = max(0, int(st.top - spacing * BAND_UP))
    y1 = min(ink.shape[0], int(st.bottom + spacing * BAND_DOWN))
    x0, x1 = max(0, int(st.left)), min(ink.shape[1], int(st.right))
    return ink[y0:y1, x0:x1]


def _norm(a: np.ndarray) -> np.ndarray:
    """너비를 맞추고 이진화한다. 단마다 높이·폭이 조금씩 다르다."""
    from PIL import Image
    if a.size == 0:
        return np.zeros((10, WIDTH), dtype=bool)
    im = Image.fromarray((a > 0).astype("uint8") * 255)
    h = max(8, round(im.height * WIDTH / max(im.width, 1)))
    return np.asarray(im.resize((WIDTH, h), Image.BILINEAR)) > 127


# 단마다 시작 x 와 세로 위치가 조금씩 어긋난다. 그대로 겹치면 같은 음악도
# 0.5 밖에 안 나온다 — 조금씩 밀어 보고 가장 잘 맞는 값을 쓴다.
SHIFT_X = 24
SHIFT_Y = 6


def similar(a: np.ndarray, b: np.ndarray) -> float:
    """두 띠의 잉크가 얼마나 겹치나 (0~1). 조금 밀어 가며 가장 잘 맞는 값."""
    a, b = _norm(a), _norm(b)
    h = min(a.shape[0], b.shape[0])
    if h < 8:
        return 0.0
    a, b = a[:h], b[:h]
    best = 0.0
    for dy in range(-SHIFT_Y, SHIFT_Y + 1, 2):
        bb = np.roll(b, dy, axis=0)
        for dx in range(-SHIFT_X, SHIFT_X + 1, 4):
            c = np.roll(bb, dx, axis=1)
            inter = np.logical_and(a, c).sum()
            union = np.logical_or(a, c).sum()
            if union:
                v = inter / union
                if v > best:
                    best = v
    return float(best)


def find_pairs(ink: np.ndarray, staves, spacing: float,
               thresh: float = SAME, ratio: float = RATIO
               ) -> list[tuple[int, int, float]]:
    """
    닮은 단 쌍을 [(i, j, 닮은 정도), ...] 로. `ink` 는 오선을 지운 것.

    **절대값만으로 자르지 않는다.** 인쇄 품질·해상도에 따라 같은 음악의
    닮은 정도가 0.5 도 되고 0.8 도 된다. 그래서 "그 단이 다른 단들과 보통
    얼마나 닮는가"를 기준선으로 두고, 거기서 충분히 튀는 쌍만 고른다
    (실측 now0918-12: 기준선 0.37, 반복 쌍 0.50·0.65).
    """
    n = len(staves)
    if n < 2:
        return []
    # `ink` 는 **오선을 이미 지운** 것이어야 한다 (위 상수 주석의 이유).
    bands = [band(ink, s, spacing) for s in staves]
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            sim[i][j] = sim[j][i] = similar(bands[i], bands[j])
    base = []
    for i in range(n):
        others = sorted(sim[i][j] for j in range(n) if j != i)
        base.append(others[len(others) // 2] if others else 0.0)   # 중앙값
    out = []
    for i in range(n):
        for j in range(i + 1, n):
            v = sim[i][j]
            if v >= thresh and v >= max(base[i], base[j]) * ratio:
                out.append((i, j, round(v, 3)))
    return out


DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}


def rhythm(system: dict) -> list[tuple]:
    """단 하나를 마디별 리듬 문자열로. 음높이는 빼고 **음가와 쉼표만** 본다."""
    out = []
    for m in sorted({n["measure"] for n in system.get("notes", [])}):
        seq = []
        for n in system["notes"]:
            if n["measure"] != m or n.get("chord"):
                continue
            v = DUR.get(n["duration"], 0)
            if n.get("dotted"):
                v = v * 3 // 2
            seq.append(("R" if n.get("rest") else "N", v))
        out.append((m, tuple(seq)))
    return out


def mismatches(struct: dict, pairs) -> list[dict]:
    """닮은 단끼리 리듬이 다른 마디를 찾는다."""
    bad = []
    for i, j, sim in pairs:
        if i >= len(struct["systems"]) or j >= len(struct["systems"]):
            continue
        ra, rb = rhythm(struct["systems"][i]), rhythm(struct["systems"][j])
        # 마디 수가 다르면 그 자체가 불일치다
        if len(ra) != len(rb):
            bad.append({"a": i, "b": j, "sim": sim, "measure": None,
                        "why": f"마디 수 {len(ra)} vs {len(rb)}"})
            continue
        for (ma, sa), (mb, sb) in zip(ra, rb):
            if sa != sb:
                bad.append({"a": i, "b": j, "sim": sim, "measure": (ma, mb),
                            "why": f"{_fmt(sa)}  vs  {_fmt(sb)}"})
    return bad


_S = {32: "o", 16: "h", 24: "h.", 8: "q", 12: "q.", 4: "e", 6: "e.", 2: "s", 3: "s."}


def _fmt(seq) -> str:
    return "".join(("[" + _S.get(v, "?") + "]" if k == "R" else _S.get(v, "?"))
                   for k, v in seq)


def _units(items) -> int:
    """마디 음가 합 (8분음표=4 눈금). 화음 구성음은 박을 안 차지한다."""
    t = 0
    for x in items:
        if x.get("chord"):
            continue
        v = DUR.get(x["duration"], 0)
        t += v * 3 // 2 if x.get("dotted") else v
    return t


def repair(pages: list[list[dict]], ink: np.ndarray, staves,
           spacing: float, beats: float = 4.0) -> int:
    """
    **반복끼리 다르게 읽은 마디를 고친다.** `ink` 는 오선을 지운 것.

    어느 쪽이 맞는지는 이렇게 고른다: **박자 규칙이 손대지 않은 쪽을 믿는다.**
    `fitted` 는 "검출 결과로는 박이 안 맞아서 음가를 비틀었다"는 뜻이므로,
    손 안 댄 읽기가 더 믿을 만하다(실측 now0918-12: 단1 마디1 은 손댄 곳이
    없고 단3 마디1 은 셋이었는데, 쉼표를 놓친 쪽이 단3 이었다).

    **음표 개수가 같을 때만 고친다.** 쉼표는 넣고 빼도 음높이가 안 꼬이지만,
    음표 개수가 다르면 어느 음이 어느 음인지 짝지을 수 없다 — 그때는
    고치지 않고 표시만 남긴다(`repeatDiff`).

    반환: 고친 마디 수.
    """
    if len(pages) != len(staves):
        return 0
    pairs = find_pairs(ink, staves, spacing)
    if not pairs:
        return 0
    fixed = 0
    for i, j, _sim in pairs:
        for mi in range(min(len(pages[i]), len(pages[j]))):
            a, b = pages[i][mi], pages[j][mi]
            ia, ib = a.get("items") or [], b.get("items") or []
            if _rhythm_of(ia) == _rhythm_of(ib):
                continue
            # **어느 쪽을 믿을지 정하는 규칙은 둘이다.**
            #
            # ① 한쪽만 온전한 4박이면 그쪽을 믿는다. 박자 검산이 이미
            #    "깨졌다"고 말한 마디를, 같은 그림의 멀쩡한 짝으로 고치는
            #    것이므로 깨진 마디까지 함께 줄어든다.
            # ② 둘 다 4박이면 **박자 규칙이 손대지 않은 쪽**을 믿는다.
            #    `fitted` 는 "검출로는 박이 안 맞아 음가를 비틀었다"는 뜻이다.
            #
            # 둘 다 4박이 아니면 고르지 않는다 — 어느 쪽도 믿을 근거가 없다.
            # (제한 없이 옮겼더니 깨진 마디가 142→146 으로 늘었다.)
            full = int(beats * 8)
            ua, ub = _units(ia), _units(ib)
            na = sum(1 for x in ia if not x.get("rest"))
            nb = sum(1 for x in ib if not x.get("rest"))
            src = dst = None
            if na == nb:
                if ua == full and ub != full:
                    src, dst = ia, ib
                elif ub == full and ua != full:
                    src, dst = ib, ia
                elif ua == full and ub == full:
                    ta, tb = _touched(ia), _touched(ib)
                    if ta == 0 and tb > 0:
                        src, dst = ia, ib
                    elif tb == 0 and ta > 0:
                        src, dst = ib, ia
            if src is None:
                for x in ia + ib:
                    x["repeatDiff"] = True     # 못 고쳤다는 표시만 남긴다
                continue
            _copy_rhythm(src, dst)
            fixed += 1
    return fixed


def _rhythm_of(items) -> tuple:
    return tuple((bool(x.get("rest")), x["duration"], bool(x.get("dotted")))
                 for x in items if not x.get("chord"))


def _touched(items) -> int:
    return sum(1 for x in items if x.get("fitted") or x.get("guessed"))


def _copy_rhythm(src, dst) -> None:
    """믿는 쪽(src)의 리듬을 dst 에 옮긴다. 음높이는 dst 것을 순서대로 쓴다."""
    heads = [x for x in dst if not x.get("rest")]
    out, k = [], 0
    for x in src:
        if x.get("rest"):
            out.append({"duration": x["duration"], "dotted": bool(x.get("dotted")),
                        "rest": True, "tie": False, "repeatFixed": True})
        else:
            h = heads[k] if k < len(heads) else dict(heads[-1])
            k += 1
            h = dict(h)
            h["duration"] = x["duration"]
            h["dotted"] = bool(x.get("dotted"))
            h["repeatFixed"] = True
            h.pop("fitted", None)
            h.pop("guessed", None)
            out.append(h)
    dst[:] = out
