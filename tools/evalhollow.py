#!/usr/bin/env python3
"""
실제 악보에서 **속 빈 머리를 찾는지** 추론 크기별로 훑는다.

이 파일이 있는 이유: 학습셋의 흰 머리 라벨 절반이 그림과 반대였고(실측 50%),
그 결과 마커스 악보의 흰 머리 15개 중 1개만 검출됐다 — 오분류가 아니라
**아예 안 잡혔다.** 라벨을 정직하게 고친 뒤 진짜 나아졌는지 재려면,
"몇 개 찾았나"를 정답과 대 봐야 한다.

정답은 LLM 구조 읽기(<sheet>.struct.json)의 음가에서 온다. 검출기는 부류를
틀려도 되지만 — 음높이는 상자 위치로만 정해지므로 — **놓치면 안 된다.**
그래서 두 수치를 따로 뽑는다: 총 검출 수(놓침 여부)와 흰 부류 수(분류).

  python tools/evalhollow.py models/omr.pt 악보.jpg --struct 악보.struct.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

HOLLOW = ("notehead_half", "notehead_whole")


def truth(struct_path: Path) -> dict:
    """구조 읽기 결과에서 음가별 개수를 센다."""
    d = json.loads(struct_path.read_text(encoding="utf-8"))

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "notes" and isinstance(v, list):
                    yield from v
                else:
                    yield from walk(v)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v)

    # **쉼표는 빼야 한다.** 2분쉼표·온쉼표는 음가가 half/whole이지만
    # 머리가 없다 — 세면 정답이 부풀어 재현율이 실제보다 낮게 나온다
    # (실측: 음표 131개·흰 15개가 158개·흰 29개로 잘못 잡혔다).
    ns = [n for n in walk(d) if isinstance(n, dict) and not n.get("rest")]
    hol = sum(1 for n in ns if n.get("duration") in ("half", "whole"))
    return {"total": len(ns), "hollow": hol}


def main() -> None:
    ap = argparse.ArgumentParser(description="흰 머리 검출 평가")
    ap.add_argument("weights")
    ap.add_argument("image")
    ap.add_argument("--struct", help="정답용 <sheet>.struct.json")
    ap.add_argument("--conf", type=float, default=0.50)
    ap.add_argument("--targets", default="6.5,8,9,10,11,12,14",
                    help="모델 입력에서의 오선 간격 후보(px)")
    a = ap.parse_args()

    from PIL import Image
    from ultralytics import YOLO

    import evaldet as E
    import sheetcv as cv

    img = Image.open(a.image).convert("L")
    _ink, staves = cv.find_staves_best(img)
    sp = cv.median_spacing(staves)
    print(f"{Path(a.image).name} · {img.size} · 단 {len(staves)}개 · "
          f"오선 간격 {sp:.2f}px")

    t = truth(Path(a.struct)) if a.struct else None
    if t:
        print(f"정답: 음표 {t['total']}개 (그중 흰 머리 {t['hollow']}개)\n")

    model = YOLO(a.weights)
    print(f"{'입력간격':>8s} {'배율':>6s} {'머리합':>7s} {'꽉참':>6s} "
          f"{'2분':>5s} {'온':>4s} {'흰합':>5s}", end="")
    if t:
        print(f" {'놓침':>6s} {'흰재현':>7s}")
    else:
        print()

    for tg in [float(x) for x in a.targets.split(",")]:
        boxes, _n = E.detect_by_staff(model, img, a.conf, tg)
        heads = [b for b in boxes if b["class"].startswith("notehead")]
        f = sum(1 for b in heads if b["class"] == "notehead_filled")
        h = sum(1 for b in heads if b["class"] == "notehead_half")
        w = sum(1 for b in heads if b["class"] == "notehead_whole")
        print(f"{tg:8.1f} {tg/sp:6.2f} {len(heads):7d} {f:6d} "
              f"{h:5d} {w:4d} {h+w:5d}", end="")
        if t:
            miss = t["total"] - len(heads)
            rec = (h + w) / t["hollow"] * 100 if t["hollow"] else 0.0
            print(f" {miss:+6d} {rec:6.0f}%")
        else:
            print()


if __name__ == "__main__":
    main()
