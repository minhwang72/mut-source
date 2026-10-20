#!/usr/bin/env python3
"""
재조립한 MusicXML을 **원본과 같은 배치의 한 페이지**로 그리고, 가사를
원본 픽셀에서 옮겨 붙인다.

배치 보존의 근거(실측): `breaks="auto"`로 두면 Verovio가 9단을 6단으로
흘려버린다. 단마다 `<print new-system="yes">`를 넣고 `breaks="encoded"`로
그리면 원본의 단별 마디 수 [5,4,4,4,5,3,4,4,6]가 그대로 나온다.

가사는 LLM에 묻지 않는다 — 한글 가사를 그럴듯하게 지어낸다(실측: "주 이름
찬양"→"즐거운 찬란한"). 원본에서 음절 조각을 오려 그대로 붙인다.

  python tools/renderpage.py rebuilt.musicxml 원본.jpg -o page.png
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 출력 가로 해상도. 세로와 배율은 **원본에서 계산한다**(아래 fit_to)
PAGE_W = 1650
SCALE = 38


def render_svg(xml: str, font: str = "Leipzig", page_h: int = 2340,
               scale: float = SCALE, sys_space: float | None = None,
               header: str = "none", margin_top: float | None = None) -> str:
    import verovio
    tk = verovio.toolkit()
    opts = {
        "pageWidth": PAGE_W, "pageHeight": page_h, "scale": scale,
        "font": font,
        # 원본 배치를 그대로 쓴다 — 이게 없으면 단이 합쳐진다
        "breaks": "encoded",
        "adjustPageHeight": False,
        "svgBoundingBoxes": True,
        "header": header, "footer": "none",
        # **마디 번호를 찍지 않는다.** 원본 콘티 악보에는 없다 — 원본과
        # 같은 그림이어야 연주자가 같은 악보로 읽는다.
        "mnumInterval": 0,
    }
    if margin_top is not None:
        # 원본의 머리글(제목·송폼)을 옮겨 붙일 자리를 비운다
        opts["pageMarginTop"] = margin_top
    if sys_space is not None:
        # Verovio는 가사를 모르니 단 사이를 좁게 잡는다(실측: 필요한 간격의
        # 60%). 원본에서 잰 간격을 넣어 준다.
        opts["spacingSystem"] = sys_space
    tk.setOptions(opts)
    if not tk.loadData(xml):
        raise SystemExit("Verovio가 MusicXML을 못 읽었습니다")
    if tk.getPageCount() != 1:
        print(f"⚠️  {tk.getPageCount()}페이지로 나왔습니다 "
              f"(원본과 같게 하려면 1페이지여야 합니다)", file=sys.stderr)
    return tk.renderToSVG(1)


def fit_to(xml: str, src_w: int, src_h: int, sp: float, gap: float,
           font: str = "Leipzig",
           reserve_top: int = 0) -> tuple[str, int]:
    """
    **원본의 비율을 그대로 재현한다.**

    원본을 폭 PAGE_W로 늘렸다고 보고, 그때의 오선 간격과 단 간격을 맞춘다.
    Verovio의 `scale`은 오선 간격에 비례하므로 한 번 그려 재고 한 번 더 그린다
    (실측: scale 38에서 26.3px이 나왔는데 원본 비율로는 18.4px이어야 했다 —
    43% 크게 그려져 가사가 다음 단 코드와 겹쳤다).

    반환: (svg, page_h)
    """
    f = PAGE_W / src_w
    # **머리글 자리를 빼고 그린다.** Verovio의 pageMarginTop 은 breaks="encoded"
    # 에서 무시된다(실측: 0~400 어느 값이든 첫 단 top 이 36px 고정). 그래서
    # 옵션에 기대지 않고, 그림을 그만큼 짧게 그린 뒤 아래로 붙인다.
    page_h = int(round(src_h * f)) - max(0, reserve_top)
    want_sp = sp * f                 # 목표 오선 간격(출력 px)
    want_gap = gap * f               # 목표 단 간격(출력 px)

    svg = render_svg(xml, font, page_h, SCALE)
    k = view_scale(svg)
    rows = staff_rows(svg)
    if not rows:
        return svg, page_h
    got_sp = (rows[0]["bottom"] - rows[0]["top"]) * k / 4.0
    scale = SCALE * want_sp / got_sp if got_sp > 0 else SCALE
    # 단 간격은 오선 간격(칸) 단위로 준다
    sys_space = max(3.0, min(24.0, want_gap / want_sp))

    # **내용이 페이지보다 길면 페이지를 늘린다.**
    #
    # `breaks="encoded"`는 지시받은 단을 **모두 한 페이지에 그린다** — 페이지가
    # 짧아도 2페이지로 나누지 않고 아래로 넘겨 버린다. 그 높이만큼만 래스터화하면
    # 아래 단이 **조용히 잘린다**(직접 겪었다: 젊은이교회 10단 악보에서 내용이
    # 2,601px인데 2,019px만 그려 마지막 3단의 오선이 사라지고 가사만 떴다).
    out = render_svg(xml, font, page_h, scale, sys_space)
    rows = staff_rows(out)
    if rows:
        k = view_scale(out)
        bottom = max(r["bottom"] for r in rows) * k + want_sp * 4
        if bottom > page_h:
            page_h = int(round(bottom))
            out = render_svg(xml, font, page_h, scale, sys_space)
    return out, page_h


def note_cols(svg: str) -> list[list[float]]:
    """
    단별 **출력 음표 x** (SVG 좌표, 정렬).

    왜 필요한가(실측): 가사를 원본 x 를 비율 변환한 자리에 붙였더니 음표와
    어긋났다. Verovio 는 음가에 따라 간격을 자기 기준으로 다시 잡는다 —
    마커스에서 단4~7 이 통째로 중앙 0.7~1.7칸(최대 6.4칸) 밀렸고, 음표 머리
    폭이 1.2칸이니 **한 칸 옆 음표 자리**로 간 셈이다.
    """
    import xml.etree.ElementTree as ET

    NS = "{http://www.w3.org/2000/svg}"
    root = ET.fromstring(svg)
    out: list[list[float]] = []
    for sysg in root.iter(f"{NS}g"):
        cls_ = (sysg.get("class") or "").split()
        # `system bounding-box` 도 같이 걸린다 — 그러면 빈 단이 끼어 단 수가
        # 두 배가 되고 짝이 어긋나 재정렬이 통째로 취소된다(실측: 18단으로 셌다).
        if "system" not in cls_ or "bounding-box" in cls_:
            continue
        xs: list[float] = []
        for g in sysg.iter(f"{NS}g"):
            cls = (g.get("class") or "").split()
            if "note" not in cls or "bounding-box" in cls:
                continue
            for c in g:
                if "bounding-box" in (c.get("class") or ""):
                    r = c.find(f"{NS}rect")
                    if r is not None and r.get("x") is not None:
                        xs.append(float(r.get("x"))
                                  + float(r.get("width") or 0) / 2)
                    break
        if xs:
            out.append(sorted(xs))
    return out


def note_shift(src_x: list[float], out_x: list[float],
               k: float, fx: float) -> list[float] | None:
    """
    음절을 **그 음표가 출력에서 간 자리**로 옮기는 양(페이지 px).

    개수가 다르면 손대지 않는다 — 짝이 어긋난 채로 옮기면 더 나빠진다.
    """
    if not src_x or not out_x or len(src_x) < 2 or len(src_x) != len(out_x):
        return None
    return [out_x[i] * k - sx * fx for i, sx in enumerate(src_x)]


def _lyric_overflow(svg, src, staves, sp: float, fx: float, head_h: int,
                    full_h: int, drop: float) -> int:
    """가사가 전체 높이를 몇 px 넘는가. 0이면 들어간다."""
    import numpy as np

    import lyricstrip as LS
    import sheetcv as cv

    rows = staff_rows(svg)
    if len(rows) != len(staves):
        return 0
    k = view_scale(svg)
    ink, _st = cv.find_staves_best(src)
    arr = np.asarray(ink)
    bot = 0
    for i, st in enumerate(staves):
        R = rows[i]
        nxt = staves[i + 1].top if i + 1 < len(staves) else None
        lb = cv.find_lyric_band(arr, st, sp, nxt)
        if not lb:
            continue
        lb = LS.band_of(arr, lb, sp, pad_below=True)
        rsp = (R["bottom"] - R["top"]) * k / 4.0
        off = (lb[0] - st.bottom) / sp
        y = head_h + int(R["bottom"] * k + rsp * off)
        y = max(y, head_h + int(R["low"] * k + rsp * drop))
        bot = max(bot, y + int(round((lb[1] - lb[0]) * fx)))
    return max(0, bot - full_h)


def _first_top(svg: str, page_w: int) -> float | None:
    """그린 SVG에서 첫 단 오선 맨 위의 출력 y."""
    rows = staff_rows(svg)
    if not rows:
        return None
    return rows[0]["top"] * view_scale(svg, page_w)


def view_scale(svg: str, page_w: int = PAGE_W) -> float:
    """
    SVG 좌표 → 출력 픽셀 배율.

    Verovio의 viewBox 단위는 출력 픽셀의 10배쯤이다. 이걸 곱하지 않으면
    가사 y가 페이지 높이를 넘어가 **조용히 전부 버려진다**(실측: 153개 중
    9개만 붙었다 — 첫 단만 살아남은 것).
    """
    import re
    m = re.search(r'viewBox="\s*[\d.-]+\s+[\d.-]+\s+([\d.]+)', svg)
    return page_w / float(m.group(1)) if m else 1.0


def staff_rows(svg: str) -> list[dict]:
    """
    그려진 SVG에서 단마다 (오선 위·아래, 음표 머리 최저점)을 뽑는다.

    가사를 어디에 놓을지는 **오선 아래끝이 아니라 음표 머리 최저점** 기준으로
    잡아야 한다. 오선 아래로 내려간 음표(아래 덧줄)가 있으면 오선 기준으로는
    가사가 음표를 덮는다.
    """
    import xml.etree.ElementTree as ET
    root = ET.fromstring(svg)
    ns = {"s": "http://www.w3.org/2000/svg"}
    rows = []
    for sysel in root.iter("{http://www.w3.org/2000/svg}g"):
        if sysel.get("class") != "system":
            continue
        ys, lows, xs = [], [], []
        for g in sysel.iter("{http://www.w3.org/2000/svg}g"):
            cls = g.get("class") or ""
            if "staff" in cls.split() or "note" in cls.split():
                for p in g.iter():
                    d = p.get("d") or ""
                    for m in re.finditer(r"[ML]\s*(-?\d+)\s+(-?\d+)", d):
                        x, y = int(m.group(1)), int(m.group(2))
                        ys.append(y)
                        if "staff" in cls.split():
                            xs.append(x)
                        if "note" in cls.split():
                            lows.append(y)
        if not ys:
            continue
        rows.append({"top": min(ys), "bottom": max(ys),
                     "low": max(lows) if lows else max(ys),
                     "left": min(xs) if xs else 0})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="한 페이지로 다시 그리기")
    ap.add_argument("musicxml")
    ap.add_argument("image", help="가사를 오려 올 원본")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--font", default="Leipzig")
    ap.add_argument("--drop", type=float, default=1.0,
                    help="음표 최저점 아래로 최소 몇 칸은 띄울지")
    ap.add_argument("--no-lyrics", action="store_true")
    ap.add_argument("--chords", help="판독 결과(.ex.json) — 머리글 자를 위치용")
    ap.add_argument("--heads", help="단별 음표 x (rebuild --dump-struct 출력) — "
                                    "가사를 출력 음표 자리로 옮기는 데 쓴다")
    ap.add_argument("--header", action="store_true",
                    help="Verovio가 제목·작곡자를 그린다 (보통 원본을 옮기므로 불필요)")
    ap.add_argument("--no-header", action="store_true",
                    help="원본 머리글(제목·송폼)을 옮기지 않는다")
    ap.add_argument("--no-marks", action="store_true",
                    help="구역 표시(A2·B·C)를 옮기지 않는다")
    a = ap.parse_args()

    import cairosvg
    import numpy as np
    from PIL import Image

    import lyricstrip as LS
    import sheetcv as cv

    # **원본을 먼저 잰다.** 페이지 비율·오선 간격·단 간격이 여기서 나온다.
    src = Image.open(a.image).convert("L")
    ink, staves = cv.find_staves_best(src)
    sp = cv.median_spacing(staves)
    arr = np.asarray(ink)
    gaps = [staves[i + 1].top - staves[i].bottom
            for i in range(len(staves) - 1)]
    gap = sorted(gaps)[len(gaps) // 2] if gaps else sp * 5

    # 첫 단 코드 상자의 위쪽 — 머리글은 이보다 위에서 자른다
    header_cut_hints: list[int] = []
    if a.chords:
        import json as _json
        try:
            ex = _json.loads(Path(a.chords).read_text(encoding="utf-8"))
            fx0 = src.width / float(
                (ex.get("imageSize") or {}).get("w") or src.width)
            ys = [c["box"]["y"] * fx0
                  for sysd in ex.get("systems", [])
                  if sysd.get("index") == 0
                  for c in sysd.get("chords", [])]
            if ys:
                header_cut_hints.append(int(min(ys) - sp * 0.8))
        except Exception as e:                       # noqa: BLE001
            print(f"  코드 상자를 읽지 못했습니다: {e}", file=sys.stderr)

    xml = Path(a.musicxml).read_text(encoding="utf-8")
    # **구역 표시 자리를 먼저 재서 페이지를 넓힌다.**
    #
    # 콘티 악보는 오선 왼쪽 여백에 A2·B·C·A′ 같은 구역 상자를 둔다. 머리글의
    # 송폼과 짝이 되는 정보라 이것 없이는 곡 형식을 따라갈 수 없다.
    #
    # Verovio는 오선을 페이지 왼쪽 끝부터 그리고 `pageMarginLeft`가 듣지 않는다
    # (실측: 0~300 어느 값이든 오선 left 가 0). 그래서 **페이지를 그만큼 넓혀
    # 본문을 오른쪽으로 민다.** 가로 배율은 그대로 두고 오프셋만 더하면 되므로
    # 가사 정렬을 다시 잡을 필요가 없다 — 그게 이 방식을 고른 이유다.
    fx = PAGE_W / src.width
    marks_src: list[tuple[int, tuple[int, int, int, int]]] = []
    if not a.no_marks and staves:
        from collections import Counter
        base_left = Counter(int(st.left) for st in staves).most_common(1)[0][0]
        edge = base_left - int(sp * 1.5)
        # 왼쪽 여백이 좁으면 오선 끝 잉크를 표시로 오해한다(실측: 마커스에서
        # 없는 표시 9개를 경고했다).
        if edge >= sp * 3:
            for i, st in enumerate(staves):
                y0 = max(0, int(st.top - sp * 2.2))
                y1 = min(arr.shape[0], int(st.bottom + sp * 2.2))
                strip = arr[y0:y1, :edge]
                if not strip.any():
                    continue
                ys, xs = np.nonzero(strip)
                mx0, mx1 = int(xs.min()), int(xs.max()) + 1
                my0, my1 = y0 + int(ys.min()), y0 + int(ys.max()) + 1
                # 글자 하나가 들어갈 크기가 아니면 표시가 아니다
                if mx1 - mx0 < sp * 1.2 or my1 - my0 < sp * 1.2:
                    continue
                marks_src.append((i, (mx0, my0, mx1, my1)))
    mark_w = 0
    if marks_src:
        widest = max(b[2] - b[0] for _i, b in marks_src)
        mark_w = int(round(widest * fx)) + int(sp * fx * 0.6)
    head_cut = 0
    if not a.no_header:
        head_cut = int(staves[0].top - sp * 1.2)
        for c in header_cut_hints:
            head_cut = min(head_cut, c)
        head_cut = max(0, head_cut)
    head_h = int(round(head_cut * fx)) if head_cut > 2 else 0

    # **바닥 고지(저작권 표기)를 옮길 자리.** 머리글과 같은 이유 —
    # "Copyright … All rights reserved." 는 다시 만들 수 없다.
    # 판정 근거는 render.footer_cut_for 주석 참고.
    import render as R  # 바닥 고지 판정만 쓴다
    foot_cut = R.footer_cut_for(ink, staves, sp) if staves else 0
    foot_src_h = max(0, src.height - foot_cut) if foot_cut else 0
    foot_h = int(round(foot_src_h * fx)) if foot_src_h > 2 else 0

    # **원본 비율에 맞춘다.** Verovio는 가사를 모르니 단을 자기 기준으로만
    # 쌓는다. 머리글까지 넣으면 마지막 단의 가사가 페이지 아래로 넘친다
    # (실측: 위싱 콘티에서 51개가 잘렸다). 넘친 만큼 본문을 줄여 다시 그린다 —
    # 페이지를 늘리면 한 장은 유지되지만 인쇄할 때 축소되어 작아진다.
    full_h = int(round(src.height * fx))
    body_h = max(200, full_h - head_h)
    # Verovio는 단을 위에서부터 자기 간격으로 쌓는다 — 페이지를 짧게 해도
    # 압축되지 않고 2페이지가 될 뿐이다(직접 겪었다: 높이가 0이 되어 죽었다).
    # 넘치는 만큼 **단 간격을 줄인다.** 원본 간격에는 가사 자리가 이미
    # 들어 있지만, Verovio의 자체 위쪽 여백과 오선 높이 차이만큼 모자란다.
    g = gap
    svg = None
    for _try in range(5):
        # **fit_to가 늘린 높이를 받아 쓴다.** 버리면 그 높이만큼만 래스터화되어
        # 아래 단이 조용히 잘린다(직접 겪었다: 젊은이교회 10단 악보에서
        # 마지막 3단의 오선이 사라지고 가사만 떴다).
        svg, body_h = fit_to(xml, src.width, src.height, sp, g, a.font, head_h)
        over = 0 if a.no_lyrics else _lyric_overflow(
            svg, src, staves, sp, fx, head_h, full_h, a.drop)
        if over <= 0:
            break
        n_gap = max(1, len(staves) - 1)
        # **간격은 조금만 줄인다.** 많이 줄이면 다음 단의 코드가 앞 단 가사와
        # 겹친다(직접 확인: 젊은이교회 악보에서 "B♭"이 앞 단 가사 줄에 얹혔다).
        # 원본 간격의 88%까지만 줄이고, 남는 만큼은 페이지를 늘린다 —
        # 한 페이지라는 조건은 지켜지고, 비율만 조금 길어진다.
        g = max(gap * 0.88, g - (over / fx) / n_gap - 0.5)
        if g <= gap * 0.881:
            break
    # 본문이 원본 비율보다 길어지면 페이지도 그만큼 길어진다
    page_h = max(full_h, head_h + body_h) + foot_h

    png = Path(a.out)
    rows = staff_rows(svg)
    k = view_scale(svg)

    # **가사 자리를 먼저 계산한다.** 마지막 단의 가사가 페이지 아래로 넘칠 수
    # 있어서다 — 머리글을 넣으면 본문이 그만큼 짧아지고, 원본 비율로 잡은
    # 가사 위치가 페이지를 벗어난다(실측: 위싱 콘티에서 51개가 잘렸다).
    # 필요한 높이를 재서 페이지를 늘린다.
    # 원본 음표 x (단별) — 있으면 가사를 출력 음표 자리로 옮긴다
    head_x: list[list[float]] = []
    if a.heads:
        try:
            head_x = json.loads(Path(a.heads).read_text()).get("headX") or []
        except Exception as e:                   # noqa: BLE001
            print(f"⚠️  음표 위치를 못 읽었습니다({e}) — 가사를 원본 자리에 둡니다",
                  file=sys.stderr)
    out_cols = note_cols(svg) if head_x else []
    n_shift = 0

    placed: list[tuple[tuple[int, int, int, int], tuple[int, int, int, int]]] = []
    if not a.no_lyrics and len(rows) == len(staves):
        for i, st in enumerate(staves):
            R = rows[i]
            nxt = staves[i + 1].top if i + 1 < len(staves) else None
            lb = cv.find_lyric_band(arr, st, sp, nxt)
            if not lb:
                continue
            lb = LS.band_of(arr, lb, sp, pad_below=True)
            syl = LS.syllables(arr, lb, sp)
            if not syl:
                continue
            rsp = (R["bottom"] - R["top"]) * k / 4.0
            # **원본이 가사를 오선 아래 몇 칸에 뒀는지 재서 그대로 쓴다.**
            off = (lb[0] - st.bottom) / sp
            y = head_h + int(R["bottom"] * k + rsp * off)
            # 오선 아래로 내려간 음표(아래 덧줄)보다는 아래여야 한다
            y = max(y, head_h + int(R["low"] * k + rsp * a.drop))
            h = max(1, int(round((lb[1] - lb[0]) * fx)))
            sxs = head_x[i] if i < len(head_x) else []
            shift = note_shift(sxs, out_cols[i] if i < len(out_cols) else [],
                               k, fx)
            for x0, x1 in syl:
                w = max(1, int(round((x1 - x0) * fx)))
                dx = 0
                if shift:
                    # **음절을 그 음표가 간 자리로 옮긴다.**
                    cx = (x0 + x1) / 2.0
                    j = min(range(len(sxs)), key=lambda t: abs(sxs[t] - cx))
                    dx = int(round(shift[j]))
                    if dx:
                        n_shift += 1
                px = mark_w + max(0, min(PAGE_W - w, int(x0 * fx) + dx))
                placed.append(((x0, lb[0], x1, lb[1]),
                               (px, y, px + w, y + h)))
    elif not a.no_lyrics:
        print(f"⚠️  그린 단 {len(rows)}개 vs 원본 단 {len(staves)}개 — "
              f"가사를 옮기지 않습니다", file=sys.stderr)

    if n_shift:
        print(f"  가사 {n_shift}개를 출력 음표 자리로 옮겼습니다", file=sys.stderr)

    need = max([d[3] for _s, d in placed], default=0) + int(sp * fx * 0.4)
    if need > page_h:
        # 그래도 넘치면 페이지를 늘린다 — 가사를 자르는 것보다 낫다
        print(f"⚠️  가사가 페이지를 {need - page_h}px 넘어 페이지를 늘립니다",
              file=sys.stderr)
        page_h = need

    # **배경색을 반드시 준다.** 없으면 투명 PNG가 나오고, 그걸 "L"로 바꾸면
    # 알파가 검정이 되어 페이지 전체가 새까맣게 된다.
    import io as _io
    buf = _io.BytesIO()
    cairosvg.svg2png(bytestring=svg.encode(), write_to=buf,
                     output_width=PAGE_W, output_height=body_h,
                     background_color="white")
    buf.seek(0)
    body = Image.open(buf).convert("L")
    page = Image.new("L", (PAGE_W + mark_w, page_h), 255)
    page.paste(body, (mark_w, head_h))

    # **머리글을 원본에서 옮긴다.** 제목·부제·작곡자·저작권 표기는 물론이고,
    # 콘티에는 **송폼**이 적혀 있다("Intro(8) - A1 - A'1 - B - Int(4) - …").
    # 찬양팀이 그걸 보고 연주하므로 사라지면 악보를 못 쓴다. 다시 조판해서
    # 만들 수 있는 것이 아니므로 픽셀을 그대로 오려 붙인다 — 가사와 같은 이유다.
    if head_h > 0:
        blk = src.crop((0, 0, src.width, head_cut)).resize(
            (PAGE_W, head_h), Image.LANCZOS)
        page.paste(blk, (mark_w, 0))
        print(f"  머리글 {head_cut}px 옮김 → {head_h}px", file=sys.stderr)

    if foot_h > 0:
        blk = src.crop((0, foot_cut, src.width, src.height)).resize(
            (PAGE_W, foot_h), Image.LANCZOS)
        page.paste(blk, (mark_w, page_h - foot_h))
        print(f"  바닥 고지 {foot_src_h}px 옮김 → {foot_h}px", file=sys.stderr)

    marks = 0
    for i, (mx0, my0, mx1, my1) in marks_src:
        if i >= len(rows):
            continue
        R = rows[i]
        piece = src.crop((mx0, my0, mx1, my1))
        pw = max(1, int(round(piece.width * fx)))
        ph = max(1, int(round(piece.height * fx)))
        piece = piece.resize((pw, ph), Image.LANCZOS)
        cy = head_h + int((R["top"] + R["bottom"]) / 2 * k)
        px = max(0, mark_w - pw - int(sp * fx * 0.3))
        box = (px, cy - ph // 2, px + pw, cy - ph // 2 + ph)
        if box[1] < 0 or box[3] > page_h:
            continue
        under = page.crop(box)
        page.paste(Image.fromarray(
            np.minimum(np.asarray(under), np.asarray(piece))), box)
        marks += 1
    if marks:
        print(f"  구역 표시 {marks}개 옮김 (페이지를 {mark_w}px 넓힘)",
              file=sys.stderr)

    n = 0
    for (sx0, sy0, sx1, sy1), box in placed:
        piece = src.crop((sx0, sy0, sx1, sy1)).resize(
            (box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
        under = page.crop(box)
        # 어두운 쪽만 남긴다 — 흰 배경이 오선을 덮지 않도록
        page.paste(Image.fromarray(
            np.minimum(np.asarray(under), np.asarray(piece))), box)
        n += 1

    page.save(png)
    print(f"→ {png}  {page.size}  가사 {n}개"
          + (f" · 구역 표시 {marks}개" if marks else ""))


if __name__ == "__main__":
    main()
