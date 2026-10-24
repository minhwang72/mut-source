#!/usr/bin/env python3
"""
**실제 콘티로 학습 라벨을 만든다 — 사람 라벨링 없이.**

합성 데이터만으로는 정체됐다(2차 학습 27장 < 1차 29장). 실제 콘티의 생김새(흐림·
카톡 압축·펜 표시)를 배우려면 실제 이미지가 필요한데 정답 상자가 없다. 그래서
**두 판독기(우리 검출기 + homr)가 단 전체를 똑같이 읽은 단**만 골라, 그 단의
검출 상자를 정답으로 쓴다. 독립된 두 판독이 마디마다 같으면 거의 틀리지 않는다
(통과 29장의 마디 98% 이상이 이 일치로 확인됐고 원본 대조에서 틀린 곳이 없었다).

더 걸러 내는 것 — 상자가 실제와 다를 수 있는 단:
  · 판독이 스스로 고친 음표가 있는 단(찍기·되살린 머리·점 승격 등 UNSURE)
  · 점음표인데 그 옆에 붙임점 상자가 없는 단(화소로 점을 찾은 경우 — 상자가 없다)

출력: <out>/images/train/*.png (회색, 오선 간격 6.5px — 추론과 같은 크기) + YOLO 라벨.
외부 API 를 부르지 않는다(로컬 판독 + homr).

    MUTE_HOMR_BIN=.homr-venv/bin/homr .venv/bin/python eval/pseudo_label.py \\
        악보샘플/학습용_이미지 data/real_pseudo
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path[:0] = ["tools", "server"]

import devcache  # noqa: E402

devcache.install()

import crosscheck as C  # noqa: E402
import evaldet as E  # noqa: E402
import homr_runner as H  # noqa: E402
import local_reader as LR  # noqa: E402
import sheetcv as cv  # noqa: E402

NAMES = ["notehead_filled", "notehead_half", "notehead_whole", "flag_8th", "flag_16th",
         "accidental_sharp", "accidental_flat", "accidental_natural", "rest_whole",
         "rest_half", "rest_quarter", "rest_8th", "rest_16th", "clef_g", "timesig",
         "beam1", "beam2", "aug_dot", "tie"]
CLS = {n: i for i, n in enumerate(NAMES)}
TARGET = 6.5          # evaldet.INPUT_SPACING — 추론 때 모델이 보는 오선 간격
MIN_NOTES = 4

_cap: dict = {}
_orig = E.detect_guided


def _spy(model, big, *a, **k):
    out = _orig(model, big, *a, **k)
    if "boxes" not in _cap:                      # 첫 호출 = 기호 검출기(둘째는 붙임줄)
        _cap["boxes"], _cap["img"] = out[0], big
    return out


E.detect_guided = _spy


def strip_ok(sysd: dict, boxes: list, st, sp: float) -> bool:
    notes = sysd.get("notes") or []
    if sum(1 for n in notes if not n.get("rest")) < MIN_NOTES or sysd.get("review"):
        return False
    if not all(n.get("crossChecked") for n in notes):
        return False
    if any(n.get(k) for n in notes for k in C.UNSURE):
        return False
    dots = [b for b in boxes if b["class"] == "aug_dot"]
    for n in notes:
        if n.get("dotted") and n.get("head") and not n.get("rest"):
            h = n["head"]
            cx, cy = h["x"] + h["w"], h["y"] + h["h"] / 2
            if not any(abs(d["x"] - cx) < sp * 1.5 and abs(d["y"] + d["h"] / 2 - cy) < sp
                       for d in dots):
                return False
    return True


def main(src: str, out: str) -> None:
    from PIL import Image
    os.makedirs(f"{out}/images/train", exist_ok=True)
    os.makedirs(f"{out}/labels/train", exist_ok=True)
    stat = {"pages": 0, "systems": 0, "kept": 0, "boxes": 0}
    log = open(f"{out}/log.jsonl", "a")
    for f in sorted(glob.glob(f"{src}/*.png")):
        name = os.path.basename(f)[:-4]
        if os.path.exists(f"{out}/labels/train/{name}_s0.txt"):
            continue
        stat["pages"] += 1
        _cap.clear()
        png = open(f, "rb").read()
        try:
            ex = LR.read_sheet_local(png)
            homr = H.read(png)
        except Exception as e:                   # noqa: BLE001
            print(f"{name}: 실패 {type(e).__name__}: {e}"[:160], flush=True)
            continue
        st = ex.get("struct") or {}
        if not homr or not st.get("systems") or "img" not in _cap:
            continue
        C.merge(st, homr)
        big = _cap["img"].convert("L")
        boxes = _cap["boxes"]
        _ink, staves = cv.find_staves_best(big)
        if len(staves) != len(st["systems"]):
            continue
        sp = cv.median_spacing(staves)
        kept = 0
        for si, (sysd, stf) in enumerate(zip(st["systems"], staves)):
            stat["systems"] += 1
            y0 = max(0, int(stf.top - sp * 5))
            y1 = min(big.height, int(stf.bottom + sp * 6))
            mine = [b for b in boxes if y0 <= b["y"] + b["h"] / 2 <= y1]
            if not strip_ok(sysd, mine, stf, sp):
                continue
            k = TARGET / sp
            crop = big.crop((0, y0, big.width, y1))
            crop = crop.resize((max(1, round(crop.width * k)), max(1, round(crop.height * k))),
                               Image.LANCZOS)
            W, Hh = big.width, y1 - y0
            lines = []
            for b in mine:
                c = CLS.get(b["class"])
                if c is None:
                    continue
                x0 = max(0.0, b["x"]); x1 = min(W, b["x"] + b["w"])
                yy0 = max(0.0, b["y"] - y0); yy1 = min(Hh, b["y"] + b["h"] - y0)
                if x1 <= x0 or yy1 <= yy0:
                    continue
                lines.append(f"{c} {(x0 + x1) / 2 / W:.6f} {(yy0 + yy1) / 2 / Hh:.6f} "
                             f"{(x1 - x0) / W:.6f} {(yy1 - yy0) / Hh:.6f}")
            if not lines:
                continue
            crop.save(f"{out}/images/train/{name}_s{si}.png")
            open(f"{out}/labels/train/{name}_s{si}.txt", "w").write("\n".join(lines) + "\n")
            kept += 1
            stat["boxes"] += len(lines)
        stat["kept"] += kept
        log.write(json.dumps({"page": name, "systems": len(staves), "kept": kept}) + "\n")
        log.flush()
        print(f"{name}: 단 {len(staves)} 중 {kept} 채택 · 누적 {stat}", flush=True)
    print("끝", stat)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
