"""
마디가 말이 안 되게 크면 마디선 기준을 완화해 다시 보는가.

왜: 엄격한 기준(최장런이 오선 밖으로 안 벗어날 것)은 음표가 빽빽한 단에서
마디선을 통째로 잃는다 — 실측 now0918-1 단4 는 단 전체가 **17박 한 마디**가
됐다. 느슨한 기준(오선 구간 채움률)은 기둥까지 받으므로 기본으로 깔면
멀쩡하던 장이 0개에서 5개로 깨진다(105장 실측). 그래서 **박자가 심판**이다:
가장 큰 마디가 정상 박의 1.8배를 넘을 때만 재시도하고, **작아질 때만** 받는다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import detstruct as DS

N = lambda x, d="quarter": {"x": float(x), "w": 8.0, "duration": d, "dotted": False}

# 마디 경계 [0, 100, 200] 에 4분음표 4개씩 → 각 4박
notes = [N(x) for x in (10, 30, 50, 70, 110, 130, 150, 170)]
assert DS._worst_measure([0, 100, 200], notes, []) == 4.0

# 마디선을 놓쳐 하나로 합쳐지면 8박
assert DS._worst_measure([0, 200], notes, []) == 8.0

# 쉼표도 센다
rests = [{"x": 110.0, "w": 8.0, "class": "rest_half"}]
assert DS._worst_measure([100, 200], [], rests) == 2.0

# **판정 문턱**: 4박 기준에서 8박은 재시도 대상, 4박은 아니다
BEATS = 4.0
assert DS._worst_measure([0, 200], notes, []) >= BEATS * 1.8
assert DS._worst_measure([0, 100, 200], notes, []) < BEATS * 1.8

print("ok")
