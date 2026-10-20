#!/usr/bin/env python3
"""
원본 악보의 **단·마디 배치**를 읽는다.

왜 필요한가: XML로 새로 그릴 때 조판이 원본과 달라지면 콘티로 못 쓴다.
찬양팀은 "3단 두 번째 마디부터"처럼 위치로 소통하고, 한 페이지에 들어가던
곡이 두 페이지가 되면 넘기며 연주해야 한다. 그래서 **몇 단에 몇 마디씩**을
원본에서 읽어 그대로 강제한다.

마디선은 학습 검출기가 못 찾는다(폭 27 : 높이 747의 극단적 세로 막대라
960px로 줄면 1px가 된다 — 실측 mAP 0.085). 고전적 영상처리가 훨씬 잘한다:
"오선 높이의 대부분을 차지하는 긴 세로 잉크 런". find_fixed_objects 가
그것을 이미 하고 있다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sheetcv as cv  # noqa: E402


def barlines_of(strict, st, spacing: float,
                heads: list[dict] | None = None,
                x_from: float | None = None,
                loose: bool = False) -> list[float]:
    """
    한 단의 마디선 x좌표(중심).

    두 조건을 함께 본다:
      ① **열의 잉크가 오선 높이를 한 줄로 관통한다.** 마디선은 위에서 아래까지
         끊기지 않는다.
      ② **옆에 음표 머리가 없다.** 기둥도 오선을 관통할 수 있다 — 머리가 오선
         아래, 빔이 위에 있으면 그렇다(실측: 높이 조건만으로는 한 단에서
         마디선을 11~16개로 과검출했다. 실제는 3~9개).

    ②는 학습 검출기가 준다. heads 가 없으면 ①만 쓰고, 그때는 과검출을
    감수한다 — 조용히 틀리는 것보다 낫다.
    """
    top, bot = int(st.top), int(st.bottom) + 1
    # **음자리표 뒤부터 본다.** 높은음자리표의 세로 획은 오선을 관통해서
    # 마디선과 구별이 안 된다(실측: 9단 전부에서 x≈82에 거짓 마디선).
    x0 = max(0, int(x_from if x_from is not None else st.left))
    x1 = min(strict.shape[1], int(st.right) + 1)
    if bot <= top or x1 <= x0:
        return []
    # **오선 밖까지 넉넉히 본다.** 마디선은 오선에서 끝나지만 기둥은 빔까지
    # 위로(또는 머리까지 아래로) 뻗는다. 그 차이로 가른다.
    margin = max(2, int(spacing * 1.6))
    wy0 = max(0, top - margin)
    wy1 = min(strict.shape[0], bot + margin)
    band = strict[wy0:wy1, x0:x1]
    height = bot - top
    rel_top = top - wy0
    rel_bot = bot - wy0
    slack = max(1, int(spacing * 0.35))

    if loose:
        # **느슨한 기준: 오선 구간의 채움률.** 엄격한 기준은 "최장 연속런이
        # 오선 밖으로 안 벗어날 것"을 요구하는데, 음표가 빽빽한 단에서는
        # 마디선 열에 빔 잉크가 이어 붙어 런이 삐져나가 걸린다(실측
        # now0918-1 단4: 오선 구간만 보면 14개인데 엄격 기준으로 4개).
        # 대신 기둥까지 받아들이므로 **멀쩡한 단에 쓰면 손해다** — 실측
        # 105장에서 이걸 기본으로 하면 0개였던 장이 5개로 깨졌다.
        # 그래서 호출 쪽이 **박자가 말이 안 될 때만** 이 길로 온다.
        inner = band[rel_top:rel_bot, :]
        fill = inner.sum(axis=0) / max(1, inner.shape[0])
        good = [bool(v >= 0.90) for v in fill]
    else:
        good = []
        for i in range(band.shape[1]):
            col = band[:, i]
            best = bs = 0
            run = 0
            start = 0
            for y, v in enumerate(col):
                if v:
                    if run == 0:
                        start = y
                    run += 1
                    if run > best:
                        best, bs = run, start
                else:
                    run = 0
            be = bs + best - 1
            # 오선 높이를 관통하고, **오선 밖으로 크게 벗어나지 않아야** 한다
            good.append(best >= height * 0.85
                        and bs >= rel_top - slack and be <= rel_bot + slack)

    # 머리가 가까이 있으면 기둥이다 (남은 경우를 걸러낸다)
    if heads:
        near = spacing * 1.1
        hx = [h["x"] + h["w"] / 2.0 for h in heads]
        kept = list(good)
        for i in range(len(kept)):
            if kept[i] and any(abs(x0 + i - c) < near for c in hx):
                kept[i] = False
        # **전부 죽었으면 필터를 포기한다.** 음표가 빽빽한 단에서는 모든
        # 마디선 옆에 머리가 있어 하나도 안 남는다 — 그러면 단 전체가 한
        # 마디가 된다(실측 now0918-1 단4: 후보 4개 → 0개 → 17박).
        # 과검출은 박자 검산·마디 수리가 걸러 주지만, 마디선이 아예 없으면
        # 그 단은 통째로 못 쓴다. 덜 나쁜 쪽을 고른다.
        if any(kept) or not any(good):
            good = kept

    out: list[float] = []
    start = None
    for i, v in enumerate(good):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append(x0 + (start + i - 1) / 2.0)
            start = None
    if start is not None:
        out.append(x0 + (start + len(good) - 1) / 2.0)
    return out


def systems_of(img, heads: list[dict] | None = None,
               marks: list[dict] | None = None) -> dict:
    """
    악보 전체의 배치.

    반환: {"spacing", "systems": [{"index","top","bottom","left","right",
            "barlines":[x...], "measures": n}]}
    """
    ink, staves = cv.find_staves_best(img)
    if not staves:
        return {"spacing": 0.0, "systems": []}
    spacing = cv.median_spacing(staves)
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=False)

    out = []
    for i, st in enumerate(staves):
        mid = (st.top + st.bottom) / 2.0
        half = (st.bottom - st.top) * 1.4
        mine = [h for h in (heads or [])
                if abs(h["y"] + h["h"] / 2.0 - mid) < half]
        others = [b for b in (marks or [])
                  if abs(b["y"] + b["h"] / 2.0 - mid) < half]
        # 머리 구간의 끝 = 첫 음표·쉼표의 왼쪽. 조표 개수에 따라 달라지므로
        # 고정 배수로 잡으면 안 된다.
        firsts = [b["x"] for b in others
                  if b["class"].startswith("notehead")
                  or b["class"].startswith("rest")]
        x_from = (min(firsts) - spacing * 0.6) if firsts else None
        bars = barlines_of(strict, st, spacing, mine, x_from)
        # 단 끝의 겹친 마디선(||, :|)을 하나로 본다
        merged: list[float] = []
        for b in bars:
            # 겹마디선(‖·:‖)은 두 줄이 1~2칸 떨어져 있다. 하나로 센다
            # (실측: 1.2칸으로 잡으니 1.6칸 떨어진 쌍이 두 개로 세어졌다).
            if merged and b - merged[-1] < spacing * 2.4:
                merged[-1] = (merged[-1] + b) / 2.0
                continue
            merged.append(b)
        # **마디 수 = 단 안의 마디선으로 나뉜 구간 수.** 단 왼쪽 끝(음자리표
        # 뒤)에서 시작해 오른쪽 끝까지이므로, 내부 마디선 수 + 1 이다.
        inner = [b for b in merged if st.left + spacing * 3 < b < st.right - spacing * 0.8]
        out.append({
            "index": i, "top": int(st.top), "bottom": int(st.bottom),
            "left": int(st.left), "right": int(st.right),
            "barlines": [round(b, 1) for b in inner],
            "measures": len(inner) + 1,
        })
    return {"spacing": round(spacing, 1), "systems": out}


def main() -> None:
    import argparse

    from PIL import Image

    ap = argparse.ArgumentParser(description="원본 단·마디 배치 읽기")
    ap.add_argument("image")
    ap.add_argument("--upscale", action="store_true",
                    help="렌더와 같은 조건(확대)에서 잰다")
    a = ap.parse_args()

    img = Image.open(a.image).convert("RGB")
    if a.upscale:
        import probe as P
        img, f = P.upscale(img)
        print(f"확대 {f:.2f}배", file=sys.stderr)

    r = systems_of(img)
    print(f"오선 간격 {r['spacing']}px · {len(r['systems'])}단")
    total = 0
    for s in r["systems"]:
        total += s["measures"]
        print(f"  단{s['index']}: 마디 {s['measures']}개 "
              f"(마디선 {len(s['barlines'])}개)")
    print(f"총 마디 {total}개")


if __name__ == "__main__":
    main()


def barlines_fit(strict, st, spacing: float, heads, want: int,
                 x_from: float | None = None) -> list[float]:
    """
    **마디 수를 알고 있을 때** 막대선 위치를 맞춘다.

    왜 필요한가(실측): CV 막대선 검출은 저해상도에서 과검출한다 — 마커스
    악보(폭 582px)에서 단마다 1~4개를 더 셌다(오선 오른쪽 끝을 세고, 6px
    떨어진 중복을 따로 셌다). 그래서 코드를 마디에 배정하는 데 그대로 쓸 수
    없었다.

    그런데 **마디 수는 LLM이 읽어 준다.** 음표 검출에서 개수를 단서로 문턱을
    정한 것과 같은 구조다: CV가 위치를, LLM이 개수를 준다.

    절차: ① 후보를 뽑고 ② 오선 오른쪽 끝의 마지막 막대선을 뺀 뒤
    ③ 가까운 것끼리 합치고 ④ want-1 개로 맞춘다(많으면 간격이 고른 쪽을
    남기고, 적으면 빈 구간을 균등히 나눈다).

    반환: 막대선 x 목록 (want-1 개). want<=1 이면 빈 목록.
    """
    if want <= 1:
        return []
    cand = barlines_of(strict, st, spacing, heads, x_from)
    right = float(st.right)
    # 오선 끝의 마지막 막대선은 마디 구분선이 아니다
    cand = [x for x in cand if x < right - spacing * 1.5]
    # 가까운 것끼리 합친다 (중복 검출)
    merged: list[float] = []
    for x in sorted(cand):
        if merged and x - merged[-1] < spacing * 2.4:
            merged[-1] = (merged[-1] + x) / 2.0
        else:
            merged.append(x)

    need = want - 1
    left = float(st.left)
    if len(merged) == need:
        return merged
    if len(merged) > need:
        # **간격이 고른 조합을 고른다.** 원본 조판은 마디 폭이 들쭉날쭉하지만,
        # 과검출된 거짓 막대선은 진짜 옆에 붙어 있어 간격을 크게 망친다.
        import itertools
        best, score = None, None
        for combo in itertools.combinations(merged, need):
            pts = [left] + list(combo) + [right]
            gaps = [pts[i + 1] - pts[i] for i in range(len(pts) - 1)]
            if min(gaps) <= spacing * 2:
                continue                       # 너무 좁은 마디는 없다
            avg = sum(gaps) / len(gaps)
            var = sum((g - avg) ** 2 for g in gaps)
            if score is None or var < score:
                best, score = list(combo), var
        return best if best else merged[:need]
    # 모자라면 가장 넓은 구간을 쪼갠다
    pts = [left] + merged + [right]
    while len(pts) - 2 < need:
        gaps = [(pts[i + 1] - pts[i], i) for i in range(len(pts) - 1)]
        _g, i = max(gaps)
        pts.insert(i + 1, (pts[i] + pts[i + 1]) / 2.0)
    return pts[1:-1]
