"""
프록시 뒤에서 열리는 두 구멍을 막았는지 본다.
  1. 공개 Host 를 허용 안 하면 사이트가 통째로 403 이다.
  2. XFF 를 안 보면 모든 손님이 127.0.0.1 이라 IP 제한이 전 세계 12회/시가 된다.
  3. 반대로 프록시 뒤가 아닌데 XFF 를 믿으면 헤더 위조로 제한이 뚫린다.
"""
import os, sys, threading, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve


def get(port, path="/api/account", host=None, origin=None, xff=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if host:   req.add_header("Host", host)
    if origin: req.add_header("Origin", origin)
    if xff:    req.add_header("X-Forwarded-For", xff)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def run(origin):
    srv = serve.build_server(0, "local", reader=lambda b, o, progress=None: {"ok": True},
                             origin=origin)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# --- 프록시 뒤
srv, port = run("https://conti.eungming.com")
try:
    assert get(port, host="conti.eungming.com") == 200, "공개 Host 가 막힌다"
    assert get(port, host="conti.eungming.com",
               origin="https://conti.eungming.com") == 200, "정상 Origin 이 막힌다"
    assert get(port, host="evil.example.com") == 403, "남의 Host 가 통과한다"
    assert get(port, host="conti.eungming.com",
               origin="https://evil.example.com") == 403, "남의 Origin 이 통과한다"

    h = serve.Handler.__new__(serve.Handler)
    h.headers = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}
    h.client_address = ("127.0.0.1", 1)
    assert h._client_ip() == "1.2.3.4", "프록시 뒤에서 진짜 IP 를 못 본다"
finally:
    srv.shutdown(); serve.STATE["store"].stop()

# --- 직접 노출 (origin 없음): XFF 를 믿으면 안 된다
srv, port = run(None)
try:
    assert get(port, host="conti.eungming.com") == 403, "origin 없이 외부 Host 가 통과한다"
    h = serve.Handler.__new__(serve.Handler)
    h.headers = {"X-Forwarded-For": "9.9.9.9"}
    h.client_address = ("203.0.113.7", 1)
    assert h._client_ip() == "203.0.113.7", "위조 XFF 로 IP 제한이 뚫린다"
finally:
    srv.shutdown(); serve.STATE["store"].stop()

print("ok")
