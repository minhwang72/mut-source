#!/usr/bin/env python3
"""
악보 한 장에 두 검출기를 돌려 **어디서 깨지는지** 기록한다.

왜 필요한가: 지금 음표 머리와 가사 음절 검출은 실측으로 맞춘 문턱값
(가로 폭 1.25~2.6칸, 채움률 0.97, 열 높이 0.22배 …)에 기대고 있다.
이 값들은 악보 한 장에서 뽑았다. 다른 출판사·폰트·손글씨에서 그대로
통한다는 근거가 없으므로, **여러 장을 넣어 깨지는 지점을 모아야** 한다.
그 목록이 곧 학습 기반 검출기(YOLO)의 클래스 설계가 된다.

    python3 tools/probe.py <이미지...> [--out 폴더]

각 단마다 이렇게 본다:
  · 음표 머리 개수와 음이름
  · **의심 신호** — 겹친 씨앗(같은 x에 꽉참+속빔), head_end에 잘린 첫 음표,
    오선 밖으로 너무 멀리 나간 머리
  · 가사 음절 개수 · 폭 균일도 · 붙은 덩어리
  · 음표 수 대비 음절 수
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lyricstrip as LS  # noqa: E402
import notes as N  # noqa: E402
import sheetcv as cv  # noqa: E402

TARGET_SPACING = 18.0


def upscale(img: Image.Image) -> tuple[Image.Image, float]:
    """오선 간격을 18px 근처로 올린다. 저해상도에서 조표·머리가 깨진다."""
    _, staves = cv.find_staves_best(img)
    if not staves:
        return img, 1.0
    sp = cv.median_spacing(staves)
    if sp <= 0:
        return img, 1.0
    f = min(3.0, max(1.0, TARGET_SPACING / sp))
    if f < 1.3:
        return img, 1.0
    return img.resize((int(img.width * f), int(img.height * f)),
                      Image.LANCZOS), f


def chord_bottom_of(ink: np.ndarray, st, spacing: float,
                    prev_bottom: int | None) -> float | None:
    """오선 위 코드 글자 띠의 아래끝. 글자 속 구멍이 속 빈 머리로 잡힌다."""
    top = max(0, int(st.top - spacing * 5.5))
    if prev_bottom is not None:
        top = max(top, prev_bottom + int(spacing * 1.5))
    stop = int(st.top - spacing * 0.6)
    if stop <= top:
        return None
    rows = ink[top:stop, :].sum(axis=1)
    hits = np.nonzero(rows > 0)[0]
    return float(top + hits[-1]) if hits.size else None


def probe_image(path: str, out_dir: Path | None) -> dict:
    img = Image.open(path).convert("RGB")
    big, factor = upscale(img)
    ink, staves = cv.find_staves_best(big)
    if not staves:
        return {"file": Path(path).name, "error": "오선을 못 찾음"}
    sp = cv.median_spacing(staves)
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=False)

    rows = []
    prev_bottom = None
    for i, st in enumerate(staves):
        nxt = staves[i + 1].top if i + 1 < len(staves) else None
        cb = chord_bottom_of(ink, st, sp, prev_bottom)
        prev_bottom = int(st.bottom)
        band = cv.find_lyric_band(ink, st, sp, nxt)
        objs = cv.find_fixed_objects(strict, st, sp)

        # head_end를 쓰지 않는다 — 실측에서 첫 음표를 잘랐다(단8, x=220).
        # 대신 조표가 끝나는 지점을 넉넉히 잡는다.
        he = int(st.left + sp * 6)
        heads = N.heads_of_staff(ink, st, sp, objs, band, he, cb)

        # 의심 신호: 같은 x에 꽉참과 속빔이 겹쳐 잡힌 것
        dup = 0
        for a in heads:
            for b in heads:
                if a is b or a["filled"] == b["filled"]:
                    continue
                if abs(a["x"] - b["x"]) < sp * 1.2:
                    dup += 1
                    break
        syl = LS.syllables(ink, band, sp) if band else []
        widths = [(b - a) / sp for a, b in syl]
        merged = sum(1 for w in widths if w > 4.0)
        rows.append({
            "staff": i, "heads": len(heads), "dupPairs": dup // 2,
            "hollow": sum(1 for h in heads if not h["filled"]),
            "syllables": len(syl), "merged": merged,
            "widthMed": round(float(np.median(widths)), 2) if widths else 0.0,
            "widthMax": round(max(widths), 2) if widths else 0.0,
            "pitches": [N.step_name(N.pitch_step(h["y"], st, sp)) for h in heads],
        })

        if out_dir is not None:
            _overlay(out_dir, Path(path).stem, i, big, st, sp, heads, band, syl)

    return {"file": Path(path).name, "scale": round(factor, 2),
            "spacing": round(sp, 1), "staves": len(staves), "rows": rows}


def _overlay(out_dir, stem, i, big, st, sp, heads, band, syl) -> None:
    y0 = max(0, int(st.top - sp * 5))
    y1 = min(big.height, int((band[1] if band else st.bottom + sp * 4) + 8))
    crop = big.crop((0, y0, big.width, y1)).convert("RGB")
    d = ImageDraw.Draw(crop)
    for h in heads:
        r = sp * 0.6
        col = (220, 0, 0) if h["filled"] else (0, 90, 220)
        d.ellipse([h["x"] - r, h["y"] - y0 - r, h["x"] + r, h["y"] - y0 + r],
                  outline=col, width=3)
    for a, b in syl:
        d.rectangle([a, band[0] - y0, b, band[1] - y0],
                    outline=(0, 150, 0), width=2)
    out_dir.mkdir(parents=True, exist_ok=True)
    crop.save(out_dir / f"{stem}_s{i}.png")


def main() -> None:
    ap = argparse.ArgumentParser(description="악보 검출기 진단")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", help="단별 오버레이 이미지를 저장할 폴더")
    a = ap.parse_args()
    out = Path(a.out) if a.out else None

    for p in a.images:
        r = probe_image(p, out)
        print(f"\n═══ {r['file']} ═══")
        if "error" in r:
            print(f"  ⚠️  {r['error']}")
            continue
        print(f"  {r['staves']}단 · 간격 {r['spacing']}px "
              f"(업스케일 {r['scale']}배)")
        print(f"  {'단':>3} {'머리':>4} {'속빔':>4} {'겹침':>4} "
              f"{'음절':>4} {'붙음':>4} {'폭중앙':>6} {'폭최대':>6}")
        for x in r["rows"]:
            flag = ""
            if x["dupPairs"]:
                flag += " ⚠겹침"
            if x["merged"]:
                flag += " ⚠붙음"
            if x["syllables"] and x["heads"] and \
                    abs(x["heads"] - x["syllables"]) > max(3, x["heads"] * 0.4):
                flag += " ⚠개수차"
            print(f"  {x['staff']:>3} {x['heads']:>4} {x['hollow']:>4} "
                  f"{x['dupPairs']:>4} {x['syllables']:>4} {x['merged']:>4} "
                  f"{x['widthMed']:>6.2f} {x['widthMax']:>6.2f}{flag}")


if __name__ == "__main__":
    main()
