#!/usr/bin/env python3
"""
구조 읽기 결과를 **박자로 검산한다.**

이 검사가 있는 이유: 음가·마디는 LLM이 읽고 음높이는 검출기가 잰다. 그런데
LLM이 음표를 하나 빠뜨렸는지 어떻게 아나? 정답 악보가 없으면 못 안다 —
**단 하나, 박자표를 빼면.** 4/4박이면 마디마다 음가 합이 정확히 4분음표
4개분이어야 한다. 안 맞으면 그 마디에서 뭔가 놓쳤거나 잘못 읽은 것이다.

실측 근거: 쉼표를 안 읽던 판독으로 39마디를 검산했더니 18마디가 안 맞았는데,
그중 17개는 쉼표가 빠진 탓이고 진짜 오류는 1개(5.00박)였다. 쉼표를 읽게 한
뒤에야 이 검사가 오류 검출기로 쓸 만해진다.

  python tools/checkbeats.py 악보.struct.json [--beats 4]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

# 8분음표 = 4로 두는 내부 단위 (musicxml.DIVISIONS=8과 같은 눈금)
DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}


def beats_per_measure(struct: dict) -> list[dict]:
    """단마다 {마디: 음가합} 을 낸다 (내부 단위, 4분음표 = 8)."""
    out = []
    for s in struct["systems"]:
        per = collections.defaultdict(int)
        for n in s.get("notes", []):
            if n.get("chord"):
                continue            # 화음 구성음은 박을 차지하지 않는다
            v = DUR.get(n.get("duration"), 0)
            if n.get("dotted"):
                v = v * 3 // 2
            per[n.get("measure")] += v
        out.append(dict(per))
    return out


def splits(per: list[dict], full: int) -> list[tuple[int, int, int]]:
    """
    **단 경계에서 쪼개진 마디**를 찾는다.

    악보는 마디 중간에서 줄을 바꾸기도 한다. 그러면 앞 단의 마지막 마디와
    뒷 단의 첫 마디가 각각 반쪽이 되어 검산에 걸리는데, 오류가 아니다 —
    합이 정확히 한 마디면 원래 한 마디다(실측: 단7 마디4가 2박, 단8 마디1이
    2박으로 합 4박이었다).

    이걸 모르면 재조립 때 **없는 줄막대를 하나 그린다.**

    반환: [(앞단 번호, 앞단 마디, 뒷단 마디), ...]
    """
    out = []
    for i in range(len(per) - 1):
        a, b = per[i], per[i + 1]
        if not a or not b:
            continue
        la, fb = max(a), min(b)
        if a[la] < full and b[fb] < full and a[la] + b[fb] == full:
            out.append((i, la, fb))
    return out


def check(struct: dict, beats: int = 4, unit: int = 4) -> dict:
    """
    반환: {"ok": 맞은 마디, "over": [...], "under": [...], "splits": [...]}

    `over`(초과)는 **확실한 오류**다 — 음표를 더 읽었거나 음가를 크게 봤다.
    `under`(미달)는 쉼표를 안 읽었을 때도 나므로, 쉼표 정보가 있을 때만
    오류로 센다. 단 경계에서 쪼개진 마디는 둘을 합쳐 한 마디로 검산한다.
    """
    full = DUR["quarter"] * beats * 4 // unit
    has_rest = any("rest" in n for s in struct["systems"]
                   for n in s.get("notes", []))
    per = beats_per_measure(struct)
    sp = splits(per, full)
    # 쪼개진 짝은 검산에서 한 마디로 본다
    skip = set()
    for i, la, fb in sp:
        skip.add((i, la))
        skip.add((i + 1, fb))

    # **곡의 첫 마디가 짧으면 못갖춘마디(pickup)다.** 조판 관행이고 오류가
    # 아니다. 고전적 판정("첫 마디 + 마지막 마디 = 한 마디")은 이 레퍼토리에
    # 안 맞는다 — 실측 103장 중 첫 마디가 짧은 20장 **전부** 그 짝이 안 맞았다.
    # 콘티 악보는 반복해서 부르므로 마지막 마디가 온전한 경우가 많다.
    # 그래서 짝을 요구하지 않고 첫 마디만 면제한다. 면제한 사실은 남긴다.
    pickup = None
    if per and per[0]:
        m0 = min(per[0])
        if 0 < per[0][m0] < full:
            pickup = (0, m0, per[0][m0] / DUR["quarter"])
            skip.add((0, m0))

    over, under, ok = [], [], len(sp)
    for i, pm in enumerate(per):
        for m in sorted(pm):
            if (i, m) in skip:
                continue
            v = pm[m]
            if v == full:
                ok += 1
            elif v > full:
                over.append((i, m, v / DUR["quarter"]))
            else:
                under.append((i, m, v / DUR["quarter"]))
    return {"full": full, "beats": beats, "has_rest": has_rest,
            "checked": ok + len(over) + len(under), "ok": ok,
            "over": over, "under": under, "splits": sp, "pickup": pickup}


def main() -> None:
    ap = argparse.ArgumentParser(description="구조 읽기 박자 검산")
    ap.add_argument("struct")
    ap.add_argument("--beats", type=int, default=4)
    a = ap.parse_args()

    d = json.loads(Path(a.struct).read_text(encoding="utf-8"))
    r = check(d, a.beats)
    bad = r["over"] + (r["under"] if r["has_rest"] else [])
    print(f"{a.beats}/4박 · 검산한 마디 {r['checked']}개 · 맞음 {r['ok']}개")
    for i, la, fb in r["splits"]:
        print(f"  · 단{i} 마디{la} + 단{i+1} 마디{fb} = 한 마디 "
              f"(단 경계에서 쪼개짐)")
    if not r["has_rest"]:
        print("  ⚠ 쉼표 정보가 없어 '미달' 마디는 판단을 보류합니다 "
              f"({len(r['under'])}개). readstruct를 --force로 다시 돌리세요.")
    for i, m, v in sorted(bad):
        tag = "초과" if v > r["full"] / DUR["quarter"] else "미달"
        print(f"  ✗ 단{i} 마디{m}: {v:.2f}박 ({tag})")
    if not bad:
        print("  ✓ 어긋난 마디 없음")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
