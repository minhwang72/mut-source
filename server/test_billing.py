"""과금은 저장이 아니라 **판독**에서 일어난다 — 그리고 못 준 판독은 안 받는다."""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))
import jobs as J

def store(reader, **kw):
    return J.JobStore(reader, trial_balance=2, ttl=60, workers=1,
                      ip_hourly=0, **kw)

def wait(st, sid, jid, n=200):
    for _ in range(n):
        j = st.get(sid, jid)
        if j and j["status"] in ("done", "failed"):
            return j
        time.sleep(0.02)
    raise AssertionError("작업이 안 끝났다")

ready = lambda *a, **k: {"qualityGate": {"status": "ready"}}
needs = lambda *a, **k: {"qualityGate": {"status": "review"}}
def boom(*a, **k): raise RuntimeError("읽기 실패")

# ① 판독이 성공하면 그 자리에서 깎인다 — 저장 전에 이미
st = store(ready); sid = st.new_session()
assert st.account(sid)["balance"] == 2
job, _ = st.submit(sid, b"a", {})
assert st.account(sid)["balance"] == 1, "판독 시작 때 잡아야 한다"
wait(st, sid, job["id"])
assert st.account(sid)["balance"] == 1
assert st.get(sid, job["id"])["charged"] is True

# ② 저장(commit)은 더 이상 깎지 않는다 — 몇 번을 불러도 잔액 그대로
for _ in range(3):
    st.commit(sid, job["id"])
assert st.account(sid)["balance"] == 1, "저장에서 또 깎으면 안 된다"

# ③ 읽다 실패하면 돌려준다
st = store(boom); sid = st.new_session()
job, _ = st.submit(sid, b"b", {})
wait(st, sid, job["id"])
assert st.account(sid)["balance"] == 2, "실패한 판독에 받으면 안 된다"

# ④ 확인이 필요한 결과도 돌려준다
st = store(needs); sid = st.new_session()
job, _ = st.submit(sid, b"c", {})
wait(st, sid, job["id"])
assert st.account(sid)["balance"] == 2, "검사 미통과는 받지 않는다"
try:
    st.commit(sid, job["id"]); raise AssertionError("저장이 통과되면 안 된다")
except J.Denied:
    pass

# ⑤ 잔액이 0이면 판독 자체를 시작하지 않는다
st = store(ready); sid = st.new_session()
for i in range(2):
    wait(st, sid, st.submit(sid, f"x{i}".encode(), {})[0]["id"])
assert st.account(sid)["balance"] == 0
try:
    st.submit(sid, b"z", {}); raise AssertionError("잔액 0에서 판독이 시작됐다")
except J.Denied:
    pass

# ⑥ 같은 그림을 다시 올리면 공짜다 (같은 작업 재사용)
st = store(ready); sid = st.new_session()
job, reused = st.submit(sid, b"same", {}); wait(st, sid, job["id"])
again, reused = st.submit(sid, b"same", {})
assert reused and again["id"] == job["id"]
assert st.account(sid)["balance"] == 1, "재사용은 안 깎는다"

# ⑦ 쿠키를 지워도 같은 IP 면 체험이 되살아나지 않는다
st = store(ready)
for i in range(2):
    s = st.new_session()                      # 매번 새 세션 = 쿠키 지우기
    wait(st, s, st.submit(s, f"p{i}".encode(), {}, ip="1.2.3.4")[0]["id"])
fresh = st.new_session()
try:
    st.submit(fresh, b"q", {}, ip="1.2.3.4")
    raise AssertionError("IP 체험 한도를 넘어 판독이 시작됐다")
except J.Denied:
    pass
# 다른 IP 는 영향 없다
other = st.new_session()
st.submit(other, b"r", {}, ip="5.6.7.8")

print("ok — 판독 과금 · 실패 환불 · 재사용 무료 · IP 체험 한도")

# ⑧ 마스터 세션은 잔액·IP 한도와 무관하게 판독한다 (결제 붙기 전 임시)
st = store(ready); sid = st.new_session()
st.grant_master(sid)
assert st.is_master(sid) and st.account(sid)["master"] is True
before = st.account(sid)["balance"]
for i in range(4):                                  # 체험 2크레딧을 넘겨서
    wait(st, sid, st.submit(sid, f"m{i}".encode(), {}, ip="9.9.9.9")[0]["id"])
assert st.account(sid)["balance"] == before, "마스터는 차감되지 않는다"
# 마스터가 아닌 세션은 같은 IP 라도 한도를 그대로 받는다
plain = st.new_session()
for i in range(2):
    wait(st, plain, st.submit(plain, f"n{i}".encode(), {}, ip="8.8.8.8")[0]["id"])
try:
    st.submit(st.new_session(), b"x", {}, ip="8.8.8.8")
    raise AssertionError("일반 세션이 IP 한도를 넘었다")
except J.Denied:
    pass
print("ok — 마스터 세션 무제한 · 일반 세션은 그대로")

# ⑨ 계정 잠금: 로그인 안 한 세션은 판독을 시작하지 못한다
st = store(ready); st.require_auth = True
plain = st.new_session()
try:
    st.submit(plain, b"lock", {})
    raise AssertionError("잠금 상태에서 판독이 시작됐다")
except J.Denied as e:
    assert "로그인" in str(e), e
assert st.account(plain)["authRequired"] is True
assert st.account(plain)["authed"] is False

# 마스터는 그대로 쓴다
m = st.new_session(); st.grant_master(m)
assert st.account(m)["authed"] is True
wait(st, m, st.submit(m, b"ok", {})[0]["id"])

# 로그인하면 열린다 (카카오 로그인이 붙으면 grant_auth 를 부른다)
u = st.new_session(); st.grant_auth(u)
assert st.account(u)["authed"] is True
wait(st, u, st.submit(u, b"user", {})[0]["id"])
assert st.account(u)["balance"] == 1, "로그인 사용자는 정상 차감된다"

# 잠금을 끄면 예전처럼 동작한다
st.require_auth = False
anon = st.new_session()
wait(st, anon, st.submit(anon, b"anon", {})[0]["id"])

print("ok — 계정 잠금 · 마스터 통과 · 로그인 시 정상 차감")

# ⑩ 로그인하면 장부가 **세션이 아니라 회원**을 따라간다
st = store(ready); st.require_auth = True
s1 = st.new_session(); st.grant_auth(s1, user="kakao:777", name="황민")
assert st.account(s1)["name"] == "황민"
wait(st, s1, st.submit(s1, b"one", {})[0]["id"])
assert st.account(s1)["balance"] == 1

# 다른 기기(새 세션)로 같은 회원이 로그인하면 잔액이 이어진다
s2 = st.new_session(); st.grant_auth(s2, user="kakao:777")
assert st.account(s2)["balance"] == 1, "회원 잔액이 이어지지 않았다"

# 다른 회원은 자기 체험 크레딧을 받는다
s3 = st.new_session(); st.grant_auth(s3, user="kakao:888")
assert st.account(s3)["balance"] == 2

# 환불도 회원 잔액에 반영된다
st2 = store(needs); st2.require_auth = True
s4 = st2.new_session(); st2.grant_auth(s4, user="kakao:999")
wait(st2, s4, st2.submit(s4, b"x", {})[0]["id"])
assert st2.account(s4)["balance"] == 2, "검사 미통과는 회원 잔액도 되돌려야 한다"
s5 = st2.new_session(); st2.grant_auth(s5, user="kakao:999")
assert st2.account(s5)["balance"] == 2

print("ok — 회원 단위 장부 · 기기 바뀌어도 이어짐")

# ⑪ 로그아웃 — 신원만 떼고 잔액은 회원번호에 남긴다
st = store(ready); st.require_auth = True
s1 = st.new_session(); st.grant_auth(s1, user="kakao:77", name="민")
job, _ = st.submit(s1, b"a", {}); wait(st, s1, job["id"])
spent = st.account(s1)["balance"]
assert spent == 1, spent
st.revoke_auth(s1)
a = st.account(s1)
assert not a["authed"], a          # 더는 로그인 상태가 아니고
assert a["name"] == "", a          # 이름도 안 남는다
denied = None                      # 판독도 막힌다
try:
    st.submit(s1, b"a", {})
except Exception as e:
    denied = e
assert denied is not None, "로그아웃했는데 판독이 됐다"
assert "로그인" in str(denied), denied
# 앞사람 결과가 남아 있으면 안 된다 — 재사용 경로는 로그인 검사보다 앞이다
assert not [j for j in st._jobs.values() if j["owner"] == s1], "로그아웃했는데 결과가 남았다"
# 다시 로그인하면 쓰던 잔액 그대로 — 로그아웃으로 크레딧이 복원되지 않는다
s2 = st.new_session(); st.grant_auth(s2, user="kakao:77", name="민")
assert st.account(s2)["balance"] == spent, st.account(s2)
assert st.account(s2)["name"] == "민"
print("# pass 11 / # fail 0")
