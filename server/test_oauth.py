"""간편 로그인 — state 는 **세션과 제공자 둘 다**에 묶여야 한다."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ["KAKAO_REST_KEY"] = "k"
os.environ["NAVER_CLIENT_ID"] = "n"
import serve as S

H = S.Handler

# ① 제공자 표에 둘 다 있고, 각자 다른 회원 접두사를 쓴다
assert set(H.OAUTH) == {"kakao", "naver"}

# ② 프로필 파싱 — 응답 모양이 서로 다르다
assert H._profile("kakao", {"id": 7, "kakao_account": {
    "profile": {"nickname": "민", "profile_image_url": "u"}}}) == ("7", "민", "u")
assert H._profile("naver", {"response": {
    "id": "abc", "nickname": "민", "profile_image": "u"}}) == ("abc", "민", "u")
# 이메일이 와도 무시한다 — 받아서 보관할 이유가 없다
assert H._profile("naver", {"response": {
    "id": "abc", "email": "x@y.z"}}) == ("abc", "", "")
# 빈 응답이면 uid 가 비고, 호출부가 거기서 막는다
assert H._profile("kakao", {})[0] == ""
assert H._profile("naver", {})[0] == ""

# ③ 회원 id 가 제공자별로 갈린다 — 카카오 123 과 네이버 123 은 남남
assert f"kakao:{H._profile('kakao', {'id': 123})[0]}" != \
       f"naver:{H._profile('naver', {'response': {'id': '123'}})[0]}"

# ④ state 는 (세션, 제공자, 시각) 세 칸이다. 두 칸이면 카카오로 받은
#    state 를 네이버 콜백에 들이밀 수 있다.
S._OAUTH_STATE["s1"] = ("sid", "kakao", 0.0)
sid, prov, _t = S._OAUTH_STATE["s1"]
assert (sid, prov) == ("sid", "kakao")

print("# pass 8 / # fail 0")
