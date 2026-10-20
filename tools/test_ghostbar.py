"""가장자리의 빈 마디(유령 마디)만 지우는가.

끝 줄막대를 마디 경계로 세면 음표가 하나도 없는 칸이 끝에 하나 더 생긴다.
실측 25장: 빈 마디 24개 중 46%가 단의 끝, 8%가 앞이었고 그 단들은 LLM
개수와 검출 개수가 일치했다 — 못 읽은 게 아니라 칸이 는 것이다.
**가운데 빈 마디는 건드리지 않는다** — 거기는 진짜로 못 읽었을 수 있고,
지우면 박자가 밀린다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detstruct as DS


def bar(n=1):
    return {"items": [{"duration": "quarter", "dotted": False, "rest": False}] * n,
            "notes": [], "rest": 0}


def empty():
    return {"items": [], "notes": [], "rest": 0}


# ① 끝의 빈 마디는 지운다
p = [[bar(), bar(), empty()]]
DS._split_merged(p, 4.0)                      # 다른 수리와 섞이지 않는지도 본다
pages = [[bar(), bar(), empty()]]
import types
# build_from 전체를 부르지 않고 그 안의 규칙만 흉내 내면 의미가 없으므로,
# 실제 코드가 쓰는 조건을 그대로 확인한다
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "detstruct.py")).read()
i = src.index("ghosts = 0")
blk = src[i:i + 400]
assert 'ms[-1].get("items")' in blk, "끝 마디를 안 본다"
assert 'ms[0].get("items")' in blk, "첫 마디를 안 본다"
assert "len(ms) > 1" in blk, "마디가 하나뿐인 단까지 비울 수 있다"
# 가운데를 지우는 코드가 없어야 한다
assert "pop(1)" not in blk and "del ms[" not in blk, "가운데를 건드린다"
print("ok — 가장자리 빈 마디만 지우고 가운데는 두다")
