#!/usr/bin/env python3
"""
로컬 판독기 — **외부 API를 한 번도 부르지 않는다.**

기존 read_sheet(serve.py) 와 같은 모양의 결과를 내되, 코드 글자는
Tesseract(로컬)로 읽고 개수 판독(LLM)은 아예 하지 않는다.

정직하게 남기는 것:
  · 개수 단서가 없으므로 검출 문턱을 낮춰 채우지 않는다. 속 빈 머리·2분쉼표가
    빠질 수 있고, 그건 qualityGate 가 `needs_review` 로 잡는다.
  · 박자 합이 맞는다고 품질을 주장하지 않는다. 실제로 웹과 **같은 조립 코드**
    (tools/assemble.mjs → web/rebuild.js)를 돌려 미해결 항목을 받아 온다.
  · 조성은 조표 검출로 좁히지만 장·단조를 가르지 못한다. X-Key-Hint 가
    없으면 추정이라고 표시하고 review 로 보낸다.

이미지는 메모리에만 있고 디스크로 내려가지 않는다. 모델은 읽기만 하며,
자동 내려받기는 하지 않는다(경로가 실제로 있을 때만 YOLO 를 만든다).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

os.environ['YOLO_OFFLINE'] = 'true'
os.environ['YOLO_AUTOINSTALL'] = 'false'

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

# 원본 저장소의 모델을 **읽기만** 한다. 이 작업 사본에는 models/ 가 없다.
FALLBACK_MODEL_DIR = Path("/Users/hwangmin/development/pj/min/mut/models")

MAJOR_BY_FIFTHS = {-7: "Cb", -6: "Gb", -5: "Db", -4: "Ab", -3: "Eb", -2: "Bb",
                   -1: "F", 0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B",
                   6: "F#", 7: "C#"}

# ponytail: 프로세스 전역 락 하나로 YOLO 로딩과 추론을 함께 직렬화한다.
# 기본 워커가 1개라 경합이 없다. 워커를 늘릴 때 모델별 락으로 쪼개면 된다.
_LOCK = threading.Lock()
_MODELS: dict[str, object] = {}


def model_path(env: str = "MUTE_MODEL", name: str = "omr.pt") -> Path | None:
    """검출기 가중치 경로. 없으면 None — **이름만 넘겨 내려받지 않는다.**"""
    p = os.environ.get(env)
    if p:
        return Path(p) if Path(p).exists() else None
    for base in (REPO / "models", FALLBACK_MODEL_DIR):
        w = base / name
        if w.exists():
            return w
    return None


def model_version() -> str:
    """캐시 키에 들어갈 모델 지문. 모델을 바꾸면 이전 결과를 재사용하지 않는다."""
    parts = []
    for env, name in (("MUTE_MODEL", "omr.pt"), ("MUTE_TIE_MODEL", "omr_tie.pt")):
        w = model_path(env, name)
        parts.append(f"{name}:none" if w is None
                     else f"{name}:{w.stat().st_size}:{int(w.stat().st_mtime)}")
    return "|".join(parts)


def _model(path: Path):
    """프로세스당 한 번만 적재한다. YOLO 생성은 수백 MB·수 초짜리다."""
    key = str(path)
    m = _MODELS.get(key)
    if m is None:
        from ultralytics import YOLO
        m = _MODELS[key] = YOLO(key)
    return m


# ─────────────────────────────────────────────────────────── 판독 본체

def read_sheet_local(image_bytes: bytes, key_hint: str | None = None,
                     time_hint: str | None = None,
                     progress=None) -> dict:
    """이미지 바이트 → 구조 데이터. 저장하지 않고, 외부 호출도 하지 않는다."""
    import detect_chords
    import local_chords
    import probe
    import render
    import sheetcv as cv
    from PIL import Image

    step = progress or (lambda *_a: None)

    step("prepare", 10)
    with Image.open(io.BytesIO(image_bytes)) as source:
        # Match browser decoding: EXIF orientation is applied by modern browsers.
        from PIL import ImageOps
        source = ImageOps.exif_transpose(source).convert('RGBA')
        img = Image.new('RGBA', source.size, 'white')
        img.alpha_composite(source)
        img = img.convert('RGB')
    ink, staves = cv.find_staves_best(img)
    if not staves:
        raise ValueError(blank_reason(ink) or
                         "오선을 찾지 못했습니다. 악보가 맞는지, 잘리거나 "
                         "흐리지 않은지 확인해 주세요.")

    issues: list[str] = []
    # **기울기 보정은 배율이 아니다.** 브라우저는 scale 만 적용하므로,
    # 회전이 들어간 판은 좌표가 원본 사진과 어긋난다. 숨기지 않고 알린다.
    skew = 0.0
    spacing = cv.median_spacing(staves)
    scale = min(3.0, max(1.0, probe.TARGET_SPACING / spacing))
    if scale < 1.3:
        scale = 1.0
    if img.width * img.height * scale * scale > 24_000_000:
        raise ValueError('확대 후 이미지가 너무 큽니다. 악보를 한 단씩 나누어 올려 주세요.')
    report = {'size': list(img.size), 'staves': len(staves), 'spacing': spacing,
              'upscale': scale, 'skewDeg': 0, 'mode': 'scale-only'}

    step("chords", 30)
    detect = detect_chords.detect_from_ink(img, ink, staves)
    boxes = [{"system": s["index"], **c}
             for s in detect["systems"]
             for c in sorted(s["chords"], key=lambda b: b["x"])]

    step("ocr", 45)
    reads = local_chords.read_boxes(img, boxes) if boxes else []

    # **단 하나도 빠뜨리지 않는다.** 코드가 없는 단도 자리를 만든다 —
    # 구조(struct)와 단 수가 어긋나면 브라우저가 통째로 물러난다.
    systems = [{"index": st.index, "page": 0, "chords": [],
                "staffTop": int(st.top), "staffBottom": int(st.bottom)}
               for st in staves]
    chord_issues = []
    for b, r in zip(boxes, reads):
        si = b["system"]
        if not (0 <= si < len(systems)):
            continue
        box = {"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"]}
        if not r["ok"]:
            chord_issues.append({"system": si, "box": box, "reason": r["reason"],
                                 "text": r["text"]})
            continue
        systems[si]["chords"].append({"text": r["text"], "box": box,
                                      "confidence": r["confidence"]})
        if r["reason"]:
            chord_issues.append({"system": si, "box": box, "reason": r["reason"],
                                 "text": r["text"]})
    if chord_issues:
        issues.append(f"코드 {len(chord_issues)}개를 확인해야 합니다 "
                      f"(못 읽음·확신도 낮음)")

    # ── 조성 ────────────────────────────────────────────────────────
    step("key", 55)
    key, key_meta = _resolve_key(img, key_hint)
    if not key_meta["certain"]:
        issues.append(key_meta["reason"])
    src_fifths = render.call_engine(key, 0, [])["fifthsFrom"]

    # ── 렌더용 확대 ──────────────────────────────────────────────────
    # 판독은 원본 크기에서 끝났다. 좌표만 같은 배율로 옮긴다(서버가 하는
    # 좌표 변환은 **배율뿐**이며 브라우저가 그대로 따라한다).
    scale = float(report.get("upscale", 1.0))
    if scale > 1.0:
        big = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
        ink_b, staves_b = cv.find_staves_best(big)
        if staves_b and len(staves_b) == len(staves):
            r = lambda v: int(round(v * scale))                      # noqa: E731
            for sysd in systems:
                for k in ("staffTop", "staffBottom"):
                    sysd[k] = r(sysd[k])
                for c in sysd["chords"]:
                    bx = c["box"]
                    bx["x"], bx["y"] = r(bx["x"]), r(bx["y"])
                    bx["w"], bx["h"] = max(1, r(bx["w"])), max(1, r(bx["h"]))
            for ci in chord_issues:
                bx = ci["box"]
                bx["x"], bx["y"] = r(bx["x"]), r(bx["y"])
                bx["w"], bx["h"] = max(1, r(bx["w"])), max(1, r(bx["h"]))
            img, ink, staves = big, ink_b, staves_b
        else:
            scale = 1.0

    step("geometry", 70)
    import serve  # 순수 함수만 가져온다 (build_geometry / _add_barlines)

    geometry = serve.build_geometry(img, ink, staves, src_fifths)
    geometry["scale"] = scale
    geometry["deskewDeg"] = round(skew, 2)

    step("structure", 80)
    struct, heads, struct_issues = _read_structure_local(img, ink, staves,
                                                         src_fifths, time_hint)
    issues.extend(struct_issues)
    geometry["heads"] = heads
    if struct and struct.get("systems"):
        serve._add_barlines(geometry, ink, staves, struct, heads)

    extraction = {
        "meta": {"key": key, "pageCount": 1,
                 "timeSignature": (struct or {}).get("timeSignature") or ""},
        "imageSize": {"w": img.width, "h": img.height},
        "systems": systems,
        "quality": report,
        "keyGuess": key_meta,
        "geometry": geometry,
        "struct": struct,
        "chordIssues": chord_issues,
        "reader": "local",
        "modelVersion": model_version(),
        "cost": {"directApiCalls": 0},
    }

    step("verify", 92)
    extraction["qualityGate"] = quality_gate(extraction, issues)
    return extraction



# 잉크가 이 아래면 "빈 종이"로 본다.
# **실측 105장**: 빈 표지 2장은 정확히 0.0000 이고, 오선을 찾은 103장은
# 최소 0.0315 · 5% 0.0367 · 중앙값 0.0719 였다. 둘 사이가 넓게 비어 있어
# 0.004 면 가장 옅은 악보보다 8배 아래다. 글자만 있는 속표지는 이 값을
# 넘겨 일반 문구로 빠지는데, 그게 맞다 — 빈 종이가 아니라 악보가 아닌
# 페이지이므로 "악보가 맞는지 확인해 주세요"가 옳은 안내다.
BLANK_INK = 0.004


def blank_reason(ink) -> str | None:
    """
    오선을 못 찾았을 때, **왜 못 찾았는지 나눠서 말한다.**

    빈 페이지한테 "더 밝고 평평하게 찍어 주세요"는 쓸모없는 조언이다 —
    사진이 어둡거나 기울어서가 아니라 **아무것도 없어서**다. 콘티 PDF 에는
    표지가 흔해서 실제로 자주 올라온다(실측: 실사용 하드 실패 4건이 전부
    이 사유였고, 견본 105장 중 2장도 빈 표지였다).
    """
    import numpy as np
    a = np.asarray(ink)
    if a.size == 0:
        return "빈 이미지입니다."
    ratio = float((a > 0).mean()) if a.dtype != bool else float(a.mean())
    if ratio <= BLANK_INK:
        return ("내용이 거의 없는 빈 페이지로 보입니다. "
                "표지 말고 악보가 있는 쪽을 올려 주세요.")
    return None


def _resolve_key(img, key_hint: str | None) -> tuple[str, dict]:
    """
    조성. **힌트가 있으면 그게 정답**이고, 없으면 조표에서 좁히되 추정으로 둔다.

    조표는 장·단조를 가르지 못한다(♭1 은 F장조와 d단조가 같다). 코드 통계로
    가르는 길도 있지만 실측에서 갈렸다(guesskey 주석) — 자동 판정이 틀리면
    악보 전체가 틀리므로, 여기서는 **모른다고 말한다.**
    """
    if key_hint:
        return key_hint, {"key": key_hint, "certain": True, "basis": "사용자 지정",
                          "reason": None}
    fifths = _keysig_fifths(img)
    if fifths is None:
        return "C", {"key": "C", "certain": False, "basis": "기본값",
                     "reason": "원조성을 확인하지 못했습니다 — 직접 골라 주세요"}
    key = MAJOR_BY_FIFTHS.get(int(fifths), "C")
    return key, {"key": key, "certain": False, "basis": f"조표 fifths={fifths}",
                 "reason": f"조표로 {key}장조로 추정했습니다 — 단조일 수 있어 확인이 필요합니다"}


def _keysig_fifths(img) -> int | None:
    """조표의 ♯/♭ 개수 → fifths. 확대본에서 센다(원본 크기에선 거의 안 잡힌다)."""
    w = model_path()
    if w is None:
        return None
    try:
        import evaldet as E
        import guesskey as G
        import probe as P
        big, _f = P.upscale(img.convert("RGB"))
        with _LOCK:
            counts = E.keysig_counts(_model(w), big.convert("L"))
        return G.keysig_fifths(counts)
    except Exception as e:                        # noqa: BLE001
        print(f"  조표 세기 실패: {e}", file=sys.stderr)
        return None


def _read_structure_local(img, ink, staves, src_fifths: int,
                          time_hint: str | None) -> tuple[dict, list, list[str]]:
    """
    구조(음가·붙임점·마디)를 **검출기만으로** 만든다. 개수 판독(LLM)은 없다.

    개수 단서가 없으므로 detect_guided 의 저점수 보충을 끄고(expect=0) 높은
    문턱만 쓴다. 속 빈 머리·2분쉼표가 빠질 수 있으며 그건 조립 검증이 잡는다.
    """
    issues: list[str] = []
    w = model_path()
    if w is None:
        return ({"error": "검출기 가중치가 없습니다 (MUTE_MODEL 확인)"}, [],
                ["음표 구조를 읽지 못했습니다 — 검출기 가중치가 없습니다"])
    try:
        import numpy as np

        import detstruct as DS
        import evaldet as E
        import guesskey as GK
        import sheetcv as cv

        n = len(staves)
        zero = [0] * n
        with _LOCK:
            model = _model(w)
            boxes, detmeta = E.detect_guided(model, img, zero, conf_hi=0.50,
                                             expect_rests=zero)
            # **단별 조표는 전조가 있을 때만 쓴다.**
            # rebuild.js 는 `srcFifths ?? sourceFifths` 로 단별 값을 먼저
            # 본다 — 전조가 없는 악보에서 이 값을 실어 보내면, 검출이 한 번만
            # 빗나가도 **사용자가 고른 조성을 덮어쓴다**(실측: 합성 악보가
            # ♭2인데 단별로 ♭5가 나왔다). 값이 단마다 같으면 전조 정보가
            # 아니라 잡음일 뿐이므로 비운다.
            sections = None
            try:
                per = GK.keysig_sections(E.keysig_counts(model, img))
                if per and len(set(per)) > 1:
                    sections = per
                    issues.append("곡 중간에 조표가 바뀌는 것으로 보입니다 — 확인이 필요합니다")
            except Exception as e:                # noqa: BLE001
                print(f"  단별 조표 실패: {e}", file=sys.stderr)

            # **여기서만** 개수를 쓴다. 붙임줄 모델에 줄 기대치는 방금 우리가
            # 센 것이지 LLM이 읽어 준 것이 아니다.
            curves = None
            tie = model_path("MUTE_TIE_MODEL", "omr_tie.pt")
            if tie is not None:
                ex, exr = _local_expects(boxes, staves)
                try:
                    curve_boxes, _ = E.detect_guided(_model(tie), img, ex, expect_rests=exr)
                    curves = [b for b in curve_boxes if b['class'] == 'tie']
                except Exception as e:            # noqa: BLE001
                    print(f"  붙임줄 검출 실패: {e}", file=sys.stderr)
                    issues.append("붙임줄을 읽지 못했습니다")
            else:
                issues.append("붙임줄 모델이 없어 붙임줄을 비웠습니다")

        sp = cv.median_spacing(staves)
        strict = cv.remove_staff_lines(ink, staves, protect_noteheads=True)
        gray = np.asarray(img.convert("L")).astype("float32")

        counts: list[dict] = [{} for _ in staves]
        if time_hint and counts:
            counts[0]["time_signature"] = time_hint

        # repair=False — 박자 합이 맞는다고 없던 줄막대·음가를 만들지 않는다.
        struct = DS.build_from(boxes, staves, strict, sp, gray, counts,
                               curves=curves, sections=sections, meta=detmeta,
                               repair=False, dots=DOT_PROMOTE,
                               repeats=REPEAT_FIX, merged=SPLIT_MERGED,
                               fit=FIT_PAGE,
                               # 빨간 펜 표시를 붙임점으로 세지 않게 — ai 경로와 같다
                               rgb=np.asarray(img.convert("RGB")))
        struct["sourceFifths"] = int(src_fifths)
        if not time_hint and not struct.get("timeSignature"):
            issues.append(f"박자표를 읽지 못해 마디 {struct.get('beats')}박으로 "
                          f"추정했습니다 — X-Time-Signature 로 알려 주세요")
        heads = [{"x": int(b["x"]), "y": int(b["y"]),
                  "w": int(b["w"]), "h": int(b["h"]), "cls": b["class"]}
                 for b in boxes if b["class"].startswith("notehead")]
        return struct, heads, issues
    except Exception as e:                        # noqa: BLE001
        print(f"  구조 조립 실패: {e}", file=sys.stderr)
        return ({"error": str(e)[:200]}, [], [f"음표 구조를 읽지 못했습니다: {e}"[:160]])


def _local_expects(boxes, staves) -> tuple[list[int], list[int]]:
    """검출 결과를 단별로 나눠 개수를 센다 — build_from 과 같은 방식으로 나눈다."""
    mids = [(s.top + s.bottom) / 2.0 for s in staves]
    ex = [0] * len(staves)
    exr = [0] * len(staves)
    for b in boxes:
        cy = b["y"] + b["h"] / 2.0
        i = min(range(len(mids)), key=lambda k: abs(mids[k] - cy))
        if b["class"].startswith("notehead"):
            ex[i] += 1
        elif b["class"].startswith("rest"):
            exr[i] += 1
    return ex, exr


# 한 기둥에 머리가 여럿 달린 비율이 이보다 높으면 2성부로 본다.
# 실측 103장에서 이 값이 두 부류를 정확히 갈랐다 — 2성부 악보 4장은
# 44~55%, 리드시트 99장은 0~33%.
# **붙임점 승격만 따로 켠다.** repair 는 없던 음가를 찍어 만들 수 있어
# 꺼 두지만, 붙임점 승격은 화소에서 본 흔적을 박자가 확인해 주는 것이라
# 성격이 다르다. 측정으로 켜고 끌 수 있게 환경변수로 둔다.
DOT_PROMOTE = os.environ.get("MUTE_DOT_PROMOTE", "1") != "0"
# **반복 비교 수리 — 켠다.** 박자 검산이 통과시킨 마디를 잡는 유일한
# 심판이다(쉼표를 음표로 잘못 읽고 음가를 비틀어 4박을 맞춘 마디는 합이
# 맞으니 검산이 통과시킨다).
#
# A/B 103장: 깨진 마디 809 -> 793(-16) · 맞던 마디가 깨진 경우 0.
# 고친 마디를 짝과 나란히 놓고 눈으로 확인했다 — Verse 1/2/3 짝짓기가
# 맞았고, 고친 내용도 맞았다(기둥 없는 머리를 half -> whole, 온쉼표 옆
# 헛검출 16분쉼표 제거). 붙임점 문턱 때처럼 지표만 보고 켜지 않았다.
REPEAT_FIX = os.environ.get("MUTE_REPEAT_FIX", "1") != "0"
# **합쳐진 마디 분리 — 켠다.** 줄막대를 놓치면 두 마디가 하나로 붙는다.
#
# A/B 103장: 깨진 마디 793 -> 773(-20). 보고된 "나빠짐 2" 는 측정 한계다 —
# 마디를 쪼개면 번호가 밀리는데(day2sb-4 는 30 -> 34) A/B 가 (단, 마디번호)
# 로 비교해서 새 번호를 나빠짐으로 센다. 실제로 맞던 마디가 깨진 자리는
# 0 개였고, 번호와 무관한 총계가 줄었다.
#
# 이 수리기는 합이 기준의 **정확한 배수**이고 자를 자리가 음표 경계에 딱
# 떨어질 때만 나눈다. 맞는 마디는 배수가 1 이라 애초에 후보가 아니다.
SPLIT_MERGED = os.environ.get("MUTE_SPLIT_MERGED", "1") != "0"
# 박자 기반 음가 수리. **이것만은 찍기다** — 합이 맞을 때까지 음가를
# 비튼다. 기본값 꺼짐. 깨진 마디 수로는 판단할 수 없어서(정의상
# 줄어든다) 찍은 음표 수와 게이트 통과 장 수를 함께 재고 정한다.
# **켠다.** 비어 보이는 마디보다 채워진 마디가 낫고, 찍은 자리는 화면이
# guessed 로 짚어 준다. 과금은 quality_gate 가 따로 막는다 — 찍은 음표가
# 하나라도 있으면 통과시키지 않는다.
FIT_PAGE = os.environ.get("MUTE_FIT_PAGE", "1") != "0"

TWO_VOICE = 0.35


def two_voice_ratio(struct: dict) -> float:
    """화음 구성음이 전체 음표에서 차지하는 비율. 2성부의 지표."""
    tot = ch = 0
    for s in (struct.get("systems") or []):
        for n in (s.get("notes") or []):
            if n.get("rest"):
                continue
            tot += 1
            if n.get("chord"):
                ch += 1
    return ch / tot if tot else 0.0


_UNITS = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}


def broken_beam_groups(struct: dict) -> int:
    """
    8분 박자 격자에서 끝나지 않는 빔 묶음 수 — fitdur._whole_groups 와 같은
    기준(끝나는 자리)을 구조 데이터에 적용한다. 쉼표는 자리만 차지하고
    화음 구성음은 자리를 차지하지 않는다.
    """
    bad = 0
    for sy in struct.get("systems") or []:
        pos: dict[int, int] = {}
        ends: dict[tuple, int] = {}
        for n in sy.get("notes") or []:
            if n.get("chord"):
                continue
            mi = n.get("measure")
            v = _UNITS.get(n.get("duration"), 8)
            pos[mi] = pos.get(mi, 0) + (v * 3 // 2 if n.get("dotted") else v)
            g = n.get("beamGroup")
            if g is not None and g >= 0 and not n.get("rest"):
                ends[(mi, g)] = pos[mi]
        bad += sum(1 for v in ends.values() if v % 4)
    return bad


def quality_gate(extraction: dict, issues: list[str]) -> dict:
    """
    **박자 합으로 품질을 주장하지 않는다.** 브라우저가 실제로 쓰는 조립
    코드(web/rebuild.js)를 tools/assemble.mjs 로 그대로 돌려, 그것이
    "못 풀었다"고 말한 항목을 받아 온다.

    이건 자동 점검이지 정답 보증이 아니다 — 사람이 봐야 하는 것을 놓치지
    않게 하려는 것이지, 통과했다고 원본과 같다는 뜻이 아니다.
    """
    struct = extraction.get("struct") or {}
    geo = extraction.get("geometry") or {}
    # **돈은 "상품이 나왔는가"로 받는다.** 두 가지를 섞어 세면 안 된다.
    #
    #   notes(안내) — 다시 그려는 줬고 한 항목을 짐작했다는 말이다.
    #     "조표를 못 읽어 C장조로 추정했습니다" 같은 것. 사용자는 화면에서
    #     키를 직접 고를 수 있다. 이게 과금을 막으면 **조표가 없는 악보는
    #     아무리 잘 읽어도 영원히 무료**다(실사용 35건 전부 환불된 이유).
    #
    #   found(차단) — 아래에서 우리가 직접 찾아낸 것. rebuild.js 가 "이 단을
    #     다시 그릴 수 없다"고 한 것이 여기 들어온다. 상품이 안 나왔다.
    #
    # 가르는 기준을 문자열로 두지 않는다 — 문구가 바뀌면 조용히 틀어진다.
    # **들어온 것은 안내, 여기서 찾은 것은 차단**이라는 출처로 가른다.
    notes = list(issues)
    found: list[str] = []

    # **찍은 음표가 있으면 돈을 받지 않는다.**
    #
    # fit_page 는 박자 합이 맞을 때까지 음가를 비튼다. 그러면 게이트가
    # 통과하는데, 그건 "잘 읽었다"가 아니라 "합을 맞춰 놨다"는 뜻이다.
    # 지어낸 음표가 든 악보에 돈을 받는 일이 여기서 생긴다.
    #
    # 다만 고친 것을 다 막지는 않는다. fitdur 는 두 단계로 표시한다 —
    # 고칠 방법이 하나뿐이라 연역한 것은 fitted, 답이 여럿이라 고른 것만
    # guessed 다. 앞은 증거가 있고 뒤는 없다. **경계는 거기다.**
    #
    # 실측 103장: fit_page 를 켜면 게이트 통과가 0 -> 11장인데, 그중 4장만
    # 찍은 음표가 0 이다. 나머지 7장은 최대 16개를 찍고도 통과한다.
    guessed = sum(1 for sy in (struct.get("systems") or [])
                  for n in (sy.get("notes") or []) if n.get("guessed"))
    if guessed:
        # **다시 막는다.** 한동안 막지 않고 알리기만 했다. 그때 근거는
        # "막으면 사실상 아무도 통과하지 못한다"였다 — 배포 경로 25장에서
        # 추정이 하나도 없는 장이 2장뿐이었다.
        #
        # **그 전제가 바뀌었다.** 지어내는 이유를 하나씩 없애고 다시 재니
        # (40장, 배포 설정으로 게이트 · 수리를 꺼서 깨진 마디):
        #   통과 8장 중 **4장이 지어낸 음가 0** · 깨진 마디 0~1
        # 막아도 팔 게 남는다. 그러면 "짐작한 자리를 표시하고 받는다"보다
        # **"지어내면 안 받는다"**가 낫다 — 약속이 단순하고, 틀린 악보에
        # 돈을 받을 일이 없다.
        #
        # fitted(고칠 방법이 하나뿐이라 연역한 것)는 여전히 막지 않는다.
        # 경계는 **증거가 있느냐**다.
        found.append(f"박자를 맞추려고 음가 {guessed}군데를 짐작했습니다 — "
                     f"원본과 달라질 수 있어 과금하지 않습니다")

    # **빔 묶음이 8분 단위로 안 끝나면 어딘가 틀렸다.** 붙임점 하나가 옆
    # 음으로 옮겨 붙으면 마디 합은 그대로라 박자 검사를 통과한다(실측
    # day2conti-2: 점8분+16분을 8분+16분, 옆 8분에 점 — 틀린 채 과금).
    # 묶음은 8+16(0.75박)처럼 끝날 수 없으므로, 남아 있으면 막는다.
    bad = broken_beam_groups(struct)
    if bad:
        found.append(f"빔 묶음 {bad}개의 음가 합이 박에 맞지 않습니다 — "
                     f"붙임점을 잘못 읽었을 수 있어 과금하지 않습니다")

    two = two_voice_ratio(struct)
    if two >= TWO_VOICE:
        # **2성부 악보는 지원하지 않는다.** 두 성부가 한 오선에 겹쳐 있으면
        # 한 기둥에 여러 머리가 달려 박 계산이 성립하지 않고, 박자 역산이
        # 마디를 통째로 비튼다. 실측 103장: "한 마디에서 음가를 3개 이상
        # 고친" 마디의 상위를 2성부 악보가 차지했다(상위 10장 화음비 중앙값
        # 13%, 전체는 0%). 고쳐서 내보내는 것보다 **못 읽는다고 말하는 게**
        # 낫다 — 검사를 통과하지 못하므로 크레딧도 차감되지 않는다.
        found.append("두 성부가 한 오선에 겹친 악보(합창·2부)는 아직 "
                     "지원하지 않습니다. 멜로디 한 줄짜리 악보를 올려 주세요")

    if struct.get("error") or not struct.get("systems"):
        found.append("음표 구조가 없어 다시 그릴 수 없습니다")
    elif len(struct["systems"]) != len(geo.get("systems") or []):
        found.append(f"단 수가 다릅니다 (구조 {len(struct['systems'])} vs "
                     f"오선 {len(geo.get('systems') or [])})")
    else:
        chords = {str(s["index"]): [{"text": c["text"], "x": c["box"]["x"]}
                                    for c in s["chords"]]
                  for s in extraction["systems"]}
        try:
            proc = subprocess.run(
                ["node", str(REPO / "tools" / "assemble.mjs")],
                input=json.dumps({"struct": struct, "geometry": geo,
                                  "chords": chords}),
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode != 0:
                found.append(f"구조 검증 실패: {proc.stderr.strip()[:120]}")
            else:
                rep = json.loads(proc.stdout)["report"]
                # **간주 줄은 오류가 아니다.** 콘티에는 멜로디 없이 코드만
                # 적힌 줄이 있다(간주·전주). 음표가 없는 게 맞는데 게이트는
                # "읽은 음표·쉼표가 없어 원본 확인 필요"로 막는다.
                # 실측: 검출 신뢰도를 0.05 까지 내려도 그 줄의 머리 후보는
                # 0개였고, LLM 도 0개라고 답했다 — 둘 다 맞았고 게이트만
                # 틀렸다. 코드가 있는 줄에 한해 이 사유를 뺀다.
                interlude = {
                    si for si, sy in enumerate(struct.get("systems") or [])
                    if not (sy.get("notes") or [])
                    and len(((extraction.get("systems") or [{}])[si]
                             if si < len(extraction.get("systems") or [])
                             else {}).get("chords") or []) > 0}
                seen = set()
                for u in rep.get("unresolved", []):
                    si = u.get("system", 0)
                    if si in interlude and "읽은 음표" in str(u.get("reason")):
                        continue
                    msg = f"단 {si + 1}: {u.get('reason')}"
                    if msg not in seen:
                        seen.add(msg)
                        found.append(msg)
                if rep.get("missingPitch"):
                    found.append(f"음높이를 정하지 못한 음표 {rep['missingPitch']}개")
        except Exception as e:                    # noqa: BLE001
            found.append(f"구조 검증 실패: {e}"[:160])

    return {"status": "ready" if not found else "needs_review",
            # 화면은 둘을 나눠 보여 준다. issues 는 예전 이름이라 남긴다.
            "blocking": found[:40],
            "notes": notes[:40],
            "twoVoice": round(two, 3),
            "issues": (found + notes)[:40],
            "checkedBy": "local automated checks (not a correctness guarantee)"}
