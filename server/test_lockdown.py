"""
**로그인 잠금은 화면이 아니라 서버가 건다.**

개발자도구·curl·스크립트로 화면을 건너뛰고 API 를 직접 때리는 사람을
막는 건 오직 여기다. 돈 받고 파는 서비스라 화면 숨김은 방어가 아니다.
이 파일은 로그인 없이 유료 경로가 하나라도 열리면 실패한다.
"""
import sys, os, json, threading, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
import serve as S

srv = S.build_server(port=0, mode="local", reader=lambda *a, **k: {"notes": []},
                     trial_balance=5, ttl=60, workers=1, ip_hourly=3)
S.STATE["store"].require_auth = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
BASE = f"http://127.0.0.1:{PORT}"


def hit(method, path, body=None, ctype="application/json", cookie=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=body if body is not None else None)
    req.add_header("Host", f"127.0.0.1:{PORT}")
    if body is not None:
        req.add_header("Content-Type", ctype)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), r.headers.get("Set-Cookie") or ""
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Set-Cookie") or ""


def _png():
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("L", (600, 400), 255).save(b, "PNG")
    return b.getvalue()

PNG = _png()
fails = []


def deny(name, got, allowed=(401, 402, 403, 404, 429, 500)):
    if got not in allowed:
        fails.append(f"{name}: {got}")


# ① 유료 경로 — 로그인 없이는 어느 것도 판독을 시작하지 못한다
code, body, ck = hit("POST", "/api/jobs", PNG, "image/png")
deny("POST /api/jobs", code)
assert b"\\uc5c5\\ub85c\\ub4dc" not in body or code != 200

code, _, _ = hit("POST", "/api/read", PNG, "image/png")
deny("POST /api/read", code)

# ② 남의 작업은 존재 여부도 안 알려준다
code, _, _ = hit("GET", "/api/jobs/aaaaaaaaaaaa")
deny("GET /api/jobs/<남의것>", code, (404,))
code, _, _ = hit("POST", "/api/jobs/aaaaaaaaaaaa/commit", b"{}")
deny("POST commit/<남의것>", code, (404, 403, 409))

# ③ 프로필은 로그인한 사람만 쓴다
code, _, _ = hit("POST", "/api/profile", json.dumps({"email": "a@b.co"}).encode())
deny("POST /api/profile", code, (403,))

# ④ 개발 통로는 배포에서 닫혀 있다
for p in ("/dev/sheet?name=x.png", "/dev/save"):
    code, _, _ = hit("POST" if "save" in p else "GET", p,
                     b"{}" if "save" in p else None)
    deny(f"{p}", code, (404,))

# ⑤ 표에 없는 로그인 제공자는 404 — 열린 리다이렉트 면을 안 만든다
code, _, _ = hit("GET", "/auth/google")
deny("GET /auth/google", code, (404,))

# ⑥ 다른 출처에서 온 요청은 받지 않는다(Host 를 바꿔 본다)
req = urllib.request.Request(BASE + "/api/jobs", method="POST", data=PNG)
req.add_header("Host", "evil.example")
req.add_header("Content-Type", "image/png")
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        fails.append(f"남의 Host 로 POST 가 통과: {r.status}")
except urllib.error.HTTPError as e:
    if e.code != 403:
        fails.append(f"남의 Host: {e.code}")

# ⑦ 로그인하면 열린다 — 잠금이 과해서 정상 사용까지 막으면 그것도 버그다
_, _, ck = hit("GET", "/api/health")
cookie = ck.split(";")[0]
sid = S._unsign(cookie.split("=", 1)[1])
S.STATE["store"].grant_auth(sid, user="kakao:1", name="민")
code, _, _ = hit("POST", "/api/jobs", PNG, "image/png", cookie=cookie)
if code != 202:                       # 202 = 접수됨
    fails.append(f"로그인했는데 판독이 막혔다: {code}")

# ⑧ **IP 한도는 모든 판독 경로에 걸려야 한다.** /api/read 로만 때려서
#    시간당 제한을 통째로 우회할 수 있으면 안 된다.
st = S.STATE["store"]
st._ip_hits.clear()
for i in range(6):
    hit("POST", "/api/read", PNG + bytes([i]), "image/png", cookie=cookie)
seen = sum(len(v) for v in st._ip_hits.values())
if seen == 0:
    fails.append("/api/read 가 IP 한도 집계를 통째로 건너뛴다")

srv.shutdown()
if fails:
    print("\n".join("FAIL " + f for f in fails))
    raise SystemExit(1)
print("# pass 12 / # fail 0")
