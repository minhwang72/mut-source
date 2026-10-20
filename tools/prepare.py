#!/usr/bin/env python3
"""
사진 전처리 + 품질 진단.

웹에서 받은 이미지와 핸드폰 사진은 전혀 다른 문제를 낸다.
실측(3024×4032 화면 촬영본)에서 확인한 것:

| 문제 | 증상 | 대응 |
|---|---|---|
| 화면 모아레 | 빈 여백 화소가 112~254로 4px 주기 진동 | 저역통과(다운샘플) |
| 종이 질감 | 전역 Otsu에서 잉크 비율 38% (정상 3~12%) | Sauvola 적응형 |
| 기울기 | +0.75° → 폭 2400px에서 31px 드리프트 | 투영 프로파일 보정 |
| 조명·초점 기울기 | 아래쪽 선명도 24.7 → 9.3 | 검출 실패를 사용자에게 알림 |

마지막 항목이 중요하다. 사진이 나쁘면 조용히 일부만 처리하는 대신
**무엇이 왜 안 됐는지 알려주고 다시 찍게** 해야 한다.

    python3 tools/prepare.py <이미지> [--out prepared.png] [--debug]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sheetcv as cv

# 이 비율을 넘으면 전역 임계값이 배경을 잉크로 잡은 것 (사진 신호)
PHOTO_INK_RATIO = 0.20
# 오선 간격이 이보다 크면 굳이 원본 해상도를 쓸 필요가 없다.
# 모아레 제거 효과도 같이 얻으므로 이 값까지 줄인다.
TARGET_SPACING = 20.0


def load(path: str) -> Image.Image:
    """EXIF 회전을 적용해 세로/가로를 바로잡는다 (핸드폰 사진 필수)."""
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def analyze(path: str, verbose: bool = False) -> dict:
    """파일 경로용 진입점."""
    report, img, ink, staves = analyze_image(load(path))
    report["source"] = path
    return report, img, ink, staves


# 오선 간격이 이만큼은 되어야 화소 단위 판정(오선 제거·음표 이동·조표 그리기)이
# 정확하다. 실측: 7px에서 음표 머리 보존 76~85%, 13.5px에서 82~94%,
# 20px에서 94~98% (고해상도 원본은 98~100%).
TARGET_SPACING = 18.0
MAX_UPSCALE = 3.0


def _staves_via_upscale(img, staves, report):
    """확대본에서 오선을 더 찾으면 그 결과를 원본 좌표로 되돌려 쓴다."""
    from dataclasses import replace

    sp0 = cv.median_spacing(staves)
    up, scale = upscale_for_spacing(img, sp0)
    if scale <= 1.0:
        return staves
    try:
        _ink, st_up = cv.find_staves_best(up)
    except Exception:
        return staves
    if len(st_up) <= len(staves):
        return staves
    k = 1.0 / scale
    out = []
    for i, s in enumerate(st_up):
        out.append(replace(
            s, index=i,
            top=int(round(s.top * k)), bottom=int(round(s.bottom * k)),
            left=int(round(s.left * k)), right=int(round(s.right * k)),
            lines=[int(round(v * k)) for v in s.lines],
            spans=[(int(round(a * k)), int(round(b * k))) for a, b in s.spans],
        ))
    report["steps"].append(
        f"확대본에서 오선 {len(st_up)}단 (원본 {len(staves)}단) → 확대본 결과 채택"
    )
    return out


def upscale_for_spacing(img: Image.Image, spacing: float) -> tuple[Image.Image, float]:
    """
    오선 간격이 작으면 **확대한다.** 정보가 늘어나진 않지만, 우리 파이프라인은
    전부 화소 단위 판정(세로 런 길이, 1행 인페인팅, 반칸 이동)이라 표현이
    촘촘해지면 정확도가 크게 오른다.

    실측(정답 데이터 있는 픽스처, 음표 머리 보존):
        1배 (간격  7px) → 76~85%
        2배 (간격 13px) → 82~94%
        3배 (간격 20px) → 94~98%
    """
    if spacing <= 0 or spacing >= TARGET_SPACING:
        return img, 1.0
    scale = min(MAX_UPSCALE, TARGET_SPACING / spacing)
    # 조금 모자란 정도면 확대하지 않는다 — 파일만 커지고 이득이 없다
    if scale <= 1.3:
        return img, 1.0
    w = int(round(img.width * scale))
    h = int(round(img.height * scale))
    return img.resize((w, h), Image.LANCZOS), scale


# **연한 오선 구제용 고정 문턱.** Otsu 는 전역 통계, Sauvola 는 국소 통계에
# 기대는데, 150dpi 로 뽑은 PDF 는 오선이 1px 연회색이라 **둘 다 날려 버린다**
# (실측: wish0906-5 는 두 경로 모두 0단, 고정 문턱 200 에서 7단 — 정답).
LIGHT_THRESHOLDS = (180, 200, 220)


def rescue_light_staves(img, ink, staves, report=None):
    """
    문턱을 올려 가며 오선을 더 찾아본다. **더 많이 찾은 경우에만** 바꾼다.

    문턱을 마냥 올리면 잉크가 늘어 오검출이 생기므로, 판정은 `find_staves`
    에 맡긴다 — 5줄이 고르게 서 있어야 한 단으로 친다. 그 조건을 통과한
    단이 더 많다면 진짜로 더 찾은 것이다.
    """
    best_ink, best, best_th = ink, staves, None
    for th in LIGHT_THRESHOLDS:
        try:
            cand_ink = cv.binarize_fixed(img, th)
            cand = cv.find_staves(cand_ink)
        except Exception:                        # noqa: BLE001
            continue
        if len(cand) > len(best):
            best_ink, best, best_th = cand_ink, cand, th
    if best_th is not None and report is not None:
        report["steps"].append(
            f"연한 오선 구제: 고정 문턱 {best_th} → {len(staves)}단 → {len(best)}단")
        report["lightRescue"] = {"threshold": best_th,
                                 "before": len(staves), "after": len(best)}
    return best_ink, best


def analyze_image(img: Image.Image) -> tuple[dict, Image.Image, "np.ndarray", list]:
    """
    이미 열려 있는 이미지를 진단·전처리한다 (서버용 — 파일로 쓰지 않는다).
    반환: (리포트, 보정된 이미지, 잉크 마스크, 오선 목록)
    """
    report: dict = {"size": list(img.size), "steps": []}

    # 스캔 모드를 먼저 시도하고, 오선을 못 찾으면 사진 모드로 폴백한다.
    #
    # 잉크 비율로 사진/스캔을 가르려 했는데 실패했다: 저해상도 웹 이미지는
    # 표기가 화면을 크게 차지해 Otsu 잉크 비율이 21%까지 올라간다(사진과 구별
    # 안 됨). 결과로 판단하는 편이 정확하다 — 스캔 경로가 오선을 제대로
    # 찾았으면 스캔인 것이다.
    otsu = cv.binarize_otsu(img)
    report["otsuInkRatio"] = round(float(otsu.mean()), 4)
    scan_staves = cv.find_staves(otsu)
    scan_sp = cv.median_spacing(scan_staves)

    # 사진 경로는 기울기 탐색까지 하므로 비싸다. 스캔 경로가 이미 충분히
    # 많은 단을 찾았거나 이미지가 작으면(웹 다운로드) 굳이 돌리지 않는다.
    small_image = min(img.size) < 1200
    try_photo = not (small_image and len(scan_staves) >= 3)

    if not try_photo:
        report["mode"] = "scan"
        report["isPhoto"] = False
        ink, staves = otsu, scan_staves

        # Otsu는 전역 문턱이라 인쇄가 옅은 줄을 놓친다. 국소 문턱(Sauvola)은
        # 기울기 탐색이 없어 싸므로 **항상 함께 비교**한다. "3단 이상 찾았으면
        # 충분"이라는 판단으로는 9단 중 8단인지 구별할 수 없다 — 실제 사용자
        # 악보에서 한 단을 놓쳐 그 단만 코드·멜로디·조표가 원본으로 남았다.
        try:
            sauv = cv.binarize_sauvola(img)
            sauv_staves = cv.find_staves(sauv)
        except Exception:
            sauv_staves = []
        if len(sauv_staves) > len(scan_staves):
            ink, staves = sauv, sauv_staves
            report["steps"].append(
                f"전역 Otsu {len(scan_staves)}단 < 국소 Sauvola "
                f"{len(sauv_staves)}단 → Sauvola 채택"
            )
        else:
            report["steps"].append(
                f"전역 Otsu로 오선 {len(scan_staves)}단 확보 → 스캔·웹이미지 경로"
            )
    else:
        report["mode"] = "photo"
        report["isPhoto"] = True
        report["steps"].append(
            f"전역 Otsu 경로: 오선 {len(scan_staves)}단 (간격 {scan_sp:.1f}px)"
        )
        ink = cv.binarize_sauvola(img, radius=max(8, min(img.size) // 60), k=0.35)
        report["sauvolaInkRatio"] = round(float(ink.mean()), 4)
        report["steps"].append(f"Sauvola 적응형 이진화 → 잉크 {ink.mean()*100:.1f}%")

        # 기울기 추정은 축소본에서 (속도)
        small = img.resize((img.width // 3, img.height // 3), Image.LANCZOS)
        skew = cv.estimate_skew(
            cv.binarize_sauvola(small, radius=max(8, min(small.size) // 60), k=0.35)
        )
        report["skewDeg"] = skew
        if abs(skew) > 0.1:
            img = img.rotate(skew, resample=Image.BICUBIC,
                             fillcolor=(255, 255, 255), expand=False)
            ink = cv.binarize_sauvola(img, radius=max(8, min(img.size) // 60), k=0.35)
            report["steps"].append(f"기울기 {skew:+.2f}° 보정")
        photo_staves = cv.find_staves_photo(ink)
        report["steps"].append(
            f"사진 경로: 오선 {len(photo_staves)}단 "
            f"(간격 {cv.median_spacing(photo_staves):.1f}px)"
        )
        # 두 경로 중 오선을 더 많이 찾은 쪽을 쓴다. 동수면 스캔 쪽(단순·안전).
        if len(photo_staves) > len(scan_staves):
            staves = photo_staves
            report["steps"].append("→ 사진 경로 채택")
        else:
            ink, staves = otsu, scan_staves
            report["mode"] = "scan"
            report["isPhoto"] = False
            report["steps"].append("→ 스캔 경로 채택")

    # 두 경로 모두 통계 기반이라 연한 오선을 함께 놓칠 수 있다 — 구제한다.
    ink, staves = rescue_light_staves(img, ink, staves, report)

    # **오선은 확대본에서 세고, 좌표만 원본으로 되돌린다.**
    #
    # 판독 자체는 원본 크기에서 해야 한다(아래 주석: 확대본에서 코드를 찾으면
    # 밴드가 뭉개져 마커스 44개 → 0개가 됐다). 그런데 **오선을 몇 단 찾는지**는
    # 확대본이 훨씬 낫다 — 워터마크가 겹친 악보에서 원본은 8~9단, 확대본은
    # 11단을 찾았다(실측: 「지금 여기 우리」 콘티). 한 단을 놓치면 그 단의
    # 코드·멜로디가 통째로 원본으로 남는다.
    #
    # 그래서 세는 일만 확대본에 맡기고, 찾은 자리를 원본 좌표로 나눠 쓴다.
    staves = _staves_via_upscale(img, staves, report)

    report["staves"] = len(staves)
    spacing = cv.median_spacing(staves)
    report["spacing"] = round(spacing, 1)
    report["steps"].append(f"오선 {len(staves)}단 검출 · 간격 {spacing:.1f}px")

    # 단별 선명도 — 어디가 흐린지 알려주기 위해
    gray = np.asarray(img.convert("L"))
    focus = []
    for st in staves:
        s = cv.sharpness(gray, st.top - 40, st.bottom + 40, st.left, st.right)
        focus.append({"staff": st.index, "y": st.top, "sharpness": round(s, 2)})
    report["focus"] = focus

    if focus:
        vals = [f["sharpness"] for f in focus]
        best = max(vals)
        weak = [f for f in focus if f["sharpness"] < best * 0.55]
        report["weakStaves"] = [w["staff"] for w in weak]
        if weak:
            report["warning"] = (
                f"{len(weak)}개 단이 다른 곳보다 크게 흐립니다"
                f"(선명도 {min(v for v in vals):.1f} vs {best:.1f}). "
                f"이 단은 판독이 실패할 수 있습니다 — 정면에서 평평하게 다시 찍어보세요."
            )

    # ── 확대 배율만 정한다 (여기서 적용하지는 않는다) ─────────────────
    # 확대는 **렌더 품질**을 위한 것이지 판독을 위한 게 아니다. 확대본에서
    # 코드를 찾으면 오선 위 흐릿한 띠가 밴드 폭 전체로 이어져 코드 상자를
    # 통째로 삼킨다(실측: 마커스 악보에서 44개 → 0개).
    # 그래서 **판독은 원본 크기에서, 렌더는 확대본에서** 한다.
    sp0 = cv.median_spacing(staves)
    _, scale = upscale_for_spacing(img, sp0)
    report["upscale"] = round(scale, 2)
    if scale > 1.0:
        report["steps"].append(
            f"오선 간격 {sp0:.1f}px < {TARGET_SPACING:.0f}px → "
            f"렌더는 {scale:.1f}배 확대본으로 (판독은 원본 크기에서)"
        )

    return report, img, ink, staves


def main() -> None:
    ap = argparse.ArgumentParser(description="악보 사진 전처리 · 품질 진단")
    ap.add_argument("image")
    ap.add_argument("--out", help="전처리된 이미지 저장 경로")
    ap.add_argument("--json", help="진단 리포트 JSON 저장 경로")
    args = ap.parse_args()

    report, img, ink, staves = analyze(args.image)

    e = sys.stderr
    print(f"{report['source']}  {report['size'][0]}x{report['size'][1]}  "
          f"[{report['mode']}]", file=e)
    for s in report["steps"]:
        print(f"  · {s}", file=e)
    if report.get("focus"):
        print("  단별 선명도: " +
              " ".join(f"{f['staff']}:{f['sharpness']:.0f}" for f in report["focus"]),
              file=e)
    if report.get("warning"):
        print(f"  ⚠️  {report['warning']}", file=e)

    if args.out:
        img.save(args.out)
        print(f"  → {args.out}", file=e)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
