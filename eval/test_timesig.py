"""
판독한 박자표를 마디 합이 정면으로 반박하면 버리는가.

왜 버려야 하나: 실측 camp0814c-09 는 악보에 **4/4** 라 찍혀 있는데 판독이
2/4 로 읽었고, 그대로 쓰면 깨진 마디가 2개에서 **18개**가 됐다.
왜 함부로 버리면 안 되나: wish0830-8 은 판독이 **6/8** 로 맞았는데 마디 합
만으로는 6/8 과 3/4 를 절대 못 가른다 — 합이 같다. 합으로 뒤집으면 4/4 로
그려진다(깨진 마디는 0이라 지표가 그걸 못 본다).
그래서 **크게 틀렸을 때만** 뒤집는다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import detstruct as DS


def page(sums, beats_unit="quarter"):
    """마디 합이 sums 인 한 단을 만든다 (4분음표 개수로)."""
    return [[{"items": [{"duration": "quarter", "dotted": False}] * int(v)}
             for v in sums]]


# ── 마디가 전부 4박인데 판독이 2/4 라고 하면 → 버린다
four = page([4, 4, 4, 4, 4, 4, 4, 4])
assert DS._broken(four, 2.0) == 8, DS._broken(four, 2.0)
assert DS._broken(four, 4.0) == 0

# ── 합이 애매하면(둘 다 비슷하게 깨지면) 판독을 지킨다
mixed = page([3, 4, 3, 4])
assert DS._broken(mixed, 4.0) == 2
assert DS._broken(mixed, 3.0) == 2
# 2 >= 2*2 가 아니므로 뒤집지 않는다 — 조건을 그대로 확인
assert not (DS._broken(mixed, 4.0) >= DS._broken(mixed, 3.0) * 2
            and DS._broken(mixed, 4.0) - DS._broken(mixed, 3.0) >= 4)

# ── 차이가 작으면(3개 이하) 뒤집지 않는다 — 우연한 쏠림을 막는다
few = page([4, 4, 4, 2, 2])
assert not (DS._broken(few, 4.0) >= DS._broken(few, 2.0) * 2
            and DS._broken(few, 4.0) - DS._broken(few, 2.0) >= 4), \
    "차이가 작은데 뒤집는다"

# ── 빈 마디는 세지 않는다 (합 0 은 판단 근거가 못 된다)
assert DS._broken([[{"items": []}]], 4.0) == 0

print("ok")

# ── 6/8 인가 3/4 인가 — 빔 묶음이 가른다 ──────────────────────────
# 마디 합은 둘 다 3.0박이라 영영 못 가른다. 6/8 은 8분음표를 3개씩,
# 3/4 는 2개씩 묶는다. 실측: 105장 중 박자표를 못 읽은 4장이 전부 6/8 이었고
# (눈으로 확인), 이 규칙이 4/4 맞혔다.
def beamed(sizes):
    """묶음 크기 목록대로 한 마디를 만든다."""
    items, g = [], 0
    for n in sizes:
        items += [{"duration": "eighth", "dotted": False, "beamGroup": g}] * n
        g += 1
    return [[{"items": items}]]

assert DS._three_or_six(beamed([3, 3, 3, 3])) == "6/8"
assert DS._three_or_six(beamed([3, 3, 3])) == "6/8"
assert DS._three_or_six(beamed([2, 2, 2])) == ""          # 3/4 — 기존 동작
assert DS._three_or_six(beamed([2, 2, 2, 2])) == ""
# 섞여 있으면 많은 쪽 (3개짜리가 우세하면 6/8)
assert DS._three_or_six(beamed([3, 3, 3, 2])) == "6/8"
# **근거가 약하면 건드리지 않는다** — 묶음 3개 미만이면 기존 동작 유지
assert DS._three_or_six(beamed([3, 3])) == ""
assert DS._three_or_six(beamed([3])) == ""
# 빔 묶음이 없는 음표는 안 센다
assert DS._three_or_six([[{"items": [{"duration": "eighth", "dotted": False}] * 6}]]) == ""

print("6/8 판정 ok")
