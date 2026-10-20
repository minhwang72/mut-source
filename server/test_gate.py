"""
판독 경로마다 qualityGate 를 내는가.

왜 이 테스트가 있나(실측): ai 경로가 qualityGate 를 안 만들었다. 브라우저는
`qualityGate?.status !== 'ready'` 로 저장을 막으므로, **판독이 완벽해도**
PDF·PNG 버튼이 영영 잠겼다. 배포된 기본 모드가 ai 라 사이트에서 아무도
결과를 못 받고 있었는데, 서버는 'done' 을 냈고 로그도 조용했다.
경로가 둘이면 둘 다 확인해야 한다.
"""
import ast, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import local_reader

# ── ① 게이트 자체가 판정을 하는가
empty = {"struct": {}, "geometry": {}, "systems": []}
g = local_reader.quality_gate(empty, [])
assert g["status"] == "needs_review", g
assert g.get("issues"), "사유 없이 막으면 사용자가 뭘 고칠지 모른다"

g2 = local_reader.quality_gate(empty, ["판독 실패"])
assert "판독 실패" in g2["issues"], g2

# ── ② 두 판독 경로가 모두 게이트를 붙이는가
#     (모델·API 없이 돌려야 해서 호출 대신 배정문을 확인한다)
def assigns_gate(path: str, func: str) -> bool:
    src = ast.parse(open(path, encoding="utf-8").read())
    for fn in ast.walk(src):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == func):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Subscript)
                            and isinstance(t.slice, ast.Constant)
                            and t.slice.value == "qualityGate" for t in node.targets)):
                return True
    return False

assert assigns_gate(os.path.join(os.path.dirname(__file__), "local_reader.py"), "read_sheet_local"), \
    "local 경로가 qualityGate 를 안 붙인다"
assert assigns_gate(os.path.join(os.path.dirname(__file__), "serve.py"), "read_sheet"), \
    "ai 경로가 qualityGate 를 안 붙인다 — 저장 버튼이 영영 잠긴다"

print("ok")


# ── ④ **안내는 과금을 막지 않는다** ──────────────────────────────────
# 실사용 일주일: 회원 11명 · 판독 35건 · 환불 35건. 차감이 하나도 없었다.
# 게이트가 이슈 하나라도 있으면 막았기 때문인데, 그 이슈에는 "조표를 못
# 읽어 C장조로 추정했습니다" 같은 **안내**가 섞여 있었다. 다시 그려 주고도
# 돈을 못 받는 구조였다. 이게 되돌아가면 매출이 다시 0이 된다.
def _page(n_systems=1):
    return {
        "struct": {"systems": [{"index": i, "notes": [],
                                "measures": []} for i in range(n_systems)]},
        "geometry": {"systems": [{"index": i} for i in range(n_systems)]},
        "systems": [{"index": i, "chords": []} for i in range(n_systems)],
    }


ADVICE = ["조표로 C장조로 추정했습니다 — 단조일 수 있어 확인이 필요합니다",
          "박자표를 읽지 못해 마디 4박으로 추정했습니다",
          "코드 3개를 확인해야 합니다 (못 읽음·확신도 낮음)"]

clean = local_reader.quality_gate(_page(), [])
g = local_reader.quality_gate(_page(), list(ADVICE))
# 안내만 있으면 판정은 안내가 없을 때와 같아야 한다
assert g["status"] == clean["status"], (g["status"], clean["status"])
assert g["notes"] == ADVICE, g["notes"]
assert not [m for m in ADVICE if m in g["blocking"]], g["blocking"]
# 화면은 둘 다 봐야 한다 — 안내를 숨기면 짐작한 걸 아무도 못 본다
assert all(m in g["issues"] for m in ADVICE), g["issues"]

# 차단 사유는 그대로 막는다 — 2성부는 상품이 안 나온다
two = {"struct": {"systems": [{"index": 0, "notes": [
    {"measure": 0, "chordSize": 3}] * 4, "measures": []}]},
    "geometry": {"systems": [{"index": 0}]},
    "systems": [{"index": 0, "chords": []}]}
gt = local_reader.quality_gate(two, list(ADVICE))
assert gt["status"] == "needs_review", gt
assert gt["blocking"], "차단 사유가 비면 왜 막혔는지 알 수 없다"

print("ok — 안내는 통과, 차단은 막음")


# ── ⑤ **찍은 음표가 있으면 통과시키지 않는다** ──────────────────────
# fit_page 는 박자 합이 맞을 때까지 음가를 비튼다. 합이 맞으면 게이트가
# 통과하는데 그건 "잘 읽었다"가 아니라 "합을 맞춰 놨다"는 뜻이다. 지어낸
# 음표가 든 악보에 돈을 받게 된다. 실측 103장: fit_page 를 켜면 통과가
# 0 -> 11장인데 그중 4장만 찍은 음표가 0 이고, 한 장은 16개를 찍고도 통과했다.
def _with(flags):
    ns = [dict(flags)]
    return {"struct": {"systems": [{"index": 0, "notes": ns, "measures": []}]},
            "geometry": {"systems": [{"index": 0}]},
            "systems": [{"index": 0, "chords": []}]}


plain = local_reader.quality_gate(_with({}), [])
fitted = local_reader.quality_gate(_with({"fitted": True}), [])
guess = local_reader.quality_gate(_with({"guessed": True}), [])

# 고칠 방법이 하나뿐이라 연역한 것(fitted)은 막지 않는다 — 증거가 있다
assert fitted["status"] == plain["status"], (fitted["status"], plain["status"])
assert not [m for m in fitted["blocking"] if "추정" in m], fitted["blocking"]

# **지어낸 자리는 막는다.** 한동안 알리기만 했다 — 그때는 막으면 ai 경로
# 25장 중 추정이 없는 장이 2장뿐이라 사실상 전원 차단이었다. 지어내는
# 이유를 하나씩 없앤 뒤 다시 재니 40장 중 통과 8장의 절반이 지어낸 음가
# 0 이다. 막아도 팔 게 남으므로 약속을 단순하게 되돌린다 —
# **지어내면 돈을 받지 않는다.**
assert [m for m in guess["blocking"] if "짐작" in m], guess["blocking"]
assert not [m for m in guess["notes"] if "짐작" in m], guess["notes"]
# 과금하지 않는다는 말이 문구에 있어야 한다 — 상태만 바뀌면 사용자는 모른다
assert [m for m in guess["blocking"] if "과금하지 않습니다" in m], guess["blocking"]
assert [m for m in guess["issues"] if "짐작" in m], guess["issues"]

print("ok — 지어낸 자리는 막고, 과금하지 않는다고 말한다")


# ── ⑥ **간주 줄은 오류가 아니다** ───────────────────────────────────
# 콘티에는 멜로디 없이 코드만 적힌 줄이 있다(간주·전주). 음표가 없는 게
# 맞는데 게이트가 "읽은 음표·쉼표가 없어"로 막았다. 실측: 검출 신뢰도를
# 0.05 까지 내려도 그 줄의 머리 후보는 0개였고 LLM 도 0개라고 답했다 —
# 둘 다 맞았고 게이트만 틀렸다.
import inspect
src = inspect.getsource(local_reader.quality_gate)
assert "interlude" in src, "간주 줄 예외가 없다"
i = src.index("interlude = {")
blk = src[i:i + 500]
# **코드가 있을 때만** 뺀다 — 코드도 음표도 없으면 진짜 못 읽은 것이다
assert '"chords"' in blk, "코드 유무를 안 본다"
assert 'sy.get("notes")' in blk, "음표 유무를 안 본다"
# 다른 사유까지 통째로 빼면 안 된다
j = src.index("if si in interlude")
assert '"읽은 음표" in' in src[j:j + 200], "사유를 가리지 않고 통째로 뺀다"

print("ok — 코드만 있는 간주 줄은 막지 않는다")
