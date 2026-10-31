"""
**homr 로 같은 장을 한 번 더 읽는다 — 교차 검증용.**

homr(https://github.com/liebharc/homr, AGPL-3.0)는 **수정하지 않고 별도
프로세스로만** 부른다. 컨테이너 안 전용 가상환경(/opt/homr)에 있고, 우리
코드와는 이미지 파일을 주고 MusicXML 파일을 받는 것 말고는 아무것도 나누지
않는다(homr LICENSE_FAQ: "separate process ... gives a clear separation").

**이미지를 남기지 않는다.** homr 가 파일 경로를 받으므로 메모리 위 임시
폴더(/dev/shm)에 잠깐 쓰고, 읽고 나면 폴더째 지운다.

실패·시간 초과·미설치면 None — 교차 검증 없이 우리 판독만으로 간다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

HOMR = os.environ.get("MUTE_HOMR_BIN") or "/opt/homr/bin/homr"
TIMEOUT = float(os.environ.get("MUTE_HOMR_TIMEOUT") or 120)


def available() -> bool:
    return os.environ.get("MUTE_HOMR", "1") != "0" and os.path.exists(HOMR)


def read(png: bytes) -> dict | None:
    """원본 이미지 → {"dur": 음가 토큰, "pitch": 음높이} (systems 참고). 실패하면 None."""
    if not available():
        return None
    base = "/dev/shm" if os.path.isdir("/dev/shm") else None
    try:
        with tempfile.TemporaryDirectory(dir=base) as d:
            src = os.path.join(d, "page.png")
            with open(src, "wb") as fh:
                fh.write(png)
            subprocess.run([HOMR, src], cwd=d, timeout=TIMEOUT,
                           capture_output=True, check=False)
            out = os.path.join(d, "page.musicxml")
            return systems(out) if os.path.exists(out) else None
    except Exception as e:                                  # noqa: BLE001
        print(f"  homr 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def systems(path: str) -> dict:
    """
    homr MusicXML → 단(new-system)마다 마디마다 두 목록.

    dur:   음가 토큰 — 박 단위 길이(4분음표 = 1)의 짧은 문자열, 쉼표는 'r' 를 붙인다.
    pitch: 같은 자리의 음높이 'F#5'·'Bb4'(쉼표는 'r') — 임시표 대조용.
    key:   그 마디의 조표 fifths — 우리 조표 판독과 대조용.
    tie:   같은 자리 음이 **다음 음과 붙임줄**로 이어지는가(True/False).
           homr 는 곡선을 전부 <slur> 로 적는다 — 같은 높이 이웃 두 음을 잇는
           곡선이 붙임줄이다. 다음 음은 다음 마디·다음 단이어도 된다(실측
           camp0814a-3: 우리가 거의 못 보는 16분→8분 붙임줄을 homr 는 다 잡았다).
    화음 구성음·꾸밈음·2성부는 뺀다(박을 차지하지 않거나 우리가 안 읽는 것).
    """
    root = ET.parse(path).getroot()
    part = next(root.iter("part"))
    div, fifths, dur, pitch, key = 1, None, [[]], [[]], [[]]
    flat: list[tuple] = []                     # (시작 번호들, 끝 번호들, 음높이) — 붙임줄 판정용
    where: list[list] = []                     # 같은 순서로 (단, 마디 안 순서)
    for i, m in enumerate(part.iter("measure")):
        pr = m.find("print")
        if i and pr is not None and pr.get("new-system") == "yes":
            dur.append([]); pitch.append([]); key.append([])
        at = m.find("attributes")
        if at is not None and at.find("divisions") is not None:
            div = int(at.find("divisions").text)
        for a in m.iter("attributes"):         # 한 마디에 attributes 가 여럿일 수 있다
            if a.findtext("key/fifths") is not None:
                fifths = int(a.findtext("key/fifths"))
        seq, ps = [], []
        for n in m.iter("note"):
            if n.find("chord") is not None or n.find("grace") is not None:
                continue
            v = n.find("voice")
            if v is not None and v.text != "1":
                continue
            d = n.find("duration")
            if d is None:
                continue
            rest = n.find("rest") is not None
            seq.append(("r" if rest else "") + f"{int(d.text) / div:g}")
            p = n.find("pitch")
            if rest or p is None:
                ps.append("r")
            else:
                alt = int(float(p.findtext("alter") or 0))
                ps.append(p.findtext("step") + ("#" * alt if alt > 0 else "b" * -alt)
                          + p.findtext("octave"))
            sl = [(x.get("type"), x.get("number") or "1") for x in n.iter("slur")]
            flat.append(({k for t, k in sl if t == "start"},
                         {k for t, k in sl if t == "stop"}, ps[-1]))
            where.append([len(dur) - 1, len(dur[-1]), len(ps) - 1])
        dur[-1].append(seq)
        pitch[-1].append(ps)
        key[-1].append(fifths)
    tie = [[[False] * len(m) for m in sysm] for sysm in dur]
    for i in range(len(flat) - 1):
        (st, _, pa), (_, sp, pb) = flat[i], flat[i + 1]
        if st & sp and pa != "r" and pa == pb:
            si, mi, k = where[i]
            tie[si][mi][k] = True
    return {"dur": dur, "pitch": pitch, "key": key, "tie": tie}
