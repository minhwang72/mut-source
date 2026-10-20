"""합쳐진 마디를 나눌 때 **화음 구성음을 박으로 세지 않는가.**

화음 구성음은 기둥 하나를 나눠 쓰므로 박을 차지하지 않는다. 이 함수만
세고 있어서, 화음이 많은 장에서 4박 마디를 8박으로 착각해 두 동강 냈다
(실측 A/B: 깨진 마디 793 -> 825, 나빠진 마디 51개).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detstruct as DS


def note(d, chord=False, rest=False):
    return {"duration": d, "dotted": False, "rest": rest, "chord": chord}


# ① 4분음표 4개 + 화음 구성음 4개 = 4박짜리 한 마디. 나누면 안 된다.
m = {"items": [note("quarter"), note("quarter", chord=True),
               note("quarter"), note("quarter", chord=True),
               note("quarter"), note("quarter", chord=True),
               note("quarter"), note("quarter", chord=True)]}
pages = [[m]]
assert DS._split_merged(pages, 4.0) == 0, "화음을 세어 4박 마디를 쪼갰다"
assert len(pages[0]) == 1

# ② 진짜 8박(줄막대 누락)은 둘로 나눈다
m2 = {"items": [note("quarter") for _ in range(8)]}
pages2 = [[m2]]
assert DS._split_merged(pages2, 4.0) == 1
assert len(pages2[0]) == 2
assert all(len(x["items"]) == 4 for x in pages2[0])

# ③ 화음이 섞인 진짜 8박도 나눈다 — 박을 먹는 음표로만 센다
m3 = {"items": [note("quarter"), note("quarter", chord=True)] * 8}
pages3 = [[m3]]
assert DS._split_merged(pages3, 4.0) == 1, "화음을 뺀 8박을 못 알아봤다"
assert len(pages3[0]) == 2

print("ok — 화음 구성음은 박으로 세지 않는다")
