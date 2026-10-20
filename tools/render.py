#!/usr/bin/env python3
"""
뮤트 렌더러 — 원본 이미지 위에서 조표·코드를 교체한다 (Tier 1.5).

재조판이 아니라 덮어쓰기이므로 오선·음표·가사·마디가 그대로 남고,
**입력 N장 = 출력 N장**이 구조적으로 보장된다.

    python3 tools/render.py <이미지> <extraction.json> -s -3 -o out.png

브라우저에서는 같은 순서를 canvas 2d로 수행한다. 이 스크립트는 그 검증판이다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))

import keysig
import lyricstrip as LS
import sheetcv as cv

REPO = Path(__file__).resolve().parent.parent

TEXT_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

# 오선을 제거해야 하는 작업(조표 교체·멜로디 이동)의 최소 오선 간격(px).
#
# 실측(오선 간격 6px 악보)으로 확인한 두 가지 실패:
#  1. 속 빈 음표의 테두리가 1px라 오선과 구별되지 않는다 → 음표 훼손
#  2. 음자리표와 조표가 한 덩어리로 붙는다 → 조표 위치 탐색 불가
# 둘 다 해상도 문제이므로 임계값 튜닝으로는 넘을 수 없다.
# 오선 간격 12px 이상(긴 변 약 1500px 이상)이면 테두리가 2~3px가 되어 갈린다.
#
# 코드 오버레이(Tier 1)는 오선을 건드리지 않으므로 이 제한과 무관하다.
MIN_SPACING_FOR_STAFF_EDIT = 6.0
# 조표 위치 합의에 필요한 최소 단 수. 한 단만 검출되면 그 하나가
# 틀렸을 때 악보 전체가 같이 틀린다(실측: 9단 중 1단이 엉뚱한
# 자리를 잡아 9단 전부에 조표를 잘못 그렸다).
MIN_KEYSIG_AGREE = 3


def load_text_font(size: int) -> ImageFont.FreeTypeFont:
    for p in TEXT_FONTS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise SystemExit("사용할 폰트를 찾지 못했습니다.")


def call_engine(from_key: str, semitones: int, chords: list[str]) -> dict:
    """이조 로직은 TS 코어(src/)에만 존재한다. 여기서 다시 구현하지 않는다."""
    proc = subprocess.run(
        ["node", "--disable-warning=ExperimentalWarning", "--experimental-strip-types",
         str(REPO / "src" / "cli.ts"), "map"],
        input=json.dumps({"fromKey": from_key, "semitones": semitones, "chords": chords}),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"엔진 호출 실패:\n{proc.stderr}")
    return json.loads(proc.stdout)


def paper_color(arr: np.ndarray, box: dict, pad: int = 3) -> tuple[int, int, int]:
    """박스 주변 밝은 화소의 중앙값 = 종이색. 스캔본은 순백이 아니다."""
    h, w = arr.shape[:2]
    y0, y1 = max(0, box["y"] - pad), min(h, box["y"] + box["h"] + pad)
    x0, x1 = max(0, box["x"] - pad), min(w, box["x"] + box["w"] + pad)
    ring = arr[y0:y1, x0:x1].reshape(-1, arr.shape[2])
    if ring.size == 0:
        return (255, 255, 255)
    lum = ring.astype(np.int32).sum(axis=1)
    bright = ring[lum >= np.percentile(lum, 75)]
    return tuple(int(v) for v in np.median(bright, axis=0)[:3])


def base_font_size(chords: list[dict]) -> int:
    """
    한 장의 코드 심볼은 모두 같은 크기다. 박스별로 '들어가는 최대 크기'를
    찾으면 여유 공간이 넓은 코드만 거대해진다.

    크기는 **원본 글꼴 크기를 역산해서** 정한다. 상자 높이에 고정 계수를
    곱하면 안 된다 — 상자 높이는 잉크 높이인데 글꼴 크기는 em 크기라서,
    0.78을 곱하면 실제로 원본의 58% 크기로 그려진다(두 해상도에서 실측).
    글자마다 어센더·디센더가 달라 잉크 높이가 다르므로, 코드별로 "그 글자를
    그 상자 높이로 만드는 크기"를 구한 뒤 중앙값을 쓴다.
    """
    REF = 40
    sizes = []
    for c in chords:
        text = (c.get("text") or "").strip()
        h = c["box"]["h"]
        if not text or h <= 0:
            continue
        font = load_text_font(REF)
        _, t, _, b = font.getbbox(text)
        ink = b - t
        if ink <= 0:
            continue
        est = REF * h / ink
        # 스케일이 완전히 선형은 아니라 한 번 보정한다
        font2 = load_text_font(max(6, round(est)))
        _, t2, _, b2 = font2.getbbox(text)
        if b2 - t2 > 0:
            est = max(6, round(est)) * h / (b2 - t2)
        sizes.append(est)
    if not sizes:
        return 12
    sizes.sort()
    return max(7, round(sizes[len(sizes) // 2]))


def shrink_to_fit(text: str, size: int, max_w: int):
    for s in range(size, 5, -1):
        font = load_text_font(s)
        l, _, r, _ = font.getbbox(text)
        if r - l <= max_w:
            return font, s < size
    return load_text_font(6), True


# ------------------------------------------------------------------ 조표

def keysig_feasible(content: np.ndarray, staves: list[cv.Staff],
                    fifths_from: int) -> tuple[bool, str]:
    """
    조표를 **믿을 수 있게** 바꿀 수 있는가. 그리기 전에 미리 판정한다.

    왜 미리 보나: 조표를 못 바꾸는데 멜로디만 옮기면 조표와 음표가 어긋난
    악보가 된다 — 연주자가 원래 조표로 읽으면 전부 틀린 음이 나온다.
    바꿀 수 없으면 **아무것도 옮기지 않는 편**이 안전하다.
    """
    if fifths_from == 0:
        return True, ""            # 조표가 없으면 지울 것도 없다
    found = sum(1 for st in staves
                if keysig.locate(content, st, fifths_from) is not None)
    if found >= MIN_KEYSIG_AGREE:
        return True, ""
    return False, (f"조표 검출 {found}/{len(staves)}단 — 자리를 믿을 수 없습니다")


def replace_key_signatures(
    img: Image.Image, content: np.ndarray, staves: list[cv.Staff],
    fifths_from: int, fifths_to: int, arr: np.ndarray,
    original: np.ndarray | None = None, extraction: dict | None = None,
) -> int:
    # **전 단이 가능할 때만** 바꾼다. 일부 단만 조표가 바뀐 악보는 안 바뀐
    # 악보보다 헷갈린다 — 연주자가 어느 조표를 믿어야 할지 알 수 없다.
    # 저해상도에서는 조표가 늘어날 자리가 단마다 다르게 부족해서, 이 규칙이
    # 없으면 8단 중 3단만 바뀌는 일이 생긴다(실측).
    # 단별 첫 코드 x — 조표가 그 자리를 넘지 않게 한다
    chord_x = {}
    for sysd in (extraction or {}).get("systems", []):
        xs = [c["box"]["x"] for c in sysd["chords"]]
        if xs:
            chord_x[sysd["index"]] = min(xs)

    boxes = []
    for st in staves:
        box = {"x": st.left, "y": st.top,
               "w": int(st.spacing * 8), "h": st.bottom - st.top}
        boxes.append((st, box, paper_color(arr, box)))

    # 단별 검출값을 모아 **합의값**을 만든다 (머리 배치는 모든 단이 같다)
    xs, ws, nx = [], [], []
    for st, _box, _paper in boxes:
        reg = keysig.locate(content, st, fifths_from)
        if reg is None:
            continue
        blk = keysig.next_block(content, st, reg,
                               st.left + int(st.spacing * 4.5))
        xs.append(reg.x)
        ws.append(reg.w)
        if blk:
            nx.append(blk[0])
    # **합의값은 여러 단이 동의할 때만 쓴다.** 한 단만 검출되면 그 하나가
    # 틀렸을 때 9단 전체가 같이 틀린다 — 실측: ♯1개짜리 악보에서 8단이
    # 검출 실패하고 남은 1단이 엉뚱한 자리(오선 끝 +9.3칸, 조표는 보통
    # 2~4칸)를 잡았는데, 그 값으로 9단 전부에 새 조표를 잘못 그렸다.
    # 게다가 옛 조표는 그대로 남아 ♯이 3개처럼 보였다.
    hint = None
    if len(xs) >= MIN_KEYSIG_AGREE and len(nx) >= MIN_KEYSIG_AGREE:
        med = lambda v: sorted(v)[len(v) // 2]
        hint = (med(xs), med(ws), med(nx))
    elif xs:
        return 0

    for st, _box, paper in boxes:
        probe = keysig.replace(img, content, st, fifths_from, fifths_to, paper,
                               original, dry_run=True, hint=hint,
                               chord_limit=chord_x.get(st.index))
        if probe.get("skipped"):
            return 0

    done = 0
    for st, _box, paper in boxes:
        r = keysig.replace(img, content, st, fifths_from, fifths_to, paper,
                           original, hint=hint,
                           chord_limit=chord_x.get(st.index))
        if not r.get("skipped"):
            done += 1
    return done


# ------------------------------------------------------------------ 코드

def head_end_for(content: np.ndarray, st, spacing: float, source_fifths: int) -> int:
    """
    이 단의 '머리 구간' 오른쪽 끝 — 음자리표·조표·(있으면)박자표까지.

    오선 간격의 고정 배수로 잡으면 안 된다. 조표 개수와 박자표 유무에 따라
    머리 길이가 달라져서, 짧은 단에서는 **첫 음표가 머리 구간 안에 들어간다**
    (실측: 단1의 첫 음표 x=207 < headEnd 208 → 그 음표만 이동에서 빠지고
    새 조표가 위에 덮여 뭉개졌다).
    """
    reg = keysig.locate(content, st, source_fifths)
    blk = keysig.next_block(content, st, reg, st.left + int(spacing * 4.5))
    gap = max(2, int(spacing * 0.5))
    if blk and blk[3]:                 # 박자표가 있다 — 그 뒤가 머리 끝
        return min(int(blk[1] + gap), st.right)
    if reg:                            # 조표까지가 머리
        return min(int(reg.x + reg.w + gap), st.right)
    if blk:                            # 조표가 없다 — 첫 요소 앞까지
        return max(st.left, int(blk[0] - gap))
    return st.left + int(spacing * 10)


def erase_chord_ink(
    img: Image.Image, arr: np.ndarray, box: dict, dy: int, pad_px: float = 1.0
) -> None:
    """
    옛 코드 글자를 지운다. 마스크는 **원본의 코드 상자**에서 뽑아 dy만큼 옮긴다.

    이동한 이미지에서 덩어리를 찾아 지우려 하면, 위로 이조할 때 음표가 코드
    글자에 닿아 한 덩어리가 되고 그 덩어리째 지워져 음표가 사라진다
    (실측: +2·+4키에서 음표 머리 잉크가 22~45%로 떨어졌다).

    원본 상자 안의 잉크는 검출기가 보장한 대로 **코드 글자뿐**이다. 그것만
    옮겨 지우면 음표는 절대 건드리지 않는다.
    """
    h, w = arr.shape[:2]
    bx0 = max(0, box["x"] - 1)
    bx1 = min(w, box["x"] + box["w"] + 1)
    by0 = max(0, box["y"] - 1)
    by1 = min(h, box["y"] + box["h"] + 1)
    if bx1 <= bx0 or by1 <= by0:
        return
    src = arr[by0:by1, bx0:bx1]
    gray = src.mean(axis=2) if src.ndim == 3 else src
    # 문턱은 **그 상자의 종이색 기준**으로 잡는다.
    #   · 128 고정으로 자르면 글자의 회색 안티에일리어싱 테두리가 남아,
    #     새 글자 뒤에 흐린 잔상이 겹쳐 보인다(실측: F²→D2 에서 윗첨자 2의
    #     윤곽이 남았다).
    #   · 그렇다고 215 고정으로 올리면 종이색이 200 근처인 스캔 악보에서
    #     상자 전체가 마스크가 되어, 이동한 자리의 **음표 머리까지 지운다**
    #     (실측: 조표·코드는 완벽해졌는데 멜로디가 사라졌다).
    # 상자 안 밝기 분포에서 잉크와 종이를 잡아 그 사이를 자른다.
    flat = np.sort(gray.reshape(-1))
    if flat.size >= 8:
        ink_lv = float(flat[int(flat.size * 0.10)])
        paper_lv = float(flat[int(flat.size * 0.90)])
    else:
        ink_lv, paper_lv = 30.0, 240.0
    cut = ink_lv + (paper_lv - ink_lv) * 0.72
    mask = gray < max(100.0, min(cut, paper_lv - 12.0))
    if not mask.any():
        return
    # 팽창. 상자는 글자에 딱 붙어 있어서 안티에일리어싱 경계가 상자 밖으로
    # 삐져나온다 — 팽창하지 않으면 이조 후 그 화소가 얇은 선으로 남는다.
    # **확대본에서는 삐져나오는 폭도 배율만큼 커진다.** 1px 고정으로 두면
    # 3배 확대한 악보에서 코드 윗첨자(♭·7)의 잔상이 그대로 남는다(실측).
    for _ in range(max(1, int(round(pad_px)))):
        d = mask.copy()
        d[1:, :] |= mask[:-1, :]
        d[:-1, :] |= mask[1:, :]
        d[:, 1:] |= mask[:, :-1]
        d[:, :-1] |= mask[:, 1:]
        mask = d

    ty0 = by0 + dy
    ty1 = by1 + dy
    lo = max(0, -ty0)
    hi = mask.shape[0] - max(0, ty1 - h)
    if hi <= lo:
        return
    out = np.asarray(img).copy()
    reg = out[ty0 + lo:ty0 + hi, bx0:bx1]
    reg[mask[lo:hi]] = paper_color(arr, box)
    out[ty0 + lo:ty0 + hi, bx0:bx1] = reg
    img.paste(Image.fromarray(out))


# 코드 심볼을 실제 악보처럼 그린다. 근음은 크게, 나머지는 작게, 숫자는
# 위로 올린다 — 원본 조판이 그렇다(실측: 마커스 악보의 F² 는 2가 윗첨자,
# Dm7 은 m 이 작고 7 이 더 위에 있다). 전부 같은 크기로 그리면 원본과
# 눈에 띄게 달라 보이고 폭도 더 든다.
SUP_RATIO = 0.66          # 뒷부분 글자 크기 비율
SUP_RISE = 0.34           # 숫자·기호를 올리는 높이 (근음 잉크 높이 대비)


def split_chord(text: str) -> tuple[str, str]:
    """'Ebmaj7' → ('Eb', 'maj7'). 근음(글자+임시표)과 나머지를 나눈다."""
    if not text:
        return "", ""
    i = 1
    while i < len(text) and text[i] in "#b♯♭":
        i += 1
    return text[:i], text[i:]


def chord_layout(text: str, size: int) -> tuple[list[tuple], int, int]:
    """
    (그릴 조각들, 전체 폭, 근음 잉크 높이).
    조각 = (문자열, 폰트, x오프셋, y올림)
    """
    root, tail = split_chord(text)
    big = load_text_font(size)
    small = load_text_font(max(6, int(round(size * SUP_RATIO))))
    _l, t, _r, b = big.getbbox(root or text)
    root_h = max(1, b - t)

    parts: list[tuple] = []
    x = 0
    if root:
        parts.append((root, big, x, 0))
        x += int(round(big.getlength(root)))
    # 뒷부분: 숫자·기호는 올리고, 글자(m·maj·sus·dim·add)는 밑줄에 둔다
    buf = ""
    raise_now = None
    for ch in tail:
        up = ch.isdigit() or ch in "+#b♯♭"
        if raise_now is None:
            raise_now = up
        if up != raise_now and buf:
            parts.append((buf, small, x, int(round(root_h * SUP_RISE))
                          if raise_now else 0))
            x += int(round(small.getlength(buf)))
            buf = ""
            raise_now = up
        buf += ch
    if buf:
        parts.append((buf, small, x, int(round(root_h * SUP_RISE))
                      if raise_now else 0))
        x += int(round(small.getlength(buf)))
    return parts, x, root_h


def draw_chord(d: ImageDraw.ImageDraw, text: str, size: int,
               x: int, baseline_y: int) -> int:
    """baseline_y 를 근음 잉크의 아래끝으로 삼아 그린다. 그린 폭을 낸다."""
    parts, width, _root_h = chord_layout(text, size)
    for frag, font, dx, rise in parts:
        _l, _t, _r, b = font.getbbox(frag)
        # getbbox 의 b 는 그리기 원점에서 잉크 아래끝까지의 거리다.
        # 잉크 아래끝을 baseline_y - rise 에 맞춘다.
        d.text((x + dx, baseline_y - rise - b), frag, fill=(0, 0, 0), font=font)
    return width


def chord_fits(text: str, size: int, avail: int) -> int:
    """avail 안에 들어가는 가장 큰 크기 (윗첨자 레이아웃 기준)."""
    s = size
    while s > 6 and chord_layout(text, s)[1] > avail:
        s -= 1
    return s


def overlay_chords(
    img: Image.Image, arr: np.ndarray, extraction: dict, mapping: list[dict],
    expand_y: int = 0, staff_tops: dict | None = None, spacing: float = 8.0,
) -> int:
    d = ImageDraw.Draw(img)
    systems = extraction["systems"]
    flat = [(s["index"], c) for s in systems for c in s["chords"]]
    size = base_font_size([c for _, c in flat])

    # **한 장의 코드는 모두 같은 크기다.** 안 들어가는 것만 줄이면 크기가
    # 들쭉날쭉해져 원본의 균일한 조판과 어긋난다(실측: 43개 중 15개만 줄어
    # 큰 글자와 작은 글자가 섞였다). 그래서 "가장 빠듯한 코드에 맞춘 크기"를
    # 한 번 구해 전부에 쓴다.
    def avail_for(sys_idx, box):
        same = [c["box"]["x"] for s in systems if s["index"] == sys_idx
                for c in s["chords"] if c["box"]["x"] > box["x"]]
        limit = min(same) if same else extraction["imageSize"]["w"]
        keep = max(4, int(round(spacing * 0.6)))
        return max(8, limit - box["x"] - keep)

    # 가장 빠듯한 코드에 맞춘 크기를 한 번 구해 전부에 쓴다
    for (sys_idx, chord), m in zip(flat, mapping):
        size = min(size, chord_fits(m["to"], size,
                                    avail_for(sys_idx, chord["box"])))
    shrunk = 0

    for (sys_idx, chord), m in zip(flat, mapping):
        box = chord["box"]
        # 다음 코드와 **최소 간격**을 남긴다. 2px만 두면 겹치진 않아도 붙어
        # 보인다(실측: 43개 중 12개가 여유 2~3px로 서로 닿아 보였다).
        avail = avail_for(sys_idx, box)

        # expand_y(부호 있음): 멜로디를 옮겼으면 원래 자리와 밀려난 자리를
        # 모두 지운다. **방향은 이동 부호를 따른다** — 위로 옮겼는데 아래만
        # 넓히면 위에 남고, 아래만 넓히면 오선을 침범한다.
        erase_chord_ink(img, arr, box, expand_y, max(1.0, spacing / 7.0))
        use = chord_fits(m["to"], size, avail)
        shrunk += 1 if use < size else 0
        # 원본 상자의 아래끝을 근음 잉크의 아래끝으로 삼는다
        draw_chord(d, m["to"], use, box["x"], box["y"] + box["h"])
    return shrunk


# ------------------------------------------------------------------ 파이프라인

# 오선 간격을 이만큼으로 올려놓고 렌더한다. 웹에서 받은 악보는 간격이
# 6~7px인 경우가 흔한데, 그 해상도에서는 조표를 지우고 다시 그릴 여유가
# 없다(실측: 12개 키 중 조표 교체 성공이 0단 → 업스케일 후 9단 전부).
# 판독은 원본 해상도에서 해야 정확하므로(코드 검출이 44 → 0으로 무너졌다)
# **읽기는 원본, 그리기는 확대본**으로 나눈다.
TARGET_SPACING = 18.0
MAX_UPSCALE = 3.0


def _scale_boxes(obj, k: float):
    """추출 결과의 좌표를 배율만큼 키운다."""
    if isinstance(obj, dict):
        return {a: (int(round(b * k)) if a in ("x", "y", "w", "h")
                    and isinstance(b, (int, float))
                    else _scale_boxes(b, k)) for a, b in obj.items()}
    if isinstance(obj, list):
        return [_scale_boxes(v, k) for v in obj]
    return obj


def render(image_path: str, extraction: dict, semitones: int, out_path: str,
           shift_melody: bool = True, upscale: bool = True,
           protect: list[dict] | None = None) -> dict:
    """
    protect: 이동 후 음표 머리가 놓일 상자 목록(확대 좌표). 가사 띠를 되돌릴
    때 이 자리는 건드리지 않는다.

    왜 필요한가: 가사 띠는 오선 바로 아래부터 잡히고, 아래로 이조하면 덧줄
    음표가 그 안으로 내려온다. 띠를 원본으로 통째로 덮으면 그 음표가 지워진다
    (실측: 머리 115개 중 36개가 잉크 절반 이하, 그중 92%가 이 띠 안이었다).
    띠를 좁히거나 잉크만 되돌리는 방법을 네 가지 시도했지만, 밀려간 가사
    복사본이 남아 가사 일치율이 54~87%로 떨어졌다. 그래서 **어디를 지켜야
    하는지 검출기에게 묻는다** — 그 정보가 있으면 정확히 그 자리만 비켜간다.
    """
    src = Image.open(image_path).convert("RGB")
    ink, staves = cv.find_staves_best(src)
    if not staves:
        raise SystemExit("오선을 찾지 못했습니다.")
    spacing = cv.median_spacing(staves)

    scale = 1.0
    if upscale and spacing > 0:
        f = min(MAX_UPSCALE, TARGET_SPACING / spacing)
        # 1.3배 미만은 얻는 게 없고 파일만 커진다
        if f >= 1.3:
            src = src.resize((int(src.width * f), int(src.height * f)),
                             Image.LANCZOS)
            extraction = _scale_boxes(extraction, f)
            ink, staves = cv.find_staves_best(src)
            if not staves:
                raise SystemExit("확대 후 오선을 찾지 못했습니다.")
            spacing = cv.median_spacing(staves)
            scale = f

    systems = extraction["systems"]
    chords = [c["text"] for s in systems for c in s["chords"]]
    plan = call_engine(extraction["meta"]["key"], semitones, chords)

    img = src.copy()
    arr = np.asarray(src)

    # ── 해상도 게이트 ─────────────────────────────────────────────
    # 오선을 건드리는 작업은 해상도가 받쳐줄 때만 한다. 반쯤 망가진 조표를
    # 그리는 것보다 손대지 않고 명시하는 게 낫다.
    # **조표를 못 바꾸면 멜로디도 옮기지 않는다.** 옮겨 놓고 조표를 그대로
    # 두면 조표와 음표가 어긋나, 연주자가 원래 조표로 읽었을 때 전부 틀린
    # 음이 된다. 그럴 바에는 아무것도 안 바꾸고 코드차트를 권하는 게 낫다.
    ksig_ok, ksig_why = keysig_feasible(
        cv.remove_staff_lines(ink, staves, protect_noteheads=False),
        staves, plan["fifthsFrom"])

    staff_edit_ok = spacing >= MIN_SPACING_FOR_STAFF_EDIT and ksig_ok
    gate_reason = None if staff_edit_ok else (ksig_why if not ksig_ok else
        f"오선 간격 {spacing:.0f}px < 최소 {MIN_SPACING_FOR_STAFF_EDIT:.0f}px "
        f"— 조표를 읽을 수 있게 그리려면 더 큰 이미지가 필요합니다"
    )

    ksig = 0
    melody: dict = {"shifted": False, "reason": None}

    # 이조해도 움직이면 안 되는 것들(마디선·쉼표)은 이조 방식과 무관하게
    # 항상 복원해야 한다 — 코드 지우기 사각형이 이것들을 뚫기 때문이다.
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=False)
    pristine = np.asarray(img).copy()

    # 가사는 이조와 무관하므로 항상 원본으로 되돌린다. 이동 창이 기둥을
    # 덮으려면 오선 아래로 내려가야 하고, 그러면 가사 영역에 기둥 조각이
    # 남는다(실측: 래스터 경로에서 가사 일치율 80~90%).
    lyric_bands = {}
    for i, st in enumerate(staves):
        nxt = staves[i + 1].top if i + 1 < len(staves) else None
        b = cv.find_lyric_band(ink, st, spacing, nxt)
        if b:
            # **띠를 좁혀서 쓴다.** find_lyric_band 는 두 단 사이를 넉넉히
            # 잡아 오선 바로 아래(0.3칸)부터 포함하는 경우가 있는데, 그
            # 범위를 원본으로 되돌리면 **아래로 이조해 그 자리에 내려온
            # 음표가 지워진다** (실측: 잉크 절반 이하로 망가진 머리 36개 중
            # 33개가 이동 후 이 띠 안에 있었다. 정상인 것은 6%뿐).
            # lyricstrip.band_of 는 띠 위쪽의 가장 깊은 골짜기에서 잘라
            # 음표·이음줄을 제외한다 — 음절 분할에서 125/125로 검증된 함수다.
            lyric_bands[st.index] = b

    fixed_all = []
    for st in staves:
        he = head_end_for(strict, st, spacing, plan["fifthsFrom"])
        fixed_all.append((st, he, [o for o in cv.find_fixed_objects(strict, st, spacing)
                                   if o["x"] >= he]))

    # ── 멜로디 평행이동 ──────────────────────────────────────────
    # 짝수 단(3·5·7도)과 홀수 단(2·4·6도)을 **같은 방법으로** 처리한다.
    # 오선 줄을 이웃 행으로 1행 인페인팅해서 지우고, 반칸 격자를 따라
    # 재배치한 뒤 원본 오선을 되돌린다(sheetcv.shift_notes_raster 주석 참고).
    #
    # 예전에는 홀수 단만 오선을 통째로 제거해야 해서 오선 간격 12px 이상을
    # 요구했다. 인페인팅은 이웃이 어두우면 잉크를 남기므로 저해상도에서도
    # 음표가 살아남는다 — 그래서 **멜로디 이동에는 해상도 게이트가 없다.**
    # (조표 교체는 오선 안에 글리프를 새로 그려야 하므로 게이트를 유지한다.)
    dy = int(round(-plan["steps"] * (spacing / 2.0)))
    # **조표를 못 바꾸면 음표도 옮기지 않는다.** 옮겨 놓고 조표를 원본으로
    # 두면 연주자가 원래 조표로 읽었을 때 전부 틀린 음이 된다. 코드만 바꾼
    # 악보를 주고 그 사실을 알리는 편이 정직하다.
    if shift_melody and dy != 0 and not ksig_ok:
        melody["reason"] = ("조표를 못 바꿔서 음표도 그대로 두었습니다 "
                            "— 멜로디는 원래 조성으로 읽으세요")
        shift_melody = False
    if shift_melody and dy != 0:
        work = np.asarray(img).copy()
        results = []
        # 단별 코드 상자 윗변 — 이동 창이 그 위(제목·작곡자)를 건드리지 않게
        chord_top = {}
        for sysd in extraction["systems"]:
            ys = [c["box"]["y"] for c in sysd["chords"]]
            if ys:
                chord_top[sysd["index"]] = min(ys) - 2
        for st, he, objs in fixed_all:
            results.append(cv.shift_notes_raster(
                work, st, dy, he, spacing, draw_lines=False, fixed=objs,
                win_top=chord_top.get(st.index)))
        ok = [r for r in results if r["shifted"]]
        if ok:
            img = Image.fromarray(work.astype(np.uint8))
            melody = {"shifted": True, "dy": dy, "staves": len(ok),
                      "fixed": sum(len(o) for _, _, o in fixed_all),
                      "reason": None, "pending": ok, "mode": "resample"}
        else:
            melody["reason"] = results[0]["reason"] if results else "오선 없음"
    elif dy == 0:
        melody["reason"] = "이조량 0 — 음표 위치는 그대로이고 임시표만 달라집니다"

    # ── 조표 교체 ────────────────────────────────────────────────
    # 조표는 오선 안에 있어 제거가 필요하므로 해상도 게이트를 적용한다.
    if staff_edit_ok:
        content = cv.remove_staff_lines(ink, staves, protect_noteheads=False)
        ksig = replace_key_signatures(
            img, content, staves, plan["fifthsFrom"], plan["fifthsTo"], arr,
            pristine, extraction
        )

    # ── 코드 오버레이 ────────────────────────────────────────────
    # 오선을 건드리지 않으므로 항상 수행한다. 멜로디를 옮겼다면 코드도 같이
    # 밀려났으므로 지우는 범위를 이동량만큼 넓힌다.
    shrunk = overlay_chords(
        img, arr, extraction, plan["chords"],
        expand_y=dy if melody["shifted"] else 0,
        staff_tops={st.index: st.top for st in staves},
        spacing=spacing,
    )

    # ── 고정 객체 + 오선 복원 (반드시 코드 오버레이 뒤) ─────────────
    # 코드 지우기 사각형이 오선과 마디선 윗부분을 뚫는다(실측: 마디선 일치율
    # 75~86%, 홀수 단에서는 오선 잉크 16px 소실). 이조 방식과 무관하게 복원한다.
    work2 = np.asarray(img).copy()
    # 고정 객체는 이동 소스에서 이미 빠졌으므로(sheetcv 주석) 밀려간 복사본이
    # 없다. 복원 범위를 넓힐 필요가 없고, 넓히면 그 자리에 온 음표를 덮는다.
    shift_dy = 0
    h_, w_ = work2.shape[:2]
    for band in lyric_bands.values():
        y0, y1 = band
        if not protect:
            work2[y0:y1, :] = pristine[y0:y1, :]
            continue
        # 지킬 자리를 뺀 나머지만 되돌린다
        keep = np.zeros((y1 - y0, work2.shape[1]), dtype=bool)
        for pb in protect:
            px0 = max(0, int(pb["x"])); px1 = min(work2.shape[1],
                                                  int(pb["x"] + pb["w"]))
            py0 = max(y0, int(pb["y"])); py1 = min(y1, int(pb["y"] + pb["h"]))
            if px1 > px0 and py1 > py0:
                keep[py0 - y0:py1 - y0, px0:px1] = True
        blk = work2[y0:y1, :]
        src_blk = pristine[y0:y1, :]
        if blk.ndim == 3:
            m = ~keep
            for ch in range(blk.shape[2]):
                blk[:, :, ch][m] = src_blk[:, :, ch][m]
        else:
            blk[~keep] = src_blk[~keep]
    for st, _he, objs in fixed_all:
        for o in objs:
            y0 = max(0, min(o["y"], o["y"] + shift_dy) - 1)
            y1 = min(h_, max(o["y"] + o["h"], o["y"] + o["h"] + shift_dy) + 1)
            x0 = max(0, o["x"] - 1)
            x1 = min(w_, o["x"] + o["w"] + 1)
            if x1 > x0 and y1 > y0:
                work2[y0:y1, x0:x1] = pristine[y0:y1, x0:x1]
    # ── 오선 복원: **줄 잉크만** 되돌린다 ────────────────────────
    # 예전에는 원본 전체와 어두운 쪽을 택했다(np.minimum(work2, pristine)).
    # 그러면 원본에서 줄 위에 앉아 있던 음표 머리가 그 줄 행에서 되살아나,
    # 음표를 다 옮긴 뒤에도 줄마다 옛 머리 조각이 유령으로 남았다
    # (실측: 3배 확대 이조본에서 오선 위 가로 막대 잔상).
    # 이제 세로 런이 줄 두께 이하인 화소 = 순수한 오선만 되돌린다.
    #
    # x 범위는 headEnd가 아니라 오선 전체 폭이다. 머리 구간 오선은 원본과
    # 같으므로 되돌려도 안전하고, headEnd 왼쪽 코드가 뚫은 구멍을 메운다
    # (실측: 첫 코드 x=185 < headEnd 240 → 56px 구멍).
    #
    # 되돌릴 줄 범위는 **회색 헤일로까지** 잡는다. 이진화된 심(core)만
    # 되돌리면 확대본에서 줄이 얇아지고 코드를 지운 자리마다 끊겨 보인다
    # (실측: 3배 확대 악보에서 오선이 점선처럼 됐다).
    gray_p = (pristine.mean(axis=2) if pristine.ndim == 3
              else pristine.astype(float))
    regions = []
    for st, _he, _objs in fixed_all:
        x0, x1 = st.left, min(st.right + 1, w_)
        if x1 <= x0:
            continue
        spans_wide = cv.expand_line_spans_gray(gray_p, st, x0, x1)
        regions.append({"x0": x0, "x1": x1, "spans": [
            (int(a), int(b), int(c1 - c0 + 1))
            for (a, b), (c0, c1) in zip(spans_wide, st.spans)]})
    if regions:
        # 줄 잉크만 뽑아 **그 줄의 색**을 알아낸 뒤, 그 색으로 줄을 가로로
        # 이어 그린다. 뽑은 화소를 그대로 되돌리기만 하면, 원본에서 머리가
        # 줄을 덮고 있던 자리에는 되돌릴 잉크가 없어 줄에 구멍이 난다
        # (실측: 옛 머리를 지우자 오선이 점선처럼 끊겼다).
        # 오선이 음표 위로 지나가는 것은 원래 정상적인 조판이므로, 가로로
        # 통째로 이어 그려도 음표를 해치지 않는다. 덮어쓰지 않고 **더 어두운
        # 쪽**을 택하므로 그 자리에 온 새 음표 머리도 그대로 남는다.
        lines_only, covered = cv.staff_line_ink(pristine, regions)
        # 마디선·쉼표 상자는 이어 그리기에서 뺀다. 그 자리는 위에서 원본을
        # 그대로 되돌렸으므로 줄이 이미 이어져 있고, 덧칠하면 마디선의
        # 부드러운 가장자리가 줄 색으로 어두워져 화소가 달라진다
        # (실측: 고정 객체 일치율 84.7%).
        for _st, _he, objs in fixed_all:
            for o in objs:
                oy0 = max(0, o["y"] - 1); oy1 = min(h_, o["y"] + o["h"] + 1)
                ox0 = max(0, o["x"] - 1); ox1 = min(w_, o["x"] + o["w"] + 1)
                if oy1 > oy0 and ox1 > ox0:
                    covered[oy0:oy1, ox0:ox1] = False
        for reg in regions:
            rx0, rx1 = reg["x0"], reg["x1"]
            for (a, b, _core) in reg["spans"]:
                # ① 순수한 줄 화소는 원본 값 그대로 되돌린다 — 화소가
                #    바뀌지 않아야 검증(완전일치)이 통과한다.
                work2[a:b + 1, rx0:rx1] = np.minimum(
                    work2[a:b + 1, rx0:rx1], lines_only[a:b + 1, rx0:rx1])
                # ② 원본에서 음표가 줄을 덮고 있던 자리에만 줄 색을 이어
                #    그린다. 그 자리에는 되돌릴 줄 잉크가 없어 구멍이 난다.
                #    전 폭을 다시 칠하면 헤일로 행까지 균일해져 회색 띠가 생겼다.
                for y in range(a, b + 1):
                    cov = covered[y, rx0:rx1]
                    if not cov.any():
                        continue
                    row = lines_only[y, rx0:rx1]
                    lum = row.mean(axis=1) if row.ndim == 2 else row
                    m = lum < 250
                    if int(m.sum()) < 3:
                        continue
                    tone = np.median(row[m], axis=0)
                    sub = work2[y, rx0:rx1]
                    sel = cov[:, None] if sub.ndim == 2 else cov
                    work2[y, rx0:rx1] = np.where(sel, np.minimum(sub, tone), sub)
    img = Image.fromarray(work2.astype(np.uint8))

    img.save(out_path)

    return {
        "summary": plan["summary"],
        "fromKey": plan["fromKey"],
        "toKey": plan["toKey"],
        "fifths": (plan["fifthsFrom"], plan["fifthsTo"]),
        "steps": plan["steps"],
        "spacing": spacing,
        "scale": round(scale, 2),
        "staves": len(staves),
        "headEnds": {st.index: he for st, he, _ in fixed_all},
        "staffEditOk": staff_edit_ok,
        "gateReason": gate_reason,
        "keySignatures": ksig,
        "chords": len(chords),
        "shrunk": shrunk,
        "capo": plan["capo"],
        "melody": melody,
        "fixed": sum(len(o) for _, _, o in fixed_all),
    }


def protect_boxes(image_path: str, extraction: dict, semitones: int,
                  model_path: str) -> list[dict] | None:
    """
    이동 후 음표 머리가 놓일 상자. 못 구하면 None (조용히 건너뛴다).

    검출기(ultralytics)는 별도 환경에 있을 수 있으므로 MUTE_DETECT_PYTHON 으로
    넘겨 실행한다 — 코어 도구는 의존성 0을 유지한다.
    """
    import json as _json
    import os
    import subprocess
    import tempfile

    script = Path(__file__).resolve().parent / "protect.py"
    if not script.exists():
        return None
    py = os.environ.get("MUTE_DETECT_PYTHON") or sys.executable
    exp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                        encoding="utf-8") as f:
            _json.dump(extraction, f, ensure_ascii=False)
            exp = f.name
        r = subprocess.run([py, str(script), image_path, exp,
                            "-s", str(semitones), "--model", model_path],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return None
        return _json.loads(r.stdout)
    except Exception:
        return None
    finally:
        if exp:
            Path(exp).unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="뮤트 렌더러 (Tier 1.5)")
    ap.add_argument("image")
    ap.add_argument("extraction")
    ap.add_argument("-s", "--semitones", type=int, required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--no-melody", action="store_true", help="멜로디 이동 시도 안 함")
    # 픽셀을 미는 방식은 임시표를 다시 계산하지 못한다. 실측으로는 실제
    # 콘티 22쪽 음표 2,512개 중 멜로디 임시표가 5개(0.2%)뿐이지만, 그
    # 5개는 반음이 틀린다. 방식을 바꾸는 대신 **어디인지 짚어준다.**
    ap.add_argument("--model", default="models/omr.pt",
                    help="임시표 경고용 검출기 (없으면 경고 생략)")
    ap.add_argument("--no-warn", action="store_true", help="임시표 경고 끔")
    ap.add_argument("--protect-heads", action="store_true",
                    help="검출기로 음표 자리를 찾아 가사 되돌리기에서 비켜간다")
    args = ap.parse_args()

    with open(args.extraction, encoding="utf-8") as f:
        extraction = json.load(f)

    protect = None
    if args.protect_heads and Path(args.model).exists():
        protect = protect_boxes(args.image, extraction, args.semitones,
                                args.model)
    info = render(args.image, extraction, args.semitones, args.out,
                  shift_melody=not args.no_melody, protect=protect)

    e = sys.stderr
    print(info["summary"], file=e)
    if info.get("scale", 1.0) != 1.0:
        print(f"확대 {info['scale']}배 (오선 간격을 {TARGET_SPACING:.0f}px로)", file=e)
    print(f"오선 {info['staves']}단 · 간격 {info['spacing']:.0f}px "
          f"· 온음계 {info['steps']}단 이동", file=e)
    if info["staffEditOk"]:
        print(f"조표 교체 {info['keySignatures']}단 "
              f"({info['fifths'][0]:+d} → {info['fifths'][1]:+d})", file=e)
    else:
        print(f"⚠️  조표를 바꾸지 못했습니다 — {info['gateReason']}", file=e)
        print(f"    조표·음표를 **원본 그대로** 두었습니다. 코드만 바뀌었으니"
              f" 멜로디는 원래 조성({info['fromKey']})으로 읽으세요.", file=e)
        print(f"    → 이 악보는 `--chart` 로 코드차트를 뽑는 편이 정확합니다.",
              file=e)
    print(f"코드 {info['chords']}개 교체 (축소 {info['shrunk']}개)", file=e)
    m = info["melody"]
    if m["shifted"]:
        print(f"멜로디 이동 {m['staves']}단 · {m['dy']:+d}px "
              f"(온음계 {info['steps']}단) · 마디선·쉼표 {info['fixed']}개 고정",
              file=e)
    else:
        print(f"⚠️  멜로디 미이동 — {m['reason']}", file=e)
    if not args.no_warn and Path(args.model).exists():
        # 검출기는 ultralytics가 필요한데, 코어 도구들은 의존성 0으로 둔다.
        # 검출기용 파이썬을 MUTE_DETECT_PYTHON 에 지정해 두면 그쪽으로
        # 넘겨 실행한다. 없으면 조용히 건너뛴다 — 경고가 없다고 해서
        # 임시표가 없다는 뜻은 아니므로 그때는 아무 말도 하지 않는다.
        import os
        import subprocess
        py = os.environ.get("MUTE_DETECT_PYTHON")
        script = str(Path(__file__).resolve().parent / "accidentals.py")
        try:
            if py:
                r = subprocess.run(
                    [py, script, args.image, "--model", args.model],
                    capture_output=True, text=True, timeout=180)
                line = [x for x in r.stdout.splitlines()
                        if x.strip() and not x.startswith("═")]
                if line:
                    print("", file=e)
                    print("\n".join(line), file=e)
            else:
                import accidentals as A
                from ultralytics import YOLO
                res = A.find(Image.open(args.image).convert("RGB"),
                             YOLO(args.model))
                print("", file=e)
                print(A.summary(res), file=e)
        except Exception:
            pass

    print(f"→ {args.out}", file=e)


if __name__ == "__main__":
    main()


# 바닥 고지가 시작하려면 가사 띠에서 이만큼은 떨어져 있어야 한다.
FOOT_MIN_GAP = 1.0        # 빈 줄 (칸)
FOOT_MIN_DROP = 4.0       # 마지막 오선 아래로 (칸)


def footer_cut_for(ink, staves, spacing: float) -> int:
    """
    **바닥 고지(저작권 표기)가 시작하는 y.** 없으면 0.

    악보 아래에는 두 가지가 있다 — 마지막 단의 **가사**와, 그 아래 페이지
    맨 밑의 **저작권 표기**("Copyright 2025 … All rights reserved."). 앞의
    것은 다시 그려지지만 뒤의 것은 만들 수 없으므로 원본 픽셀을 그대로
    옮겨야 한다 — 머리글과 같은 이유다(serve.py 의 head_cut).

    **거리로만 가르면 안 된다.** 마지막 단 아래 잉크가 어디까지 가사인지
    재 봤다(4장): 1.7 · 3.7 · 3.9 · 5.3칸으로 제각각이다. 그래서 거리와
    함께 **빈 줄로 끊겼는지**를 본다 — 가사와 고지 사이에는 눈에 보이는
    여백이 있고, 가사 줄들 사이에는 없다(실측 간격 0.1~0.4칸).

    반환: 자를 y (원본 좌표). 고지가 없으면 0.
    """
    import numpy as np

    if not staves:
        return 0
    last = staves[-1]
    a = np.asarray(ink)
    base = int(last.bottom)
    if base >= a.shape[0] - 2:
        return 0
    rows = a[base:, :].any(axis=1)

    blocks: list[tuple[int, int]] = []
    start = None
    for i, on in enumerate(rows):
        if on and start is None:
            start = i
        elif not on and start is not None:
            blocks.append((start, i))
            start = None
    if start is not None:
        blocks.append((start, len(rows)))
    blocks = [b for b in blocks if b[1] - b[0] >= 2]
    if len(blocks) < 2:
        return 0

    for prev, cur in zip(blocks, blocks[1:]):
        gap = (cur[0] - prev[1]) / spacing
        drop = cur[0] / spacing
        if gap >= FOOT_MIN_GAP and drop >= FOOT_MIN_DROP:
            # 여백 절반 위에서 자른다 — 고지 글자가 잘리지 않게
            return base + int(cur[0] - spacing * min(0.6, gap * 0.4))
    return 0
