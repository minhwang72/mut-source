"""
**조표를 자리로 센다.**

검출기는 조표를 못 센다. 실측(day2sb-5 · set0802-1 · wish0809-3):
♯이 0~1개면 맞히지만 3개를 1개로, 4개를 2개로 센다. 더 크게 봐도
나빠지기만 한다(목표 간격 11 이상에서 0개). 붙어 있는 같은 글리프가
학습 분포 밖이다.

그런데 조표는 **아무 데나 찍히지 않는다.** 올림표는 F#·C#·G#·D#·A#·E#·B#
순서로, 내림표는 B♭·E♭·A♭·D♭·G♭·C♭·F♭ 순서로, **오선 위 자리가 정해져
있다.** 그러니 "어딘가에 ♯이 있나"를 묻지 말고 "F# 자리에 있나, 그다음
C# 자리에 있나"를 순서대로 물으면 된다. 붙어 있어도 자리가 다르므로
섞이지 않는다.

자리는 높은음자리표 맨 윗줄(F5)을 0으로 두고 반 칸마다 1씩 아래로 센다.
"""
from __future__ import annotations

import numpy as np

# (이름, 윗줄에서 반 칸 단위 거리). 아래로 갈수록 +
SHARPS = [("F#", 0), ("C#", 3), ("G#", -1), ("D#", 2),
          ("A#", 5), ("E#", 1), ("B#", 4)]
FLATS = [("Bb", 4), ("Eb", 1), ("Ab", 5), ("Db", 2),
         ("Gb", 6), ("Cb", 3), ("Fb", 7)]


def _ink_at(band: np.ndarray, y: float, half: float,
            x_from: int, x_to: int) -> tuple[int, float] | None:
    """
    (x, 잉크량). y 를 가운데 두고 **세로로 긴 창**에서 x_from 이후 처음
    나오는 잉크 기둥.

    **창을 세로로 길게 잡는 것이 핵심이다.** 조표의 ♯·♭ 중 절반은 오선
    줄 위에 앉는데(F#·D#·B♭…), 오선을 지워도 줄 찌꺼기가 남아 그 높이의
    얇은 띠는 구간 전체가 잉크로 보인다(실측 day2sb-5: 123px 구간에서
    76칸이 문턱을 넘었다). 글리프는 두 칸 높이로 뻗고 찌꺼기는 1~2px 이니,
    창을 두 칸으로 잡고 **그 높이의 절반 이상을 채운 기둥**만 받으면
    갈린다.

    조표는 왼쪽부터 차례로 찍히므로 앞 글리프보다 오른쪽에서만 찾는다.
    """
    y0, y1 = int(round(y - half)), int(round(y + half)) + 1
    y0, y1 = max(0, y0), min(band.shape[0], y1)
    if y1 <= y0 or x_to <= x_from:
        return None
    strip = band[y0:y1, x_from:x_to]
    if strip.size == 0:
        return None
    col = strip.sum(axis=0).astype(float)
    need = max(3.0, (y1 - y0) * 0.5)
    hit = np.nonzero(col >= need)[0]
    if hit.size == 0:
        return None
    return int(hit[0]) + x_from, float(col[hit[0]])


def count(strict, staff, spacing: float, x_lo: int, x_hi: int) -> tuple[int, int]:
    """
    조표 구간에서 (♭ 개수, ♯ 개수).

    strict: 오선을 지운 이진 이미지(True = 잉크)
    x_lo:   음자리표 오른쪽 끝
    x_hi:   첫 음표·박자표 왼쪽
    """
    a = np.asarray(strict)
    if a.dtype != bool:
        a = a > 0
    top = float(staff.lines[0]) if getattr(staff, "lines", None) else float(staff.top)
    half = spacing / 2.0
    x_lo, x_hi = int(max(0, x_lo)), int(min(a.shape[1], x_hi))
    # **구간이 글리프 하나도 못 들어갈 만큼 좁으면 조표가 없는 것이다.**
    # 음자리표 바로 뒤에 박자표가 오면 구간이 몇 픽셀뿐인데, 그걸 뒤지면
    # 음자리표 가장자리를 ♯으로 센다(실측 day2conti-2: 6px 구간에서 1개).
    if x_hi - x_lo < spacing * 0.7:
        return (0, 0)

    def walk(order):
        """
        순서대로 자리를 짚어 가며 끊길 때까지 센다.

        **조표 글리프는 서로 붙어 있다.** 이 성질로 끝을 안다 — 다음
        글리프가 한 칸 반보다 멀면 그건 조표가 아니라 그 뒤의 음악이다.
        구간 끝(x_hi)은 첫 음표·박자표로 정하는데, 둘 다 검출되지 않으면
        넉넉히 잡히므로 이 간격 조건이 실질적인 울타리가 된다(실측
        day2sb-5: 울타리 없이 4개를 7개로 셌다).
        """
        n, x = 0, x_lo
        reach = spacing * 2.5                    # 음자리표 뒤 첫 글리프까지
        for _name, step in order:
            y = top + step * half
            got = _ink_at(a, y, spacing * 0.95, x, min(x_hi, x + int(reach)))
            if got is None:
                break
            n += 1
            x = got[0] + max(2, int(spacing * 0.55))
            reach = spacing * 1.5                # 그다음부터는 붙어 있어야 한다
            if x >= x_hi:
                break
        return n

    sh, fl = walk(SHARPS), walk(FLATS)
    # ♯과 ♭은 한 조표에 섞이지 않는다. 더 길게 이어진 쪽을 믿는다.
    if sh >= fl:
        return (0, sh)
    return (fl, 0)
