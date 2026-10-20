#!/usr/bin/env python3
"""
악보를 **MusicXML로 다시 조판**한다. 픽셀을 밀지 않고 처음부터 그린다.

픽셀 이동의 한계: 오선을 지우고 되돌리는 과정에서 회색 띠·코드 겹침·음표
손상이 생기고, 하나를 고치면 다른 게 깨진다(실측: 한 세션에서 다섯 번).
새로 그리면 그 문제군이 통째로 사라지고 임시표도 자동으로 맞는다.

**원본 배치를 그대로 유지한다** — 찬양팀은 "3단 두 번째 마디"처럼 위치로
소통하고, 한 페이지에 들어가던 곡이 두 장이 되면 넘기며 연주해야 한다.
`<print new-system="yes">` + Verovio `breaks="encoded"` 로 강제한다
(실측: auto 는 9단을 6단으로 흘렸고, encoded 는 원본과 완전 일치).

역할 분담(모두 실측 근거):
  · 음높이   검출기 좌표 → (머리 y − 첫 줄 y) ÷ 반칸.  원가 0
  · 음가·붙임점 검출기 빔 겹수 + 화소.  96.9% / 99.5% / 96.5% (3장)
  · 마디     그림 줄막대 + 박자 역산.  97.4% / 97.9% / 87.2%
  · 붙임줄   곡선 검출기(별도 모델) + 양 끝 음높이 같은가.  8/16 (마커스)
  · 개수     LLM Opus, 단별 음표·쉼표 수만.  출력 33,536 → 4,768토큰
  · 코드     LLM Haiku.  43/43
  · 가사     원본 픽셀 음절.  125/125 (LLM은 한글 가사를 지어낸다)

`--detector` 없이 부르면 옛 경로(LLM이 음가·마디까지 읽는 struct)를 쓴다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import musicxml as M  # noqa: E402
import notes as N  # noqa: E402
import sheetcv as cv  # noqa: E402


def pitch_of(head: dict, st, spacing: float) -> str:
    cy = head["y"] + head["h"] / 2.0
    step = N.pitch_step(cy, st, spacing)
    return N.step_name(step)


def _time_sig(struct: dict) -> tuple[int, int]:
    """
    악보에 적을 박자표 숫자. 판독이 글자로 읽어 왔으면 그대로 쓴다.

    구조의 `beats` 는 **4분음표 환산**이라 6/8 도 3.0 이다. 그 값만 보고
    3/4 로 적으면 빔 묶음이 달라진다 — 그래서 글자를 우선한다.
    """
    ts = str(struct.get("timeSignature") or "")
    if "/" in ts:
        try:
            a, b = ts.split("/")[:2]
            return int(a), int(b)
        except Exception:
            pass
    q = float(struct.get("beats") or 4)
    if abs(q - 3.0) < 1e-6:
        return 3, 4
    if abs(q - 2.0) < 1e-6:
        return 2, 4
    return 4, 4


def apply_sections(measures: list[dict], sections: list[int] | None,
                   plan: dict) -> int:
    """
    단별 원조 조표를 **목표 조표**로 옮겨 마디에 실어 준다.

    이조는 하나의 음악적 간격이므로 fifths 변화량도 일정하다 — G(1)→F#(6)
    이면 +5 이고, 같은 곡 안의 Bb(-2) 구간은 A(3) 이 된다. 그래서 구간마다
    엔진을 다시 부르지 않고 **차이(delta)를 더한다.** 이러면 구간 사이
    간격이 어긋날 수 없다.

    **기준은 `plan`의 원조성이 아니라 첫 단의 실제 조표다.** 코드로 추정한
    원조성과 조표 판독이 다를 수 있고(실측: ex.json 은 Bb, 조표는 G),
    그때 plan 기준으로 재면 **모든 마디에 조표 변경이 붙는다**
    (실측: 마커스 50마디에 `<key>` 50개). 첫 단을 사용자가 고른 목표
    조표에 맞추고, 나머지 구간은 같은 양만큼 옮긴다.

    반환: 조표가 바뀌는 지점 수
    """
    if not sections or not measures:
        return 0
    delta = int(plan["fifthsTo"]) - int(sections[0])
    si = 0
    changes = 0
    prev = None
    for mi, m in enumerate(measures):
        if mi > 0 and m.get("newSystem"):
            si += 1
        src = sections[si] if si < len(sections) else sections[-1]
        f = src + delta
        # 조표는 -7~7 만 있다. 넘으면 같은 소리의 다른 표기로 접는다
        while f > 7:
            f -= 12
        while f < -7:
            f += 12
        m["fifths"] = f
        if prev is not None and f != prev:
            changes += 1
        prev = f
    return changes


def assemble(image_path: str, struct: dict | None, extraction: dict,
             model_path: str, conf: float = 0.50,
             counts: list[dict] | None = None,
             tie_model: str | None = None) -> tuple[list[dict], dict]:
    """
    (measures, report) — 시스템 나누기까지 담긴 마디 목록.

    struct 를 주면 그것을 쓴다(LLM 판독). **counts 만 주면 구조를 검출기로
    읽는다** — 그때 LLM에게 필요한 건 단별 음표 수·쉼표 수뿐이다
    (`detstruct` 첫머리 주석에 실측 근거).
    """
    from PIL import Image
    from ultralytics import YOLO

    import evaldet as E
    import probe as P

    import layout as L

    big, factor = P.upscale(Image.open(image_path).convert("RGB"))
    ink, staves = cv.find_staves_best(big)
    spacing = cv.median_spacing(staves)
    # 막대선 검출은 오선을 지운 그림에서 한다
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=True)
    # **개수를 단서로 문턱을 정한다.** 하나의 문턱으로는 꽉 찬 머리(점수 0.9대)와
    # 속 빈 머리(0.03~0.58)를 같이 못 잡는다. LLM이 단별 음표 수를 주므로
    # 그 수만큼만 낮은 점수를 더 받는다 (실측: 머리 116→129, 흰 1→9).
    import detstruct as DS

    if struct is None and counts is None:
        raise ValueError("struct 나 counts 중 하나는 있어야 합니다.")
    use_det = struct is None
    if counts is None:
        counts = DS.counts_from_struct(struct)
    expect, expect_r = DS.expects(counts)
    boxes, det_meta = E.detect_guided(YOLO(model_path), big, expect,
                                      conf_hi=conf,
                                      expect_rests=expect_r if use_det else None)
    # **단별 원조 조표를 읽는다(전조).** 곡 중간에 키가 바뀌는 콘티가 있고,
    # 하나로 뭉치면 그 구간이 임시표투성이가 된다. 판정 근거는
    # guesskey.keysig_sections 주석 참고.
    sections: list[int] | None = None
    try:
        import guesskey as GK
        sections = GK.keysig_sections(
            E.keysig_counts(YOLO(model_path), big))
    except Exception as e:                       # noqa: BLE001
        print(f"⚠️  단별 조표를 못 읽었습니다({e}) — 한 조표로 그립니다",
              file=sys.stderr)

    if use_det:
        import numpy as np
        import os
        gray = np.asarray(big.convert("L")).astype("float32")
        # **곡선(붙임줄)은 다른 모델로 따로 검출한다** — 근거는
        # detstruct.detect_curves 주석. 없으면 붙임줄만 비운다.
        curves = None
        tm = tie_model or os.environ.get("MUTE_TIE_MODEL")
        if tm and Path(tm).exists():
            curves = DS.detect_curves(big, tm, expect, expect_r)
        elif tm:
            print(f"⚠️  곡선 모델이 없습니다: {tm} — 붙임줄을 비웁니다",
                  file=sys.stderr)
            curves = []
        struct = DS.build_from(boxes, staves, strict, spacing, gray, counts,
                               curves=curves, sections=sections,
                               meta=det_meta)
        # **단별 음표 x 를 함께 남긴다.** 렌더가 가사를 출력 음표 자리로
        # 옮기려면 원본 음표가 어디였는지 알아야 한다(renderpage --heads).
        mids_ = [(s_.top + s_.bottom) / 2.0 for s_ in staves]
        hx: list[list[float]] = [[] for _ in staves]
        for b in boxes:
            if not b["class"].startswith("notehead"):
                continue
            cy = b["y"] + b["h"] / 2.0
            i = min(range(len(mids_)), key=lambda t: abs(mids_[t] - cy))
            hx[i].append(b["x"] + b["w"] / 2.0)
        struct["headX"] = [sorted(v) for v in hx]
        det_struct = struct

    # **코드를 x좌표째로 들고 있는다.** 마디당 하나씩 나눠 주면 한 마디에
    # 코드가 둘 이상인 경우를 버리게 된다(실측: 마커스 43개 중 8개, 19%).
    #
    # **좌표계를 추측하지 말고 판독 결과가 말하는 대로 쓴다.** 코드 상자는
    # 판독할 때 쓴 이미지 좌표이고, 그 크기는 extraction의 `imageSize`에
    # 적혀 있다. 확대 배율(factor)을 그냥 곱하면 안 된다 — 판독이 이미
    # 확대본에서 이뤄졌으면 두 번 곱하는 셈이다(직접 겪었다: 코드 x가
    # 1392 → 3855가 되어 전부 마지막 마디로 밀렸다).
    src_w = float((extraction.get("imageSize") or {}).get("w") or big.width)
    kx = big.width / src_w
    chords_by_sys: dict[int, list[dict]] = {}
    for sysd in extraction.get("systems", []):
        chords_by_sys[sysd["index"]] = [
            {"text": c["text"], "x": c["box"]["x"] * kx}
            for c in sysd["chords"]
            if c.get("text") and not c.get("dropped")]

    # One canonical assembly implementation for browser and CLI. This prevents
    # repairs to pitch/key handling from silently diverging between languages.
    import render as R
    struct = dict(struct)
    struct["sourceFifths"] = R.call_engine(extraction["meta"]["key"], 0, [])["fifthsFrom"]
    if sections is not None:
        struct["systems"] = [dict(s, srcFifths=sections[i]) if i < len(sections)
                             else s for i, s in enumerate(struct["systems"])]
    systems = []
    for i, st in enumerate(staves):
        nmeas = (struct["systems"][i].get("measures", 1)
                 if i < len(struct["systems"]) else 1)
        mine = [h for h in boxes if h["class"].startswith("notehead")
                and abs(h["y"] + h["h"] / 2 - (st.top + st.bottom) / 2)
                < (st.bottom - st.top) * 1.4]
        systems.append({"staffTop": int(st.top), "staffBottom": int(st.bottom),
                        "lineSpans": [[int(a), int(b)] for a, b in st.spans],
                        "spacing": float(st.spacing), "left": int(st.left),
                        "right": int(st.right),
                        "bars": [float(x) for x in L.barlines_fit(strict, st, spacing, mine, nmeas)]})
    geometry = {"systems": systems,
                "heads": [{k: float(h[k]) for k in ("x", "y", "w", "h")}
                          for h in boxes if h["class"].startswith("notehead")]}
    measures, rep = assemble_data(struct, geometry, chords_by_sys)
    rep.update({"stacked": list(det_meta.get("stacked") or []),
                "struct": struct, "sections": sections,
                "scale": round(factor, 2), "spacing": round(spacing, 1)})
    return measures, rep


def assemble_data(struct, geometry, chords=None):
    """Pure structural input; no model or paid service is invoked here."""
    import subprocess
    result = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "assemble.mjs")],
        input=json.dumps({"struct": struct, "geometry": geometry, "chords": chords or {}}),
        capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return data["measures"], data["report"]


def main() -> None:
    ap = argparse.ArgumentParser(description="MusicXML로 다시 조판")
    ap.add_argument("image")
    ap.add_argument("struct", help="readstruct.py 출력")
    ap.add_argument("extraction", help="코드 판독 결과")
    ap.add_argument("-s", "--semitones", type=int, default=0)
    ap.add_argument("-o", "--out", required=True, help="출력 .musicxml")
    ap.add_argument("--model", default="models/omr.pt")
    ap.add_argument("--tie-model", default=None,
                    help="붙임줄(곡선)만 읽을 모델. MUTE_TIE_MODEL 로도 준다")
    ap.add_argument("--dump-struct", help="검출기로 읽은 구조를 여기에 남긴다")
    ap.add_argument("--detector", action="store_true",
                    help="구조(음가·마디)를 검출기로 읽는다. struct 파일에서는 "
                         "단별 음표·쉼표 개수만 쓴다")
    a = ap.parse_args()

    with open(a.struct, encoding="utf-8") as f:
        struct = json.load(f)
    with open(a.extraction, encoding="utf-8") as f:
        ex = json.load(f)

    if a.detector:
        import detstruct as DS
        # struct 파일이 개수만 담고 있어도(readcounts 출력) 그대로 쓴다
        first = (struct.get("systems") or [{}])[0]
        counts = (struct["systems"] if "rests" in first
                  else DS.counts_from_struct(struct))
        measures, rep = assemble(a.image, None, ex, a.model, counts=counts,
                                 tie_model=a.tie_model)
        if a.dump_struct and rep.get("struct"):
            Path(a.dump_struct).write_text(
                json.dumps(rep["struct"], ensure_ascii=False), encoding="utf-8")
    else:
        measures, rep = assemble(a.image, struct, ex, a.model)

    review = Path(a.out).with_suffix(".review.json")
    review.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    if rep.get("unresolved"):
        raise SystemExit(f"원본 확인이 필요한 구간 {len(rep['unresolved'])}개 — {review}")

    import render as R
    plan = R.call_engine(ex["meta"]["key"], a.semitones, [])
    if a.semitones:
        steps, semis = plan["steps"], a.semitones
        for m in measures:
            for n in m["notes"]:
                if n["pitch"]:
                    # **음이름에는 이미 옥타브가 붙어 있다.** 예전엔 글자만
                    # 다뤄서 "4"를 붙이고 뒤를 잘랐는데, 지금은 "B3" + "4" =
                    # "B34"(34옥타브)가 되어 옥타브가 엉뚱해졌다
                    # (실측: -3반음에서 D4가 B3이 아니라 B4로 나왔다).
                    n["pitch"] = M.transpose(n["pitch"], steps, semis)
            if m.get("chords"):
                m["chords"] = [c["to"] for c in
                               R.call_engine(ex["meta"]["key"], semis,
                                             m["chords"])["chords"]]

    n_mod = apply_sections(measures, rep.get("sections"), plan)
    if n_mod:
        print(f"  전조 {n_mod}곳 — 그 마디부터 조표를 바꿉니다", file=sys.stderr)

    meta = ex.get("meta", {})
    # **박자표.** 4/4 를 전제하면 6/8·3/4 악보의 검산과 역산이 통째로 어긋난다
    # (실측: 콘티 73쪽 중 13쪽이 4박이 아니었다). 구조가 알려 주면 그대로 쓴다.
    det = rep.get("struct") or {}
    beats, beat_type = _time_sig(det)
    if (beats, beat_type) != (4, 4):
        print(f"  박자 {beats}/{beat_type} 로 그립니다", file=sys.stderr)
    xml = M.build(measures, fifths=plan["fifthsTo"],
                  beats=beats, beat_type=beat_type,
                  title=meta.get("title", ""),
                  subtitle=meta.get("subtitle", ""),
                  composer=meta.get("composer", ""))
    Path(a.out).write_text(xml, encoding="utf-8")

    e = sys.stderr
    print(f"{rep['systems']}단 · {rep['measures']}마디 · 음표 {rep['notes']}개",
          file=e)
    if rep.get("stacked"):
        print(f"⚠️  화음이 있는 단 {rep['stacked']} — 동시에 울리는 음을 "
              f"순차 음표로 펴서 그립니다. 그 단은 리듬이 원본과 다릅니다",
              file=e)
    if rep.get("mismatch"):
        for mm in rep["mismatch"]:
            print(f"⚠️  단{mm['system']}: 검출 {mm['detected']}개 vs "
                  f"판독 {mm['expected']}개 — 그 단은 음높이가 밀렸을 수 "
                  f"있습니다. 원본과 대조해 주세요", file=e)
    if rep["missingPitch"]:
        print(f"⚠️  음높이를 못 채운 음표 {rep['missingPitch']}개 — "
              f"원본 확인이 필요합니다", file=e)
    print(f"→ {a.out}", file=e)


if __name__ == "__main__":
    main()
