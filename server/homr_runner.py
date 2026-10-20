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


def read(png: bytes) -> list[list[list[str]]] | None:
    """원본 이미지 → 단마다 마디마다 음가 토큰 목록(쉼표는 'r' 접두). 실패하면 None."""
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


def systems(path: str) -> list[list[list[str]]]:
    """
    homr MusicXML → 단(new-system)마다 마디마다 음가 토큰.

    토큰은 박 단위 길이(4분음표 = 1)의 짧은 문자열 — 쉼표는 'r' 를 붙인다.
    화음 구성음·꾸밈음·2성부는 뺀다(박을 차지하지 않거나 우리가 안 읽는 것).
    """
    root = ET.parse(path).getroot()
    part = next(root.iter("part"))
    div, out = 1, [[]]
    for i, m in enumerate(part.iter("measure")):
        pr = m.find("print")
        if i and pr is not None and pr.get("new-system") == "yes":
            out.append([])
        at = m.find("attributes")
        if at is not None and at.find("divisions") is not None:
            div = int(at.find("divisions").text)
        seq = []
        for n in m.iter("note"):
            if n.find("chord") is not None or n.find("grace") is not None:
                continue
            v = n.find("voice")
            if v is not None and v.text != "1":
                continue
            d = n.find("duration")
            if d is None:
                continue
            seq.append(("r" if n.find("rest") is not None else "")
                       + f"{int(d.text) / div:g}")
        out[-1].append(seq)
    return out
