"""마이페이지 — 회원이 채우는 칸과 카카오가 주는 칸을 섞지 않는다."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import jobs as J

E = J._looks_like_email
assert E("a@b.co") and E("zxcyui6181@naver.com")
assert not E("a@b") and not E("ab.co") and not E("a b@c.co")
assert not E("a@@b.co") and not E("a@.co") and not E("a@b.")

st = J.JobStore(lambda *a, **k: {}, trial_balance=2, ttl=60, workers=1, ip_hourly=0)
sid = st.new_session()

# ① 로그인 전에는 못 쓴다
try:
    st.set_profile(sid, {"email": "a@b.co"}); raise SystemExit("로그인 없이 저장됐다")
except J.Denied:
    pass

st.grant_auth(sid, user="kakao:1", name="민", image="https://k.kakaocdn.net/x.jpg")
assert st.profile(sid)["image"].endswith("x.jpg")

# ② 저장되고 계정에 실려 나온다
st.set_profile(sid, {"email": " a@b.co ", "label": "찬양팀"})
assert st.profile(sid) == {"image": "https://k.kakaocdn.net/x.jpg",
                           "email": "a@b.co", "label": "찬양팀"}
assert st.account(sid)["email"] == "a@b.co"

# ③ **사진은 사용자가 못 넣는다.** 넣을 수 있으면 아무 주소나 아바타가 된다
st.set_profile(sid, {"image": "https://evil.example/x.jpg"})
assert st.profile(sid)["image"] == "https://k.kakaocdn.net/x.jpg"

# ④ 형식이 틀린 이메일은 거절한다 — 저장된 값도 안 바뀐다
try:
    st.set_profile(sid, {"email": "노골뱅이"}); raise SystemExit("잘못된 메일이 통과했다")
except J.Denied:
    pass
assert st.profile(sid)["email"] == "a@b.co"

# ⑤ 빈 값은 지우는 뜻이다. 길이는 잘린다
st.set_profile(sid, {"email": ""})
assert st.profile(sid)["email"] == ""
st.set_profile(sid, {"label": "가" * 200})
assert len(st.profile(sid)["label"]) == 40

# ⑥ 다시 로그인하면 사진은 갱신되고 회원이 채운 값은 남는다
st.set_profile(sid, {"label": "찬양팀"})
s2 = st.new_session()
st.grant_auth(s2, user="kakao:1", name="민", image="https://k.kakaocdn.net/new.jpg")
assert st.profile(s2) == {"image": "https://k.kakaocdn.net/new.jpg",
                          "email": "", "label": "찬양팀"}
# ⑦ 사진 동의를 뺀 채 로그인해도 쓰던 사진을 지우지 않는다
s3 = st.new_session(); st.grant_auth(s3, user="kakao:1", name="민")
assert st.profile(s3)["image"].endswith("new.jpg")

print("# pass 16 / # fail 0")
