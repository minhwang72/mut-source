"""
개발 통로(/dev/*)가 배포에서 켜지지 않는가.

이 통로는 임의 파일을 **읽고 쓴다**. 검증 자동화에 필요해서 두지만,
배포 컨테이너에서 열리면 그대로 구멍이다. 세 조건이 모두 맞아야만 켜진다:
환경변수 · 127.0.0.1 바인딩 · --origin 없음(프록시 뒤가 아님).
"""
import os, sys, threading, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def fresh(dev_dir, origin, host):
    for m in list(sys.modules):
        if m == "serve":
            del sys.modules[m]
    if dev_dir is None:
        os.environ.pop("MUTE_DEV_DIR", None)
    else:
        os.environ["MUTE_DEV_DIR"] = dev_dir
    import serve
    srv = serve.build_server(0, "local", reader=lambda b, o, progress=None: {"ok": True},
                             host=host, origin=origin)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return serve, srv


def code(port, path, host_hdr):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    req.add_header("Host", host_hdr)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


import tempfile
d = tempfile.mkdtemp()
open(os.path.join(d, "a.png"), "wb").write(b"\x89PNG\r\n\x1a\n")

# ① 배포 모양: origin 이 있으면 꺼져 있다
serve, srv = fresh(d, "https://conti.eungming.com", "127.0.0.1")
try:
    assert not serve.dev_enabled(), "프록시 뒤인데 개발 통로가 열렸다"
    p = srv.server_address[1]
    assert code(p, "/dev/sheet?name=a.png", "conti.eungming.com") == 404
finally:
    srv.shutdown(); serve.STATE["store"].stop()

# ② 환경변수가 없으면 꺼져 있다
serve, srv = fresh(None, None, "127.0.0.1")
try:
    assert not serve.dev_enabled(), "환경변수 없이 개발 통로가 열렸다"
finally:
    srv.shutdown(); serve.STATE["store"].stop()

# ③ 0.0.0.0 바인딩이면 꺼져 있다 (컨테이너 안)
serve, srv = fresh(d, None, "0.0.0.0")
try:
    assert not serve.dev_enabled(), "외부 바인딩인데 개발 통로가 열렸다"
finally:
    srv.shutdown(); serve.STATE["store"].stop()

# ④ 셋 다 맞으면 켜지되, 디렉터리 밖은 못 읽는다
serve, srv = fresh(d, None, "127.0.0.1")
try:
    assert serve.dev_enabled(), "개발 환경인데 안 열린다"
    p = srv.server_address[1]
    h = f"127.0.0.1:{p}"
    assert code(p, "/dev/sheet?name=a.png", h) == 200
    assert code(p, "/dev/sheet?name=../../etc/passwd", h) == 400, "경로 탈출이 통한다"
    assert code(p, "/dev/sheet?name=nope.png", h) == 404
finally:
    srv.shutdown(); serve.STATE["store"].stop()

print("ok")
