"""개수 불일치는 **박자가 동의할 때만** 경고한다.

개수가 다르다는 것만으로는 누가 틀렸는지 모른다. 검출이 읽은 대로 마디
합이 전부 맞으면 그 읽기는 자체적으로 일관되고, 틀린 쪽은 LLM 개수다.
실측 25장 108단: 합이 정확한데 개수만 다른 경우가 101개(93%)였다.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "detstruct.py")).read()

# 경고를 다는 조건에 beats_ok 가 들어 있어야 한다 — 빠지면 93% 가 헛경고다
i = src.index("기존 개수 판독 {expected}개와 검출 {got_n}개 불일치")
cond = src[max(0, i - 400):i]
assert "not beats_ok" in cond, "박자 동의 조건이 빠졌다"
assert "has_chord" in cond, "화음 단 제외가 빠졌다"

# 합을 재는 쪽이 화음 구성음을 빼는가 — 안 빼면 화음 악보가 전부 걸린다
j = src.index("beats_ok = True")
blk = src[j:i]
assert 'n.get("chord")' in blk, "합을 셀 때 화음 구성음을 안 뺐다"
assert "1.5 if n.get(\"dotted\")" in blk, "점음표를 1.5배로 안 셌다"

print("ok — 박자가 동의할 때만 개수 불일치를 경고한다")
