"""세션 쿠키 — **Lax 여야 한다.** Strict 면 OAuth 콜백에서 세션이 끊긴다."""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
import serve as S

src = open(os.path.join(os.path.dirname(__file__), "serve.py")).read()
m = re.search(r'f"\{COOKIE\}=\{_sign\(sid\)\}[^"]*"', src)
assert m, "쿠키를 굽는 자리를 못 찾았다"
c = m.group(0)
# Strict 로 되돌아가면 카카오 로그인이 조용히 깨진다 — 여기서 막는다
assert "SameSite=Lax" in c, c
assert "SameSite=Strict" not in c, c
assert "HttpOnly" in c and "Path=/" in c, c
# https 로 서비스할 때만 Secure 를 붙인다(로컬 http 개발을 막지 않도록)
assert 'Secure' in src.split("self._cookies")[0][-400:], "Secure 분기가 없다"
print("# pass 4 / # fail 0")
