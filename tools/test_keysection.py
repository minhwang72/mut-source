"""
구간별 원조표를 코드로 검증하는가.

왜: 조표 임시표는 붙어 있어 덜 세인다. 실측 「지금 여기 우리」 C 섹션은
Bb장조(♭2)인데 네 단 모두 ♭1 로 읽혔고, +2 이조 결과 C장조 자리에
♯1개 조표가 그려졌다. 같은 구간 코드는 Bb장조가 명백했다.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guesskey as G

BB = ["Bb", "F/A", "Gm7", "Fm7", "Bb/D", "Eb"]
G_ = ["G/B", "C", "Am7", "D", "Em7"]

# ── 덜 센 조표를 코드가 바로잡는다
out = G.fix_sections_with_chords([1, 1, -1, -1], [G_, G_, BB, BB])
assert out == [1, 1, -2, -2], out

# ── 이미 맞으면 그대로
same = G.fix_sections_with_chords([1, 1, -2, -2], [G_, G_, BB, BB])
assert same == [1, 1, -2, -2], same

# ── 검출이 아주 틀렸으면 **구해내지 않는다.** ±1 만 움직인다 —
#    코드로 12키를 다시 찍으면 코드가 적을 때 엉뚱한 데로 간다.
far = G.fix_sections_with_chords([5, 5], [BB, BB])
assert all(abs(v - 5) <= 1 for v in far), far
assert far != [-2, -2], "±1 을 넘어 움직였다"

# ── 코드가 너무 적으면 건드리지 않는다
few = G.fix_sections_with_chords([-1, -1], [["Bb", "Eb"], []])
assert few == [-1, -1], few

# ── 코드가 없으면 그대로
assert G.fix_sections_with_chords([1, -1], [[], []]) == [1, -1]

print("ok")
