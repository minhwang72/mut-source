#!/usr/bin/env python3
"""
학습된 검출기를 **실제 악보**에 돌려 손으로 깎은 검출기와 비교한다.

합성 데이터에서 잘 나오는 것은 아무 의미가 없다. 우리가 확인해야 하는 건
**조판을 넘어서 되는가** 하나다 — 실측으로 문턱값 검출기는 마커스 악보
(머리 폭 2.21칸)에서 단당 7~18개를 잡다가 위싱 콘티(1.39칸)에서 0~1개로
전멸했다. 학습 모델이 두 악보 모두에서 비슷하게 나와야 성공이다.

    python3 tools/evaldet.py runs/omr/weights/best.pt 악보.png ... --out 폴더
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import notes as N  # noqa: E402
import probe as P  # noqa: E402
import sheetcv as cv  # noqa: E402

HEAD_CLASSES = {"notehead_filled", "notehead_half", "notehead_whole"}
COLORS = {
    "notehead_filled": (220, 0, 0), "notehead_half": (0, 110, 220),
    "notehead_whole": (0, 110, 220), "flag_8th": (255, 150, 0),
    "flag_16th": (255, 150, 0), "accidental_sharp": (0, 160, 0),
    "accidental_flat": (0, 160, 0), "accidental_natural": (0, 160, 0),
    "clef_g": (200, 0, 200), "timesig": (120, 80, 0),
}


def handmade_counts(img: Image.Image) -> list[int]:
    """문턱값 검출기가 단마다 머리를 몇 개 잡는지."""
    big, _ = P.upscale(img)
    ink, staves = cv.find_staves_best(big)
    if not staves:
        return []
    sp = cv.median_spacing(staves)
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=False)
    out = []
    prev = None
    for i, st in enumerate(staves):
        nxt = staves[i + 1].top if i + 1 < len(staves) else None
        cb = P.chord_bottom_of(ink, st, sp, prev)
        prev = int(st.bottom)
        band = cv.find_lyric_band(ink, st, sp, nxt)
        objs = cv.find_fixed_objects(strict, st, sp)
        out.append(len(N.heads_of_staff(ink, st, sp, objs, band,
                                        int(st.left + sp * 6), cb)))
    return out


# 모델 입력에서의 오선 간격 목표값. 학습셋이 바뀌면 이 값도 다시 재야 한다
# (학습 분포가 곧 최적 추론 크기다). 세 곳에서 따로 쓰던 6.5를 여기로 모았다.
INPUT_SPACING = 6.5


def _gray(img):
    """
    **검출기 입력을 회색 한 장으로 통일한다.**

    합성 학습 데이터는 회색 PNG다(`gendata`가 mode "L"로 저장한다). 그런데
    호출부마다 RGB를 넣기도 하고 L을 넣기도 했는데, **같은 이미지가 다르게
    검출됐다**(실측: 같은 악보에서 머리 199개 vs 200개, 한 단에서는 낮은 점수
    후보를 5개 받느냐 0개 받느냐로 갈렸다). 그러면 재조립과 감사가 서로 다른
    답을 보고 "배관이 어긋났다"는 잘못된 결론이 나온다.
    """
    return img if getattr(img, "mode", None) == "L" else img.convert("L")


def detect_by_staff(model, big, conf: float, target: float = INPUT_SPACING):
    """
    **단별로 잘라, 모델 입력에서 오선 간격이 target px가 되도록** 넣는다.

    전체 쪽을 통째로 넣으면 YOLO가 긴 변을 imgsz에 맞추므로, 쪽 크기가
    모델이 보는 기호 크기를 좌우한다. 같은 모델이 악보마다 다른 조건을
    받게 되어 결과가 널뛴다 — 실측: 마커스 악보를 단별로 넣었을 때
    입력 간격 6.5px에서 머리 100개, 10px에서 16개였다.
    단을 잘라 넣으면 가사·다음 단이 섞이지 않는 이점도 있다.
    """
    import numpy as np
    # 색은 _gray 전에 떠 둔다 — 회색으로 바꾸면 빨간 글자와 검은 머리가
    # 구분되지 않는다.
    rgb = np.asarray(big.convert("RGB")) if hasattr(big, "convert") else None
    big = _gray(big)
    ink, staves = cv.find_staves_best(big)
    if not staves:
        return [], {}
    sp = cv.median_spacing(staves)
    out, names = [], {}
    for st in staves:
        y0 = max(0, int(st.top - sp * 5))
        y1 = min(big.height, int(st.bottom + sp * 6))
        strip = big.crop((0, y0, big.width, y1))
        need = int(strip.width * (target / sp))
        size = 32 * max(1, round(need / 32))
        r = model.predict(strip, imgsz=size, conf=conf, verbose=False)[0]
        names = r.names
        for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(),
                           r.boxes.conf.tolist()):
            out.append({"class": r.names[int(c)], "conf": float(s),
                        "x": b[0], "y": b[1] + y0,
                        "w": b[2] - b[0], "h": b[3] - b[1]})
    return out, names


def main() -> None:
    ap = argparse.ArgumentParser(description="검출기 실제 악보 평가")
    ap.add_argument("weights")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--target", type=float, default=6.5,
                    help="모델 입력에서의 오선 간격(px)")
    a = ap.parse_args()

    from ultralytics import YOLO

    model = YOLO(a.weights)
    out_dir = Path(a.out) if a.out else None

    for path in a.images:
        img = Image.open(path).convert("RGB")
        big, factor = P.upscale(img)
        boxes, names = detect_by_staff(model, big, a.conf, a.target)
        cnt = Counter(b["class"] for b in boxes)
        heads = sum(v for k, v in cnt.items() if k in HEAD_CLASSES)
        hand = handmade_counts(img)

        print(f"\n═══ {Path(path).name} (확대 {factor:.2f}배) ═══")
        print(f"  학습 모델  머리 {heads}개 · 전체 {len(boxes)}개")
        print("   " + " ".join(f"{k}={v}" for k, v in cnt.most_common()))
        print(f"  문턱값     머리 {sum(hand)}개  단별 {hand}")

        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            vis = big.copy()
            d = ImageDraw.Draw(vis)
            for b in boxes:
                d.rectangle([b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]],
                            outline=COLORS.get(b["class"], (130, 130, 130)),
                            width=2)
            vis.save(out_dir / f"{Path(path).stem}_pred.png")


if __name__ == "__main__":
    main()


# × 머리(리듬 슬래시) 판정: 머리 개수 / 빔·꼬리 개수가 이보다 작으면 후보
SLASH_RATIO = 0.4
# 음자리표 뒤 조표가 차지하는 폭 (오선 간격 배수). ♭·♯ 네 개까지 덮는다.
KEYSIG_ALLOW = 3.0


# **유채색 오검출을 색으로 거른다.**
# 실측(8장 1110개 검출): 상대>=0.20 · 절대>=0.80 으로 37개를 버리는데
# 36개가 진짜 오검출이었다 — 빨간 코드 상자(A D/A E/G# F#m7) 31개,
# 파란 손글씨 3, 빨간 펜 1, 컬러 텍스트 1. 오제거는 1개뿐.
# 진짜 음표는 검정이라 두 조건을 같이 만족하지 않는다.
#   · 상대채도 — 주변보다 유채색인가. 형광펜은 띠 전체를 물들이므로
#     절대값만 보면 그 단의 진짜 음표를 통째로 잃는다(실측 24개).
#   · 절대채도 — 잉크 자체가 유채색인가. 스캔 색수차로 검은 머리가
#     상대채도만 높아지는 경우를 뺀다(실측 wish0830 5개).
COLOR_REL = 0.20
COLOR_ABS = 0.80
# 형광펜이 단을 통째로 물들이면 그 단에서 색은 정보가 아니다 — 잉크까지
# 물들어 진짜 음표가 유채색이 된다(실측: wish0906 청록 단에서 14개 오제거).
# 잉크 화소의 이만큼이 유채색이면 그 단은 색 판정을 끈다.
COLOR_SKIP_FRAC = 0.20


def washed(rgb, y0: int, y1: int) -> bool:
    """이 단이 형광펜으로 물들었는가."""
    if rgb is None:
        return False
    import numpy as np
    band = rgb[max(0, y0):y1].astype("float32")
    if band.size == 0:
        return False
    mx = band.max(axis=2); mn = band.min(axis=2)
    ink = mx < 200
    if ink.sum() < 50:
        return False
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0.0)
    return float((sat[ink] > 0.4).mean()) >= COLOR_SKIP_FRAC


def _sat_dark(patch):
    """가장 어두운 10% 화소의 채도 중앙값. 배경이 아니라 잉크를 본다."""
    import numpy as np
    if patch.size == 0:
        return 0.0
    mx = patch.max(axis=2); mn = patch.min(axis=2)
    lum = patch.mean(axis=2)
    k = max(4, int(lum.size * 0.10))
    idx = np.argsort(lum, axis=None)[:k]
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0.0)
    return float(np.median(sat.flatten()[idx]))


def colored(rgb, x, y, w, h) -> bool:
    """이 상자는 유채색 표시인가(= 음표가 아닌가)."""
    if rgb is None or w <= 0 or h <= 0:
        return False
    import numpy as np
    H, W = rgb.shape[:2]
    w, h = int(w), int(h)
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(W, int(x) + w), min(H, int(y) + h)
    if x1 <= x0 or y1 <= y0:
        return False
    inner = rgb[y0:y1, x0:x1].astype("float32")
    sa = _sat_dark(inner)
    if sa < COLOR_ABS:
        return False
    # **주변에서 상자 자신을 뺀다.** 안 빼면 상자가 창의 1/9 이라 "가장
    # 어두운 10%"가 상자 자신으로 채워져 차이가 늘 0 이 된다.
    oy0, oy1 = max(0, y0 - h), min(H, y1 + h)
    ox0, ox1 = max(0, x0 - w), min(W, x1 + w)
    ring = rgb[oy0:oy1, ox0:ox1].astype("float32").copy()
    ring[y0 - oy0:y1 - oy0, x0 - ox0:x1 - ox0] = 255.0   # 흰색으로 덮어 제외
    return (sa - _sat_dark(ring)) >= COLOR_REL


def detect_guided(model, big, expect: list[int], conf_hi: float = 0.50,
                  conf_lo: float = 0.05, target: float = INPUT_SPACING,
                  expect_rests: list[int] | None = None,
                  conf_mark: float = 0.25,
                  head_ends: list[int] | None = None,
                  skip_boxes: list[dict] | None = None) -> tuple[list, dict]:
    """
    **개수를 단서로 문턱을 정한다.**

    왜 필요한가(실측): 학습된 검출기는 속 빈 머리(2분·온음표)를 **보고 있는데
    점수가 낮다.** 마커스 악보에서 문턱 0.50이면 흰 머리 1개, 0.30이면 5개,
    0.05면 11개가 나왔다(점수 0.58 0.49 0.39 0.37 0.35 0.25 0.16 …).
    꽉 찬 머리는 0.9대에서 나오므로, 하나의 문턱으로는 둘을 같이 못 잡는다.

    그런데 **몇 개인지는 이미 안다** — LLM이 단별 음표 수를 읽어 준다.
    그래서 높은 문턱으로 확실한 것부터 채우고, 개수가 모자라면 낮은 점수
    후보를 겹치지 않는 것만 순서대로 더 받는다. 개수가 맞으면 멈춘다.
    문턱을 무조건 낮추는 것과 다르다 — 넘치게 받지 않는다.

    **쉼표도 같은 방식으로 채운다.** 쉼표를 문턱 하나에 맡기면 2분쉼표가
    빠진다(실측: 마커스에서 단1 −2개, 단3 −2개). 2분쉼표는 짧은 막대 하나라
    점수가 낮게 나오는데, 빠지면 마디가 2박씩 모자라 **마디 수를 산술로
    유도할 수 없다.**

    expect: 단별로 기대하는 음표 머리 개수 (쉼표 제외)
    **빔·꼬리는 문턱을 따로 낮춘다.** 둘 다 머리 기둥 자리에 붙어 있어야만
    음가로 세어지므로(durations._level), 낮게 받아도 엉뚱한 자리의 오검출은
    그냥 무시된다. 실측: 마커스 단5의 8분 꼬리가 0.417, 위싱 단2의 빔이
    0.464로 문턱 0.50에 걸려 빠졌고, 그 하나씩 때문에 그 단의 박자 합이
    어긋났다.

    expect_rests: 단별로 기대하는 쉼표 개수 (없으면 문턱만 쓴다)
    **곡선(tie)도 낮게 받는다.** 붙임줄로 인정되려면 같은 높이의 이웃 머리
    둘 사이를 덮어야 하므로(durations/detstruct._ties), 엉뚱한 자리의 곡선은
    그냥 무시된다. 실측: 문턱 0.5면 마커스 9개인데 0.2~0.5 구간에 9개가 더
    있었다.

    conf_mark: 빔·꼬리·곡선에만 쓰는 낮은 문턱
    반환: (boxes, meta) — meta에 단별로 몇 개를 낮은 점수에서 받았는지 남긴다
    """
    import numpy as np
    # 색은 _gray 전에 떠 둔다 — 회색으로 바꾸면 빨간 글자와 검은 머리가
    # 구분되지 않는다.
    rgb = np.asarray(big.convert("RGB")) if hasattr(big, "convert") else None
    big = _gray(big)
    ink, staves = cv.find_staves_best(big)
    if not staves:
        return [], {}
    sp = cv.median_spacing(staves)
    out, added, added_r = [], [], []
    # **화음(동시에 여러 음)이 있는 단을 기록한다.** 콘티는 멜로디 한 줄이지만
    # 간주 단에는 3음 화음이 있고, 파이프라인은 그것을 멜로디로 줄여 그린다.
    # 버린 후보에서 판단해야 한다 — 받아들인 것만 보면 중복 방지가 걸러낸 뒤라
    # 알 수 없다(직접 겪었다: 화음 경고가 사라졌다).
    stacked: list[int] = []
    # **버린 낮은 점수 머리를 남겨 둔다.** 개수 단서가 정확하면 버리는 게
    # 맞지만, LLM 이 하나 덜 세면 **진짜 음표가 버려진다** — 실측:
    # camp0814a-1 단8 의 점2분음표가 0.059 로 검출됐는데 LLM 이 14 라 해서
    # 고신뢰 14개로 이미 차 버렸고, 그 마디가 4박 → 1박이 됐다.
    # 박자 검산이 모자란다고 말하는 마디에서만 detstruct 가 되살린다.
    spare: list[list[dict]] = []
    # **× 머리(리듬 슬래시)를 쓰는 단을 찾는다.** 낭송·랩 파트는 음높이 없이
    # 리듬만 적으므로 머리가 ×인데, 검출기에는 × 클래스가 없어 통째로
    # 놓친다(실측: camp0814a-1 단2·3이 각각 9박·7.5박을 잃었다).
    # 다만 **기둥에 붙은 빔·꼬리는 잡히므로**, 빔·꼬리보다 머리가 적은 단이
    # 곧 신호다 — 정상 단은 머리가 훨씬 많다.
    slash: list[int] = []
    for si, st in enumerate(staves):
        y0 = max(0, int(st.top - sp * 5))
        y1 = min(big.height, int(st.bottom + sp * 6))
        strip = big.crop((0, y0, big.width, y1))
        need = int(strip.width * (target / sp))
        size = 32 * max(1, round(need / 32))
        r = model.predict(strip, imgsz=size, conf=conf_lo, verbose=False)[0]
        cands = [{"class": r.names[int(c)], "conf": float(s),
                  "x": b[0], "y": b[1] + y0,
                  "w": b[2] - b[0], "h": b[3] - b[1]}
                 for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(),
                                    r.boxes.conf.tolist())]
        wash = washed(rgb, y0, y1)
        # **구역 표시(A·B·C 상자) 안의 검출은 버린다.** 네모 상자는
        # 속 빈 머리와 닮아 `notehead_whole` 로 잡힌다 — 실측
        # camp0814b-07 단6: 'C' 상자가 신뢰도 0.06 온음표로 들어와
        # 그 마디가 4.5박이 됐다. 상자 좌표는 이미 알고 있다(geo.marks).
        skip = [m for m in (skip_boxes or []) if m.get("system") == si]

        def in_mark(c) -> bool:
            cx = c["x"] + c["w"] / 2.0
            cy = c["y"] + c["h"] / 2.0
            return any(m["x"] <= cx <= m["x"] + m["w"]
                       and m["y"] <= cy <= m["y"] + m["h"] for m in skip)

        if skip:
            cands = [c for c in cands if not in_mark(c)]
        heads = sorted((c for c in cands
                        if c["class"].startswith("notehead")
                        and (wash or not colored(rgb, c["x"], c["y"], c["w"], c["h"]))),
                       key=lambda c: -c["conf"])
        # **음자리표·조표 구간의 '쉼표'는 여기서 버린다.** 조표의 ♭ 는
        # 8분쉼표와 글리프가 닮아 자주 뒤바뀌는데, 그게 **쉼표 할당량을
        # 한 칸 먹으면 진짜 쉼표가 채워지지 못한다** — 실측
        # camp0814b-07 단4: 4분쉼표 하나가 통째로 빠져 그 마디가 3박.
        # 나중에(detstruct) 버리면 이미 늦다.
        he = head_ends[si] if head_ends and si < len(head_ends) else 0
        # **음자리표를 바닥으로 쓴다.** `render.head_end_for` 는 조표를
        # 못 찾으면 음자리표 앞에서 끊긴다(실측 camp0814b-07 단6:
        # headEnd 295 인데 음자리표가 303~350, 조표 ♭ 가 368). 그러면
        # 조표가 쉼표로 들어와 할당량을 먹는다.
        # **첫 음표를 절대 넘지 않는다** — 진짜 음을 잃는 게 더 큰 손해다.
        clefs = [c for c in cands if c["class"] == "clef_g"]
        if clefs:
            he = max(he, max(c["x"] + c["w"] for c in clefs)
                     + sp * KEYSIG_ALLOW)
        sure = [c["x"] for c in cands
                if c["class"].startswith("notehead") and c["conf"] >= conf_hi]
        if sure:
            he = min(he, min(sure) - sp * 0.5)
        # **유채색 표시는 쉼표로도 받지 않는다.** 머리에는 이미 같은 필터가
        # 걸려 있었는데 쉼표만 빠져 있었다 — 콘티는 빨간 펜으로 고쳐 쓰는
        # 악보라, 손으로 적은 쉼표가 인쇄된 쉼표로 들어오면 그 마디가
        # 통째로 어긋난다(실측 wish0809-3 단2: 빨간 𝄾 가 16분쉼표로
        # 들어와 그 마디가 3.25박이 됐다).
        rests = sorted((c for c in cands
                        if c["class"].startswith("rest")
                        and (he <= 0 or c["x"] + c["w"] / 2.0 >= he)
                        and (wash or not colored(rgb, c["x"], c["y"],
                                                 c["w"], c["h"]))),
                       key=lambda c: -c["conf"])
        others = [c for c in cands
                  if not c["class"].startswith("notehead")
                  and not c["class"].startswith("rest")
                  and c["conf"] >= (conf_mark
                                    if c["class"].startswith(("beam", "flag"))
                                    or c["class"] == "tie"
                                    else conf_hi)]

        want = expect[si] if si < len(expect) else None
        keep, extra = [], 0
        dropped: list[dict] = []
        for c in heads:
            if _overlaps(c, keep, sp):
                continue
            # **점수로는 못 가른다.** 실측: 마커스 단7의 오검출 쌍은
            # (0.82, 0.26), 젊은이 단4의 진짜 화음 쌍은 (0.10, 0.37) ·
            # (0.22, 0.30) · (0.69, 0.27)이었다 — 진짜 화음의 아래 음도 점수가
            # 낮다. 대신 **개수**가 갈라 준다: 오검출은 한 쌍, 실제 화음 단은
            # 마디마다 쌓여 여러 쌍이다.
            if _stacked_with(c, keep, sp):
                stacked.append(si)
            if c["conf"] >= conf_hi:
                keep.append(c)
            elif want is not None and len(keep) < want:
                # **낮은 점수 후보는 가로로 겹치면 받지 않는다.**
                # 개수를 채우려다 **진짜 놓친 머리 대신 같은 자리의 중복**을
                # 받아들이면, 음높이가 틀린 음표가 하나 생기고 진짜 음표가
                # 밀린다(실측: 마커스 단7에서 x 474/475에 B4·D5가 겹쳐
                # 잡혔고 하나는 점수 0.26이었다). 콘티는 멜로디 한 줄이라
                # 같은 x에 머리 둘은 거의 없다.
                if _same_x(c, keep, sp):
                    continue
                keep.append(c)
                extra += 1
            else:
                # 개수가 찼거나 기대를 모르는 경우 — 버리되 남겨 둔다
                if not _same_x(c, keep, sp):
                    dropped.append(c)
        want_r = expect_rests[si] if expect_rests and si < len(expect_rests) else None
        kept_r, extra_r = [], 0
        for c in rests:
            if _overlaps(c, kept_r, sp):
                continue
            if c["conf"] >= conf_hi:
                kept_r.append(c)
            elif want_r is not None and len(kept_r) < want_r:
                if _same_x(c, kept_r, sp):
                    continue
                kept_r.append(c)
                extra_r += 1
            # **버린 쉼표도 남겨 둔다** — 머리와 같은 이유다. LLM 이 쉼표를
            # 하나 덜 세면 진짜 쉼표가 버려지고, 그 마디는 그만큼 모자란
            # 채로 fit_page 에 넘어가 **음표를 늘려 메운다**(실측
            # day2sb-1 단4 마디3: 2분쉼표가 0.18 로 보였는데 LLM 이 4개라
            # 해서 버려졌고, 쉼표 2박이 점2분음표로 바뀌었다 — 2박 침묵이
            # 3박 지속음이 됐는데 합은 4박이라 게이트가 통과시켰다).
            # 박자 검산이 모자란다고 말하는 마디에서만 detstruct 가 되살린다.
            elif not _same_x(c, kept_r, sp):
                dropped.append(c)
        out += keep + kept_r + others
        nbm = sum(1 for c in others if c["class"].startswith(("beam", "flag")))
        # **채운 것 말고 실제로 본 것만 센다.** keep 에는 개수를 맞추려고
        # 낮은 점수에서 받은 것이 섞여 있어, 안내 개수가 있으면 × 머리 단도
        # keep 이 부풀어 신호가 사라진다(실측: camp0814a-1 단2가 자체 개수로는
        # 머리 1개인데 LLM 개수로는 13개까지 채워졌다). 고신뢰 검출만 세면
        # 안내와 무관해진다.
        nhi = len(keep) - extra
        # 문턱은 실측으로 갈랐다(고신뢰 머리 / 빔·꼬리 비):
        #   × 머리 단  camp0814a-1 단2 0.11 · 단3 0.22
        #   평범한 단  set0816-2 단4 0.80 · day2sb-2 단1 0.92
        # 긴 붙임음 위주라 머리가 적은 단이 0.8대에 있으므로, 그냥 "머리 <
        # 빔" 으로 자르면 그런 단까지 잡는다.
        if nbm >= 3 and nhi < nbm * SLASH_RATIO:
            slash.append(si)
        added.append(extra)
        added_r.append(extra_r)
        spare.append(dropped)
    # **여러 쌍이 쌓인 단만 화음으로 본다.** 한 쌍은 검출기 오검출일 수 있다.
    from collections import Counter
    cnt = Counter(stacked)
    return out, {"spare": spare,
                 "lowConfKept": added, "lowConfRests": added_r, "spacing": sp,
                 "stackedPairs": dict(cnt),
                 "stacked": sorted(i for i, n in cnt.items() if n >= 2),
                 "slashOnly": slash,
                 "staves": len(staves), "names": r.names}


def _stacked_with(c: dict, kept: list[dict], sp: float) -> bool:
    """가로로 겹치고 세로로 떨어져 있는가 — 화음의 모양."""
    cx, cy = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2
    for k in kept:
        kx, ky = k["x"] + k["w"] / 2, k["y"] + k["h"] / 2
        if abs(cx - kx) < sp * 0.55 and abs(cy - ky) > sp * 0.8:
            return True
    return False


def _same_x(c: dict, kept: list[dict], sp: float) -> bool:
    """이미 받은 머리와 가로로 겹치는가 (세로 위치는 상관없이)."""
    cx = c["x"] + c["w"] / 2
    return any(abs(cx - (k["x"] + k["w"] / 2)) < sp * 0.55 for k in kept)


def _overlaps(c: dict, kept: list[dict], sp: float) -> bool:
    """이미 받은 상자와 같은 자리인가. 머리 하나를 두 번 받지 않기 위해."""
    cx, cy = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2
    for k in kept:
        kx, ky = k["x"] + k["w"] / 2, k["y"] + k["h"] / 2
        if abs(cx - kx) < sp * 0.8 and abs(cy - ky) < sp * 0.7:
            return True
    return False


def keysig_counts(model, big, conf: float = 0.25,
                  target: float = INPUT_SPACING) -> list[tuple[int, int]]:
    """
    단별 조표의 (♭ 개수, ♯ 개수). 조성 추정의 **가장 확실한 근거**다.

    코드 통계만으로는 조성이 갈린다(실측: 위싱 콘티의 `Bb C F Gm F/A`를
    Bb키로 추정했으나 실제는 F키 — 조표는 ♭ 하나로 명확했다).

    구간은 **음자리표 끝 ~ 첫 음표(또는 박자표) 앞**이다. 그 밖의 임시표는
    조표가 아니라 곡 중간의 임시표다.

    **조표만 따로 크게 본다.** 단 전체를 오선 간격 6.5px로 줄여서 보면
    임시표가 6px밖에 안 되어 놓친다 — 실측(5장): ♭은 단 한 번도 검출되지
    않았고(문턱 0.02에서도 aug_dot·rest_8th로 오분류), ♯도 2개 중 1개만
    세었다. 조표 구간은 단의 앞 15칸뿐이라 크게 키워도 값이 싸다.
    """
    big = _gray(big)
    ink, staves = cv.find_staves_best(big)
    if not staves:
        return []
    sp = cv.median_spacing(staves)

    # **자리로 세는 쪽을 먼저 쓴다.** 검출기는 조표를 못 센다 — 실측
    # 정답 7장에서 ♯이 0~1개면 맞히지만 3개를 1개로, 4개를 1개로, 5개를
    # 1개로 셌다(4/7). 더 크게 봐도 나빠지기만 한다. 붙어 있는 같은
    # 글리프가 학습 분포 밖이다.
    #
    # 조표는 오선 위 자리와 순서가 정해져 있으므로, "어딘가에 ♯이 있나"가
    # 아니라 "F# 자리에 있나, 그다음 C# 자리에 있나"를 물으면 된다.
    # 같은 정답 7장에서 **7/7**. 조성이 틀리면 악보 전체의 음이 틀리므로
    # 여기는 정확도가 전부다.
    try:
        pos = _keysig_by_position(model, big, ink, staves, sp, conf)
        if pos is not None:
            return pos
    except Exception as e:                       # noqa: BLE001
        print(f"  조표 자리 세기 실패, 검출기로 물러납니다: {type(e).__name__}",
              file=__import__("sys").stderr)
    return [_keysig_one(model, big, st, sp, conf) for st in staves]


def _keysig_by_position(model, big, ink, staves, sp: float, conf: float):
    """조표를 오선 위 자리로 센다. 쓸 수 없으면 None."""
    import keysigpos as KP

    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=True)
    r = model.predict(big, imgsz=1280, conf=conf, verbose=False)[0]
    nm = r.names
    boxes = [(nm[int(k)], float(b[0]), float(b[2]), (float(b[1]) + float(b[3])) / 2)
             for b, k in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist())]
    out = []
    for st in staves:
        band = [b for b in boxes if st.top - sp * 4 <= b[3] <= st.bottom + sp * 4]
        lo = max((b[2] for b in band if b[0] == "clef_g"),
                 default=float(st.left) + sp * 2)
        stops = [b[1] for b in band
                 if (b[0].startswith("notehead") or b[0] == "timesig"
                     or b[0].startswith("rest")) and b[1] > lo]
        hi = min(stops, default=lo + sp * 12)
        out.append(KP.count(strict, st, sp, int(lo), int(hi)))
    return out


# 조표를 볼 때 목표로 하는 오선 간격.
#
# **크게 키운다고 좋아지지 않는다.** 검출기는 자기가 배운 배율에서만 본다.
# 같은 조각을 배율만 바꿔 재 봤다(마커스 ♯1 · 위싱샘플 ♭1):
#   6.5칸 → 둘 다 못 봄        (지금 쓰는 단 전체 배율)
#   9칸  → ♯ 0.90 · ♭ 0.39    ← 둘 다 잡힘
#   12칸 → ♯ 0.56 (가짜 ♭ 0.26 동반)
#   16칸 → ♯ 0.85 · ♭ 0.25
#   22칸 → 둘 다 못 봄
KEYSIG_SPACING = 9.0
# **여러 배율로 보고 가장 많이 센 값을 쓴다.** 임시표는 덜 세이는 쪽으로만
# 틀린다(붙어 있어 하나로 뭉친다) — 더 세이는 오류는 관찰되지 않았다.
# 배율마다 잡히는 게 달라서(위 표) 겹쳐 보면 놓치는 게 줄어든다.
KEYSIG_SCALES = (9.0, 11.0, 14.0)


def _keysig_one(model, big, st, sp: float,
                conf: float = 0.25) -> tuple[int, int]:
    """한 단의 조표 구간을 크게 잘라 (♭, ♯)를 센다."""
    from PIL import Image

    x0 = max(0, int(st.left - sp))
    x1 = min(big.width, int(st.left + sp * 16))
    y0 = max(0, int(st.top - sp * 2.5))
    y1 = min(big.height, int(st.bottom + sp * 2.5))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return (0, 0)
    base = big.crop((x0, y0, x1, y1))
    best = (0, 0)
    for target in KEYSIG_SCALES:
        # **키우는 게 아니라 목표 배율에 맞춘다.** 들어온 그림은 이미 확대돼
        # 있을 수 있어(probe.upscale) 줄여야 할 때가 많다. 예전에 1.0 아래로
        # 못 내려가게 막아 두었더니 아무것도 검출되지 않았다.
        z = target / sp if sp > 0 else 1.0
        crop = base
        if abs(z - 1.0) > 0.02:
            crop = base.resize((max(32, int(base.width * z)),
                                max(32, int(base.height * z))), Image.LANCZOS)
        size = 32 * max(1, round(max(crop.width, crop.height) / 32))
        r = model.predict(crop, imgsz=size, conf=conf, verbose=False)[0]
        got = [{"class": r.names[int(c)], "x": float(b[0]), "conf": float(s)}
               for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(),
                                  r.boxes.conf.tolist())]
        # 음자리표 끝 ~ 첫 음표/박자표/쉼표 앞
        lo = max((g["x"] for g in got if g["class"] == "clef_g"), default=0.0)
        stops = [g["x"] for g in got
                 if (g["class"].startswith("notehead") or g["class"] == "timesig"
                     or g["class"].startswith("rest")) and g["x"] > lo]
        hi = min(stops, default=float(crop.width))
        fl = sum(1 for g in got
                 if g["class"] == "accidental_flat" and lo < g["x"] < hi)
        sh = sum(1 for g in got
                 if g["class"] == "accidental_sharp" and lo < g["x"] < hi)
        # ♭과 ♯이 한 조표에 섞일 수는 없다. 많이 센 쪽만 남긴다.
        if fl and sh:
            fl, sh = (fl, 0) if fl >= sh else (0, sh)
        if fl + sh > best[0] + best[1]:
            best = (fl, sh)
    return best
