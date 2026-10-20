"""2성부 악보는 지원하지 않는다 — 검사에서 걸러 크레딧도 안 깎는다."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import local_reader as L

def struct(pairs):
    """pairs: [(화음구성음 여부, ...)] 한 단짜리 구조"""
    return {"systems": [{"index": 0, "notes": [
        {"rest": False, "chord": c} for c in pairs]}]}

# ① 비율 계산 — 쉼표는 세지 않는다
assert L.two_voice_ratio(struct([False]*10)) == 0.0
assert L.two_voice_ratio(struct([True]*5 + [False]*5)) == 0.5
s = struct([True, False])
s["systems"][0]["notes"].append({"rest": True, "chord": False})
assert L.two_voice_ratio(s) == 0.5, "쉼표가 분모에 들어갔다"
assert L.two_voice_ratio({"systems": []}) == 0.0

# ② 실측 경계: 리드시트 최대 33%, 2성부 최소 44% → 0.35 가 가른다
assert L.two_voice_ratio(struct([True]*33 + [False]*67)) < L.TWO_VOICE
assert L.two_voice_ratio(struct([True]*44 + [False]*56)) >= L.TWO_VOICE

# ③ 2성부면 검사를 통과하지 못한다 (= 차감 안 됨)
ex = {"struct": struct([True]*5 + [False]*5), "geometry": {"systems": [{}]},
      "systems": [{"index": 0, "chords": []}]}
g = L.quality_gate(ex, [])
assert g["status"] != "ready", g
assert any("2부" in i or "합창" in i for i in g["issues"]), g["issues"]
assert g["twoVoice"] == 0.5

# ④ 리드시트는 이 이유로 막히지 않는다
ex2 = {"struct": struct([False]*20), "geometry": {"systems": [{}]},
       "systems": [{"index": 0, "chords": []}]}
g2 = L.quality_gate(ex2, [])
assert not any("합창" in i for i in g2["issues"]), g2["issues"]
assert g2["twoVoice"] == 0.0

print("ok — 2성부 판정 · 검사 차단 · 리드시트는 통과")
