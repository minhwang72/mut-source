#!/usr/bin/env python3
"""
뮤트 개발 서버 — 정적 파일 + 판독 API.

저작권 설계상 서버가 하는 일은 **구조 데이터 반환**뿐이다.
좌표와 코드 텍스트는 사실 정보이고, 악보 이미지를 합성하는 일(=복제물 생성)은
브라우저에서 일어난다. 서버는 이미지를 저장하지 않는다.

    python3 server/serve.py [--port 8000] [--mode local|ai]

기본은 `--mode ai` — 단별 **음표·쉼표 개수만** LLM에 묻는다(readcounts.py).
음가·마디·붙임점은 검출기와 그림에서 나오므로 악보가 밖으로 나가는 양은
조각 이미지 한 장뿐이다. `--mode local` 은 외부 호출을 아예 안 하지만
검출기가 못 읽는 단이 0개가 되어 막힌다(server/local_reader.py).

판독은 작업 큐로 돈다(server/jobs.py): POST /api/jobs → 202, GET /api/jobs/<id>
로 진행 상황을 받는다. 같은 세션이 같은 사진을 다시 올리면 하던 작업을
그대로 돌려준다. `/api/read` 는 예전 화면을 위해 동기 경로로 남겨 둔다.

**과금은 체험판이다.** 신원은 로컬 쿠키 하나이고 장부는 메모리에만 있다 —
다시 띄우면 초기화된다. 결제 연동·회원 인증은 없다.

127.0.0.1 에만 바인딩한다. 개발·시범용이며 운영에는 정식 서버가 필요하다.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import sys
import concurrent.futures as _cf
import threading
import time
import urllib.parse
import urllib.request

from PIL import Image
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"
WEB_ROOT = WEB.resolve()
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jobs  # noqa: E402

MAX_UPLOAD = 24 * 1024 * 1024  # 24MB — 핸드폰 사진 여유
# 화소 상한. 바이트만 막으면 압축률 높은 거대한 PNG 한 장으로 메모리가 터진다.
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

COOKIE = "mute_sid"

# **개발 전용 통로.** 검증 자동화(악보 넣기 → 변환 → PNG 저장)를 브라우저
# 밖에서 돌릴 수 없어서 둔다. 세 겹으로 잠근다:
#   ① 환경변수 MUTE_DEV_DIR 이 있어야 하고
#   ② 127.0.0.1 에 바인딩됐어야 하고
#   ③ --origin 이 없어야(= 프록시 뒤가 아니어야) 한다.
# 배포 컨테이너는 --origin 을 주고 이 변수를 안 주므로 절대 켜지지 않는다.
DEV_DIR = os.environ.get("MUTE_DEV_DIR") or ""
# 간편 로그인 CSRF 방지용 state → (세션, 제공자, 시각). 10분 뒤 버린다.
_OAUTH_STATE: dict[str, tuple[str, str, float]] = {}

# **검출 모델은 한 번만 올린다.** 한 장을 읽는 동안 YOLO(...) 를 네 번
# 새로 만들고 있었다(조성추정·조표·머리·이음줄). 서버(CPU)에서 조성추정
# 하나가 15.9초였는데 그 대부분이 로드였다. 프로세스 수명 동안 재사용한다.
_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOCK = threading.Lock()


def load_model(path: str):
    m = _MODEL_CACHE.get(path)
    if m is None:
        with _MODEL_LOCK:
            m = _MODEL_CACHE.get(path)
            if m is None:
                from ultralytics import YOLO
                m = _MODEL_CACHE[path] = YOLO(path)
    return m


def dev_enabled() -> bool:
    return bool(DEV_DIR) and STATE.get("origin") is None and STATE.get("host") == "127.0.0.1"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")

# 서버 한 판의 상태. 비밀키는 프로세스마다 새로 만든다 — 다시 띄우면 세션이
# 끊기고 체험 잔액도 초기화된다. /api/health 가 그 사실을 그대로 말한다.
STATE = {"mode": "ai", "store": None, "secret": secrets.token_bytes(32),
         "origin": None, "host": "127.0.0.1"}   # 역방향 프록시 뒤일 때 공개 출처 (예: https://conti.eungming.com)


def _sign(sid: str) -> str:
    mac = hmac.new(STATE["secret"], sid.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{sid}.{mac}"


def _unsign(token: str) -> str | None:
    sid, _, mac = token.rpartition(".")
    if not sid or not mac:
        return None
    want = hmac.new(STATE["secret"], sid.encode(), hashlib.sha256).hexdigest()[:32]
    return sid if hmac.compare_digest(mac, want) else None


def ensure_api_key() -> None:
    """
    ANTHROPIC_API_KEY 확인. 없으면 프로젝트 루트의 .env에서 읽는다.

    비대화형 셸은 ~/.zshrc 를 읽지 않으므로, 터미널에서는 되는데 서버를
    다른 방식으로 띄우면 키가 없는 상황이 생긴다. .env 는 .gitignore 에 있다.
    """
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip("\"'")
                return
    raise SystemExit(
        "ANTHROPIC_API_KEY 가 없습니다.\n"
        "  터미널에서 실행하거나, 프로젝트 루트에 .env 를 만드세요:\n"
        '    echo \'ANTHROPIC_API_KEY="sk-ant-..."\' > .env'
    )


# 오선을 건드리는 작업(조표 교체)의 최소 오선 간격. render.py와 같은 값.
MIN_SPACING_FOR_STAFF_EDIT = 6.0


def _chord_boxes_by_system(extraction: dict, n: int) -> list[list[dict]]:
    """단 번호(`index`)로 코드 상자를 줄 세운다 — 목록 순서를 믿지 않는다."""
    out: list[list[dict]] = [[] for _ in range(n)]
    for sd in (extraction.get("systems") or []):
        i = int(sd.get("index", -1))
        if 0 <= i < n:
            out[i] = [c["box"] for c in (sd.get("chords") or []) if c.get("box")]
    return out


def _ink_runs(cols, gap: int) -> list[list[int]]:
    """잉크가 있는 열(bool 배열)을 `gap` 이상 떨어지면 끊어 구간으로 묶는다."""
    runs: list[list[int]] = []
    start = last = None
    for x, on in enumerate(cols):
        if on:
            if start is None:
                start = x
            last = x
        elif start is not None and x - last > gap:
            runs.append([start, last + 1])
            start = None
    if start is not None:
        runs.append([start, last + 1])
    return [r for r in runs if r[1] - r[0] >= 2]


def build_geometry(img, ink, staves, src_fifths: int = 0,
                   chord_boxes: list | None = None) -> dict:
    """
    브라우저가 픽셀을 옮기는 데 필요한 **좌표만** 모아 보낸다.

    이렇게 하면 Otsu·오선검출을 JS로 다시 구현하지 않아도 되고, 서버는
    여전히 구조 데이터만 반환한다(악보 이미지를 만들지 않는다).
    브라우저는 임계값 하나로 getImageData 결과를 잉크/종이로 가를 수 있다.
    """
    import render
    import sheetcv as cv

    spacing = cv.median_spacing(staves)
    strict = cv.remove_staff_lines(ink, staves, protect_noteheads=False)
    out = []
    for st in staves:
        # 음자리표 + 조표 + (첫 단이면) 박자표 구간 — 이 왼쪽은 움직이지 않는다
        # 렌더러와 **같은 함수**로 구한다. 고정 배수를 쓰면 머리 구간이
        # 첫 음표를 덮어, 그 음표만 이동에서 빠지고 새 조표가 위에 덮인다
        # (실측: 첫 음표 x=207 < headEnd 208 → 머리가 뭉개졌다).
        head_end = int(render.head_end_for(strict, st, spacing, src_fifths))
        out.append({
            "index": st.index,
            "staffTop": int(st.top),
            "staffBottom": int(st.bottom),
            "lineSpans": [[int(a), int(b)] for (a, b) in st.spans],
            "left": int(st.left),
            "right": int(st.right),
            "spacing": round(st.spacing, 2),
            "thickness": int(st.thickness),
            "headEnd": head_end,
            # 가사 띠 — 이조와 무관하므로 브라우저가 원본으로 되돌린다.
            # 이동 창이 기둥을 덮으려면 오선 아래로 내려가야 해서 가사 영역과
            # 겹친다(실측: 되돌리지 않으면 가사 일치율 80~90%).
            "lyricBand": None,
        })

    # 이조해도 움직이면 안 되는 것들(마디선·쉼표)의 좌표.
    # 래스터 이동은 창 전체를 옮기므로 이것들도 따라 내려간다 — 브라우저가
    # 이 좌표로 원본 화소를 되돌린다.
    import lyricstrip as LS
    import numpy as np
    ink_arr = np.asarray(ink)
    for i, (st, entry) in enumerate(zip(staves, out)):
        nxt = staves[i + 1].top if i + 1 < len(staves) else None
        band = cv.find_lyric_band(ink, st, spacing, nxt)
        entry["lyricBand"] = [int(band[0]), int(band[1])] if band else None
        # **가사 음절 x구간을 함께 보낸다.** 새로 그리는 경로에서는 브라우저가
        # 이 조각들을 원본에서 오려 붙인다 — LLM에 가사를 물으면 한글을
        # 지어낸다(실측: "주 이름 찬양" → "즐거운 찬란한").
        # 음절 나누기는 오선 제거·골짜기 찾기가 필요해 JS로 옮기기 어렵다.
        entry["syllables"] = None
        if band:
            tight = LS.band_of(ink_arr, band, spacing, pad_below=True)
            syl = LS.syllables(ink_arr, tight, spacing)
            if syl:
                entry["lyricBand"] = [int(tight[0]), int(tight[1])]
                entry["syllables"] = [[int(a), int(b)] for a, b in syl]
        objs = cv.find_fixed_objects(strict, st, spacing)
        # 음자리표·조표·박자표 구간은 애초에 움직이지 않으므로 제외
        entry["fixed"] = [o for o in objs if o["x"] >= entry["headEnd"]]

    # **머리글을 자를 위치.** 첫 단 위에는 제목·부제·작곡자·저작권 표기와
    # 콘티의 **송폼**("Intro(8) - A1 - B - …")이 있다. 찬양팀이 그걸 보고
    # 연주하므로 사라지면 악보를 못 쓴다. 다시 조판해 만들 수 없으니
    # 브라우저가 원본 픽셀을 그대로 오려 붙인다 — 가사와 같은 이유다.
    # 첫 단 코드보다 위에서 자른다(코드는 다시 그려진다).
    head_cut = int(staves[0].top - spacing * 1.2) if staves else 0

    # **오선 위 띠(구간 표시·마디 번호·손글씨)를 오려 둔다.** 콘티의
    # "Verse 1"·"Chorus 1" 상자, 마디 번호(9·17·25), 손으로 적은 "X2"는
    # 다시 조판해 만들 수 없다 — 찬양팀은 이걸 보고 구간을 따라가므로
    # 없으면 콘티로 못 쓴다. 머리글·가사와 같은 이유로 원본 픽셀을 옮긴다.
    # 코드 기호는 다시 그려지므로 띠에서 지운다(두 번 그리지 않는다).
    # 첫 단은 머리글 오림이 이미 그 위를 통째로 가져간다 — 건너뛴다.
    for i, (st, entry) in enumerate(zip(staves, out)):
        entry["topBand"], entry["topItems"] = None, []
        if i == 0:
            continue
        cs = (chord_boxes[i] if chord_boxes and i < len(chord_boxes) else [])
        # 아래끝은 **코드 줄 아래**로 둔다. 코드는 오선 위 모든 것보다
        # 높이 있어서, 그 아래로 내리면 덧줄·높은 음표가 띠에 섞인다.
        y1 = (int(max(c["y"] + c["h"] for c in cs) + spacing * 0.2) if cs
              else int(st.top - spacing * 1.2))
        prev = int(staves[i - 1].bottom + spacing)
        pb = out[i - 1].get("lyricBand")
        if pb:
            prev = max(prev, int(pb[1]) + 1)
        y0 = max(prev, int(y1 - spacing * 6))
        if y1 - y0 < 3:
            continue
        strip = ink_arr[y0:y1].copy()
        if cs:
            # **코드 줄은 상자 단위가 아니라 띠 통째로 지운다.** 검출 상자가
            # 글자보다 조금 안쪽에 잡혀서, 상자만 지우면 글자 끝이 남아
            # 구간 표시에 딸려 오고 코드가 두 번 그려진다(실측 단1:
            # 상자 x=133 인데 C 의 잉크는 125 부터였다).
            # **첫 코드 왼쪽은 남긴다** — 마디 번호가 거기 있다.
            cut = max(y0, int(min(c["y"] for c in cs) - spacing * 0.3))
            left = max(0, int(min(c["x"] for c in cs) - spacing))
            strip[cut - y0:, left:] = 0
        items = []
        for x0, x1 in _ink_runs(strip.any(axis=0), max(2, int(spacing * 0.9))):
            # **조각마다 세로도 좁힌다.** 가로만 끊으면 「Verse 1」 상자
            # 아래에 있는 코드 기호가 같은 네모 안에 들려 와 두 번 그려진다
            # (실측: 단1 상자 밑에 C 가 하나 더 붙었다).
            # **맨 위 덩어리만 가져온다.** 아래쪽에 떨어져 있는 잉크는
            # 표시가 아니라 음자리표 꼭대기나 코드 꼬리다 — 그것까지
            # 네모에 넣으면 같이 오려져 두 번 그려진다(실측 단3: 「Verse 2」
            # 아래 11px 떨어진 자리에 높은음자리표 끝이 걸렸다).
            rs = _ink_runs(strip[:, x0:x1].any(axis=1), max(1, int(spacing * 0.4)))
            if not rs:
                continue
            items.append([x0, x1, y0 + rs[0][0], y0 + rs[0][1]])
        if items:
            entry["topBand"] = [min(i[2] for i in items),
                                max(i[3] for i in items)]
            entry["topItems"] = items

    # **바닥 고지(저작권 표기)를 자를 위치.** 페이지 맨 아래의
    # "Copyright … All rights reserved." 는 다시 만들 수 없으므로 머리글과
    # 똑같이 원본 픽셀을 오려 붙인다. 판정 근거는 render.footer_cut_for 참고.
    foot_cut = render.footer_cut_for(ink, staves, spacing)

    # **구역 표시(A2·B·C·A′)의 자리.** 콘티 악보는 오선 왼쪽 여백에 이 상자를
    # 둔다. 머리글의 송폼과 짝이 되는 정보라 없으면 곡 형식을 못 따라간다.
    # Verovio는 오선을 페이지 왼쪽 끝부터 그리므로(pageMarginLeft가 듣지 않는다)
    # 브라우저가 페이지를 넓혀 그 왼쪽에 붙인다.
    marks: list[dict] = []
    if staves:
        from collections import Counter
        base_left = Counter(int(st.left) for st in staves).most_common(1)[0][0]
        edge = base_left - int(spacing * 1.5)
        # 왼쪽 여백이 좁으면 오선 끝 잉크를 표시로 오해한다
        if edge >= spacing * 3:
            ia = np.asarray(ink)
            for i, st in enumerate(staves):
                y0 = max(0, int(st.top - spacing * 2.2))
                y1 = min(ia.shape[0], int(st.bottom + spacing * 2.2))
                strip = ia[y0:y1, :edge]
                if not strip.any():
                    continue
                ys, xs = np.nonzero(strip)
                x0, x1 = int(xs.min()), int(xs.max()) + 1
                yy0, yy1 = y0 + int(ys.min()), y0 + int(ys.max()) + 1
                if x1 - x0 < spacing * 1.2 or yy1 - yy0 < spacing * 1.2:
                    continue
                marks.append({"system": i, "x": x0, "y": yy0,
                              "w": x1 - x0, "h": yy1 - yy0})

    geo = {
        "marks": marks,
        "spacing": round(spacing, 2),
        "headerCut": max(0, head_cut),
        "footerCut": max(0, foot_cut),
        "inkThreshold": cv.otsu_threshold(img),
        "staffEditOk": spacing >= MIN_SPACING_FOR_STAFF_EDIT,
        # 서버가 확대한 배율. 브라우저는 렌더 전에 같은 배율로 확대해야
        # 좌표(오선·코드 상자·가사 띠)가 맞는다.
        "scale": 1.0,
        "systems": out,
    }

    # 조표 영역은 오선 제거가 필요해 저해상도에서 실패한다(README 참고).
    # 되는 해상도에서만 좌표를 실어 보낸다.
    if geo["staffEditOk"]:
        import keysig
        for entry, g in zip(out, keysig.geometry_for(strict, staves, src_fifths)):
            entry.update(g)
    return geo


class Stopwatch:
    """
    단계별 소요 시간을 남긴다.

    왜: "느리다"로는 못 고친다. 실측(맥)에서는 LLM 두 번이 92% 였는데
    서버(CPU)는 총 시간이 4배라 비율이 다를 수밖에 없다 — 어디를 줄일지
    숫자 없이 고르면 엉뚱한 데를 판다.
    """

    def __init__(self, label: str):
        self.label = label
        self.t0 = self.last = time.time()
        self.marks: list[tuple[str, float]] = []

    def lap(self, name: str) -> None:
        now = time.time()
        self.marks.append((name, now - self.last))
        self.last = now

    def report(self) -> dict:
        total = time.time() - self.t0
        if self.marks:
            parts = " · ".join(f"{n} {v:.1f}s" for n, v in self.marks if v >= 0.05)
            print(f"  [{self.label}] 합계 {total:.1f}s — {parts}", file=sys.stderr)
        return {"totalSeconds": round(total, 2),
                "stages": {n: round(v, 2) for n, v in self.marks}}


def read_sheet(image_bytes: bytes, key_hint: str | None) -> dict:
    """
    이미지 → 구조 데이터. 여기서 이미지는 메모리에만 존재하고 저장되지 않는다.
    """
    from PIL import Image

    import detect_chords
    import prepare
    import read_chords

    sw = Stopwatch("판독")
    # **두 번째 판독기를 먼저 띄운다.** homr 는 별도 프로세스라 우리 판독과
    # 나란히 돈다(monsil 실측 장당 16초 — 우리 쪽 25초 안에 끝난다).
    import homr_runner
    homr_pool = homr_task = None
    if homr_runner.available():
        homr_pool = _cf.ThreadPoolExecutor(max_workers=1)
        homr_task = homr_pool.submit(homr_runner.read, image_bytes)
    img = prepare.load(io.BytesIO(image_bytes))

    # ① 품질 진단 — 사진이면 기울기 보정까지 된 이미지를 받는다
    report, img, ink, staves = prepare.analyze_image(img)
    sw.lap("전처리·오선")
    # 확대했으면 브라우저도 같은 배율로 확대해야 좌표가 맞는다

    # **오선이 없으면 여기서 끝낸다.** 그냥 진행하면 오선 간격 중앙값이
    # NaN 이 되어 `cannot convert float NaN to integer` 가 그대로 사용자
    # 화면에 뜬다(ValueError 라 사유가 전달된다) — 실측으로 확인했다.
    if not staves:
        import local_reader
        raise ValueError(local_reader.blank_reason(ink) or
                         "이 이미지에서 오선을 찾지 못했습니다. "
                         "악보가 맞는지, 잘리거나 흐리지 않은지 확인해 주세요.")

    # ② 코드 박스 검출
    detect = detect_chords.detect_from_ink(img, ink, staves)
    sw.lap("코드상자")

    # ③ AI 판독 (조각 격자 1회 호출)
    boxes = read_chords.flatten_boxes(detect)
    if not boxes:
        # **무엇이 없는지 정확히 말한다.** 오선이 아예 없으면 악보가 아닌
        # 이미지(빈 페이지·표지)이고, 오선은 있는데 코드 상자가 없으면
        # 코드가 안 적힌 악보다 — 사용자가 할 일이 다르다.
        # **던져야 화면에 뜬다.** 에러를 결과 dict 로 돌려주면 작업은
        # status=done 이 되고 브라우저는 result.error 를 보지 않는다 —
        # 빈 페이지를 올리면 "성공"인데 화면만 깨졌다.
        # ValueError 는 jobs._reason 이 사용자에게 그대로 전달한다.
        raise ValueError(f"오선 {len(staves)}단은 찾았지만 코드 기호를 찾지 "
                         "못했습니다. 코드가 적힌 악보를 올려 주세요.")
    collage, n = read_chords.build_collage(img, boxes)
    # **LLM 호출과 CPU 작업을 겹친다.** 코드 판독은 네트워크 대기이고
    # 조표 세기는 YOLO 계산이라 서로 막지 않는다 — 실측(서버) 각각
    # 8.4초·10.4초를 순서대로 기다리고 있었다.
    ks_pool = _cf.ThreadPoolExecutor(max_workers=1)
    ks_task = ks_pool.submit(_keysig_counts_safe, img)
    reads = read_chords.read(collage, n)
    sw.lap("코드LLM")

    meta = {"key": key_hint or "C", "pageCount": 1}
    extraction = read_chords.to_extraction(detect, boxes, reads, meta)
    extraction["quality"] = report
    import render

    # **원조성을 코드에서 추론한다.** 이걸 모르면 keysig.locate 가 조표를
    # 찾지 못한다(source_fifths == 0 이면 즉시 None을 반환한다). 그러면
    # 브라우저가 조표를 못 바꾸고, 안전 규칙에 따라 음표도 못 옮긴다 —
    # 실측: 마커스 악보가 웹에서만 "코드만 변환"으로 끝났다. CLI는 --key 로
    # 조성을 받으므로 같은 악보에서 조표 9단을 정상 교체했다.
    # 조표 세기는 **한 번만** 한다 — 아래 조성 추정과 _read_structure 의
    # 구간별 조표가 같은 결과를 나눠 쓴다.
    import guesskey as G_
    ks_counts = ks_task.result()
    ks_pool.shutdown(wait=False)

    if not key_hint:
        import guesskey
        texts = [c["text"] for sysd in extraction["systems"]
                 for c in sysd["chords"] if c.get("text")]
        # **조표를 세서 우선 근거로 쓴다.** 코드 통계만으로는 조성이 갈린다
        # (실측: 위싱 콘티의 `Bb C F Gm F/A`를 Bb키로 추정했으나 실제는 F키 —
        # 조표는 ♭ 하나로 명확했다. 원조성이 틀리면 모든 코드가 틀린다).
        fifths_seen = G_.keysig_fifths(ks_counts) if ks_counts else None
        sw.lap("조성추정(YOLO)")
        guessed, conf, why = guesskey.guess_with_keysig(texts, fifths_seen)
        meta["key"] = guessed
        extraction["meta"]["key"] = guessed
        extraction["keyGuess"] = {"key": guessed, "confidence": conf,
                                  "basis": why}
    src_fifths = render.call_engine(meta["key"], 0, [])["fifthsFrom"]
    sw.lap("엔진호출")
    # ── 렌더용 확대 ─────────────────────────────────────────────────
    # 판독은 원본 크기에서 끝났다(확대본에서 코드를 찾으면 오선 위 흐릿한 띠가
    # 밴드를 삼킨다 — prepare 주석 참고). 이제 **렌더 품질**을 위해 확대하고,
    # 좌표를 전부 그 배율로 옮긴다. 브라우저도 같은 배율로 확대해서 그린다.
    import sheetcv as cv

    scale = float(report.get("upscale", 1.0))
    if scale > 1.0:
        big = img.resize((round(img.width * scale), round(img.height * scale)),
                         Image.LANCZOS)
        ink_b, staves_b = cv.find_staves_best(big)
        sw.lap("확대·오선재검출")
        # **단 개수가 같을 때만 확대본을 쓴다.** LANCZOS 가 옅은 오선을 번지게
        # 해 확대본에서 단이 사라진다 — 실측 105장 중 16장, set0816-5 는 1번
        # 도돌이 줄이 통째로 빠진 채 '통과'했다(펜 학습 모델). local_reader 는
        # 이미 이렇게 한다. 원본 잉크를 키워 쓰는 쪽도 재 봤지만 통과 0 그대로.
        if staves_b and len(staves_b) == len(staves):
            r = lambda v: int(round(v * scale))
            for sysd in extraction["systems"]:
                for k in ("staffTop", "staffBottom", "headEnd"):
                    if k in sysd:
                        sysd[k] = r(sysd[k])
                for c in sysd["chords"]:
                    b = c["box"]
                    b["x"], b["y"] = r(b["x"]), r(b["y"])
                    b["w"], b["h"] = max(1, r(b["w"])), max(1, r(b["h"]))
            img, ink, staves = big, ink_b, staves_b
        else:
            scale = 1.0

    # **겹치기 ②: 개수 LLM(네트워크) ∥ 가사·기하(CPU).**
    # 개수 판독은 뒤(_read_structure)에서야 쓰이는데 24초가 걸린다. 지금
    # 시작해 두면 가사 띠·음절·고정물 계산(11초) 동안 같이 흐른다.
    # **이 시점의 img 로 시작해야 한다** — 아래에서 img 가 바뀌지 않는다.
    counts_pool = _cf.ThreadPoolExecutor(max_workers=1)
    counts_task = counts_pool.submit(_read_counts_safe, img)

    extraction["geometry"] = build_geometry(
        img, ink, staves, src_fifths,
        chord_boxes=_chord_boxes_by_system(extraction, len(staves)))
    sw.lap("가사·기하")
    extraction["geometry"]["scale"] = scale

    # **음표 머리 상자를 함께 보낸다.** 브라우저가 가사 띠를 원본으로 되돌릴
    # 때 이 자리를 비켜가야 한다 — 가사 띠는 오선 바로 아래부터 잡히므로
    # 아래로 이조하면 덧줄 음표가 그 안으로 내려온다(실측: 비켜가지 않으면
    # 머리 115개 중 36개가 잉크 절반 이하, 비켜가면 4개).
    # 이동량은 브라우저가 키를 고른 뒤 정해지므로 **이동 전 좌표**를 준다.
    extraction["imageSize"] = {"w": img.width, "h": img.height}

    # **개수를 먼저 읽는다.** 순서가 중요하다 — 단별 음표·쉼표 수를 알아야
    # 점수가 낮은 기호(속 빈 머리·2분쉼표)를 개수만큼 받을 수 있다.
    # 음가·붙임점·마디는 그 뒤에 **검출기가** 읽는다(tools/detstruct.py).
    # 서버는 여전히 악보 이미지를 만들지 않는다 — 구조 데이터만 낸다.
    struct, heads = _read_structure(
        img, ink, staves, sw=sw, ks_counts=ks_counts,
        counts_task=counts_task,
        head_ends=[int(s.get("headEnd") or 0)
                   for s in extraction["geometry"]["systems"]],
        marks=extraction["geometry"].get("marks") or [],
        chords_by_system=[[c.get("text") for c in (sysd.get("chords") or [])
                           if c.get("text")]
                          for sysd in extraction["systems"]])
    # **원조표를 struct 에 실어 준다.** local 경로는 넣는데 ai 경로는
    # 빠뜨리고 있었다(실측 25장 전부 sourceFifths=None). rebuild.js 는
    # `sysd.srcFifths ?? struct.sourceFifths` 로 읽으므로, 단별 값이 없는
    # 단에서 폴백이 없어 "원조표 미확정"으로 차단된다.
    if isinstance(struct, dict):
        struct.setdefault("sourceFifths", int(src_fifths))
    extraction["struct"] = struct
    extraction["geometry"]["heads"] = heads
    # **막대선을 함께 보낸다.** 브라우저가 코드를 어느 마디에 놓을지 정하려면
    # 마디 경계가 필요하다. CV 막대선 검출은 저해상도에서 과검출하지만
    # LLM이 마디 수를 주므로 그 수에 맞춰 고를 수 있다(실측: 9단 전부 정확).
    if struct and struct.get("systems"):
        _add_barlines(extraction["geometry"], ink, staves, struct, heads)

    # **품질 게이트는 ai 경로에도 있어야 한다.** 없으면 브라우저가
    # `qualityGate?.status !== 'ready'` 로 보고 **저장 버튼을 영영 잠근다** —
    # 판독이 완벽해도 PDF·PNG 를 못 받는다(실측: 배포된 기본 모드가 ai 라
    # 사이트에서 변환 결과를 아무도 못 받고 있었다).
    # **교차 검증 — 게이트 바로 앞.** 두 판독기가 같게 읽은 마디는 확정,
    # 우리만 박이 어긋난 마디는 homr 음가로, 둘 다 맞는데 다르면 막는다
    # (tools/crosscheck.py). homr 가 없거나 실패하면 우리 판독 그대로.
    if homr_task is not None and struct.get("systems"):
        import crosscheck
        try:
            theirs = homr_task.result(timeout=homr_runner.TIMEOUT)
        except Exception:                                   # noqa: BLE001
            theirs = None
        extraction["crossCheck"] = crosscheck.merge(struct, theirs)
        sw.lap("교차검증")
    if homr_pool is not None:
        homr_pool.shutdown(wait=False)

    import local_reader
    gate_issues = [struct["error"]] if struct.get("error") else []
    extraction["qualityGate"] = local_reader.quality_gate(extraction, gate_issues)
    sw.lap("품질게이트")
    counts_pool.shutdown(wait=False)
    extraction["timing"] = sw.report()
    return extraction


def _add_barlines(geo: dict, ink, staves, struct: dict,
                  heads: list[dict]) -> None:
    """단마다 `bars`(막대선 x 목록)를 실어 준다. 실패하면 None."""
    try:
        import layout as L
        import sheetcv as cv

        sp = cv.median_spacing(staves)
        strict = cv.remove_staff_lines(ink, staves, protect_noteheads=True)
        for i, (st, entry) in enumerate(zip(staves, geo["systems"])):
            entry["bars"] = None
            if i >= len(struct["systems"]):
                continue
            want = struct["systems"][i].get("measures") or 0
            if want <= 1:
                entry["bars"] = []
                continue
            mine = [h for h in heads
                    if st.top - sp * 4 <= h["y"] + h["h"] / 2 <= st.bottom + sp * 4]
            bars = L.barlines_fit(strict, st, sp, mine, want)
            entry["bars"] = [int(round(x)) for x in bars]
    except Exception as e:                       # noqa: BLE001
        print(f"  막대선 계산 실패: {e}", file=sys.stderr)


def _read_structure(img, ink, staves, chords_by_system=None, sw=None,
                    ks_counts=None, counts_task=None, head_ends=None,
                    marks=None) -> tuple[dict | None, list[dict]]:
    """
    구조(음가·붙임점·마디)와 음표 머리 상자를 함께 낸다.

    **LLM에는 단별 음표·쉼표 개수만 묻는다.** 음가·붙임점·마디는 검출기와
    그림에서 나온다 — 실측 근거는 tools/detstruct.py 첫머리에 있다.
    출력 토큰이 33,536 → 4,768로 줄고 결과는 같았다(마커스: 마디 수 9단
    전부 일치 · 박자 37정확 · 배관 132/132).

    검출은 **한 번만** 한다 — 구조와 머리 상자가 같은 검출을 쓴다.
    개수 판독이 실패하면 옛 경로(LLM이 음가·마디까지 읽는 struct)로 물러난다.
    MUTE_LLM_STRUCT=1 이면 처음부터 옛 경로를 쓴다.
    """
    if os.environ.get("MUTE_LLM_STRUCT") == "1":
        st = _read_struct_llm(img)
        expect = ([sum(1 for n in s.get("notes", []) if not n.get("rest"))
                   for s in st["systems"]]
                  if st and st.get("systems") else None)
        return st, _head_boxes(img, expect)

    try:
        import readcounts as RC

        # 미리 띄워 둔 작업이 있으면 결과만 받는다 (가사·기하와 겹쳐 돌았다)
        counts = (counts_task.result() if counts_task is not None
                  else RC.read_page(img))
        if counts is None:
            raise RuntimeError("개수 판독 실패")
        counts = counts["systems"]
        if sw:
            sw.lap("개수LLM(대기)")
    except Exception as e:                       # noqa: BLE001
        print(f"  개수 판독 실패, LLM 구조 판독으로 물러납니다: {e}",
              file=sys.stderr)
        st = _read_struct_llm(img)
        expect = ([sum(1 for n in s.get("notes", []) if not n.get("rest"))
                   for s in st["systems"]]
                  if st and st.get("systems") else None)
        return st, _head_boxes(img, expect)

    try:
        import numpy as np
        from ultralytics import YOLO

        import detstruct as DS
        import evaldet as E
        import sheetcv as cv

        w = _model_path()
        if not w:
            return {"error": "검출기 가중치가 없습니다"}, []
        ex, exr = DS.expects(counts)
        boxes, detmeta = E.detect_guided(load_model(str(w)), img, ex,
                                         conf_hi=0.50, expect_rests=exr, head_ends=head_ends,
                                         skip_boxes=marks)
        if sw: sw.lap("머리검출")
        sp = cv.median_spacing(staves)
        strict = cv.remove_staff_lines(ink, staves, protect_noteheads=True)
        gray = np.asarray(img.convert("L")).astype("float32")
        # **곡선(붙임줄)은 다른 모델로 따로 검출한다** — 근거는
        # tools/detstruct.py detect_curves 주석. 없으면 붙임줄만 비운다.
        curves = None
        tm = os.environ.get("MUTE_TIE_MODEL") or str(
            Path(__file__).resolve().parent.parent / "models" / "omr_tie.pt")
        if Path(tm).exists():
            curves = DS.detect_curves(img, tm, ex, exr)
            if sw: sw.lap("이음줄")
        # **단별 원조 조표(전조).** 곡 중간에 키가 바뀌는 콘티가 있다.
        # 판정 근거는 guesskey.keysig_sections 주석 참고.
        sections = None
        try:
            import guesskey as GK
            sections = GK.keysig_sections(
                ks_counts if ks_counts is not None
                else E.keysig_counts(load_model(str(w)), img))
            if sw: sw.lap("조표")
            # **조표 세기만 믿지 않는다.** 붙어 있는 임시표는 덜 세이기 쉽다
            # (실측: Bb장조 ♭2 를 ♭1 로 → +2 이조 시 C장조 자리에 ♯1개).
            # 같은 구간의 코드가 조성을 말해 주므로 그걸로 검증한다.
            if chords_by_system:
                sections = GK.fix_sections_with_chords(sections, chords_by_system)
        except Exception as e:                   # noqa: BLE001
            print(f"  단별 조표 실패: {e}", file=sys.stderr)
        # **수리 스위치는 local 경로와 같은 것을 쓴다.** 여기서 안 넘기면
        # build_from 의 기본값(repair=True)이 붙어, local_reader 의 환경변수로
        # 끄고 재는 A/B 가 **ai 경로에 아무 영향도 못 준다** — 측정 도구가
        # 실제 경로와 달라지는 그 함정이다.
        import local_reader as LR
        struct = DS.build_from(boxes, staves, strict, sp, gray, counts,
                               curves=curves, sections=sections,
                               meta=detmeta, head_ends=head_ends,
                               dots=LR.DOT_PROMOTE, repeats=LR.REPEAT_FIX,
                               merged=LR.SPLIT_MERGED, fit=LR.FIT_PAGE,
                               # 쉼표 붙임점이 손글씨인지 가리는 데 쓴다
                               rgb=np.asarray(img.convert("RGB")))
        if sw: sw.lap("구조조립")
        heads = [{"x": int(b["x"]), "y": int(b["y"]),
                  "w": int(b["w"]), "h": int(b["h"]), "cls": b["class"]}
                 for b in boxes if b["class"].startswith("notehead")]
        return struct, heads
    except Exception as e:                       # noqa: BLE001
        print(f"  구조 조립 실패: {e}", file=sys.stderr)
        return {"error": str(e)[:200]}, []


def _model_path():
    """검출기 가중치. 학습 중인 것으로 시험할 수 있게 환경변수를 본다."""
    w = Path(os.environ.get("MUTE_MODEL") or
             Path(__file__).resolve().parent.parent / "models" / "omr.pt")
    return w if w.exists() else None


def _read_struct_llm(img) -> dict | None:
    """
    단별 음가·마디 수를 판독한다. 실패하면 None — 그때 브라우저는 예전
    픽셀 이동 경로로 물러난다.

    주의: 확대본(img)이 아니라 **원본 비율**로 넘겨도 readstruct가 안에서
    6배로 다시 확대한다. 확대본을 또 확대하면 메모리만 먹는다.
    """
    try:
        import readstruct as RS
        return RS.read_page(img)
    except Exception as e:                       # noqa: BLE001
        # **실패를 삼키지 않는다.** 구조가 없으면 브라우저가 예전 픽셀 경로로
        # 물러나는데, 그 이유를 알려주지 않으면 "왜 갑자기 품질이 다르지"가
        # 된다. 사유를 실어 보낸다.
        print(f"  구조 판독 실패: {e}", file=sys.stderr)
        return {"error": str(e)[:200]}


def _read_counts_safe(img):
    """readcounts 를 스레드에서 돌리는 판. 실패는 None 으로 돌려준다."""
    try:
        import readcounts as RC
        return RC.read_page(img)
    except Exception as e:                       # noqa: BLE001
        print(f"  개수 판독 실패: {e}", file=sys.stderr)
        return None


def _keysig_counts_safe(img):
    """_keysig_counts 의 예외를 삼키는 판 — 스레드에서 쓴다."""
    try:
        return _keysig_counts(img)
    except Exception as e:                       # noqa: BLE001
        print(f"  조표 세기 실패: {e}", file=sys.stderr)
        return None


def _keysig_counts(img):
    """
    조표의 ♯/♭ 개수를 단별로 센다. **확대본에서** 센다.

    한 번만 세고 두 군데(전체 조성 추정 · 구간별 조표)가 나눠 쓴다. 전에는
    각자 YOLO 를 돌렸는데, 서버(CPU)에서 그 한 번이 15.9초였고 구간별 쪽은
    원본 크기에서 세느라 덜 정확하기까지 했다.
    """
    from pathlib import Path as _P

    import evaldet as E
    import probe as P
    w = _P(os.environ.get("MUTE_MODEL") or
           _P(__file__).resolve().parent.parent / "models" / "omr.pt")
    if not w.exists():
        return None
    big, factor = P.upscale(img.convert("RGB"))
    return E.keysig_counts(load_model(str(w)), big.convert("L"))


def _keysig_fifths(img) -> int | None:
    """
    조표의 ♯/♭ 개수를 세서 fifths를 낸다. 실패하면 None.

    **확대본에서 센다.** 조표의 임시표는 붙어 있고 작아서 원본 크기(오선 간격
    6~7px)에서는 거의 안 잡힌다 — 그러면 조용히 None이 되어 코드 통계로
    돌아간다(직접 겪었다: 서버가 원본에서 세다가 아무것도 못 찾았다).
    """
    try:
        from ultralytics import YOLO

        import evaldet as E
        import guesskey as G
        import probe as P
        w = Path(os.environ.get("MUTE_MODEL") or
                 Path(__file__).resolve().parent.parent / "models" / "omr.pt")
        if not w.exists():
            return None
        big, factor = P.upscale(img.convert("RGB"))
        counts = E.keysig_counts(load_model(str(w)), big.convert("L"))
        fifths = G.keysig_fifths(counts)
        print(f"  조표: 확대 {factor:.2f}배 · 단별 {counts} → fifths {fifths}",
              file=sys.stderr)
        return fifths
    except Exception as e:                       # noqa: BLE001
        print(f"  조표 세기 실패: {e}", file=sys.stderr)
        return None


def _head_boxes(img, expect: list[int] | None = None) -> list[dict]:
    """학습된 검출기로 음표 머리 상자를 찾는다. 없으면 빈 목록."""
    try:
        from ultralytics import YOLO

        import evaldet as E
        w = _model_path()
        if not w:
            return []
        model = load_model(str(w))
        if expect:
            # **개수를 단서로 문턱을 정한다.** 하나의 문턱으로는 꽉 찬 머리
            # (점수 0.9대)와 속 빈 머리(0.03~0.58)를 같이 못 잡는다
            # (실측: 머리 116→129, 흰 1→9).
            boxes, _m = E.detect_guided(model, img, expect, conf_hi=0.50)
        else:
            boxes, _m = E.detect_by_staff(model, img, 0.50)
        return [{"x": int(b["x"]), "y": int(b["y"]),
                 "w": int(b["w"]), "h": int(b["h"]),
                 "cls": b["class"]}
                for b in boxes if b["class"].startswith("notehead")]
    except Exception:
        return []


def read_with_mode(blob: bytes, opts: dict, progress=None) -> dict:
    """모드에 맞는 판독기를 고른다. local 이 기본이고 외부 호출이 없다."""
    step = progress or (lambda *_a: None)
    if STATE["mode"] == "ai":
        step("ai", 10)
        return read_sheet(blob, opts.get("keyHint"))
    import local_reader
    return local_reader.read_sheet_local(blob, opts.get("keyHint"),
                                         opts.get("timeSignature"), step)


def check_image(blob: bytes) -> str | None:
    """헤더만 읽어 이미지인지·크기가 감당되는지 본다. 문제면 사유 문자열."""
    try:
        with Image.open(io.BytesIO(blob)) as im:
            if not im.format:
                return "이미지 형식을 알 수 없습니다."
            w, h = im.size
    except Exception:                            # noqa: BLE001
        return "이미지를 열 수 없습니다."
    if w * h > MAX_PIXELS:
        return f"이미지 화소가 너무 많습니다 (최대 {MAX_PIXELS // 1_000_000}MP)."
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "mut-dev"
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    # ---------------------------------------------------------- 응답 도우미
    def _json(self, code: int, payload: dict) -> None:
        # 거절은 본문을 읽기 전에 한다(그게 요점이다). 그러면 연결에 안 읽은
        # 바이트가 남아 다음 요청 파싱이 어긋나므로 여기서 연결을 끊는다.
        if code >= 400:
            self.close_connection = True
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # 업로드물이 캐시에 남지 않도록
        self.send_header("Cache-Control", "no-store")
        if code >= 400:
            # A rejected body may be unread. Never parse it as the next request.
            self.close_connection = True
            self.send_header('Connection', 'close')
        for c in getattr(self, "_cookies", ()):
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------- 세션·출처
    def _session(self) -> str:
        """서명된 로컬 쿠키. 없으면 만들어 첫 응답에 실어 보낸다."""
        raw = ""
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                raw = v
        sid = _unsign(raw) if raw else None
        if not sid:
            sid = STATE["store"].new_session()
        # **쿠키를 매번 다시 굽는다.** 속성은 브라우저가 들고 있어서, 만들 때만
        # 구우면 이미 Strict 로 받아 간 사람은 세션이 살아 있는 한 영원히
        # Strict 다 — 그 사람들은 카카오 로그인이 계속 실패한다.
        # **Strict 가 아니라 Lax 다.** Strict 로 두면 카카오에서
        # /auth/kakao/callback 으로 돌아올 때 브라우저가 쿠키를 빼고 보내서,
        # 콜백이 세션을 새로 만들고 state 대조가 통째로 실패한다(실측:
        # 로그인이 끝까지 안 됐다). Lax 는 최상위 GET 이동에만 쿠키를 싣고
        # 남의 사이트발 POST 에는 안 싣는다 — 상태 변경 요청은 어차피
        # _same_origin() 이 따로 막는다.
        sec = "; Secure" if (STATE["origin"] or "").startswith("https") else ""
        self._cookies = [
            f"{COOKIE}={_sign(sid)}; Path=/; HttpOnly; SameSite=Lax{sec}"]
        STATE["store"].touch(sid)
        self._master_check(sid)
        return sid

    def _master_check(self, sid: str) -> None:
        """
        `?master=<키>` 로 들어오면 그 **세션에만** 무제한 권한을 준다.

        전역 무제한으로 두지 않는 이유: 공개 주소라서 누구나 판독을 무한히
        돌릴 수 있게 되고, 그 비용은 개인 API 키에서 나간다(실측 장당 약 40원).
        키는 서버 환경변수로만 들어오고 응답에 다시 싣지 않는다.
        """
        key = os.environ.get("MUTE_MASTER_KEY") or ""
        if not key:
            return
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if (q.get("master") or [""])[0] == key:
            STATE["store"].grant_master(sid)

    def _same_origin(self) -> bool:
        """
        상태를 바꾸는 요청은 로컬 페이지에서 온 것만 받는다.

        Host 를 함께 보는 이유: DNS 리바인딩은 브라우저가 우리 주소로 붙되
        Host 에 남의 도메인을 실어 보낸다. SameSite 만으로는 부족하다.
        """
        host = self.headers.get('Host') or ''
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        pub = STATE["origin"]          # 예: https://conti.eungming.com
        if pub:
            allowed.add(urllib.parse.urlsplit(pub).netloc)
        if host not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin in (f'http://{host}', pub) if pub else origin == f'http://{host}'

    def _client_ip(self) -> str:
        """
        프록시 뒤에서는 client_address 가 전부 127.0.0.1 이라 IP 제한이
        전 세계 공용 12회/시가 된다. **공개 출처가 설정됐을 때만**
        X-Forwarded-For 를 믿는다 — 직접 노출됐을 땐 위조 헤더로
        제한을 우회할 수 있으므로 절대 보지 않는다.
        """
        if STATE["origin"]:
            xff = self.headers.get("X-Forwarded-For")
            if xff:
                return xff.split(",")[0].strip()
        return self.client_address[0]

    def _file(self, path: Path) -> None:
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in (".js", ".mjs"):
            ctype = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8"
                         if ctype.startswith("text/") else ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        # **정적 응답도 쿠키를 실어야 한다.** 앱 페이지로 처음 들어오면
        # 여기로 나가는데, 쿠키를 안 붙이면 세션이 매 요청 새로 생긴다
        # (마스터 권한도 그래서 붙지 않았다).
        for c in getattr(self, "_cookies", ()):
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(data)

    # ---------------------------------------------------------- 라우팅
    def do_GET(self) -> None:
        if not self._same_origin():
            self._json(403, {'error': '허용되지 않은 출처입니다.'})
            return
        route = self.path.split("?")[0]
        store = STATE["store"]

        if route == "/api/health":
            self._session()
            import local_reader
            self._json(200, {"mode": STATE["mode"], "ok": True,
                             "modelPresent": local_reader.model_path() is not None,
                             **store.health()})
            return
        if route == "/api/account":
            self._json(200, store.account(self._session()))
            return
        if route.startswith("/api/jobs/"):
            jid = route[len("/api/jobs/"):]
            job = store.get(self._session(), jid) if jid else None
            if job is None:
                self._json(404, {"error": "작업을 찾을 수 없습니다."})
                return
            self._json(200, job)
            return
        if route.startswith("/api/"):
            self._json(404, {"error": "not found"})
            return
        if route.startswith("/auth/"):
            rest = route[len("/auth/"):]
            p, _, tail = rest.partition("/")
            if p in self.OAUTH and tail in ("", "callback"):
                (self._oauth_callback if tail else self._oauth_start)(p)
                return
        if route == "/dev/sheet":
            if not dev_enabled():
                self._json(404, {"error": "not found"})
                return
            q = urllib.parse.parse_qs(self.path.split("?", 1)[-1])
            name = (q.get("name") or [""])[0]
            # 디렉터리 탈출 금지 — 파일 이름만 받는다
            if not name or "/" in name or ".." in name:
                self._json(400, {"error": "이름이 올바르지 않습니다."})
                return
            f = (Path(DEV_DIR) / name).resolve()
            if not f.is_file() or Path(DEV_DIR).resolve() not in f.parents:
                self._json(404, {"error": "없는 파일"})
                return
            self._file(f)
            return

        # **앱 경로는 index.html 로 되돌린다.** 화면은 둘뿐이다(변환·계정).
        # 이게 없으면 /account 를 새로고침했을 때 404 가 뜬다.
        if route in ("/", "/login", "/signup", "/account",
                     "/faq", "/contact", "/terms", "/privacy", "/oss"):
            # 세션을 여기서 연다 — `?master=` 도 이 경로로 들어온다
            self._session()
            route = "/index.html"
        target = (WEB / route.lstrip("/")).resolve()
        # 디렉터리 탈출 방지. 문자열 접두사 비교는 /web-secret 같은 형제
        # 경로를 통과시킨다 — 경로 단위로 따진다.
        try:
            target.relative_to(WEB_ROOT)
        except ValueError:
            self._json(404, {"error": "not found", "path": route})
            return
        if not target.is_file():
            self._json(404, {"error": "not found", "path": route})
            return
        self._file(target)

    def do_POST(self) -> None:
        route = self.path.split("?")[0]
        if not self._same_origin():
            self._json(403, {"error": "허용되지 않은 출처입니다."})
            return

        # **거부는 한 곳에서 답한다.** 핸들러마다 따로 잡다 보면 빠뜨리는
        # 데가 생기고, 그러면 파이썬 예외가 그대로 올라가 서버가 **응답 없이
        # 연결을 끊는다**(실측: 로그인 없이 /api/jobs 를 때리면 그랬다).
        # 화면은 "네트워크 오류"로 보이고, 진짜 이유인 403 은 사라진다.
        try:
            if route == "/api/jobs":
                self._post_job()
            elif route.startswith("/api/jobs/") and route.endswith("/commit"):
                self._post_commit(route[len("/api/jobs/"):-len("/commit")])
            elif route == "/api/read":
                self._post_read()
            elif route == "/api/login":
                self._post_login()
            elif route == "/api/signup":
                self._post_signup()
            elif route == "/api/agree":
                self._post_agree()
            elif route == "/api/profile":
                self._post_profile()
            elif route == "/api/logout":
                STATE["store"].revoke_auth(self._session())
                self._json(200, {"ok": True})
            elif route == "/dev/save" and dev_enabled():
                self._dev_save()
            else:
                self._json(404, {"error": "not found"})
        except jobs.Denied as e:
            self._json(403, {"error": str(e)})
        except jobs.Busy as e:
            self._json(429, {"error": str(e)})

    # ──────────────────────────────────── 간편 로그인 (카카오·네이버)
    # 받는 것은 **회원번호와 닉네임뿐**이다. 이메일·전화번호는 받지 않는다 —
    # 받는 순간 개인정보 보관 의무가 생기는데, 크레딧 장부에는 회원번호
    # 하나면 충분하다. CI(연계정보)도, 휴대폰 본인인증(PASS)도 필요 없다:
    # 본인확인기관을 거쳐야 하고 건당 비용이 드는데, 우리는 "같은 사람인가"만
    # 알면 되고 "누구인가"는 알 필요가 없다. 결제자 본인확인은 카드사 몫이다.
    OAUTH = {
        "kakao": {
            "name": "카카오",
            "auth": "https://kauth.kakao.com/oauth/authorize",
            "token": "https://kauth.kakao.com/oauth/token",
            "me": "https://kapi.kakao.com/v2/user/me",
            "key": "KAKAO_REST_KEY", "secret": "KAKAO_SECRET",
            # **scope 를 보내지 않는다.** 콘솔이 이미 닉네임·프로필사진
            # 말고는 전부 "권한 없음" 으로 막고 있어서, 여기서 또 지정해도
            # 더 좁혀지는 게 없다. 반대로 콘솔 상태와 조금이라도 어긋나면
            # KOE205 로 로그인이 통째로 막힌다(실측). 동의항목은 콘솔
            # 하나만 보고 간다 — 네이버와 같은 방식이다.
            "scope": "",
        },
        "naver": {
            "name": "네이버",
            "auth": "https://nid.naver.com/oauth2.0/authorize",
            "token": "https://nid.naver.com/oauth2.0/token",
            "me": "https://openapi.naver.com/v1/nid/me",
            "key": "NAVER_CLIENT_ID", "secret": "NAVER_CLIENT_SECRET",
            # 네이버는 scope 파라미터가 없다 — 제공 항목을 콘솔에서 정한다.
            # 별명 하나만 체크해 두면 된다.
            "scope": "",
        },
    }

    def _oauth_cfg(self, p: str):
        d = self.OAUTH.get(p)
        key = os.environ.get(d["key"]) if d else ""
        if not key:
            return None
        pub = STATE["origin"] or f"http://127.0.0.1:{self.server.server_port}"
        return d, key, os.environ.get(d["secret"]) or "", \
            f"{pub.rstrip('/')}/auth/{p}/callback"

    @staticmethod
    def _secure(url: str) -> str:
        """**http 로 온 사진 주소를 https 로 올린다.** 카카오·네이버 CDN 이
        http 주소를 주는데, 사이트는 https 라 브라우저가 혼합 콘텐츠로
        막는다 — 프로필 사진이 깨진 네모로 뜬다(실측). 두 CDN 모두 https
        로도 같은 파일을 준다."""
        return "https://" + url[7:] if url.startswith("http://") else url

    @classmethod
    def _profile(cls, p: str, me: dict) -> tuple[str, str, str]:
        """(회원번호, 닉네임, 프로필사진 URL). 닉네임·사진은 선택 동의라
        거절하면 빈 문자열로 온다 — 그래도 로그인은 성립한다."""
        if p == "naver":
            r = me.get("response") or {}
            return (str(r.get("id") or ""), r.get("nickname") or "",
                    cls._secure(r.get("profile_image") or ""))
        prof = ((me.get("kakao_account") or {}).get("profile") or {})
        return (str(me.get("id") or ""), prof.get("nickname") or "",
                cls._secure(prof.get("profile_image_url") or ""))

    def _oauth_start(self, p: str) -> None:
        cfg = self._oauth_cfg(p)
        if not cfg:
            self._json(503, {"error": "아직 설정되지 않은 로그인입니다."})
            return
        d, key, _secret, redirect = cfg
        sid = self._session()
        # **state 로 CSRF 를 막는다.** 이게 없으면 공격자가 자기 코드로
        # 남의 세션에 로그인시킬 수 있다(로그인 CSRF).
        state = secrets.token_urlsafe(16)
        _OAUTH_STATE[state] = (sid, p, time.time())
        args = {"client_id": key, "redirect_uri": redirect,
                "response_type": "code", "state": state}
        if d["scope"]:
            args["scope"] = d["scope"]
        self.send_response(302)
        self.send_header(
            "Location", f"{d['auth']}?{urllib.parse.urlencode(args)}")
        self.send_header("Cache-Control", "no-store")
        for c in getattr(self, "_cookies", ()):
            self.send_header("Set-Cookie", c)
        self.end_headers()

    def _oauth_callback(self, p: str) -> None:
        cfg = self._oauth_cfg(p)
        if not cfg:
            self._json(503, {"error": "아직 설정되지 않은 로그인입니다."})
            return
        d, key, secret, redirect = cfg
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        code = (q.get("code") or [""])[0]
        state = (q.get("state") or [""])[0]
        sid = self._session()
        want = _OAUTH_STATE.pop(state, None)
        # 오래된 state 는 버린다
        for k, (_s, _p, t) in list(_OAUTH_STATE.items()):
            if time.time() - t > 600:
                _OAUTH_STATE.pop(k, None)
        # **state 에 제공자까지 묶는다.** 안 묶으면 카카오로 받은 state 를
        # 네이버 콜백에 들이밀 수 있다.
        if not code or not want or want[0] != sid or want[1] != p:
            self._redirect_home("로그인을 마치지 못했습니다.")
            return
        try:
            args = {"grant_type": "authorization_code", "client_id": key,
                    "redirect_uri": redirect, "code": code}
            if secret:
                args["client_secret"] = secret
            if p == "naver":
                args["state"] = state
            req = urllib.request.Request(
                d["token"], data=urllib.parse.urlencode(args).encode(),
                headers={"Content-Type":
                         "application/x-www-form-urlencoded;charset=utf-8"})
            with urllib.request.urlopen(req, timeout=10) as r:
                tok = json.loads(r.read())
            access = tok.get("access_token") or ""
            if not access:
                raise ValueError("토큰이 없습니다")
            req2 = urllib.request.Request(
                d["me"], headers={"Authorization": f"Bearer {access}"})
            with urllib.request.urlopen(req2, timeout=10) as r:
                me = json.loads(r.read())
        except Exception as e:                     # noqa: BLE001
            # **토큰은 절대 로그에 남기지 않는다.**
            print(f"{d['name']} 로그인 실패: {type(e).__name__}", file=sys.stderr)
            self._redirect_home("로그인을 마치지 못했습니다.")
            return
        uid, nick, img = self._profile(p, me)
        if not uid:
            self._redirect_home("로그인을 마치지 못했습니다.")
            return
        store = STATE["store"]
        store.grant_auth(sid, user=f"{p}:{uid}", name=nick, image=img)
        # **처음 오신 분은 가입 화면으로.** 간편 로그인은 버튼 한 번에
        # 계정이 생기는데, 그대로 두면 약관 동의를 한 번도 안 받고 회원이
        # 된다. 동의 시각을 남길 수 없으면 분쟁에서 댈 게 없다.
        if store.account(sid).get("needsAgree"):
            self._redirect_to("/signup?welcome=1")
            return
        self._redirect_home()
    def _redirect_home(self, msg: str = "") -> None:
        self._redirect_to("/" + (f"?login={urllib.parse.quote(msg)}" if msg else ""))

    def _redirect_to(self, loc: str) -> None:
        self.send_response(302)
        self.send_header("Location", loc)
        self.send_header("Cache-Control", "no-store")
        for c in getattr(self, "_cookies", ()):
            self.send_header("Set-Cookie", c)
        self.end_headers()

    def _post_profile(self) -> None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(min(n, 8192)) or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        except Exception:                          # noqa: BLE001
            self._json(400, {"error": "요청을 읽지 못했습니다."})
            return
        try:
            self._json(200, STATE["store"].set_profile(self._session(), data))
        except jobs.Denied as e:
            self._json(403, {"error": str(e)})

    ID_RE = re.compile(r"[a-z0-9][a-z0-9_]{3,19}")
    PW_MIN = 8
    MAX_FAIL = 5                                   # 15분에 5번 틀리면 잠근다

    def _body_json(self, cap: int = 4096):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            d = json.loads(self.rfile.read(min(n, cap)) or b"{}")
            return d if isinstance(d, dict) else None
        except Exception:                          # noqa: BLE001
            return None

    def _post_signup(self) -> None:
        """아이디·비밀번호로 가입. 간편 로그인을 안 쓰는 사람을 위한 길."""
        import db
        if not db.configured():
            self._json(503, {"error": "가입을 아직 받을 수 없습니다."})
            return
        d = self._body_json()
        if d is None:
            self._json(400, {"error": "요청을 읽지 못했습니다."})
            return
        uid = str(d.get("id") or "").strip().lower()
        pw = str(d.get("pw") or "")
        email = str(d.get("email") or "").strip()
        if not self.ID_RE.fullmatch(uid):
            self._json(400, {"error": "아이디는 영문 소문자·숫자·밑줄 4~20자입니다."})
            return
        if len(pw) < self.PW_MIN:
            self._json(400, {"error": f"비밀번호는 {self.PW_MIN}자 이상이어야 합니다."})
            return
        if not jobs._looks_like_email(email):
            self._json(400, {"error": "이메일 주소를 다시 확인해 주세요."})
            return
        if not d.get("agree"):
            self._json(400, {"error": "약관에 동의해야 가입할 수 있습니다."})
            return
        full = f"local:{uid}"
        if db.get_user(full):
            self._json(409, {"error": "이미 쓰이고 있는 아이디입니다."})
            return
        sid = self._session()
        store = STATE["store"]
        db.create_local(full, pw, email, store.trial_balance)
        db.bind_session(sid, full)
        store.grant_auth(sid, user=full, name=uid)
        self._json(200, store.account(sid))

    def _post_agree(self) -> None:
        """간편 로그인으로 **처음** 들어온 사람의 약관 동의를 남긴다."""
        import db
        sid = self._session()
        u = STATE["store"].user_of(sid)
        if not (db.configured() and u):
            self._json(403, {"error": "로그인이 필요합니다."})
            return
        db.agree(u)
        self._json(200, STATE["store"].account(sid))

    def _post_login(self) -> None:
        """
        **심사용 계정 하나.** 카카오 로그인이 붙기 전까지 PG 심사자가
        결제 흐름을 확인할 수 있어야 한다 — 그것 때문에 사이트 전체를
        열어 두는 것보다 계정 하나를 주는 쪽이 낫다.

        아이디·비밀번호는 환경변수로만 들어온다(저장소에 없다). 비교는
        `secrets.compare_digest` 로 — 문자열 `==` 는 앞부분만 맞아도
        빨리 끝나 비밀번호를 한 글자씩 알아낼 수 있다.
        """
        d = self._body_json()
        if d is None:
            self._json(400, {"error": "요청을 읽지 못했습니다."})
            return
        if self._try_local_login(d):
            return
        want_id = os.environ.get("MUTE_REVIEW_ID") or ""
        want_pw = os.environ.get("MUTE_REVIEW_PW") or ""
        if not (want_id and want_pw):
            self._json(404, {"error": "not found"})
            return
        sid = self._session()
        ok = (secrets.compare_digest(str(d.get("id") or ""), want_id)
              and secrets.compare_digest(str(d.get("pw") or ""), want_pw))
        if not ok:
            time.sleep(0.5)                        # 무차별 대입을 늦춘다
            self._json(401, {"error": "아이디 또는 비밀번호가 맞지 않습니다."})
            return
        STATE["store"].grant_auth(sid)
        self._json(200, STATE["store"].account(sid))

    def _try_local_login(self, d: dict) -> bool:
        """
        아이디·비밀번호 로그인. 처리했으면 True.

        **15분에 5번 틀리면 잠근다.** 비밀번호는 언젠가 새어 나가고, 그때
        막아 주는 건 시도 횟수뿐이다. 아이디와 접속 주소 양쪽으로 센다 —
        아이디로만 세면 여러 계정을 돌려 가며 때리면 안 걸린다.
        """
        import db
        if not db.configured():
            return False
        uid = str(d.get("id") or "").strip().lower()
        pw = str(d.get("pw") or "")
        if not self.ID_RE.fullmatch(uid):
            return False
        full = f"local:{uid}"
        ip = self._client_ip() or "?"
        if (db.fail_count(full) >= self.MAX_FAIL
                or db.fail_count(ip) >= self.MAX_FAIL * 4):
            self._json(429, {"error": "시도가 너무 잦습니다. 15분 뒤 다시 해 주세요."})
            return True
        row = db.get_user(full)
        # **없는 아이디여도 해시를 한 번 돌린다.** 안 그러면 응답이 빨리
        # 돌아와서 어떤 아이디가 존재하는지 알아낼 수 있다.
        stored = (row or {}).get("pw_hash") or "scrypt$00$00"
        if not (row and db.check_pw(pw, stored)):
            db.note_fail(full)
            db.note_fail(ip)
            self._json(401, {"error": "아이디 또는 비밀번호가 맞지 않습니다."})
            return True
        db.clear_fails(full)
        sid = self._session()
        db.bind_session(sid, full)
        STATE["store"].grant_auth(sid, user=full, name=row.get("name") or uid)
        self._json(200, STATE["store"].account(sid))
        return True

    def _dev_save(self) -> None:
        """브라우저가 그린 결과를 개발 디렉터리에 떨어뜨린다(검증 자동화용)."""
        q = urllib.parse.parse_qs(self.path.split("?", 1)[-1])
        name = (q.get("name") or [""])[0]
        if not name or "/" in name or ".." in name:
            self._json(400, {"error": "이름이 올바르지 않습니다."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= 64 * 1024 * 1024:
            self._json(400, {"error": "크기가 올바르지 않습니다."})
            return
        out = Path(DEV_DIR) / "out"
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(self.rfile.read(length))
        self._json(200, {"saved": str(out / name)})

    # ---------------------------------------------------------- 엔드포인트
    def _body(self) -> bytes | None:
        """업로드 본문. 한도를 넘거나 형식이 아니면 여기서 응답하고 None."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if not ctype.startswith("image/"):
            self._json(415, {"error": "이미지 파일만 올릴 수 있습니다."})
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "Content-Length 가 올바르지 않습니다."})
            return None
        if length <= 0:
            self._json(400, {"error": "빈 요청입니다."})
            return None
        if length > MAX_UPLOAD:
            self._json(413, {"error": f"이미지가 너무 큽니다 "
                                      f"(최대 {MAX_UPLOAD // 1024 // 1024}MB)."})
            return None
        blob = self.rfile.read(length)
        if len(blob) != length:
            self._json(400, {"error": "요청이 끊겼습니다."})
            return None
        bad = check_image(blob)
        if bad:
            self._json(400, {"error": bad})
            return None
        return blob

    def _post_job(self) -> None:
        sid = self._session()
        blob = self._body()
        if blob is None:
            return
        opts = {"keyHint": self.headers.get("X-Key-Hint") or None,
                "timeSignature": self.headers.get("X-Time-Signature") or None,
                "mode": STATE["mode"]}
        if not self._valid_options(opts):
            return
        try:
            job, cached = STATE["store"].submit(
                sid, blob, opts, ip=self._client_ip())
        except jobs.Busy as e:
            self._json(429, {"error": str(e)})
            return
        finally:
            del blob
        self._json(202, {**job, "cached": cached})

    def _valid_options(self, opts) -> bool:
        import re
        key, signature = opts.get('keyHint'), opts.get('timeSignature')
        if key and not re.fullmatch(r'[A-G](?:#|b)?m?', key):
            self._json(400, {'error': '원본 조성 형식이 올바르지 않습니다.'})
            return False
        if signature and signature not in ('2/4','3/4','4/4','6/8','9/8','12/8'):
            self._json(400, {'error': '지원하는 박자를 선택해 주세요.'})
            return False
        return True

    def _post_commit(self, jid: str) -> None:
        sid = self._session()
        try:
            self._json(200, STATE["store"].commit(sid, jid))
        except KeyError:
            self._json(404, {"error": "작업을 찾을 수 없습니다."})
        except jobs.Denied as e:
            self._json(409, {"error": str(e)})

    def _post_read(self) -> None:
        """예전 동기 경로. 화면을 고치지 않아도 로컬 판독기를 쓰게 한다."""
        sid = self._session()
        blob = self._body()
        if blob is None:
            return
        opts = {"keyHint": self.headers.get("X-Key-Hint") or None,
                "timeSignature": self.headers.get("X-Time-Signature") or None,
                "mode": STATE['mode']}
        if not self._valid_options(opts):
            return
        try:
            job, _ = STATE['store'].submit(sid, blob, opts,
                                           ip=self._client_ip())
            del blob
            blob = None
            end = time.monotonic() + 120
            while time.monotonic() < end:
                current = STATE['store'].get(sid, job['id'])
                if current['status'] == 'done':
                    result = current['result']
                    break
                if current['status'] == 'failed':
                    self._json(422, {'error': current['error']})
                    return
                time.sleep(0.1)
            else:
                self._json(504, {'error': '처리가 오래 걸립니다. 같은 파일로 다시 시도해 주세요.'})
                return
        except (jobs.Busy, jobs.Denied):
            raise
        except Exception as exc:                 # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"error": jobs._safe_error(exc)})
            return
        finally:
            # 명시적으로 참조를 끊는다 — 저장하지 않는다는 설계를 코드로도 남긴다
            del blob

        self._json(200, result)


def build_server(port: int = 0, mode: str = "local", reader=None,
                 host: str = "127.0.0.1", origin: str | None = None,
                 **store_kw) -> ThreadingHTTPServer:
    """
    서버를 만들되 돌리지는 않는다. 판독기를 갈아 끼울 수 있어 테스트가
    모델·API 없이 프로토콜 전체를 확인할 수 있다.
    """
    STATE["mode"] = mode
    STATE["origin"] = origin.rstrip("/") if origin else None
    STATE["host"] = host
    # **서명 키는 재시작을 넘겨야 한다.** 매번 새로 만들면 기존 쿠키가
    # 전부 서명 검증에 실패하고, 재배포할 때마다 이용자 전원이 로그아웃된다
    # (실측). 없으면 그때만 임시로 만든다 — 로컬 개발용이다.
    env_secret = os.environ.get("MUTE_COOKIE_SECRET") or ""
    STATE["secret"] = (bytes.fromhex(env_secret) if len(env_secret) >= 32
                       else secrets.token_bytes(32))
    version = "fake"
    if reader is None:
        reader = read_with_mode
        try:
            import local_reader
            version = f"{mode}:{local_reader.model_version()}"
        except Exception:                        # noqa: BLE001
            version = mode
    STATE["store"] = jobs.JobStore(reader, reader_version=version, **store_kw)
    return ThreadingHTTPServer((host, port), Handler)


def warm_models() -> None:
    """
    검출 모델을 미리 올린다.

    왜: 모델 로드가 **첫 요청 한 사람에게 통째로 청구된다** — 실측(monsil,
    4코어 CPU) 첫 장 93초 · 둘째 장 32초. 3배 차이가 전부 로드였다.
    서버는 이미 떠 있으므로 백그라운드에서 조용히 데운다.
    """
    import threading as _t

    def go():
        base = Path(__file__).resolve().parent.parent / "models"
        for env, name in (("MUTE_MODEL", "omr.pt"), ("MUTE_TIE_MODEL", "omr_tie.pt")):
            w = os.environ.get(env) or str(base / name)
            if Path(w).exists():
                try:
                    load_model(w)
                    print(f"  모델 예열 완료: {Path(w).name}", file=sys.stderr)
                except Exception as e:           # noqa: BLE001
                    print(f"  모델 예열 실패 {Path(w).name}: {e}", file=sys.stderr)
        # 이음줄 쪽은 detstruct 가 자기 캐시를 쓴다 — 같은 파일을 한 번 태운다
        try:
            import detstruct as DS
            tie = os.environ.get("MUTE_TIE_MODEL") or str(base / "omr_tie.pt")
            if Path(tie).exists():
                DS._load(tie)
        except Exception:                        # noqa: BLE001
            pass

    _t.Thread(target=go, daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    # **기본은 ai.** local 은 검출기 자체 개수만 쓰는데, 그러면 검출기가 못
    # 읽는 단이 통째로 0개가 되어 "읽은 음표가 없어 원본 확인 필요"로 막힌다.
    # 실측(7장 220마디): ai 는 깨진 마디 18개(8%), local 은 94개(43%)다.
    ap.add_argument("--mode", choices=("local", "ai"), default="ai",
                    help="ai: 단별 개수만 LLM에 묻는다(기본) · local: 외부 호출 없음")
    ap.add_argument("--trial-balance", type=int, default=5)
    ap.add_argument("--require-auth", action="store_true",
                    help="로그인한 세션만 판독을 시작할 수 있게 한다. "
                         "결제·로그인이 붙기 전까지 공개 주소를 잠그는 용도")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--ttl", type=float, default=900.0, help="결과 보관 시간(초)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="바인딩 주소. 컨테이너·프록시 뒤에서만 0.0.0.0")
    ap.add_argument("--origin", default=None,
                    help="역방향 프록시 뒤 공개 출처 (예: https://conti.eungming.com). "
                         "설정하면 그 Host 를 허용하고 X-Forwarded-For 를 신뢰한다")
    args = ap.parse_args()

    # 키는 **ai 모드에서만** 확인한다. 로컬 모드는 키 없이 돌아야 한다.
    if args.mode == "ai":
        ensure_api_key()

    if not (WEB / "index.html").is_file():
        raise SystemExit(f"web/index.html 이 없습니다: {WEB}")

    # **DB 가 설정돼 있으면 붙지 못할 때 뜨지 않는다.** 조용히 메모리로
    # 되돌아가면 결제한 크레딧이 재시작 때 사라진다 — 돈 문제는 조용히
    # 넘어갈 수 없다.
    import db
    if db.configured():
        db.setup()
        print(f"  · 장부 DB: {os.environ.get('MUT_DB_NAME')} @ "
              f"{os.environ.get('MUT_DB_HOST')}", file=sys.stderr)

    warm_models()
    srv = build_server(args.port, args.mode, host=args.host, origin=args.origin,
                       trial_balance=args.trial_balance,
                       workers=args.workers, ttl=args.ttl)
    print(f"뮤트 개발 서버 → http://127.0.0.1:{srv.server_address[1]} "
          f"[{args.mode}]", file=sys.stderr)
    print("  · 이미지는 메모리에서만 처리되고 저장되지 않습니다", file=sys.stderr)
    # **개발 통로에서는 LLM 응답을 디스크에 적어 둔다.** 같은 악보를
    # 몇십 번 다시 그려 보며 고치는 일이 많은데, 그때마다 돈이 나간다.
    # 배포는 dev_enabled() 가 거짓이라 절대 켜지지 않는다.
    if dev_enabled():
        import devcache
        print(f"  · 개발 LLM 캐시: {devcache.install()}", file=sys.stderr)
    STATE["store"].require_auth = bool(args.require_auth)
    if args.require_auth:
        print("  · **계정 잠금**: 로그인한 세션만 판독 가능")
    kind = "DB 장부" if STATE["store"].durable else "메모리 장부 — 재시작하면 초기화"
    print(f"  · 체험 크레딧 {args.trial_balance} ({kind})", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
