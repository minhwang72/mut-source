#!/usr/bin/env python3
"""
악보 영상처리 공용 모듈.

detect_chords.py(검출)와 render.py(렌더)가 같은 기하 정보를 봐야 하므로
오선 검출·이진화·연결요소는 여기 한 곳에만 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


# ---------------------------------------------------------------- 이진화

def otsu_threshold(img: Image.Image) -> int:
    """
    전역 Otsu 임계값. 브라우저에 넘겨줘야 하므로 값 자체를 꺼낼 수 있게 분리했다.
    브라우저는 이 숫자 하나로 getImageData 결과를 잉크/종이로 가를 수 있다 —
    Otsu를 JS로 다시 구현할 필요가 없다.
    """
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = np.where(denom > 0, (mu_t * omega - mu) ** 2 / denom, 0.0)
    return int(np.argmax(sigma_b))


def binarize_otsu(img: Image.Image) -> np.ndarray:
    """전역 Otsu. 조명이 고른 스캔·웹 이미지에 적합하다."""
    gray = np.asarray(img.convert("L"), dtype=np.uint8)
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = np.where(denom > 0, (mu_t * omega - mu) ** 2 / denom, 0.0)
    return gray <= int(np.argmax(sigma_b))


def _box_mean(a: np.ndarray, r: int) -> np.ndarray:
    """반지름 r 박스 평균. 적분영상으로 O(1)/화소 (scipy 없이)."""
    h, w = a.shape
    pad = np.pad(a.astype(np.float64), r + 1, mode="edge")
    ii = pad.cumsum(0).cumsum(1)
    y0, y1 = 0, 2 * r + 1
    x0, x1 = 0, 2 * r + 1
    total = (ii[y1 : y1 + h, x1 : x1 + w] - ii[y0 : y0 + h, x1 : x1 + w]
             - ii[y1 : y1 + h, x0 : x0 + w] + ii[y0 : y0 + h, x0 : x0 + w])
    return total / float((2 * r + 1) ** 2)


def binarize_sauvola(img: Image.Image, radius: int | None = None,
                     k: float = 0.30, R: float = 128.0) -> np.ndarray:
    """
    Sauvola 적응형 이진화. 핸드폰 사진용.

    왜 국소 '평균'만으로는 안 되는가: 평탄한 영역에서 평균보다 어두운 화소는
    정의상 절반이다. 노이즈가 있는 종이 바탕에 `gray < mean * 0.9`를 걸면
    잡음이 대량 통과한다(실측: 반지름을 15~75px로 바꿔도 잉크 비율 30~38%.
    정상은 3~12%).

    Sauvola는 국소 표준편차를 함께 본다:
        T = m * (1 + k * (s/R - 1))
    평탄한 바탕(s≈0)에서는 T ≈ m*(1-k)로 크게 낮아져 잡음이 걸러지고,
    잉크 경계(s가 큼)에서는 T가 m에 가까워져 글자가 살아난다.
    """
    gray = np.asarray(img.convert("L"), dtype=np.float64)
    if radius is None:
        radius = max(8, min(gray.shape) // 60)
    m = _box_mean(gray, radius)
    # 분산 = E[x²] - E[x]²  (음수는 수치오차이므로 0으로 자른다)
    var = np.maximum(_box_mean(gray * gray, radius) - m * m, 0.0)
    s = np.sqrt(var)
    return gray < m * (1.0 + k * (s / R - 1.0))


def binarize_adaptive(img: Image.Image, radius: int | None = None,
                      k: float = 0.30) -> np.ndarray:
    """적응형 이진화 (Sauvola)."""
    return binarize_sauvola(img, radius=radius, k=k)


def binarize_fixed(img: Image.Image, threshold: int) -> np.ndarray:
    """고정 문턱 이진화. Otsu·Sauvola 가 연한 오선을 날릴 때 쓰는 구제용."""
    return np.asarray(img.convert("L")) < threshold


def binarize(img: Image.Image) -> np.ndarray:
    """
    잉크를 True로. 전역 Otsu를 먼저 쓰고, 결과가 비상식적으로 검으면
    (조명 불균일 사진) 적응형으로 자동 전환한다.

    악보 한 장의 잉크 비율은 보통 3~12%다. 20%를 넘으면 배경을 잉크로
    잡은 것이므로 전역 임계값이 실패한 신호다.
    """
    otsu = binarize_otsu(img)
    if otsu.mean() <= 0.20:
        return otsu
    return binarize_adaptive(img)


# ---------------------------------------------------------------- 오선

@dataclass
class Staff:
    index: int
    top: int
    bottom: int
    """5개 오선의 중심 y좌표 (위→아래)"""
    lines: list[int]
    """각 오선의 (시작y, 끝y) — 두께 정보"""
    spans: list[tuple[int, int]]
    left: int
    right: int

    @property
    def spacing(self) -> float:
        """인접한 오선 사이 간격. 온음계 1단 = 이 값의 절반"""
        if len(self.lines) < 2:
            return 0.0
        gaps = [self.lines[i + 1] - self.lines[i] for i in range(len(self.lines) - 1)]
        return float(np.median(gaps))

    @property
    def thickness(self) -> int:
        return max(1, max(b - a + 1 for a, b in self.spans))


def keep_long_runs(mask: np.ndarray, min_len: int) -> np.ndarray:
    """
    행별로 min_len 이상 이어지는 가로 런만 남긴다.

    오선은 페이지 폭을 가로지르는 긴 런이고, 종이 질감·음표·가사·모아레는
    모두 짧은 런이다. 사진에서 오선을 찾을 때 이 필터가 결정적이다
    (실측: 잉크 29% → 긴런만 남기면 5%).
    """
    out = np.zeros_like(mask)
    h = mask.shape[0]
    for y in range(h):
        row = mask[y]
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts = np.nonzero(d == 1)[0]
        ends = np.nonzero(d == -1)[0]
        for a, b in zip(starts, ends):
            if b - a >= min_len:
                out[y, a:b] = True
    return out


def estimate_skew(ink: np.ndarray, limit: float = 3.0, step: float = 0.25) -> float:
    """
    투영 프로파일로 기울기(도)를 추정한다.

    오선이 수평일 때 행별 잉크량의 분산이 최대가 된다. 사진은 1° 정도만
    기울어도 폭 2400px에서 31px이 밀려 오선 신호가 완전히 깨진다
    (오선 간격보다 큰 드리프트).
    """
    img = Image.fromarray(np.where(ink, 255, 0).astype(np.uint8))

    def score(m: np.ndarray) -> float:
        r = m.sum(axis=1).astype(np.float64)
        return float(((r - r.mean()) ** 2).mean())

    best_deg, best = 0.0, score(ink)
    d = -limit
    while d <= limit + 1e-9:
        if abs(d) > 1e-9:
            rot = np.asarray(img.rotate(d, resample=Image.BILINEAR, fillcolor=0)) > 128
            s = score(rot)
            if s > best:
                best_deg, best = float(d), s
        d += step
    return best_deg


def merge_close(centers: list[int], min_gap: float) -> list[int]:
    """min_gap보다 가까운 선들을 하나로 합친다 (잔여 기울기로 번진 선)."""
    if not centers:
        return []
    groups: list[list[int]] = [[centers[0]]]
    for c in centers[1:]:
        if c - groups[-1][-1] < min_gap:
            groups[-1].append(c)
        else:
            groups.append([c])
    return [int(round(sum(g) / len(g))) for g in groups]


def find_staves(ink: np.ndarray, min_fill: float = 0.5) -> list[Staff]:
    """가로로 길게 이어진 행 = 오선. 4줄 이상 묶이면 한 단으로 본다."""
    h, w = ink.shape
    is_line = (ink.sum(axis=1) / w) >= min_fill

    runs: list[tuple[int, int]] = []
    y = 0
    while y < h:
        if is_line[y]:
            y0 = y
            while y < h and is_line[y]:
                y += 1
            runs.append((y0, y - 1))
        else:
            y += 1
    if not runs:
        return []

    centers = [(a + b) // 2 for a, b in runs]
    gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
    if not gaps:
        return []
    spacing = float(np.median(gaps))

    groups: list[list[int]] = [[0]]
    for i in range(1, len(centers)):
        if centers[i] - centers[groups[-1][-1]] > spacing * 2.0:
            groups.append([i])
        else:
            groups[-1].append(i)

    staves: list[Staff] = []
    for idx, g in enumerate([grp for grp in groups if len(grp) >= 4]):
        lines = [centers[i] for i in g]
        spans = [runs[i] for i in g]
        lines, spans = _complete_lines(lines, spans, ink)
        top, bottom = lines[0], lines[-1]
        band = ink[top : bottom + 1]
        cols = np.where(band.any(axis=0))[0]
        left, right = (int(cols[0]), int(cols[-1])) if cols.size else (0, w - 1)
        staves.append(Staff(idx, top, bottom, lines, spans, left, right))
    return staves


def _complete_lines(lines: list[int], spans: list, ink: np.ndarray):
    """
    **4줄만 잡힌 단에 빠진 오선 하나를 채운다.**

    흐리거나 글자에 덮인 오선 한 줄은 행 채움 50% 를 못 넘는다(실측 105장 중
    25장, 단 50여 개). 음높이는 맨 윗줄에서 세므로 윗줄이 빠지면 단 전체가
    두 음 밀리고, 가운데 줄이 빠져도 오선 지우기·높이 대조가 그 단을 건너뛴다.
      · 간격 하나가 두 배면 그 사이 — 가운데 줄이 빠졌다
      · 간격이 고르면 위·아래 한 칸 자리 중 잉크가 더 긴 쪽(15% 이상일 때만)
    """
    if len(lines) != 4:
        return lines, spans
    gaps = [b - a for a, b in zip(lines, lines[1:])]
    unit = min(gaps)
    wide = [i for i, gp in enumerate(gaps) if gp > unit * 1.6]
    if len(wide) == 1:
        i = wide[0]
        y = (lines[i] + lines[i + 1]) // 2
        return lines[:i + 1] + [y] + lines[i + 1:], spans[:i + 1] + [(y, y)] + spans[i + 1:]
    if wide:
        return lines, spans
    sp = sum(gaps) / 3.0
    h = ink.shape[0]

    def fill(y: float) -> float:
        y0, y1 = max(0, int(round(y)) - 1), min(h, int(round(y)) + 2)
        return float(ink[y0:y1].mean(axis=1).max()) if y1 > y0 else 0.0
    up, dn = lines[0] - sp, lines[-1] + sp
    fu, fd = fill(up), fill(dn)
    if max(fu, fd) < 0.15 or abs(fu - fd) < 0.05:
        return lines, spans
    if fu > fd:
        y = int(round(up))
        return [y] + lines, [(y, y)] + spans
    y = int(round(dn))
    return lines + [y], spans + [(y, y)]


def median_spacing(staves: list[Staff]) -> float:
    vals = [s.spacing for s in staves if s.spacing > 0]
    return float(np.median(vals)) if vals else 0.0


def find_staves_photo(
    ink: np.ndarray, run_frac: float = 0.08, min_fill: float = 0.20
) -> list[Staff]:
    """
    사진용 오선 검출.

    스캔용 `find_staves`는 "행의 50% 이상이 잉크"를 오선으로 본다. 사진에서는
    원근 왜곡 때문에 한 물리적 오선이 여러 행에 번져 그 조건을 못 넘는다
    (실측: 임계값 0.5에서 19개, 0.2에서 47개 — 정답은 45개).

    그래서 두 가지를 바꾼다:
      ① 긴 가로 런만 남겨 오선을 분리한다 (질감·모아레·음표는 짧은 런)
      ② 채움 임계값을 크게 낮추고, 번져서 갈라진 선을 다시 합친다
    """
    h, w = ink.shape
    lr = keep_long_runs(ink, max(8, int(w * run_frac)))
    fill = lr.sum(axis=1) / w
    rows = np.nonzero(fill >= min_fill)[0]
    if rows.size == 0:
        return []

    # 인접 행 묶기
    groups: list[list[int]] = [[int(rows[0])]]
    for y in rows[1:]:
        if int(y) - groups[-1][-1] <= 2:
            groups[-1].append(int(y))
        else:
            groups.append([int(y)])
    spans = {int(round(sum(g) / len(g))): (g[0], g[-1]) for g in groups}
    centers = sorted(spans)

    gaps = [b - a for a, b in zip(centers, centers[1:]) if 8 <= b - a <= 80]
    if not gaps:
        return []
    sp = float(np.median(gaps))

    merged = merge_close(centers, sp * 0.6)

    # 5줄씩 한 단으로
    blocks: list[list[int]] = [[merged[0]]]
    for c in merged[1:]:
        if c - blocks[-1][-1] > sp * 2.0:
            blocks.append([c])
        else:
            blocks[-1].append(c)

    def span_for(c: int) -> tuple[int, int]:
        # 병합된 중심에 가장 가까운 원본 span
        key = min(spans, key=lambda k: abs(k - c))
        return spans[key]

    out: list[Staff] = []
    for g in blocks:
        if len(g) != 5:
            continue  # 사진 위·아래 끝에 걸린 다른 페이지 조각을 버린다
        sp_list = [span_for(c) for c in g]
        band = ink[g[0] : g[-1] + 1]
        cols = np.where(band.any(axis=0))[0]
        left, right = (int(cols[0]), int(cols[-1])) if cols.size else (0, w - 1)
        out.append(Staff(len(out), g[0], g[-1], g, sp_list, left, right))
    return out


def sharpness(gray: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> float:
    """세로 방향 밝기 변화량 — 초점·흔들림 지표. 값이 작으면 흐리다."""
    band = gray[max(0, y0) : y1, max(0, x0) : x1].astype(np.float64)
    if band.size < 2:
        return 0.0
    return float(np.abs(np.diff(band, axis=0)).mean())


# ---------------------------------------------------------------- 연결 요소

@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def merged(self, o: "Box") -> "Box":
        x = min(self.x, o.x)
        y = min(self.y, o.y)
        return Box(x, y, max(self.right, o.right) - x, max(self.bottom, o.bottom) - y)


def components(mask: np.ndarray) -> list[Box]:
    """4-이웃 연결 요소. 반복적 flood fill (재귀 없음)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out: list[Box] = []
    ys, xs = np.nonzero(mask)
    for sy, sx in zip(ys, xs):
        if seen[sy, sx]:
            continue
        stack = [(int(sy), int(sx))]
        seen[sy, sx] = True
        x0 = x1 = int(sx)
        y0 = y1 = int(sy)
        while stack:
            cy, cx = stack.pop()
            x0 = min(x0, cx)
            x1 = max(x1, cx)
            y0 = min(y0, cy)
            y1 = max(y1, cy)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append(Box(x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    return out


def merge_horizontal(boxes: list[Box], max_gap: int,
                     stack_gap: int = 0) -> list[Box]:
    """
    가로로 가까운 덩어리를 하나로. 'Ebmaj7'의 E/b/maj/7 을 합치는 용도.

    **세로로 겹치는 것끼리만** 합친다. 가로 간격만 보면 밴드 위쪽 조각과
    아래쪽 조각이 사슬처럼 이어져 전부 한 덩어리가 된다(실측: 3배 확대한
    악보에서 13조각이 1682x84 상자 하나로 합쳐져 코드가 0개가 됐다).
    같은 글자열이면 세로 위치가 겹친다.

    `stack_gap` 을 주면 **위첨자**도 합친다. 위첨자(Gm⁷의 7, F²의 2)는
    본체 **위에 얹혀** 세로 겹침이 0이라 위 규칙에서 떨어져 나가고, 혼자서는
    최소 높이에 못 미쳐 버려진다 — 실측: 'Gm7' 상자가 h16 이 아니라 h10 으로
    잡혀 7이 잘렸고 LLM 이 'Gm' 으로 읽었다(F2 → F 도 같은 원인).
    사슬 병합을 막으려고 **가로로 실제 겹칠 것**을 요구한다. 간격만 보면
    옆 코드의 위첨자까지 이어진다.
    """
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b.x)
    out: list[Box] = []
    for b in boxes:
        placed = False
        for i, o in enumerate(out):
            if b.x - o.right > max_gap:
                continue
            # 세로 겹침이 둘 중 작은 높이의 50% 이상이어야 같은 글자열이다
            ov = min(o.bottom, b.bottom) - max(o.y, b.y)
            if ov >= 0.5 * min(o.h, b.h):
                out[i] = o.merged(b)
                placed = True
                break
            if stack_gap and _stacked(o, b, stack_gap):
                out[i] = o.merged(b)
                placed = True
                break
        if not placed:
            out.append(b)
    return out


def _stacked(a: Box, b: Box, stack_gap: int) -> bool:
    """
    b 가 a 의 위/아래 첨자인가.

    두 배치를 다 받는다(실측 좌표, 오선간격 6px 악보):
      · 바로 위에 얹힌 것 — Gm⁷ 의 7 (x169 y68 h8, 본체 x153 y74 h10)
      · 오른쪽 위로 비낀 것 — F² 의 2 (x204 y67 h9, 본체 x195 y72 h12).
        세로 겹침 4px 로 50% 기준(4.5px)을 **0.5px 차이로** 못 넘고
        가로로도 안 겹친다. 그래서 2가 버려지고 'F' 로 읽혔다.

    사슬 병합(옆 코드까지 이어붙는 것)은 두 가지로 막는다: 호출 쪽의
    max_gap(가로 거리)과, 여기의 **크기비** — 옆 코드의 본체 글자는
    이 코드 본체와 높이가 비슷해서 첨자로 안 쳐준다.
    """
    small, big = (b, a) if b.h <= a.h else (a, b)
    if small.h > big.h * 0.85:          # 비슷한 크기면 첨자가 아니다
        return False
    xov = min(a.right, b.right) - max(a.x, b.x)
    if xov >= 0.5 * small.w:
        # 가로로 겹치면 바로 위/아래에 붙어 있을 때만
        return (abs(big.y - small.bottom) <= stack_gap
                or abs(small.y - big.bottom) <= stack_gap)
    # 가로로 안 겹치면 **오른쪽 위 위첨자**만 인정한다.
    # 본체보다 위에서 시작해 위에서 끝나야 하고, **세로로도 붙어 있어야** 한다.
    # 거리 제한이 없으면 위 줄 손글씨 가사가 아래 빔에 붙어 코드 아닌 상자가
    # 생긴다(실측 마커스 단5: "적내" + 빔이 41x26 상자로 잡혀 없는 코드가
    # 하나 더 읽혔다).
    return (small.y < big.y and small.bottom < big.bottom
            and small.bottom >= big.y - stack_gap)


# ---------------------------------------------------------------- 오선 제거

def remove_staff_lines(
    ink: np.ndarray, staves: list[Staff], protect_noteheads: bool = True,
    tol_margin: float = 0.25,
) -> np.ndarray:
    """
    오선만 지우고 음표·기둥·빔은 남긴 '내용 레이어'를 만든다.

    판별 기준: 어떤 열에서 오선 행을 지나는 잉크의 세로 연속 길이가
    선 두께 수준이면 그건 순수한 오선이다. 음표머리나 기둥이 지나가면
    그 연속 길이가 훨씬 길어지므로 남긴다.
    """
    content = ink.copy()
    h, w = ink.shape

    for st in staves:
        # tol_margin이 클수록 더 많이 지운다. 0.25는 오선을 확실히 없애지만
        # 속 빈 음표의 테두리(세로 런 2~3px)까지 삼킨다 — 홀수 단 이조에서
        # 2분·온음표가 부서지는 원인이었다. 그 경로는 더 좁게 부른다.
        tol = st.thickness + max(1, int(round(st.spacing * tol_margin)))
        # 음표머리 보호 반경. 속 빈 음표(2분·온음표)의 좌우 벽은 세로로 길어
        # '두꺼운 열'로 잡히고, 가운데 얇은 위아래 호(弧)는 오선과 구별되지
        # 않는다. 두꺼운 열 주변을 보호 구간으로 넓혀 호를 살린다.
        # 이 처리가 없으면 2분음표가 기둥만 남고 사라진다.
        # protect_noteheads=False로 부르면 음표는 상하지만 구조가 깨끗하게
        # 분리된다. 음자리표·조표·마디선 **위치를 찾는 용도**에는 그쪽이 낫다.
        protect_r = max(1, int(round(st.spacing * 0.6))) if protect_noteheads else 0

        for (a, b) in st.spans:
            mid = (a + b) // 2
            cols = np.nonzero(ink[mid])[0]
            if cols.size == 0:
                continue

            runs = np.zeros(w, dtype=np.int32)
            tops = np.zeros(w, dtype=np.int32)
            bots = np.zeros(w, dtype=np.int32)
            for x in cols:
                top = mid
                while top - 1 >= 0 and ink[top - 1, x]:
                    top -= 1
                bot = mid
                while bot + 1 < h and ink[bot + 1, x]:
                    bot += 1
                runs[x] = bot - top + 1
                tops[x] = top
                bots[x] = bot

            protect = np.zeros(w, dtype=bool)
            if protect_r > 0:
                for x in np.nonzero(runs > tol)[0]:
                    protect[max(0, x - protect_r) : min(w, x + protect_r + 1)] = True

            for x in cols:
                if runs[x] <= tol and not protect[x]:
                    content[tops[x] : bots[x] + 1, x] = False
    return content


def draw_staff_lines(ink: np.ndarray, staves: list[Staff]) -> None:
    """제거했던 오선을 원래 두께·범위로 다시 그린다 (제자리 수정)."""
    for st in staves:
        for (a, b) in st.spans:
            ink[a : b + 1, st.left : st.right + 1] = True



def expand_line_spans_gray(gray: np.ndarray, st: Staff, x0: int, x1: int,
                           margin: float = 6.0) -> list[tuple[int, int]]:
    """
    오선 줄의 범위를 **회색조로** 잰다 — 잉크 문턱(<128) 아래의 회색 헤일로까지.

    JPEG로 축소된 악보는 줄 주변에 값 200~250의 회색띠가 남는다. 이진 기준으로
    범위를 잡으면 이 띠가 남아 내용과 함께 옮겨져, 칸 가운데에 회색 줄무늬가
    생긴다(실측: 칸 배경이 250 → 175~220으로 어두워졌다).
    """
    h = gray.shape[0]
    x1 = min(x1, gray.shape[1])
    if x1 <= x0:
        return [(int(a), int(b)) for (a, b) in st.spans]
    # 행 **평균**을 쓰면 안 된다. 음표가 있는 행도 평균이 내려가서 오선 전체가
    # 한 덩어리로 확장됐다(실측: 5줄이 (71,127) 하나로 합쳐졌다).
    # 줄은 폭의 대부분이 어둡고, 음표 행은 일부만 어둡다 — 60분위수로 가른다.
    band = gray[:, x0:x1]
    rows = np.percentile(band, 60, axis=1)
    lo = max(0, st.top - (st.bottom - st.top))
    hi = min(h, st.bottom + (st.bottom - st.top))
    paper = float(np.percentile(rows[lo:hi], 90))
    LIMIT = 1                      # 헤일로는 대개 1px. 넓게 잡으면 음표가 얇아진다
    out = []
    for (a, b) in st.spans:
        a2, b2 = int(a), int(b)
        while a2 - 1 >= 0 and a - a2 < LIMIT and rows[a2 - 1] < paper - margin:
            a2 -= 1
        while b2 + 1 < h and b2 - b < LIMIT and rows[b2 + 1] < paper - margin:
            b2 += 1
        out.append((a2, b2))
    return out


def expand_line_spans(ink: np.ndarray, st: Staff, x0: int, x1: int,
                      frac: float = 0.35) -> list[tuple[int, int]]:
    """
    오선 줄의 **실제 두께**를 이미지에서 잰다.

    find_staves가 주는 span은 이진화 후의 심(core)이라 실제보다 얇다. JPEG로
    축소된 악보는 줄 위아래에 회색 띠가 남아서, span만 믿고 그 바깥을
    샘플링하면 여전히 줄 잉크를 집는다 — 그러면 인페인팅이 줄을 지우지 못하고
    옮겨진 줄이 음표 사이에 남는다(실측: 실제 악보에서 음표 구간에 가로줄이
    여러 개 생겼다).

    판별자: 줄은 오선 폭의 frac 이상을 채운다. 그 조건이 유지되는 동안 넓힌다.
    """
    h = ink.shape[0]
    x1 = min(x1, ink.shape[1])
    if x1 <= x0:
        return [(int(a), int(b)) for (a, b) in st.spans]
    out = []
    for (a, b) in st.spans:
        a2, b2 = int(a), int(b)
        while a2 - 1 >= 0 and float(ink[a2 - 1, x0:x1].mean()) >= frac:
            a2 -= 1
        while b2 + 1 < h and float(ink[b2 + 1, x0:x1].mean()) >= frac:
            b2 += 1
        out.append((a2, b2))
    return out


def _row_window_min(row: np.ndarray, r: int) -> np.ndarray:
    """행 안에서 좌우 r칸까지 중 **가장 어두운 값**. (창 최소값 필터)"""
    if r <= 0:
        return row
    out = row.copy()
    for d in range(1, r + 1):
        out[:-d] = np.minimum(out[:-d], row[d:])
        out[d:] = np.minimum(out[d:], row[:-d])
    return out


def inpaint_staff_rows(block: np.ndarray, spans, halo: int = 1,
                       reach: int = 2, sp_hint: float | None = None
                       ) -> np.ndarray:
    """
    오선 줄만 지운다. 판별자는 **그 열의 세로 런 길이**다.

    순수한 오선은 줄 두께만큼만 이어진다. 음표 머리·기둥·빔이 지나가는 열은
    그보다 두껍다. 그래서 "줄 두께 + 1 이하인 런"만 지운다.

    예전 시도들이 실패한 이유를 기록해 둔다:
      · 허용치를 두께+0.25칸으로 잡았더니 저해상도에서 2px 빔이 3~4px로 걸려
        같이 지워졌다(실측: 머리 잉크 59%, 빔이 조각남).
      · 위·아래 이웃으로 메우는 방식은, 한쪽만 보면 머리가 줄 두께만큼
        번져 음표대 잉크가 176%까지 부풀고(실측), 양쪽을 요구하면 줄을
        지나는 머리가 깎였다(실측: 머리 86%).
    세로 런 길이는 이 둘을 모두 피한다 — 빔은 얇아도 줄과 합쳐지면 두꺼워지고,
    순수한 줄은 어떤 해상도에서도 딱 줄 두께다.
    """
    lum = block.mean(axis=2) if block.ndim == 3 else block.astype(float)
    ink = lum < 128
    h, w = ink.shape

    # 각 화소의 세로 런 길이 = 위로 이어진 수 + 아래로 이어진 수 - 1
    up = np.zeros((h, w), dtype=np.int32)
    dn = np.zeros((h, w), dtype=np.int32)
    prev = np.zeros(w, dtype=np.int32)
    for y in range(h):
        prev = np.where(ink[y], prev + 1, 0)
        up[y] = prev
    prev[:] = 0
    for y in range(h - 1, -1, -1):
        prev = np.where(ink[y], prev + 1, 0)
        dn[y] = prev
    run = up + dn - 1

    out = block.copy()
    for item in spans:
        if len(item) == 3:
            a, b, core = item
        else:
            a, b = item
            core = b - a + 1
        # 두께 판정은 **줄 심(core)** 기준이다. 확장된 범위로 잡으면 허용치가
        # 커져서 기둥·빔 같은 얇은 구조까지 지워진다.
        tol = core + 1
        ai = max(0, a - 1)
        bi = min(h - 1, b + 1)
        # 메우는 값은 위·아래 중 **더 밝은 쪽** — 종이색을 그대로 쓴다
        fill = np.maximum(block[ai], block[bi])
        # **가늘어지는 좌우 끝을 지키기 위해 keep 을 가로로 넓힌다.**
        # 음표 머리는 타원이라 좌우 끝에서 세로 두께가 줄어든다. 열 단위로만
        # 판정하면 그 끝이 "얇으니 줄이다"로 걸려 파여, 원본에서 줄 위에 있던
        # 머리에 구멍이 남는다. 이동해서 빈칸에 오면 그 구멍이 그대로 보인다
        # (실측: 머리 115개 중 36개가 잉크 절반 이하로 떨어졌고, 그중 92%가
        #  이동 후 빈칸에 놓인 것이었다).
        grow = max(1, int(round(sp_hint * 0.22))) if sp_hint else 2
        for y in range(a, b + 1):
            # **두꺼운 잉크만 남긴다.** 얇은 잉크(줄 심)와 잉크가 아닌 회색
            # 헤일로는 모두 메운다 — 헤일로를 남기면 칸 가운데로 옮겨져
            # 회색 줄무늬가 된다(실측: 배경 250 → 175).
            thick = ink[y] & (run[y] > tol)
            wide = thick.copy()
            for k in range(1, grow + 1):
                wide[k:] |= thick[:-k]
                wide[:-k] |= thick[k:]
            keep = ink[y] & wide
            if block.ndim == 3:
                keep = keep[:, None]
            out[y] = np.where(keep, block[y], fill)
    return out


def staff_line_ink(arr: np.ndarray, regions: list[dict],
                   paper: int = 255) -> np.ndarray:
    """
    **오선 줄 잉크만** 남기고 나머지를 종이색으로 지운 그림을 만든다.

    쓰임: 이조 뒤 오선을 되돌릴 때 쓴다. 예전에는 원본 전체와 어두운 쪽을
    택했는데(np.minimum), 그러면 **원본 음표 머리가 줄 위에 유령으로 되살아
    난다.** 원본에서 G4 줄에 앉아 있던 머리는 그 줄 행에서도 검으므로,
    음표를 다 옮긴 뒤에도 그 조각이 그대로 남았다(실측: 이조본에서 줄마다
    옛 머리 조각이 가로 막대처럼 보였다).

    판별자는 inpaint_staff_rows 와 같다 — **세로 런이 줄 두께 이하**면 순수한
    오선. 머리·기둥·빔이 지나가는 열은 그보다 두꺼우므로 남지 않는다.

    regions: [{"x0","x1","spans":[(a, b, core), ...]}, ...]
    """
    lum = arr.mean(axis=2) if arr.ndim == 3 else arr.astype(float)
    ink = lum < 128
    h, w = ink.shape

    up = np.zeros((h, w), dtype=np.int32)
    dn = np.zeros((h, w), dtype=np.int32)
    prev = np.zeros(w, dtype=np.int32)
    for y in range(h):
        prev = np.where(ink[y], prev + 1, 0)
        up[y] = prev
    prev[:] = 0
    for y in range(h - 1, -1, -1):
        prev = np.where(ink[y], prev + 1, 0)
        dn[y] = prev
    run = up + dn - 1

    out = np.full_like(arr, paper)
    covered = np.zeros((h, w), dtype=bool)
    for reg in regions:
        x0 = max(0, int(reg["x0"]))
        x1 = min(w, int(reg["x1"]))
        if x1 <= x0:
            continue
        for (a, b, core) in reg["spans"]:
            tol = core + 1
            a = max(0, int(a))
            b = min(h - 1, int(b))
            for y in range(a, b + 1):
                thin = ink[y, x0:x1] & (run[y, x0:x1] <= tol)
                # 잉크이면서 두꺼운 자리 = 원본에서 음표·기둥·빔·마디선이
                # 줄을 덮고 있던 곳. 그 줄 조각은 되돌릴 수 없으므로
                # 호출자가 줄 색으로 이어 그려야 한다.
                covered[y, x0:x1] = ink[y, x0:x1] & ~thin
                keep = thin[:, None] if arr.ndim == 3 else thin
                out[y, x0:x1] = np.where(keep, arr[y, x0:x1], out[y, x0:x1])
    return out, covered


def half_step_grid(mids: np.ndarray, ext: int) -> np.ndarray:
    """
    오선 줄과 칸 중앙을 번갈아 놓은 **반칸 격자**. 온음계 1단 = 격자 1칸.

    짝수 단(3·5·7도)은 줄→줄, 홀수 단(2·4·6도)은 줄→칸 중앙으로 간다.
    같은 격자로 두 경우를 한 번에 처리한다.
    """
    knots = []
    for i in range(len(mids) - 1):
        knots.append(mids[i])
        knots.append((mids[i] + mids[i + 1]) / 2.0)
    knots.append(mids[-1])
    g = np.array(knots, dtype=float)
    up_step = g[1] - g[0]
    dn_step = g[-1] - g[-2]
    above = [g[0] - up_step * i for i in range(ext, 0, -1)]
    below = [g[-1] + dn_step * i for i in range(1, ext + 1)]
    return np.concatenate([above, g, below]), ext


def shift_notes_raster(
    arr: np.ndarray, st: Staff, dy: int, head_end: int,
    spacing: float | None = None, paper: int = 255,
    draw_lines: bool = True, fixed: list[dict] | None = None,
    original: np.ndarray | None = None, win_top: int | None = None,
    win_bot: int | None = None, blank_mask: np.ndarray | None = None,
) -> dict:
    """
    음표를 dy만큼 세로 이동한다. **오선을 제거하지 않는다.**

    착상: 이동량이 오선 간격의 정수배이면(= 온음계 짝수 단: 3도·5도·7도)
    함께 옮겨진 오선이 다른 오선 자리에 정확히 내려앉는다. 그러면
      · 끝쪽에 남는 '군더더기 선' k줄만 지우고
      · 반대쪽에 빠진 선 k줄만 그리면 된다.

    음표를 한 번도 건드리지 않으므로 **해상도와 무관하다.** 저해상도 웹
    이미지에서 오선 제거가 속 빈 음표를 파괴하던 문제를 우회한다.

    한계: 온음계 홀수 단(2도·4도·6도)은 이동량이 간격의 반이라 옮겨진 선이
    칸 가운데에 내려앉는다. 그 경우는 오선 제거가 필요하다.

    arr는 그레이스케일 또는 RGB 배열이며 제자리 수정된다.
    head_end 왼쪽(음자리표·조표·박자표)은 움직이지 않는다.
    """
    sp = spacing if spacing else st.spacing
    if sp <= 0 or dy == 0:
        return {"shifted": False, "reason": "이동량 0"}

    mids = np.array([(a + b) / 2.0 for (a, b) in st.spans], dtype=float)
    if mids.size < 2:
        return {"shifted": False, "reason": "오선 줄이 부족합니다"}

    # 온음계 몇 단인지 = 반칸 격자로 몇 칸인지. 이동량은 반칸의 정수배여야 한다.
    half = sp / 2.0
    mh = int(round(dy / half))
    if mh == 0 or abs(dy - mh * half) > 1.0:
        return {"shifted": False,
                "reason": f"이동량 {dy}px가 반칸({half:.1f}px)의 정수배가 아닙니다"}
    k = abs(mh) / 2.0
    if k > len(st.spans) - 1:
        return {"shifted": False,
                "reason": f"이동량이 오선 높이를 넘습니다 ({k:.1f}칸)"}

    h = arr.shape[0]
    x_hi = min(st.right + 1, arr.shape[1])

    # 이동 창: 오선 위아래로 음표·빔·기둥·(올려놓은)코드가 뻗는 범위.
    # 창 상단은 **그 단의 코드 상자 바로 위**까지다. 오선에서 6칸을 그냥
    # 올라가면 첫 단에서 제목·작곡자 줄까지 창에 들어와 함께 밀린다
    # (실측: 'Russell Frager'가 3px 밀려 뭉개졌다).
    default_top = st.top - int(sp * 6.0)
    win_top = max(0, default_top if win_top is None else max(win_top, default_top))
    # 창 아래끝은 **가사 잉크에 닿지 않게** 제한할 수 있다. 넘어가면 가사가
    # 함께 밀려 복사본이 남고, 그걸 지우려고 가사 띠를 넓게 되돌리면 그 자리로
    # 내려온 음표가 지워진다(실측: 머리 115개 중 36개가 잉크 절반 이하).
    # 창을 가사 위에서 끊으면 두 문제가 동시에 사라진다.
    default_bot = st.bottom + int(sp * 4.0)
    win_bot = min(h, default_bot if win_bot is None
                  else min(int(win_bot), default_bot))

    # ── ① 오선 줄을 1행 인페인팅으로 지운다 ────────────────────────
    # 오선을 지우지 않고 통째로 밀면, 옮겨진 줄이 실제 줄 자리에서 어긋나거나
    # (간격 불균일) 칸 가운데에 내려앉는다(홀수 단). 예전에는 그 줄을 "세로로
    # 얇은 런"으로 찾아 지웠는데 빔·머리도 얇아서 같이 지워졌다.
    # 이웃 행으로 메우면 오선만 사라지고 음표는 남는다 — 해상도에 강하다.
    # 줄의 실제 두께를 재서 그 바깥을 샘플링한다 (expand_line_spans 주석 참고)
    gray_full = arr.mean(axis=2) if arr.ndim == 3 else arr.astype(float)
    wide = expand_line_spans_gray(gray_full, st, st.left, x_hi)
    line_spans = [(w[0], w[1], (c[1] - c[0] + 1))
                  for w, c in zip(wide, st.spans)]
    halo = 1
    reach = int(min(3, max(1, round(sp * 0.25))))
    block = inpaint_staff_rows(arr[:, head_end:].copy(), line_spans,
                               halo, reach, sp_hint=sp)

    # 마디선·쉼표는 **이동 대상에서 뺀다.** 함께 옮기면 밀려간 복사본이
    # 유령으로 남고, 그것을 지우려고 복원 범위를 이동량만큼 넓히면 그 자리에
    # 온 음표까지 덮인다(실측: 아래로 이조할 때 마디선 옆 음표에 조각이 남았다).
    # 원본에서 지워 두면 유령이 생기지 않고, 원본 자리 복원만 하면 된다.
    # **가사처럼 상자로 못 잡는 것은 마스크로 지운다.** 마디선·쉼표는
    # 사각형이지만 가사는 글자마다 흩어져 있어, 상자로 지우면 그 사이로
    # 내려온 음표까지 지운다. 원본에서 가사 잉크만 지워 두면 밀려간
    # 복사본이 생기지 않고, 되돌릴 때도 잉크만 덧칠하면 된다.
    if blank_mask is not None:
        mm = blank_mask[:, head_end:]
        if mm.shape == block.shape[:2]:
            if block.ndim == 3:
                block[mm] = paper
            else:
                block[mm] = paper

    for o in (fixed or []):
        fy0 = max(0, o["y"] - 1)
        fy1 = min(h, o["y"] + o["h"] + 1)
        fx0 = max(0, o["x"] - 1 - head_end)
        fx1 = min(block.shape[1], o["x"] + o["w"] + 1 - head_end)
        if fx1 > fx0 and fy1 > fy0:
            block[fy0:fy1, fx0:fx1] = paper

    # ── ② 균일 정수 이동 ─────────────────────────────────────────
    # 구간별 보간으로 옮기면 오선 간격이 불균일한 만큼 행이 복제·생략되어
    # 빔이 두꺼워지고 머리가 뭉개진다(실측: 오선 6.5px 악보에서 빔이 겹친
    # 막대처럼 보였다). 구간별 매핑이 필요했던 이유는 "옮겨진 오선이 실제 선
    # 자리에 앉게" 하려던 것인데, 이제 오선은 인페인팅으로 지우고 원본에서
    # 되돌리므로 맞출 대상이 없다. 그래서 **행을 그대로 dy만큼 옮긴다** —
    # 복제가 없어 선명하다. 오선 간격 편차(6.5 vs 7)로 생기는 음높이 오차는
    # 0.5px 수준으로 보이지 않는다.
    rows = np.arange(win_top, win_bot)
    src_rows = rows - dy
    ok = (src_rows >= 0) & (src_rows < h)

    arr[win_top:win_bot, head_end:] = paper
    arr[rows[ok], head_end:] = block[src_rows[ok]]

    removed = 0

    # 고정 객체 복원은 **코드 오버레이 뒤에** 해야 한다.
    # 코드 지우기 사각형이 이동량만큼 아래로 확장되어 오선 안까지 들어오고,
    # 그 자리에 마디선 윗부분이 있으면 잘려 나간다(실측: 마디선 일치율 75~86%).
    # 그래서 여기서는 하지 않고, 필요한 좌표만 호출자에게 넘긴다.
    n_fixed = 0

    # 오선 재작성은 호출자가 **코드 오버레이 뒤에** 하도록 미룰 수 있다.
    # 코드를 지우는 사각형이 오선 맨 위 줄을 뚫기 때문에, 순서가 뒤바뀌면
    # 오선에 구멍이 난다(실측: 맨 위 줄에서 잉크 118px 소실).
    if draw_lines:
        for (a, b) in st.spans:
            arr[a : b + 1, head_end:x_hi] = 0

    return {
        "shifted": True,
        "fixed": n_fixed,
        "lineSpans": [(int(t[0]), int(t[1])) for t in line_spans],
        "xRange": (int(head_end), int(x_hi)),
        "dy": dy,
        "lines": k,
        "halfSteps": mh,
        "strayPixels": removed,
        "window": (win_top, win_bot),
    }


def find_staves_best(img) -> tuple[np.ndarray, list]:
    """
    이진화를 **둘 다 시도해** 오선을 더 많이 찾는 쪽을 쓴다. (ink, staves) 반환.

    Otsu는 전역 문턱이라 인쇄가 옅거나 스캔 밝기가 고르지 않은 악보에서
    오선 줄 몇 개를 놓친다. 실제 사용자 악보(800x1054, 오선 6px)에서 Otsu는
    9단 중 8단만 찾았고, 놓친 단은 코드·멜로디·조표가 전부 그대로 남아
    "일부만 바뀐 악보"가 나왔다. Sauvola(국소 문턱)는 9단을 다 찾았다.

    prepare.analyze 는 이미 이렇게 하고 있었는데 렌더러는 그러지 않아서,
    판독 단계와 렌더 단계가 서로 다른 오선을 보고 있었다.
    """
    best = None
    for fn in (binarize, binarize_sauvola):
        try:
            ink = fn(img)
        except Exception:
            continue
        st = find_staves(ink)
        if best is None or len(st) > len(best[1]):
            best = (ink, st)
    return best if best else (binarize(img), [])


# 가사 띠 높이의 **안전망** (오선 간격 배수). 실제 범위는 아래 덩어리 선택이
# 정하므로 여기서 조일 이유가 없다 — 3절까지 적힌 악보가 있다(실측
# wish0830-7: 세 줄이 8.3칸). 폭주만 막는다.
MAX_LYRIC_BAND = 9.0
# 글자 한 줄로 볼 최소 덩어리 높이 / 같은 가사로 이어 붙일 최대 빈틈 (칸)
LYRIC_LINE_MIN = 1.0
LYRIC_JOIN_GAP = 0.8
# 글자 줄로 볼 최소 가로 폭 (오선 폭 대비). 구역 표시 상자는 이보다 좁다.
LYRIC_WIDE = 0.30
# 구역 표시가 놓이는 오선 왼쪽 여백 (오선 간격 배수). 가사는 이 뒤에서 시작한다.
MARK_MARGIN = 5.0
# 이음줄 오탐 판정: 조각이 이만큼 이하이면서 폭 중앙값이 이보다 넓으면 글자가 아니다.
SLUR_MAX_PARTS = 8
SLUR_MIN_WIDTH = 2.5
# 글자 줄로 볼 최소 띠 높이 (오선 간격 배수).
LYRIC_MIN_HEIGHT = 1.4


def _part_widths(ink, ys, y0, y1):
    # 띠 안 잉크 덩어리들의 (폭, 높이). 가로 런으로 센다.
    rows = ink[max(0, y0):max(0, y1), :]
    if rows.size == 0:
        return []
    cols = rows.any(axis=0)
    out = []
    start = None
    for i, v in enumerate(cols):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((i - start, y1 - y0))
            start = None
    if start is not None:
        out.append((len(cols) - start, y1 - y0))
    return out


def find_lyric_band(ink: np.ndarray, st: Staff, spacing: float,
                    next_top: int | None) -> tuple[int, int] | None:
    """
    오선 아래 가사 띠를 찾는다.

    판별자: **오선에 연결되지 않은 덩어리**가 가사다. 음표·기둥·빔은 오선에
    붙어 있어 덩어리가 오선까지 이어진다. 가사는 아래에 따로 떠 있다.

    처음엔 "가로 런이 5개 이상인 행"으로 했는데 실패했다 — 저해상도에서
    음표머리가 늘어선 행도 그 조건을 만족해서, 가사 띠가 음표 영역을 덮었다
    (실측: 가사 일치율이 100%에서 87%로 떨어져 오탐이 드러났다).

    왜 필요한가: 음표 이동 창이 기둥을 덮으려면 오선 아래로 넉넉히 내려가야
    하는데, 그러면 가사까지 밀린다. 가사를 고정 대상으로 잡아야 한다.
    """
    h = ink.shape[0]
    # 두 단 사이의 중간 지점에서 끊는다. 아래쪽 절반은 **다음 단의 코드 밴드**
    # 이므로 포함하면 코드가 가사로 잡혀 검증이 망가진다
    # (실측: 가사 일치율이 77%까지 떨어졌다).
    # 띠 높이 상한(MAX_LYRIC_BAND)은 아래에서 **고른 띠에** 건다 — 그 띠의
    # 픽셀이 결과 악보에 그대로 붙으므로 남의 단 음표가 딸려 오면 안 된다.
    # **절대 상한은 창이 아니라 고른 띠에 건다.** 창을 미리 자르면 가사
    # 덩어리가 창 끝에 닿아 버려서, 아래의 "창 끝에 닿으면 다음 단 것" 규칙이
    # **진짜 가사를 버린다**(실측 now0918-1 단1: 6.8칸 가사가 통째로 날아가고
    # 1.3칸 잔재가 뽑혔다). 창은 다음 단까지의 0.75 만 본다.
    if next_top:
        limit = min(h, st.bottom + int((next_top - st.bottom) * 0.75))
    else:
        limit = min(h, st.bottom + int(round(spacing * 5)))
    if limit <= st.bottom + 2:
        return None

    # 오선 위쪽부터 잘라 연결성을 보존한다 — 기둥이 오선에 붙어 있는지 봐야 한다
    top = st.top
    band = ink[top:limit, :]
    below = st.bottom - top          # 이보다 아래에서만 시작하는 덩어리 = 가사
    # **구역 표시(A·B·C 상자)는 오선 왼쪽 끝에 있다.** 가사는 음자리표
    # 뒤에서 시작하므로 그 앞은 볼 필요가 없다. 안 빼면 표시 상자가
    # 가사 줄과 세로로 겹쳐 한 덩어리가 되고, 음절 분할이 통째로
    # 깨진다(실측 「지금 여기 우리」 단5: 음절 23개 → 2개, 그 단
    # 가사가 결과에서 통째로 사라졌다).
    x_from = st.left + spacing * MARK_MARGIN
    ys = []
    for b in components(band):
        if b.y <= below:             # 오선까지 이어짐 → 음표·기둥·마디선
            continue
        if b.w < 2 or b.h < 2:
            continue
        if b.x + b.w / 2.0 < x_from:
            continue
        ys.append((b.y + top, b.y + b.h + top))
    if not ys:
        return None
    # **빈 줄에서 끊는다.** 전에는 "두 단 사이의 0.55 지점까지" 였는데,
    # 그러면 **1·2절 두 줄 가사의 아래 줄이 반쯤 잘린다**(실측 now0918-1:
    # 2절 글자 아래가 날아갔다). 줄 사이 틈은 좁고 다음 단 코드 줄과의 틈은
    # 넓다 — 그 차이로 가른다.
    #
    # 조각(연결성분) 사슬로 하면 한글 자모가 쪼개져서 한 줄 안에서도 끊긴다
    # (실측: 117px 띠가 27px 로 잘렸다). **행 단위 잉크**로 봐야 안정적이다.
    # **가사 덩어리만 고른다.**
    #
    # 남은 조각들이 덮는 행으로 프로파일을 만들고 덩어리로 쪼갠다. 실측
    # (now0918-1, 오선 간격 배수):
    #   단1  [0.5, 1.3, **6.8**, 0.1]  빈틈 [0.1, 1.0, 2.6]   ← 6.8 이 1·2절
    #   단2  [0.5, **3.0**, **3.1**, 0.2]  빈틈 [1.9, 0.7, 2.5] ← 3.0+3.1 이 1·2절
    #   단3  [0.5, **5.4**, 1.9]  빈틈 [1.8, 0.9]              ← 1.9 는 다음 단
    # **빈틈 길이만으로는 못 가른다** — 단2 의 줄 사이(0.7)와 단3 의 다음 단
    # 경계(0.9)가 거의 같다. 세 가지를 함께 본다:
    #   ① 창 끝에 닿는 마지막 덩어리는 잘린 것이다 = 다음 단 것
    #   ② 가장 두꺼운 덩어리가 가사 본체다
    #   ③ 거기에 **가까이 붙은(≤0.8칸) 또 다른 글자 줄(≥1.0칸)** 만 이어 붙인다
    lo0 = int(st.bottom) + 1
    rows = np.zeros(max(1, limit - lo0), dtype=bool)
    for a, b in ys:
        rows[max(0, a - lo0):max(0, b - lo0)] = True
    # **구역 표시(A·B·C 상자)를 가사로 착각하지 않는다.** 가사 줄은 오선 폭의
    # 상당 부분을 채우지만 표시 상자는 왼쪽에 좁게 있다. 붙여 버리면 띠가
    # 커지고 음절 분할이 통째로 깨진다(실측 「지금 여기 우리」 단5:
    # 띠 6.1칸인데 음절 2개 — 그 단 가사가 결과에서 사라졌다).
    wide_need = max(1, int((st.right - st.left) * LYRIC_WIDE))
    blocks = []
    start = None
    for y, v in enumerate(rows):
        if v and start is None:
            start = y
        elif not v and start is not None:
            blocks.append((start, y))
            start = None
    if start is not None:
        blocks.append((start, len(rows)))
    if not blocks:
        return None
    if len(blocks) > 1 and blocks[-1][1] >= len(rows) - 1:
        blocks.pop()                       # ① 창 끝에 닿음 → 다음 단
    k = max(range(len(blocks)), key=lambda i: blocks[i][1] - blocks[i][0])
    a, b = blocks[k]                       # ②
    line = spacing * LYRIC_LINE_MIN
    near = spacing * LYRIC_JOIN_GAP
    def wide(blk):
        # 가로로 넓은가 = 글자 줄인가 (구역 표시 상자는 좁다)
        return int(ink[lo0 + blk[0]:lo0 + blk[1], :].any(axis=0).sum()) >= wide_need

    i = k                                  # ③ 위로
    while i > 0 and (a - blocks[i-1][1]) <= near \
            and (blocks[i-1][1] - blocks[i-1][0]) >= line and wide(blocks[i-1]):
        i -= 1
        a = blocks[i][0]
    j = k                                  #    아래로
    while j + 1 < len(blocks) and (blocks[j+1][0] - b) <= near \
            and (blocks[j+1][1] - blocks[j+1][0]) >= line and wide(blocks[j+1]):
        j += 1
        b = blocks[j][1]
    b = min(b, a + int(round(spacing * MAX_LYRIC_BAND)))
    # **가사가 없는 단도 있다.** 오선 아래로 늘어진 **이음줄**이 조각으로
    # 남아 띠가 잡히면, 그 픽셀이 결과 악보에 붙어 음표 위에 얹힌다
    # (실측 camp0814b-07 단5: 가사 0인데 '음절' 50개가 잡혔다).
    # 글자와 이음줄은 **조각의 폭과 개수**로 갈린다 — 실측 405개 띠:
    #   글자   폭중앙 1.33칸(p90 1.94) · 조각 12~78개
    #   이음줄 폭중앙 2.9~3.7칸 · 조각 4~5개
    # 글꼴이 큰 악보는 폭이 3칸을 넘기도 하므로 **둘 다** 봐야 한다.
    # 글자 줄은 최소 높이가 있다 — 실측 379개 띠의 최소가 1.44칸, p5 가
    # 1.78칸이다. 이보다 얇으면 이음줄을 가로로 스친 것이다
    # (실측 camp0814b-07 단5: 0.56칸짜리 띠가 '음절' 50개를 냈다).
    if (b - a) < spacing * LYRIC_MIN_HEIGHT:
        return None
    inside = [t for t in ys if t[0] >= lo0 + a and t[1] <= lo0 + b + 2]
    if len(inside) <= SLUR_MAX_PARTS:
        widths = sorted(w for w, _ in _part_widths(ink, ys, lo0 + a, lo0 + b))
        if widths and widths[len(widths) // 2] > spacing * SLUR_MIN_WIDTH:
            return None
    return (lo0 + a, min(limit, lo0 + b))


def shift_notes_halfstep(
    arr: np.ndarray, ink: np.ndarray, staves: list[Staff], dy: int,
    head_ends: list[int], fixed_all: list, original: np.ndarray,
    spacing: float, lyric_bands: dict | None = None,
) -> dict:
    """
    온음계 **홀수** 단(2·4·6도) 이조 — 오선을 제거하고 음표만 옮긴다.

    짝수 단은 옮겨진 오선이 다른 오선 자리에 내려앉아 래스터를 통째로 옮길 수
    있었다(shift_notes_raster). 홀수 단은 이동량이 오선 간격의 **반**이라
    옮겨진 오선이 칸 가운데에 내려앉는다 — 그래서 오선을 빼고 음표만 옮겨야 한다.

    순서: ① 창을 종이색으로 비움 ② 오선 제거된 내용을 dy만큼 옮겨 찍음
          ③ 오선을 원본 화소로 복원 ④ 마디선·쉼표를 원본 자리에 복원

    ③④는 원본 화소를 그대로 쓰므로 굵기·색이 원본과 같다.
    마디선과 쉼표는 음높이가 없으니 **옮기지 않는다.**
    """
    # 허용치를 좁게 잡는다. 넉넉하면 속 빈 음표의 테두리까지 지워져
    # 2분·온음표가 부서진다(실측: 이동량이 -8px 기대인데 -5.6px로 측정됐다).
    content = remove_staff_lines(ink, staves, protect_noteheads=False,
                                 tol_margin=0.05)
    h, w = ink.shape

    # 고정 객체 화소는 옮기지 않는다 — 원본 자리에 그대로 복원할 것이다
    frozen = np.zeros_like(ink)
    for _st, _he, objs in fixed_all:
        for o in objs:
            y0 = max(0, o["y"] - 1)
            y1 = min(h, o["y"] + o["h"] + 1)
            x0 = max(0, o["x"] - 1)
            x1 = min(w, o["x"] + o["w"] + 1)
            frozen[y0:y1, x0:x1] = True
    movable = content & ~frozen

    done = 0
    for (st, he, objs) in fixed_all:
        x0 = min(he, w - 1)
        x1 = min(st.right + 1, w)
        if x1 <= x0:
            continue
        # 창 상단은 넉넉히 잡는다. 위로 크게 이조하면 높은 음의 기둥·덧줄이
        # 창 밖으로 나가 잘린다(실측: 3단 위 이조에서 음표 적중률 93%).
        # 코드는 어차피 다시 그리므로 코드 밴드와 겹쳐도 문제없다.
        top = max(0, st.top - int(round(spacing * 6.0)))
        # 하단은 기둥을 덮을 만큼 내려간다. 가사는 아래에서 원본으로
        # 되돌리므로 겹쳐도 된다 — 좁게 잡으면 기둥이 잘려 조각이 남는다.
        bot = min(h, st.bottom + int(round(spacing * 4.0)))
        if bot - top <= abs(dy):
            continue

        # ① 종이색으로 비운다. 스캔본은 순백이 아니므로 창 안의 밝은 화소에서
        #    행마다 종이색을 샘플링한다.
        win = original[top:bot, x0:x1]
        flat = win.reshape(-1, win.shape[-1]) if win.ndim == 3 else win.reshape(-1, 1)
        lum = flat.astype(np.int32).sum(axis=1)
        paper = np.median(flat[lum >= np.percentile(lum, 75)], axis=0)
        arr[top:bot, x0:x1] = paper.astype(arr.dtype)

        # ② 내용을 dy만큼 옮겨 찍는다 (원본 잉크 색을 그대로 가져온다)
        for y in range(top, bot):
            sy = y - dy
            if not (0 <= sy < h):
                continue
            cols = np.nonzero(movable[sy, x0:x1])[0]
            if cols.size:
                arr[y, x0 + cols] = original[sy, x0 + cols]
        done += 1

    # ③ 가사 복원 — 가사는 이조와 무관하다
    for (st, _he, _objs) in fixed_all:
        band = lyric_bands.get(st.index) if lyric_bands else None
        if band:
            arr[band[0]:band[1], :] = original[band[0]:band[1], :]

    # ④ 오선 복원 — 더 어두운 쪽을 택한다 (덮어쓰면 그 줄로 옮겨온 음표
    #    머리의 가운데가 얇은 선으로 바뀌어 잘린다. render.py 주석 참고)
    for (st, _he, _objs) in fixed_all:
        lx0, lx1 = st.left, min(st.right + 1, w)
        for (a, b) in st.spans:
            arr[a:b + 1, lx0:lx1] = np.minimum(
                arr[a:b + 1, lx0:lx1], original[a:b + 1, lx0:lx1])

    # ⑤ 마디선·쉼표 복원 — 원본 자리, 이동 없음
    n_fixed = 0
    for (_st, _he, objs) in fixed_all:
        for o in objs:
            y0 = max(0, o["y"] - 1)
            y1 = min(h, o["y"] + o["h"] + 1)
            x0 = max(0, o["x"] - 1)
            x1 = min(w, o["x"] + o["w"] + 1)
            if x1 > x0 and y1 > y0:
                arr[y0:y1, x0:x1] = original[y0:y1, x0:x1]
                n_fixed += 1

    return {"shifted": done > 0, "dy": dy, "staves": done, "fixed": n_fixed}


def find_fixed_objects(content: np.ndarray, st: Staff, spacing: float) -> list[dict]:
    """
    이조해도 **움직여서는 안 되는** 것들을 찾는다: 마디선과 쉼표.

    마디선은 오선에 정렬돼 있고, 쉼표는 음높이가 없어 위치가 관습으로 고정된다.
    래스터 이동은 창 전체를 옮기므로 이것들도 따라 내려간다 — 그래서 원본
    화소로 되돌려야 한다.

    판별자는 실측으로 정했다(오선 간격 6.5px 악보, 오선 높이 27px):

    | 종류        | w/간격    | h/간격   | 채움  |
    |------------|----------|---------|------|
    | 마디선      | 0.31     | 4.15    | 1.00 |
    | 온·2분쉼표  | 2.31     | 1.23    | 1.00 |
    | 4·8분쉼표   | 1.69     | 2.31    | 0.52 |
    | 음표+기둥   | 2.2~4.9  | 4.0~5.4 | 0.25~0.5 |

    핵심은 **높이**다. 쉼표는 오선 간격의 2.9배 이하, 음표는 기둥 때문에 4배
    이상이다. 속 빈 온음표(h/간격 ≈ 0.9)는 온쉼표와 높이가 겹치지만
    **채움률**이 다르다 — 쉼표는 꽉 찬 블록(1.0), 음표는 가운데가 비어 0.5다.
    """
    sp = spacing
    if sp <= 0:
        return []
    staff_h = st.bottom - st.top + 1
    top = max(0, st.top - int(sp * 2))
    bot = min(content.shape[0], st.bottom + int(sp * 2))
    band = content[top:bot, :]

    out: list[dict] = []
    for b in components(band):
        if b.w < 2 or b.h < 2:
            continue
        # 쉼표와 마디선은 **오선 안**에 있다. 코드 심볼은 오선 위에 뜬다.
        # 밴드가 오선 위 2칸까지 걸치므로 코드 글자가 섞여 들어오는데
        # (실측: 'D7+5'의 D와 'Fm7'의 F가 4·8분쉼표 규격과 일치해 오분류됐다),
        # **덩어리의 세로 중심이 오선 안인지**로 깔끔하게 갈린다.
        center = b.y + top + b.h / 2.0
        if not (st.top <= center <= st.bottom):
            continue
        sub = band[b.y : b.y + b.h, b.x : b.x + b.w]
        fill = float(sub.mean())
        wr = b.w / sp
        hr = b.h / sp
        kind = None

        if b.h >= staff_h * 0.85 and b.w <= max(2, sp * 0.65) and fill >= 0.7:
            kind = "barline"
        elif fill >= 0.85 and 1.3 <= wr <= 3.2 and 0.5 <= hr <= 1.8:
            kind = "rest"          # 온·2분쉼표 (꽉 찬 블록)
        elif 1.8 <= hr <= 2.9 and 0.8 <= wr <= 2.4:
            kind = "rest"          # 4·8분쉼표

        # 저해상도에서는 위 규격만으로 부족하다. 오선 간격 7px에서 2분음표의
        # 머리+기둥이 h/간격 2.86, w/간격 1.14로 4분쉼표 규격에 정확히 걸렸다
        # (실측: 그 음표만 이동에서 빠져 머리 잉크가 21%로 나왔다).
        #
        # 구조로 가른다: **행별 폭의 중앙값 / 최대값.**
        #   · 쉼표·마디선 → 전체가 고르게 넓다 (실측 0.62~1.00)
        #   · 음표 머리+기둥 → 머리만 넓고 대부분은 얇은 기둥 (실측 0.29)
        if kind == "rest":
            widths = sub.sum(axis=1)
            widths = widths[widths > 0]
            if widths.size and float(np.median(widths) / widths.max()) < 0.45:
                kind = None

        if kind:
            out.append({"kind": kind, "x": int(b.x), "y": int(b.y + top),
                        "w": int(b.w), "h": int(b.h)})

    # ── 열 기반 마디선 보강 ────────────────────────────────────────
    # 덩어리 기반 검출은 마디선이 빔이나 음표에 닿으면 한 덩어리가 되어 규격을
    # 벗어나 놓친다. 저해상도에서 특히 심했다(단당 4개 중 1개만 잡혔고, 놓친
    # 마디선은 음표와 함께 밀려 내려갔다).
    # 열 단위로 보면 닿아 있어도 잡힌다: **오선 맨 위·맨 아래에 걸쳐 있고
    # 그 사이가 이어진 열**이 마디선이다.
    cols = []
    y_lo = max(0, st.top - 1)
    y_hi = min(content.shape[0], st.bottom + 2)
    need = int((y_hi - y_lo) * 0.92)
    for x in range(max(0, st.left), min(st.right + 1, content.shape[1])):
        col = content[y_lo:y_hi, x]
        if int(col.sum()) < need:
            continue
        if not (col[:3].any() and col[-3:].any()):
            continue
        cols.append(x)
    runs = []
    for x in cols:
        if runs and x == runs[-1][1] + 1:
            runs[-1][1] = x
        else:
            runs.append([x, x])
    for (x0, x1) in runs:
        if (x1 - x0 + 1) > max(3, sp * 0.7):
            continue                      # 너무 넓다 — 마디선이 아니다
        if any(o["kind"] == "barline" and o["x"] - 2 <= x0 <= o["x"] + o["w"] + 2
               for o in out):
            continue                      # 이미 잡힌 것
        out.append({"kind": "barline", "x": int(x0), "y": int(y_lo),
                    "w": int(x1 - x0 + 1), "h": int(y_hi - y_lo)})
    return out


def find_barlines(content: np.ndarray, st: Staff) -> list[Box]:
    """
    마디선: 오선 높이를 거의 다 채우는 세로로 긴 얇은 덩어리.
    음표를 이동할 때 마디선은 **따라 움직이면 안 된다** — 오선에 정렬돼 있다.
    """
    band = content[st.top : st.bottom + 1, :]
    staff_h = st.bottom - st.top + 1
    out = []
    for b in components(band):
        if b.h >= staff_h * 0.8 and b.w <= max(2, int(round(st.spacing * 0.6))):
            out.append(Box(b.x, b.y + st.top, b.w, b.h))
    return out
