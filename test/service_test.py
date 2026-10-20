#!/usr/bin/env python3
"""
서비스 계층 테스트 — **모델도 API도 쓰지 않는다.**

판독기를 갈아 끼워(build_server(reader=...)) 프로토콜만 확인한다. 그래서
이 파일은 몇 초 안에 끝나고, GPU나 키가 없는 곳에서도 돈다.
마지막 하나(로컬 판독기 연기 시험)만 실제 모델을 쓰며, 없으면 건너뛴다.

    mute-venv/bin/python -m unittest discover -s test -p 'service_test.py' -v
"""

from __future__ import annotations

import http.client
import io
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(REPO / "tools"))

import serve  # noqa: E402


def png(w: int = 40, h: int = 30, color=(255, 255, 255)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class Client:
    """쿠키 하나를 들고 다니는 아주 작은 클라이언트 = 사용자 한 명."""

    def __init__(self, port: int):
        self.port = port
        self.cookie = None

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict | None = None, keep_cookie: bool = True):
        h = dict(headers or {})
        if self.cookie:
            h["Cookie"] = self.cookie
        h.setdefault("Host", f"127.0.0.1:{self.port}")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.request(method, path, body=body, headers=h)
            res = conn.getresponse()
            raw = res.read()
            setc = res.getheader("Set-Cookie")
            if setc and keep_cookie:
                self.cookie = setc.split(";")[0]
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:                    # noqa: BLE001
                data = {"_raw": raw[:80]}
            return res.status, data, res
        finally:
            conn.close()

    def upload(self, blob: bytes, **headers):
        h = {"Content-Type": "image/png", "Content-Length": str(len(blob)),
             "Origin": f"http://127.0.0.1:{self.port}", **headers}
        return self.request("POST", "/api/jobs", blob, h)

    def wait(self, jid: str, want=("done", "failed"), timeout: float = 10.0):
        end = time.time() + timeout
        while time.time() < end:
            st, data, _ = self.request("GET", f"/api/jobs/{jid}")
            if st != 200 or data.get("status") in want:
                return st, data
            time.sleep(0.02)
        raise AssertionError(f"작업이 끝나지 않았습니다: {jid}")

    def commit(self, jid: str):
        return self.request("POST", f"/api/jobs/{jid}/commit", b"", {
            "Content-Length": "0", "Origin": f"http://127.0.0.1:{self.port}"})


# 가짜 판독기 — 키 힌트로 결과를 조종한다.
GATE = threading.Event()
GATE.set()


def fake_reader(blob: bytes, opts: dict, progress):
    progress("fake", 50)
    GATE.wait(timeout=10)
    hint = opts.get("keyHint") or ""
    if hint == "Dm":
        raise RuntimeError("내부 경로 /secret/path 가 노출되면 안 된다")
    gate = "needs_review" if hint == "Fm" else "ready"
    return {"meta": {"key": hint or "C", "pageCount": 1}, "systems": [],
            "geometry": {"systems": []}, "struct": {"systems": []},
            "qualityGate": {"status": gate, "issues": []},
            "cost": {"directApiCalls": 0}, "bytes": len(blob)}


class ServiceCase(unittest.TestCase):
    store_kw: dict = {}

    def setUp(self):
        GATE.set()
        self.srv = serve.build_server(0, "local", reader=fake_reader,
                                      **self.store_kw)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.t.start()
        self.c = Client(self.port)

    def tearDown(self):
        GATE.set()
        serve.STATE["store"].stop()
        self.srv.shutdown()
        self.srv.server_close()
        self.t.join(timeout=5)

    def done_job(self, blob=None, **headers):
        st, job, _ = self.c.upload(blob or png(), **headers)
        self.assertEqual(202, st, job)
        _, data = self.c.wait(job["id"])
        return job["id"], data


class TestProtocol(ServiceCase):
    def test_health_and_account_are_honest_and_leak_nothing(self):
        st, h, _ = self.c.request("GET", "/api/health")
        self.assertEqual(200, st)
        self.assertEqual("local", h["mode"])
        self.assertEqual("trial", h["billingMode"])
        self.assertTrue(h["resetsOnRestart"])
        blob = json.dumps(h)
        self.assertNotIn("/Users/", blob)
        self.assertNotIn("sk-ant", blob)

        st, a, _ = self.c.request("GET", "/api/account")
        self.assertEqual(200, st)
        self.assertEqual({"trial": True, "balance": 5, "pricePerScore": 1,
                          "storage": "memory", "resetsOnRestart": True}, a)

    def test_cookie_is_set_once_httponly_and_signed(self):
        _, _, res = self.c.request("GET", "/api/account")
        setc = res.getheader("Set-Cookie")
        self.assertIn("HttpOnly", setc)
        self.assertIn("SameSite=Strict", setc)
        # 두 번째 요청에는 다시 설정하지 않는다
        _, _, res2 = self.c.request("GET", "/api/account")
        self.assertIsNone(res2.getheader("Set-Cookie"))
        # 서명을 건드리면 새 세션이 된다 — 남의 세션을 만들어 낼 수 없다
        forged = Client(self.port)
        forged.cookie = self.c.cookie[:-1] + ("a" if self.c.cookie[-1] != "a" else "b")
        _, _, res3 = forged.request("GET", "/api/account", keep_cookie=False)
        self.assertIsNotNone(res3.getheader("Set-Cookie"))

    def test_same_image_and_options_coalesce_into_one_job(self):
        blob = png()
        GATE.clear()
        st1, j1, _ = self.c.upload(blob)
        st2, j2, _ = self.c.upload(blob)
        GATE.set()
        self.assertEqual((202, 202), (st1, st2))
        self.assertFalse(j1["cached"])
        self.assertTrue(j2["cached"])
        self.assertEqual(j1["id"], j2["id"])

        # 옵션이 다르면 다른 작업이다 — 결과가 달라지기 때문이다
        _, j3, _ = self.c.upload(blob, **{"X-Key-Hint": "G"})
        self.assertNotEqual(j1["id"], j3["id"])
        self.assertFalse(j3["cached"])

    def test_owner_isolation(self):
        jid, _ = self.done_job()
        other = Client(self.port)
        st, data, _ = other.request("GET", f"/api/jobs/{jid}")
        self.assertEqual(404, st)
        self.assertNotIn("result", data)
        st, _, _ = other.commit(jid)
        self.assertEqual(404, st)
        # 원래 주인은 그대로 본다
        st, mine, _ = self.c.request("GET", f"/api/jobs/{jid}")
        self.assertEqual(200, st)
        self.assertEqual("done", mine["status"])
        self.assertEqual(0, mine["result"]["cost"]["directApiCalls"])

    def test_commit_charges_once_for_a_ready_score(self):
        jid, data = self.done_job()
        self.assertEqual("ready", data["result"]["qualityGate"]["status"])
        st, r, _ = self.c.commit(jid)
        self.assertEqual(200, st)
        self.assertEqual({"charged": True, "alreadyCharged": False,
                          "balance": 4, "jobId": jid}, r)
        _, a, _ = self.c.request("GET", "/api/account")
        self.assertEqual(4, a["balance"])

    def test_repeat_commit_is_idempotent(self):
        jid, _ = self.done_job()
        self.c.commit(jid)
        for _ in range(3):
            st, r, _ = self.c.commit(jid)
            self.assertEqual(200, st)
            self.assertFalse(r["charged"])
            self.assertTrue(r["alreadyCharged"])
        _, a, _ = self.c.request("GET", "/api/account")
        self.assertEqual(4, a["balance"])

    def test_review_result_is_never_charged(self):
        jid, data = self.done_job(**{"X-Key-Hint": "Fm"})
        self.assertEqual("needs_review", data["result"]["qualityGate"]["status"])
        st, r, _ = self.c.commit(jid)
        self.assertEqual(409, st)
        _, a, _ = self.c.request("GET", "/api/account")
        self.assertEqual(5, a["balance"])

    def test_failed_job_is_never_charged_and_hides_internals(self):
        jid, data = self.done_job(**{"X-Key-Hint": "Dm"})
        self.assertEqual("failed", data["status"])
        self.assertNotIn("/secret/path", json.dumps(data))
        self.assertNotIn("Traceback", json.dumps(data))
        st, _, _ = self.c.commit(jid)
        self.assertEqual(409, st)
        _, a, _ = self.c.request("GET", "/api/account")
        self.assertEqual(5, a["balance"])

    def test_unfinished_job_cannot_be_committed(self):
        GATE.clear()
        _, job, _ = self.c.upload(png())
        st, _, _ = self.c.commit(job["id"])
        GATE.set()
        self.assertEqual(409, st)

    def test_mutating_endpoints_reject_foreign_origin_and_host(self):
        st, _, _ = self.c.request("POST", "/api/jobs", png(), {
            "Content-Type": "image/png", "Origin": "https://evil.example"})
        self.assertEqual(403, st)
        st, _, _ = self.c.request("POST", "/api/jobs", png(), {
            "Content-Type": "image/png", "Host": "evil.example"})
        self.assertEqual(403, st)

    def test_malformed_uploads_are_rejected(self):
        p = self.port
        origin = {"Origin": f"http://127.0.0.1:{p}"}
        cases = [
            (415, b"x", {"Content-Type": "text/plain", **origin}),
            (400, b"", {"Content-Type": "image/png", **origin}),
            (400, b"not an image at all", {"Content-Type": "image/png", **origin}),
        ]
        for want, body, headers in cases:
            st, data, _ = self.c.request("POST", "/api/jobs", body, headers)
            self.assertEqual(want, st, data)

        # Content-Length 가 한도를 넘으면 본문을 읽지도 않는다
        conn = http.client.HTTPConnection("127.0.0.1", p, timeout=10)
        conn.putrequest("POST", "/api/jobs")
        conn.putheader("Content-Type", "image/png")
        conn.putheader("Origin", f"http://127.0.0.1:{p}")
        conn.putheader("Content-Length", str(serve.MAX_UPLOAD + 1))
        conn.endheaders()
        self.assertEqual(413, conn.getresponse().status)
        conn.close()

    def test_null_or_cross_port_origin_is_rejected(self):
        for origin in ('null', 'http://127.0.0.1:1', f'https://127.0.0.1:{self.port}'):
            status, _, _ = self.c.upload(png(), Origin=origin)
            self.assertEqual(403, status)

    def test_invalid_source_options_are_rejected_before_processing(self):
        for headers in ({'X-Key-Hint':'unknown'}, {'X-Time-Signature':'0/0'}):
            status, _, _ = self.c.upload(png(), **headers)
            self.assertEqual(400, status)

    def test_legacy_read_reuses_the_bounded_job(self):
        blob = png()
        jid, _ = self.done_job(blob)
        status, data, _ = self.c.request('POST', '/api/read', blob, {'Content-Type':'image/png'})
        self.assertEqual(200, status)
        self.assertEqual('ready', data['qualityGate']['status'])
        self.assertEqual(1, serve.STATE['store'].health()['jobs'])

    def test_oversized_pixels_are_rejected(self):
        old = serve.MAX_PIXELS
        serve.MAX_PIXELS = 100
        try:
            st, data, _ = self.c.upload(png(40, 30))
            self.assertEqual(400, st)
            self.assertIn("화소", data["error"])
        finally:
            serve.MAX_PIXELS = old

    def test_static_traversal_is_blocked(self):
        for path in ("/../server/serve.py", "/..%2fserver%2fserve.py",
                     "/../package.json"):
            st, _, _ = self.c.request("GET", path)
            self.assertEqual(404, st, path)
        st, _, res = self.c.request("GET", "/index.html")
        self.assertEqual(200, st)


class TestLimits(ServiceCase):
    store_kw = {"max_active": 1, "max_queue": 1}

    def test_active_job_limit_per_user(self):
        GATE.clear()
        st1, _, _ = self.c.upload(png(40, 30))
        st2, data, _ = self.c.upload(png(41, 30))
        GATE.set()
        self.assertEqual(202, st1)
        self.assertEqual(429, st2, data)
        # 다른 사용자는 막히지 않는다 — 한도는 사용자별이다
        other = Client(self.port)
        self.assertEqual(202, other.upload(png(42, 30))[0])


class TestQueueDepth(ServiceCase):
    store_kw = {"max_active": 9, "max_queue": 1}

    def test_queue_depth_limit(self):
        GATE.clear()
        self.assertEqual(202, self.c.upload(png(40, 30))[0])   # 워커가 집어감
        time.sleep(0.15)
        self.assertEqual(202, self.c.upload(png(41, 30))[0])   # 대기열 1/1
        st, data, _ = self.c.upload(png(42, 30))
        GATE.set()
        self.assertEqual(429, st, data)


class TestTTL(ServiceCase):
    store_kw = {"ttl": 0.2}

    def test_old_results_expire(self):
        jid, data = self.done_job()
        self.assertEqual("done", data["status"])
        time.sleep(0.35)
        st, _, _ = self.c.request("GET", f"/api/jobs/{jid}")
        self.assertEqual(404, st)


class TestCredits(ServiceCase):
    store_kw = {"trial_balance": 1}

    def test_credit_exhaustion_blocks_further_commits(self):
        a, _ = self.done_job(png(40, 30))
        b, _ = self.done_job(png(41, 30))
        self.assertEqual(200, self.c.commit(a)[0])
        st, data, _ = self.c.commit(b)
        self.assertEqual(409, st)
        self.assertIn("크레딧", data["error"])
        _, acc, _ = self.c.request("GET", "/api/account")
        self.assertEqual(0, acc["balance"])
        # 이미 값을 치른 작업은 잔액이 0이어도 계속 열린다
        st, r, _ = self.c.commit(a)
        self.assertEqual(200, st)
        self.assertTrue(r["alreadyCharged"])


class TestLocalReaderSmoke(unittest.TestCase):
    """
    실제 로컬 판독기를 합성 악보 한 장에 돌린다. 모델이 없으면 건너뛴다.

    **정확도를 주장하지 않는다.** 확인하는 것은 계약뿐이다 — 외부 호출 0,
    브라우저가 쓰는 필드가 다 있는지, 품질 게이트가 근거를 남기는지.
    """

    def test_reads_a_synthetic_sheet_without_any_api_call(self):
        import local_reader as LR
        if LR.model_path() is None:
            self.skipTest("검출기 가중치가 없습니다 (MUTE_MODEL)")
        sys.modules.pop("anthropic", None)

        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sheet.png"
            truth = Path(tmp) / "sheet.json"
            r = subprocess.run(
                [sys.executable, str(REPO / "tools" / "make_test_sheet.py"),
                 "-o", str(out), "--extraction", str(truth),
                 "--spacing", "16", "--systems", "3"],
                capture_output=True, timeout=120)
            if r.returncode != 0:
                self.skipTest(f"합성 악보를 만들지 못했습니다: {r.stderr[:200]}")
            blob = out.read_bytes()
            want = json.loads(truth.read_text(encoding="utf-8"))

        ex = LR.read_sheet_local(blob, key_hint=want["meta"]["key"],
                                 time_hint=want["meta"]["timeSignature"])

        # 외부 호출 없음 — anthropic 이 적재되지도 않았다
        self.assertEqual(0, ex["cost"]["directApiCalls"])
        self.assertNotIn("anthropic", sys.modules)
        self.assertEqual("local", ex["reader"])

        # 브라우저(web/app.js · web/redraw.js)가 쓰는 필드
        for k in ("meta", "imageSize", "systems", "geometry", "struct",
                  "qualityGate"):
            self.assertIn(k, ex)
        self.assertEqual(want["meta"]["key"], ex["meta"]["key"])
        # 코드가 없는 단도 자리를 지킨다 — 단 수가 어긋나면 화면이 물러난다
        self.assertEqual(len(ex["geometry"]["systems"]), len(ex["systems"]))
        self.assertEqual(1.0, ex["geometry"]["scale"])
        self.assertEqual(0.0, ex["geometry"]["deskewDeg"])

        # 코드를 실제로 읽었다 (정확도는 주장하지 않는다)
        got = [c["text"] for s in ex["systems"] for c in s["chords"]]
        self.assertGreater(len(got), 0)
        self.assertIn("Bb", got)

        gate = ex["qualityGate"]
        self.assertIn(gate["status"], ("ready", "needs_review"))
        if gate["status"] == "needs_review":
            self.assertTrue(gate["issues"], "review 인데 사유가 비어 있다")


if __name__ == "__main__":
    unittest.main(verbosity=2)
