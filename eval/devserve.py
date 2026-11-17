#!/usr/bin/env python3
"""
**화면 확인용 로컬 서버.** 측정(eval/sweep.py)이 남긴 판독 결과를 그대로 돌려준다 —
모델·API 없이 결과 화면과 마디 고치기를 실제 데이터로 눌러 보려는 것.

    .venv/bin/python eval/devserve.py eval/sweep_hb_c1_structs 악보샘플/학습용_이미지 8765

브라우저에서 업로드한 이미지의 해시로 어느 장인지 찾는다. /dev/<장>.png 는 그 원본
이미지다(업로드 흉내용). **이 머신에서만 쓴다** — 악보는 저작물이라 밖으로 내지 않는다.
127.0.0.1 에만 붙는다.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
SDIR = Path(sys.argv[1])
IMG = Path(sys.argv[2])
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 8765

PAGES = {p.stem: p for p in SDIR.glob("*.json")}
BY_HASH = {}
for name in PAGES:
    png = IMG / f"{name}.png"
    if png.exists():
        BY_HASH[hashlib.sha1(png.read_bytes()).hexdigest()] = name
print(f"{len(PAGES)}장 · 이미지 {len(BY_HASH)}장", flush=True)


def extraction(name: str) -> dict:
    d = json.loads(PAGES[name].read_text())
    ex = dict(d.get("ex") or {})
    ex["struct"] = d["struct"]
    ex.setdefault("qualityGate", d.get("gate"))
    return ex


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code: int = 200) -> None:
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/api/health":
            return self.json({"mode": "local", "modelPresent": True})
        if route == "/api/account":
            return self.json({"balance": 99, "authed": True, "master": True, "authRequired": False})
        if route.startswith("/api/jobs/"):
            name = route.rsplit("/", 1)[1]
            if name not in PAGES:
                return self.json({"error": "없는 장"}, 404)
            return self.json({"status": "done", "progress": 1, "charged": False,
                              "result": extraction(name)})
        if route == "/dev/pages":
            return self.json(sorted(BY_HASH.values()))
        if route.startswith("/dev/") and route.endswith(".png"):
            p = IMG / Path(route).name
            if p.exists():
                return self.send(200, p.read_bytes(), "image/png")
            return self.json({"error": "없음"}, 404)
        rel = route.lstrip("/") or "index.html"
        f = (WEB / rel).resolve()
        if not str(f).startswith(str(WEB)) or not f.is_file():
            f = WEB / "index.html"            # /account 같은 주소는 앱이 그린다
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if f.suffix in (".js", ".mjs"):
            ctype = "text/javascript"
        self.send(200, f.read_bytes(), ctype)

    def do_POST(self):
        route = self.path.split("?")[0]
        # 점검용: 브라우저가 그린 결과 그림을 eval/logs/render/ 에 남긴다(저장소 밖·로컬 전용)
        if route.startswith("/dev/save/") and route.endswith((".png", ".json")):
            out = ROOT / "eval" / "logs" / "render"
            out.mkdir(parents=True, exist_ok=True)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            (out / Path(route).name).write_bytes(body)
            return self.json({"ok": True})
        if route == "/api/jobs":
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            name = BY_HASH.get(hashlib.sha1(body).hexdigest())
            if not name:
                return self.json({"error": "측정 결과에 없는 이미지입니다"}, 404)
            return self.json({"id": name, "status": "queued"})
        self.json({"error": "없는 경로"}, 404)


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
