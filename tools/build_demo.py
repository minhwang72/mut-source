#!/usr/bin/env python3
"""
데모용 페이로드 생성 — 샘플 악보 + 판독 결과 + 기하 정보를 JSON 하나로.

왜 필요한가: Artifact 런타임에는 Claude 호출 기능이 없어(artifact/downloads/
mcp/self 뿐) 판독을 브라우저에서 할 수 없다. 판독 **이후**의 모든 단계
(이조·멜로디 이동·조표 교체·렌더·PDF)는 이미 브라우저에서 돌므로,
판독 결과를 미리 구워 넣으면 공유 가능한 데모가 된다.

⚠️ 샘플은 **반드시 저작권 없는 악보**여야 한다. 상용 악보를 공유 페이지에
박는 것은 이 프로젝트가 금지하는 바로 그 행위다(설계 제약 4번).
그래서 make_test_sheet.py로 만든 합성 악보를 쓴다.

    python3 tools/build_demo.py <합성악보.png> <truth.json> -o web/demo-data.json
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image

import render
import sheetcv as cv

MIN_SPACING_FOR_STAFF_EDIT = 6.0


def build_geometry(img, ink, staves, src_fifths: int = 0) -> dict:
    """서버의 build_geometry와 동일한 구조 — 브라우저가 이 좌표로 픽셀을 옮긴다."""
    import keysig
    import render

    spacing = cv.median_spacing(staves)
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=False)
    out = []
    for si, st in enumerate(staves):
        # 렌더러와 **같은 함수**로 구한다. 고정 배수를 쓰면 머리 구간이
        # 첫 음표를 덮어, 그 음표만 이동에서 빠지고 새 조표가 위에 덮인다
        # (실측: 첫 음표 x=207 < headEnd 208 → 머리가 뭉개졌다).
        head_end = int(render.head_end_for(strict, st, spacing, src_fifths))
        entry = {
            "index": st.index,
            "staffTop": int(st.top),
            "staffBottom": int(st.bottom),
            "lineSpans": [[int(a), int(b)] for (a, b) in st.spans],
            "left": int(st.left),
            "right": int(st.right),
            "spacing": round(st.spacing, 2),
            "thickness": int(st.thickness),
            "headEnd": head_end,
            # 가사 띠 — 이조와 무관하므로 브라우저가 원본으로 되돌린다.
            # 이동 창이 기둥을 덮으려면 오선 아래로 내려가야 해서 가사 영역과
            # 겹친다(실측: 되돌리지 않으면 가사 일치율 80~90%).
            "lyricBand": (lambda b: [int(b[0]), int(b[1])] if b else None)(
                cv.find_lyric_band(
                    ink, st, spacing,
                    staves[si + 1].top if si + 1 < len(staves) else None)),
            "fixed": [o for o in cv.find_fixed_objects(strict, st, spacing)
                      if o["x"] >= head_end],
            "keysigRegion": None,
            # 조표 오른쪽 첫 요소(대개 박자표). 브라우저가 조표를 키울 때
            # 이 자리까지가 쓸 수 있는 폭이고, 박자표면 오른쪽으로 밀 수 있다.
            "nextBlock": None,
        }
        out.append(entry)

    if spacing >= MIN_SPACING_FOR_STAFF_EDIT:
        for entry, g in zip(out, keysig.geometry_for(strict, staves, src_fifths)):
            entry.update(g)

    return {
        "spacing": round(spacing, 2),
        "inkThreshold": cv.otsu_threshold(img),
        "staffEditOk": spacing >= MIN_SPACING_FOR_STAFF_EDIT,
        "systems": out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("truth", help="make_test_sheet.py의 --extraction 출력")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    img = Image.open(args.image).convert("RGB")
    ink, staves = cv.find_staves_best(img)
    if not staves:
        raise SystemExit("오선을 찾지 못했습니다.")

    with open(args.truth, encoding="utf-8") as f:
        truth = json.load(f)

    # 합성기가 만든 정답 박스를 그대로 쓴다 — 데모는 판독 오차 없이
    # 변환 결과만 보여주는 게 목적이다
    systems = []
    for s in truth["systems"]:
        systems.append({
            "index": s["index"],
            "page": 0,
            "staffTop": s["staffTop"],
            "staffBottom": s["staffBottom"],
            "chords": s["chords"],
        })

    payload = {
        "meta": {
            "title": "샘플 악보",
            "key": truth["meta"]["key"],
            "timeSignature": truth["meta"].get("timeSignature", "4/4"),
            "pageCount": 1,
            "note": "저작권 없는 합성 예시 악보입니다.",
        },
        "imageSize": truth["imageSize"],
        "systems": systems,
        "geometry": build_geometry(
            img, ink, staves,
            render.call_engine(truth["meta"]["key"], 0, [])["fifthsFrom"]),
        "imageDataUri": "data:image/png;base64,"
        + base64.b64encode(Path(args.image).read_bytes()).decode(),
    }

    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    n = sum(len(s["chords"]) for s in systems)
    size = Path(args.out).stat().st_size
    print(f"코드 {n}개 · 오선 {len(staves)}단 · 간격 {payload['geometry']['spacing']}px "
          f"· 조표교체 {payload['geometry']['staffEditOk']}", file=sys.stderr)
    print(f"→ {args.out} ({size // 1024}KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
