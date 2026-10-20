#!/usr/bin/env python3
"""
조표(key signature) 교체.

이조하면 조표도 반드시 바뀐다. 코드만 바꾸고 조표를 두면 악보 내부가 모순이다
(코드는 G키, 조표는 Bb키). 조표는 오선 안에 있어서 코드 오버레이와 달리
오선 위 정확한 음높이 위치에 새로 그려야 한다.

높은음자리표 기준 오선 위치 (아래→위): 1선 E4, 2선 G4, 3선 B4, 4선 D5, 5선 F5
칸: 1칸 F4, 2칸 A4, 3칸 C5, 4칸 E5
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sheetcv import Staff, components

# ♭♯ 글리프가 실제로 있는 폰트. Times·Arial에는 ♭가 없다(두부 박스가 나온다).
GLYPH_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Apple Symbols.ttf",
    # 리눅스 컨테이너용. DejaVu 에도 ♭♯ 가 있다.
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

FLAT = "♭"
SHARP = "♯"

# 조표에 임시표가 붙는 순서와 오선 위치.
# 위치는 "5선(맨 위 줄) = 0" 기준으로 반칸(=온음계 1단) 단위 아래로 센 값.
#   5선 F5=0, 4칸 E5=1, 4선 D5=2, 3칸 C5=3, 3선 B4=4,
#   2칸 A4=5, 2선 G4=6, 1칸 F4=7, 1선 E4=8
SHARP_STEPS = [0, 3, -1, 2, 5, 1, 4]   # F# C# G# D# A# E# B#
FLAT_STEPS = [4, 1, 5, 2, 6, 3, 7]     # Bb Eb Ab Db Gb Cb Fb


def load_glyph_font(size: int) -> ImageFont.FreeTypeFont:
    for p in GLYPH_FONTS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    raise SystemExit("♭♯ 글리프가 있는 폰트를 찾지 못했습니다.")


def cluster_x(boxes, gap: float):
    """
    x축으로 붙어 있는 조각들을 한 글리프로 묶는다.

    ♭ 하나가 기둥·몸통·점 3조각으로 분리돼서, 묶지 않으면 조표 개수를 잘못
    센다(실측: ♭ 2개짜리 조표에서 첫 ♭의 조각 2개를 조표 전체로 봤고, 두 번째
    ♭을 박자표로 오인해 지우기 폭이 엉켰다).
    """
    out: list[list] = []
    for b in sorted(boxes, key=lambda b: b.x):
        if out and b.x <= max(q.right for q in out[-1]) + gap:
            out[-1].append(b)
        else:
            out.append([b])
    return [(min(q.x for q in g), max(q.right for q in g),
             min(q.y for q in g), max(q.bottom for q in g), g) for g in out]


@dataclass
class KeySigRegion:
    """원본 조표가 차지하던 영역"""
    x: int
    y: int
    w: int
    h: int
    """임시표 개수 (부호 있음: 양수=올림표, 음수=내림표)"""
    fifths: int


def locate(content: np.ndarray, st: Staff, source_fifths: int) -> KeySigRegion | None:
    """
    음자리표 뒤의 조표 영역을 찾는다.

    content는 오선이 제거된 레이어여야 한다 — 오선이 있으면 음자리표·조표·
    마디선이 전부 한 덩어리로 붙어서 분리되지 않는다.
    """
    n = abs(source_fifths)
    if n == 0:
        return None

    sp = st.spacing
    # 머리 구간: 음자리표 + 조표 + (첫 단이면) 박자표
    head_x1 = st.left + int(sp * 14)
    band_top = max(0, st.top - int(sp * 2))
    band_bot = min(content.shape[0], st.bottom + int(sp * 2))
    band = content[band_top:band_bot, st.left:head_x1]

    boxes = sorted(components(band), key=lambda b: b.x)
    # 잡티 제거 + **오선 안에 있는 것만**. 코드 심볼은 오선 위에 떠 있는데,
    # 밴드가 오선 위 2칸까지 걸치므로 코드 글자 조각이 섞여 들어온다
    # (실측: 오선 7px에서 코드 조각 x=67이 '다음 요소'로 잡혀, 조표가 늘어날
    #  자리가 없다고 판단해 교체가 건너뛰어졌다).
    boxes = [b for b in boxes
             if b.h >= sp * 0.8 and b.w >= 1
             and st.top <= b.y + band_top + b.h / 2.0 <= st.bottom]
    if not boxes:
        return None

    # 음자리표는 **먼저 묶은 뒤** 가장 키 큰 조각이 든 덩어리로 잡는다.
    # "앞 3개 중 가장 큰 것"으로 잡으면 저해상도에서 음자리표가 조각났을 때
    # 그 조각 하나만 음자리표로 보고, 나머지 조각이 조표로 들어간다
    # (실측: 오선 7px에서 조표 영역이 음자리표 꼬리부터 시작해 첫 임시표만
    # 포함했고, 그 결과 자리가 모자라 조표 교체가 통째로 건너뛰어졌다).
    # 음자리표는 가장 키 큰 조각에서 시작해 **x가 겹치는 조각만** 이어붙여
    # 잡는다. 간격 기준으로 묶으면 저해상도에서 음자리표와 첫 임시표가 2px
    # 붙어 한 덩어리가 되어 조표를 통째로 놓친다(실측: 오선 6.5px 악보에서
    # locate가 None을 반환했다).
    tallest = max(boxes, key=lambda b: b.h)
    cx0, cx1 = tallest.x, tallest.right
    changed = True
    while changed:
        changed = False
        for b in boxes:
            if b.right < cx0 or b.x > cx1:
                continue                      # 겹치지 않는다
            if b.x < cx0 or b.right > cx1:
                cx0, cx1 = min(cx0, b.x), max(cx1, b.right)
                changed = True
    after = [b for b in boxes if b.x > cx1]
    if not after:
        return None

    # 조표 범위는 **박자표 앞까지**다. 개수(n)로 자르면 안 된다 — 저해상도에서
    # 임시표들이 서로 붙어 한 덩어리가 되면 덩어리 수가 개수보다 적어져서,
    # 뒤에 오는 박자표까지 조표로 잡고 함께 지운다(실측: 오선 6.5px 악보에서
    # 4/4가 사라졌다).
    groups = cluster_x(after, sp * 0.35)
    sig = []
    for g in groups:
        if is_timesig(g, sp, st):
            break
        sig.append(g)
        if len(sig) >= n:          # 붙지 않은 경우엔 개수로도 충분하다
            break
    if not sig:
        return None
    x0 = min(g[0] for g in sig)
    x1 = max(g[1] for g in sig)
    y0 = min(g[2] for g in sig)
    y1 = max(g[3] for g in sig)
    return KeySigRegion(
        x=x0 + st.left, y=y0 + band_top, w=x1 - x0, h=y1 - y0, fifths=source_fifths
    )


def is_timesig(group, sp: float, st: Staff) -> bool:
    """
    이 덩어리가 박자표인가.

    판별자: **세로로 겹쳐 쌓인 두 덩어리**(분자/분모)이고, 좁고(2칸 이내),
    오선을 위아래로 채운다. 개수만 세면 나란한 음표 두 개가 걸린다(실측).
    """
    mem = group[4]
    stacked = False
    for i in range(len(mem)):
        for j in range(i + 1, len(mem)):
            a, b = mem[i], mem[j]
            ov = min(a.right, b.right) - max(a.x, b.x)
            if (ov >= 0.6 * min(a.w, b.w)
                    and abs(a.y - b.y) >= sp * 1.2
                    and 0.6 <= a.w / max(1, b.w) <= 1.7):
                stacked = True
    narrow = (group[1] - group[0]) <= sp * 2.0
    fills = (group[3] - group[2]) >= sp * 2.6
    in_head = group[1] <= st.left + sp * 16
    if not (narrow and fills and in_head):
        return False
    if stacked:
        return True
    # 저해상도에서는 분자와 분모가 붙어 **한 덩어리**가 된다. 그때는 "쌓임"을
    # 볼 수 없으므로 굵기로 가른다 — 마디선은 0.65칸 이하로 얇고, 박자표는
    # 숫자라서 그보다 넓다(실측: 오선 5.5px에서 4/4가 한 덩어리가 되어
    # 박자표를 못 찾았고, 임시표가 그 위에 겹쳐 찍혔다).
    w = group[1] - group[0]
    return len(mem) == 1 and w >= sp * 0.7


def next_block(
    content: np.ndarray, st: Staff, region: KeySigRegion | None, start_x: int
) -> tuple[int, int, int] | None:
    """
    조표 오른쪽 첫 요소(보통 박자표)의 (왼쪽, 오른쪽, 그 다음 요소의 왼쪽).

    박자표는 위·아래 숫자가 별개 덩어리라 x가 겹치는 것들을 한 블록으로 묶는다.
    """
    sp = st.spacing
    x_from = (region.x + region.w) if region else start_x
    band_top = max(0, st.top - int(sp * 2))
    band_bot = min(content.shape[0], st.bottom + int(sp * 2))
    x_hi = min(content.shape[1], st.left + int(sp * 26))
    band = content[band_top:band_bot, :x_hi]
    cand = [b for b in components(band)
            if b.h >= sp * 0.6 and b.x > x_from + 1
            and st.top <= b.y + band_top + b.h / 2.0 <= st.bottom]
    groups = cluster_x(cand, sp * 0.4)   # 박자표 위/아래 숫자는 한 블록
    if not groups:
        return None
    x0, x1 = groups[0][0], groups[0][1]
    nxt = groups[1][0] if len(groups) > 1 else x_hi
    # 밀어도 되는 것은 **박자표뿐이다.** 판정은 "세로로 겹쳐 쌓인 두 덩어리".
    # 개수만 세면 나란한 음표 두 개가 박자표로 오인된다(실측: 단2·3에서
    # 머리 끝이 첫 음표 뒤로 잡혀 그 음표가 이동에서 빠졌다).
    # 음표를 밀면 리듬 위치가 틀어지고 조각이 남는다.
    return (x0, x1, nxt, is_timesig(groups[0], sp, st))


def next_element_x(
    content: np.ndarray, st: Staff, region: KeySigRegion | None, start_x: int
) -> int | None:
    """
    조표 **오른쪽에 처음 나오는 요소**의 왼쪽 x. 보통 박자표, 없으면 첫 음표다.

    이 경계를 모르면 지우기 사각형이 조표 개수만큼 오른쪽으로 자라서 박자표를
    먹는다(실측: Bb 2개 → Ab 4개로 늘자 4/4가 사라졌다).
    """
    sp = st.spacing
    x_from = (region.x + region.w) if region else start_x
    band_top = max(0, st.top - int(sp * 2))
    band_bot = min(content.shape[0], st.bottom + int(sp * 2))
    x_hi = min(content.shape[1], st.left + int(sp * 22))
    band = content[band_top:band_bot, :x_hi]
    cand = [b for b in components(band)
            if b.h >= sp * 0.8 and b.x > x_from + 1]
    if not cand:
        return None
    return min(b.x for b in cand)


def step_to_y(st: Staff, step: int) -> float:
    """
    5선(맨 위)을 0으로 한 반칸 단위 위치 → 이미지 y좌표.

    y는 아래로 갈수록 커지므로 맨 위 오선은 lines[0] 이다.
    (lines[-1]을 쓰면 맨 아래 줄이 기준이 되어 조표가 오선 밖으로 나간다.)
    """
    return st.lines[0] + step * (st.spacing / 2.0)


def draw(
    draw_ctx: ImageDraw.ImageDraw,
    st: Staff,
    target_fifths: int,
    start_x: int,
    paper: tuple[int, int, int],
    advance: int | None = None,
    scale: float = 1.0,
) -> int:
    """
    새 조표를 그리고 오른쪽 끝 x좌표를 돌려준다.
    글리프 크기는 오선 간격에 맞춘다 — 임시표는 대략 오선 두 칸 높이다.
    """
    if target_fifths == 0:
        return start_x

    sp = st.spacing
    glyph = SHARP if target_fifths > 0 else FLAT
    steps = (SHARP_STEPS if target_fifths > 0 else FLAT_STEPS)[: abs(target_fifths)]

    # 글리프가 오선 2칸(=sp*2) 높이가 되도록 폰트 크기를 맞춘다
    target_h = sp * 2.2 * scale
    size = max(6, int(round(target_h * 1.35)))
    font = load_glyph_font(size)
    l, t, r, b = font.getbbox(glyph)
    gw, gh = r - l, b - t

    if advance is None:
        advance = max(3, int(round(gw * 0.95)))
    x = start_x
    for step in steps:
        cy = step_to_y(st, step)
        # 글리프의 세로 중심을 해당 음높이에 맞춘다
        draw_ctx.text((x - l, cy - gh / 2.0 - t), glyph, fill=(0, 0, 0), font=font)
        x += advance
    return x


def repaint_staff_lines(img: Image.Image, st: Staff, x0: int, x1: int,
                        original: np.ndarray | None) -> None:
    """
    x0~x1 구간의 오선을 **그 행의 대표 색으로** 다시 칠한다.

    순검정으로 그리면 주변의 얇은 회색 선과 어긋난 검은 막대가 된다
    (실측: 오선 7px 악보에서 조표·박자표 자리에만 두꺼운 검은 띠).
    원본 화소를 그대로 되돌리면 그 자리에 있던 옛 임시표 조각이 함께 돌아와
    선이 점선처럼 끊긴다(실측). 오선은 가로로 균일하므로 그 행 전체의
    중앙값이 곧 선의 색이다.
    """
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    x0 = max(0, int(x0))
    x1 = min(w, int(x1) + 1)
    sx0, sx1 = max(0, st.left), min(w, st.right + 1)
    if x1 <= x0 or sx1 <= sx0:
        return
    src = original if original is not None else arr
    out = arr.copy()
    for (a, b) in st.spans:
        for y in range(max(0, a - 1), min(h, b + 2)):
            tone = np.median(src[y, sx0:sx1], axis=0)
            out[y, x0:x1] = tone.astype(out.dtype)
    img.paste(Image.fromarray(out))


def replace(
    img: Image.Image,
    content: np.ndarray,
    st: Staff,
    source_fifths: int,
    target_fifths: int,
    paper: tuple[int, int, int],
    original: np.ndarray | None = None,
    dry_run: bool = False,
    hint: tuple[int, int, int] | None = None,
    chord_limit: int | None = None,
) -> dict:
    """
    한 단의 조표를 교체한다 (img를 제자리 수정).

    dry_run=True 면 그리지 않고 **가능한지만** 판정한다. 호출자는 이걸로
    "전 단이 가능할 때만 교체" 규칙을 지킨다 — 일부 단만 바뀐 악보는
    안 바뀐 악보보다 헷갈린다.
    """
    d = ImageDraw.Draw(img)
    region = locate(content, st, source_fifths)

    sp = st.spacing
    # 한 악보의 머리 배치(음자리표+조표+박자표)는 모든 단이 같다. 어느 한 단에서
    # 검출이 실패해도 다른 단의 합의값으로 메운다 — 그러지 않으면 9단 중 1단의
    # 검출 실패가 악보 전체의 조표 교체를 막는다(실측).
    if region is None and hint is not None:
        hx, hw, _ = hint
        region = KeySigRegion(x=hx, y=st.top, w=hw,
                              h=st.bottom - st.top, fifths=source_fifths)
    if region is None:
        # **옛 조표를 못 찾으면 새 조표를 그리지 않는다.** 예전에는 기본
        # 위치(오선 왼쪽 + 4.5칸)에 그냥 그렸는데, 그러면 옛 조표는 그대로
        # 남고 새 조표가 그 오른쪽에 겹쳐 찍힌다 — ♯1개짜리 악보가 ♯3개처럼
        # 보였다(실측). 게다가 호출자에게는 "교체 성공"으로 보고됐다.
        # 틀린 조표를 그리느니 안 바꾸고 알리는 편이 낫다.
        return {"erased": 0, "startX": None, "endX": None,
                "skipped": "조표를 찾지 못함"}
    start_x = region.x

    # 지울 범위를 **기하학적으로** 정한다. locate가 찾은 영역만 지우면
    # 임시표 일부가 남는다(실측: 2개 중 1개만 지워졌다) — 음자리표와 겹치면
    # locate가 놓치기 때문이다. 개수와 글리프 폭은 이미 알고 있다.
    glyph = SHARP if target_fifths > 0 else FLAT
    font = load_glyph_font(max(6, int(round(sp * 2.2 * 1.35))))
    l, _, r_, _ = font.getbbox(glyph)
    advance = max(3, int(round((r_ - l) * 0.95)))
    slots = max(abs(source_fifths), abs(target_fifths))
    scale = 1.0

    # 오른쪽 경계를 넘지 않는다. 넘칠 때는 글리프 간격을 좁혀서 맞춘다 —
    # 조판을 다시 흘릴 수는 없으므로, 박자표를 지우는 대신 조표를 좁게 쓴다.
    blk = next_block(content, st, region, start_x)
    if (blk is None or (hint is not None and blk[0] < hint[2])) and hint is not None:
        # 검출된 다음 요소가 합의값보다 왼쪽이면 조각을 잡은 것이다
        blk = (hint[2], hint[2], hint[2], False)
    need = slots * advance + 4
    # 다음 요소와 최소 0.6칸은 띄운다 — 붙으면 조표가 음표에 닿는다
    avail = (blk[0] - int(sp * 0.6) - (start_x - 2)) if blk else None
    # 첫 코드 심볼과의 가로 겹침은 여기서 막지 않는다. 코드는 오선 **위**에
    # 떠 있으므로 조표(오선 안)와 세로로 다른 층이고, 가로로 제한하면 조표가
    # 늘어날 자리가 없어져 교체가 통째로 막힌다(실측: 9단 → 0단).
    # 남는 문제는 첫 코드 글자가 임시표 위에 겹쳐 보이는 것뿐이다.
    _ = chord_limit

    if blk and avail is not None and need > avail and blk[3]:
        # 자리가 부족하다. 압축하면 임시표가 겹쳐 읽을 수 없으므로(실측: Ab
        # 4개·F# 6개가 한 덩어리로 뭉쳤다), 실제 조판처럼 **박자표를 오른쪽으로
        # 민다.** 박자표와 첫 음표 사이 여백에서만 빌린다.
        b_x0, b_x1, nxt = blk[0], blk[1], blk[2]
        extra = need - avail
        room = max(0, nxt - int(sp * 0.6) - b_x1)
        move = min(extra, room)
        if move > 0 and dry_run:
            avail += move
        elif move > 0:
            top_b = max(0, st.top - int(sp * 2))
            bot_b = min(img.height, st.bottom + int(sp * 2))
            crop = img.crop((b_x0, top_b, b_x1 + 1, bot_b))
            d.rectangle([b_x0, top_b, b_x1 + move, bot_b], fill=paper)
            repaint_staff_lines(img, st, b_x0, b_x1 + move, original)
            img.paste(crop, (b_x0 + move, top_b))
            d = ImageDraw.Draw(img)
            avail += move

    # 축소는 **밀기와 무관하게** 시도한다. 예전에는 이 블록이 밀기 분기 안에
    # 있어서, 박자표가 없는 단(대부분의 단)은 축소를 해보지도 못하고 건너뛰었다
    # (실측: 오선 7px에서 8단 중 0단만 교체됨).
    # 간격만 줄이면 글리프가 겹치므로 크기도 같은 비율로 줄인다.
    if avail is not None and slots and slots * advance + 4 > avail:
        # 축소 하한은 **비율이 아니라 최종 크기**로 정한다. 0.55로 고정했더니
        # 고해상도에서도 맞춰지지 않아 교체를 통째로 건너뛰었다(실측: 오선
        # 16px 악보에서 8단 중 4단). 임시표는 8px쯤이면 읽히므로, 그 크기에
        # 해당하는 비율까지는 줄여도 된다 — 저해상도에서는 자연히 하한이 높다.
        min_scale = min(1.0, 8.0 / max(1.0, sp * 2.2))
        scale = max(min_scale, (avail - 4) / float(slots * advance))
        advance = max(3, int(advance * scale))

    # 줄이고 밀어도 자리가 없으면 **건너뛴다.** 억지로 그리면 임시표가 박자표
    # 위에 겹쳐 찍혀 읽을 수 없게 된다(실측: 오선 5.5px에서 그렇게 됐다).
    # 조표를 원본 그대로 두는 편이 낫고, 호출자가 그 사실을 알린다.
    if avail is not None and slots and slots * advance + 4 > avail:
        return {"erased": None, "startX": start_x, "endX": start_x,
                "skipped": "자리 부족"}
    if dry_run:
        return {"erased": None, "startX": start_x, "endX": start_x}

    erase_w = max(region.w if region else 0, slots * advance) + 4
    if avail is not None:
        erase_w = min(erase_w, max(0, avail))
    top = max(0, st.top - int(sp * 1.6))
    bot = st.bottom + int(sp * 1.2)

    ex0 = start_x - 2
    ex1 = ex0 + erase_w
    d.rectangle([ex0, top, ex1, bot], fill=paper)

    # 오선은 **그 행의 대표 색으로 다시 칠한다.**
    #  · 순검정으로 그리면 주변의 얇은 회색 선과 어긋난 검은 막대가 된다
    #    (실측: 오선 7px 악보에서 조표 자리에만 두꺼운 검은 띠).
    #  · 원본 화소를 그대로 되돌리면 그 자리에 있던 **옛 임시표 조각**이
    #    함께 돌아와 선이 점선처럼 끊긴다(실측).
    # 오선은 가로로 균일하므로, 그 행 전체의 중앙값이 곧 선의 색이다.
    repaint_staff_lines(img, st, ex0, ex1, original)
    d = ImageDraw.Draw(img)
    erased = {"x": ex0, "y": top, "w": erase_w, "h": bot - top}

    end_x = draw(d, st, target_fifths, start_x, paper, advance, scale)
    return {"erased": erased, "startX": start_x, "endX": end_x}


def geometry_for(content: np.ndarray, staves, source_fifths: int) -> list[dict]:
    """
    브라우저가 조표를 다시 그리는 데 필요한 **단별 좌표**.

    렌더러(render.py)와 같은 검출·합의 규칙을 쓴다 — 한 악보의 머리 배치는
    모든 단이 같으므로, 어느 단에서 검출이 실패하면 다른 단의 합의값으로
    메운다. 그래야 9단 중 1단의 실패가 악보 전체를 막지 않는다.
    """
    found = []
    for st in staves:
        reg = locate(content, st, source_fifths)
        blk = next_block(content, st, reg,
                         st.left + int(st.spacing * 4.5)) if reg else None
        found.append((st, reg, blk))

    xs = [r.x for _s, r, _b in found if r]
    ws = [r.w for _s, r, _b in found if r]
    nx = [b[0] for _s, _r, b in found if b]
    med = lambda v: sorted(v)[len(v) // 2]
    # **여러 단이 동의할 때만 합의값을 쓴다.** 한 단만 검출되면 그 하나가
    # 틀렸을 때 악보 전체가 같이 틀린다 — 실측: 9단 중 1단이 엉뚱한 자리
    # (오선 끝 +9.3칸, 조표는 보통 2~4칸)를 잡아 9단 전부에 새 조표를
    # 잘못 그렸고, 옛 조표는 남아 ♯이 3개처럼 보였다.
    # 여기서 None 을 주면 브라우저는 조표를 건드리지 않는다.
    MIN_AGREE = 3
    hint = (med(xs), med(ws), med(nx)) \
        if len(xs) >= MIN_AGREE and len(nx) >= MIN_AGREE else None
    if source_fifths != 0 and hint is None and len(xs) < MIN_AGREE:
        found = [(st, None, None) for st, _r, _b in found]

    out = []
    for st, reg, blk in found:
        if reg is None and hint:
            reg = KeySigRegion(x=hint[0], y=st.top, w=hint[1],
                               h=st.bottom - st.top, fifths=source_fifths)
        if blk is None and hint:
            blk = (hint[2], hint[2], hint[2], False)
        out.append({
            "keysigRegion": (None if reg is None else
                             {"x": int(reg.x), "y": int(reg.y),
                              "w": int(reg.w), "h": int(reg.h)}),
            "nextBlock": (None if blk is None else
                          {"x0": int(blk[0]), "x1": int(blk[1]),
                           "next": int(blk[2]), "pushable": bool(blk[3])}),
        })
    return out
