#!/usr/bin/env python3
"""
멜로디 임시표(♯·♭·♮)를 찾아 **어디를 확인해야 하는지** 알려준다.

왜 필요한가: 픽셀을 밀어 이조하는 방식은 임시표를 다시 계산하지 못한다.
Bb장조의 E♮을 C장조로 한 칸 올리면 자리는 F인데 실제 음은 F♯이어야 한다.
옛 글리프를 그대로 옮기므로 반음이 틀린다.

그런데 실측해보니 이 문제가 생각보다 작다 — 실제 콘티 22쪽, 음표 2,512개에서
**멜로디 임시표는 5개(0.2%)**였다. 조표에 붙은 107개는 이미 정상 교체된다.
그래서 방식을 바꾸는 대신 **어디가 위험한지 짚어주는 쪽**을 택했다.
모르는 위험을 아는 위험으로 바꾸는 것이 지금 가장 값싼 개선이다.

조표 구역과 멜로디를 가르는 기준은 **음자리표 오른쪽 끝 + 4.5칸**이다.
그 안쪽은 조성을 나타내는 조표이고, 바깥은 그 음 하나에만 걸리는 임시표다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sheetcv as cv  # noqa: E402

KIND = {"accidental_sharp": "♯", "accidental_flat": "♭",
        "accidental_natural": "♮"}
KEYSIG_REACH = 4.5      # 음자리표 끝에서 이만큼(칸) 안쪽은 조표


def _measure_of(x: float, bars: list[float]) -> int:
    """마디 번호 = 왼쪽에 있는 마디선 수 + 1."""
    return sum(1 for b in bars if b < x) + 1


def find(img, model, conf: float = 0.50, target: float = 6.5) -> dict:
    """
    이미지에서 멜로디 임시표를 찾는다.

    반환: {"ok": bool, "items": [{system, measure, kind, x, y}], "reason": str}
    검출기를 못 쓰면 ok=False로 돌려준다 — 없는 정보를 있는 척하지 않는다.
    """
    try:
        import evaldet as E
        import probe as P
    except Exception as e:                       # pragma: no cover
        return {"ok": False, "items": [], "reason": f"모듈 없음: {e}"}

    big, _factor = P.upscale(img)
    ink, staves = cv.find_staves_best(big)
    if not staves:
        return {"ok": False, "items": [], "reason": "오선을 찾지 못했습니다"}
    sp = cv.median_spacing(staves)
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=False)

    boxes, _ = E.detect_by_staff(model, big, conf, target)
    items = []
    for i, st in enumerate(staves):
        mid = (st.top + st.bottom) / 2.0
        half = (st.bottom - st.top) * 1.3
        band = [b for b in boxes if abs(b["y"] + b["h"] / 2 - mid) < half]
        clefs = [b for b in band if b["class"] == "clef_g"]
        if not clefs:
            continue
        edge = max(b["x"] + b["w"] for b in clefs) + sp * KEYSIG_REACH
        # 마디선은 영상처리가 더 잘한다 — 폭이 얇아 학습 검출기가 못 찾는다
        bars = sorted(o["x"] + o["w"] / 2
                      for o in cv.find_fixed_objects(strict, st, sp)
                      if o["h"] > sp * 3.2)
        for b in band:
            if b["class"] not in KIND:
                continue
            x = b["x"] + b["w"] / 2
            if x < edge:
                continue                          # 조표 — 이미 교체된다
            items.append({"system": i + 1,
                          "measure": _measure_of(x, bars),
                          "kind": KIND[b["class"]],
                          "x": round(x, 1), "y": round(b["y"] + b["h"] / 2, 1),
                          "conf": round(b.get("conf", 0.0), 2)})
    items.sort(key=lambda d: (d["system"], d["x"]))
    return {"ok": True, "items": items, "reason": ""}


def summary(res: dict) -> str:
    """사용자에게 보여줄 한두 줄."""
    if not res["ok"]:
        return f"임시표 확인 불가 — {res['reason']}"
    n = len(res["items"])
    if n == 0:
        return "멜로디 임시표 없음 — 이조 결과를 그대로 쓰셔도 됩니다."
    where = " · ".join(f"{d['system']}단 {d['measure']}마디 {d['kind']}"
                       for d in res["items"][:6])
    tail = f" 외 {n - 6}개" if n > 6 else ""
    return (f"⚠️  멜로디 임시표 {n}개 — 이 음들은 이조 후 직접 확인하세요.\n"
            f"    {where}{tail}")


def main() -> None:
    import argparse

    from PIL import Image

    ap = argparse.ArgumentParser(description="멜로디 임시표 찾기")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--model", default="models/omr.pt")
    ap.add_argument("--conf", type=float, default=0.50)
    a = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(a.model)
    for p in a.images:
        res = find(Image.open(p).convert("RGB"), model, a.conf)
        print(f"\n═══ {Path(p).name} ═══")
        print(summary(res))


if __name__ == "__main__":
    main()
