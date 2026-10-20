#!/usr/bin/env python3
"""
학습된 검출기를 **실제 악보로** 평가한다.

합성 검증 점수(mAP)는 참고만 된다 — 검증 세트가 학습과 같은 합성 데이터라
실제보다 쉽다. 진짜 시험은 실제 악보이고, 특히 조판이 다른 두 종류를 함께
봐야 한다: 마커스 인쇄본(오선 굵기 0.333칸)과 위싱 콘티(0.222칸).

세 가지를 본다:
  ① 클래스별 검출 수      — 문턱값 검출기와 비교
  ② 음높이 판독           — 사람이 확인한 정답과 대조
  ③ 그림                  — 숫자만 보면 오검출을 못 잡는다

    python3 tools/report.py <가중치> [--out 폴더]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaldet as E  # noqa: E402
import notes as N  # noqa: E402
import probe as P  # noqa: E402
import readnotes as R  # noqa: E402
import sheetcv as cv  # noqa: E402

SCRATCH = ("/private/tmp/claude-501/-Users-hwangmin-Desktop/"
           "068aa7a5-522c-41c4-8df3-eb7475a40ab2/scratchpad")

SHEETS = [
    ("마커스 내마음다해",
     "/Users/hwangmin/Desktop/악보샘플/내마음다해_-_마커스_악보_B코드.jpg"),
    ("위싱콘티 3쪽", f"{SCRATCH}/conti/p3.png"),
    ("위싱콘티 4쪽", f"{SCRATCH}/conti/p4.png"),
    ("위싱콘티 6쪽", f"{SCRATCH}/conti/p6.png"),
]

# 사람이 격자를 그려 확인한 정답. 마커스 단0 멜로디.
# (첫 음은 처음 C4로 읽었으나, 오선 5줄이 F5·D5·B4·G4·E4로 정확히 매핑되는
#  것을 확인한 뒤 B3로 정정했다 — 덧줄 아래 칸이다.)
TRUTH = {"마커스 내마음다해": {0: ["B3", "D4", "F4", "F4", "D4", "D4", "D4"]}}

# 문턱값 검출기의 실측 성적 (비교 기준)
BASELINE = {"마커스 내마음다해": 92, "위싱콘티 3쪽": 2,
            "위싱콘티 4쪽": 1, "위싱콘티 6쪽": 15}

COLORS = {
    "notehead_filled": (220, 0, 0), "notehead_half": (0, 110, 220),
    "notehead_whole": (0, 110, 220), "flag_8th": (255, 150, 0),
    "flag_16th": (255, 150, 0), "beam1": (140, 60, 220),
    "beam2": (215, 40, 120), "aug_dot": (255, 0, 0),
    "barline": (0, 150, 90), "clef_g": (200, 0, 200),
    "timesig": (120, 80, 0),
}


def evaluate(model, name: str, path: str, out_dir: Path | None,
             conf: float, target: float) -> dict:
    img = Image.open(path).convert("RGB")
    big, factor = P.upscale(img)
    boxes, _ = E.detect_by_staff(model, big, conf, target)
    cnt = Counter(b["class"] for b in boxes)
    heads = sum(v for k, v in cnt.items() if k.startswith("notehead"))

    read = R.read_image(big, boxes)
    rows = []
    for s in read["systems"]:
        rows.append([n["name"] + (n["accidental"] or "")
                     + ("" if n["kind"] == "filled" else "○")
                     for n in s["notes"]])

    hit = None
    if name in TRUTH:
        hit = {}
        for si, want in TRUTH[name].items():
            got = rows[si] if si < len(rows) else []
            same = sum(1 for a, b in zip(want, got) if a == b)
            hit[si] = (same, len(want), got)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        vis = big.copy()
        d = ImageDraw.Draw(vis)
        for b in boxes:
            d.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]],
                        outline=COLORS.get(b["class"], (140, 140, 140)),
                        width=2)
        vis.save(out_dir / f"{Path(path).stem}_pred.png")

    return {"name": name, "scale": round(factor, 2), "staves": read["staves"],
            "heads": heads, "counts": cnt, "rows": rows, "truth": hit}


def main() -> None:
    ap = argparse.ArgumentParser(description="실제 악보 평가")
    ap.add_argument("weights")
    ap.add_argument("--out", default=f"{SCRATCH}/report")
    # 실측: 0.30에서는 마커스 악보에 신뢰도 0.50짜리 오검출이 하나
    # 붙었다. 0.50으로 올리면 그것만 사라지고 진짜 검출은 거의
    # 그대로다(마커스 118→116, 위싱 184→182). 진짜 음표의
    # 신뢰도는 0.82~0.91로 충분히 위에 있다.
    ap.add_argument("--conf", type=float, default=0.50)
    ap.add_argument("--target", type=float, default=6.5,
                    help="모델 입력에서의 오선 간격(px)")
    a = ap.parse_args()

    from ultralytics import YOLO
    model = YOLO(a.weights)
    out = Path(a.out)

    results = []
    for name, path in SHEETS:
        if not Path(path).exists():
            print(f"⚠️  없는 파일: {path}")
            continue
        results.append(evaluate(model, name, path, out, a.conf, a.target))

    print(f"\n{'악보':<18} {'단':>3} {'머리':>5} {'문턱값':>6} {'배수':>5}")
    print("-" * 46)
    for r in results:
        base = BASELINE.get(r["name"])
        mult = f"{r['heads']/base:.0f}배" if base else "—"
        print(f"{r['name']:<18} {r['staves']:>3} {r['heads']:>5} "
              f"{(base if base else 0):>6} {mult:>5}")

    print("\n── 클래스별 ──")
    for r in results:
        top = " ".join(f"{k}={v}" for k, v in r["counts"].most_common(8))
        print(f"  {r['name']}: {top}")

    print("\n── 음높이 정답 대조 ──")
    any_truth = False
    for r in results:
        if not r["truth"]:
            continue
        any_truth = True
        for si, (same, total, got) in r["truth"].items():
            want = TRUTH[r["name"]][si]
            print(f"  {r['name']} 단{si}: {same}/{total} 일치")
            print(f"    정답 {' '.join(want)}")
            print(f"    판독 {' '.join(got) if got else '(없음)'}")
    if not any_truth:
        print("  (정답 데이터가 있는 악보 없음)")

    print(f"\n그림 → {out}")


if __name__ == "__main__":
    main()
