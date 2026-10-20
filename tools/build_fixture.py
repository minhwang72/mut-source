#!/usr/bin/env python3
"""
검출 박스(detect_chords.py 출력) + 사람이 확인한 코드 텍스트를
SheetExtraction 픽스처로 합친다.

실제 파이프라인에서는 텍스트를 AI가 잘라낸 조각에서 읽는다.
이 스크립트는 그 단계를 사람 판독으로 대체해 렌더러를 먼저 검증하기 위한 것이다.

    python3 tools/build_fixture.py detect.json truth.json -o fixture.json
"""

from __future__ import annotations

import argparse
import json
import sys


def build(detect: dict, truth: dict) -> dict:
    systems_out = []
    total = 0

    for sysdet in detect["systems"]:
        idx = sysdet["index"]
        spec = truth["systems"].get(str(idx)) or truth["systems"].get(idx)
        if spec is None:
            raise SystemExit(f"단 {idx}의 정답 텍스트가 없습니다.")

        texts: list[str] = spec["chords"]
        # 오검출로 확인된 박스의 x좌표. AI 판독 단계라면 "코드 아님"으로 걸러진다.
        skip_x = set(spec.get("skipBoxX", []))

        boxes = sorted(sysdet["chords"], key=lambda c: c["x"])
        boxes = [b for b in boxes if b["x"] not in skip_x]

        if len(boxes) != len(texts):
            raise SystemExit(
                f"단 {idx}: 박스 {len(boxes)}개 ≠ 텍스트 {len(texts)}개\n"
                f"  박스 x좌표: {[b['x'] for b in boxes]}\n"
                f"  텍스트: {texts}"
            )

        chords = [
            {
                "text": t,
                "box": {"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"]},
                "confidence": spec.get("confidence", {}).get(t, 1.0),
            }
            for t, b in zip(texts, boxes)
        ]
        total += len(chords)

        systems_out.append(
            {
                "index": idx,
                "page": 0,
                "staffTop": sysdet["staffTop"],
                "staffBottom": sysdet["staffBottom"],
                "chords": chords,
                **({"lyric": spec["lyric"]} if "lyric" in spec else {}),
            }
        )

    print(f"코드 {total}개 · {len(systems_out)}단 매칭 완료", file=sys.stderr)
    return {
        "meta": truth["meta"],
        "imageSize": detect["imageSize"],
        "systems": systems_out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("detect")
    ap.add_argument("truth")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    with open(args.detect, encoding="utf-8") as f:
        detect = json.load(f)
    with open(args.truth, encoding="utf-8") as f:
        truth = json.load(f)

    result = build(detect, truth)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"→ {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
