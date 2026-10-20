#!/usr/bin/env python3
"""
악보 한 장 → 키 변환된 악보. **전 과정을 한 줄로.**

    python3 tools/convert.py 악보.jpg -s 2
    python3 tools/convert.py 악보.jpg -s -3 --chart        # 코드차트로
    python3 tools/convert.py 악보.jpg --to G               # 목표 조성으로

안에서 이렇게 돈다:
  ① 오선·코드 상자 검출      영상처리, 0원
  ② 코드 글자 판독            AI 1회 호출 (곡당 한 번, 결과를 옆에 저장)
  ③ 원조성 추론               코드에서, 0원
  ④ 이조 + 렌더               브라우저와 같은 코드

**②는 한 번만 한다.** 판독 결과를 `<악보이름>.extraction.json` 으로 남기므로,
같은 곡을 여러 키로 바꿀 때는 다시 부르지 않는다 — 키를 다섯 개 뽑아도
AI 비용은 한 번이다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HERE = Path(__file__).resolve().parent


def run(args: list[str], quiet: bool = False) -> str:
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"실패: {' '.join(args[-3:])}")
    if not quiet and r.stderr.strip():
        sys.stderr.write(r.stderr)
    return r.stdout


def extraction_for(image: Path, key: str | None, model: str | None,
                   force: bool) -> tuple[dict, bool]:
    """판독 결과를 얻는다. 이미 있으면 다시 읽지 않는다. (내용, 새로읽었나)"""
    out = image.with_suffix(".extraction.json")
    if out.exists() and not force:
        with open(out, encoding="utf-8") as f:
            return json.load(f), False

    detect = image.with_suffix(".detect.json")
    run([str(HERE / "detect_chords.py"), str(image), "--json", str(detect)])
    cmd = [str(HERE / "read_chords.py"), str(image), str(detect), "-o", str(out)]
    if key:
        cmd += ["--key", key]
    if model:
        cmd += ["--model", model]
    run(cmd)
    detect.unlink(missing_ok=True)
    with open(out, encoding="utf-8") as f:
        return json.load(f), True


def main() -> None:
    ap = argparse.ArgumentParser(description="악보 키 변환 (전 과정)")
    ap.add_argument("image")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("-s", "--semitones", type=int, help="반음 단위 이동")
    g.add_argument("--to", help="목표 조성 (예: G, Eb)")
    ap.add_argument("-o", "--out", help="출력 파일 (기본: 옆에 자동 이름)")
    ap.add_argument("--chart", action="store_true",
                    help="멜로디 없이 코드차트로 (이조가 완전히 정확)")
    ap.add_argument("--key", help="원조성을 직접 지정 (기본: 코드에서 추론)")
    ap.add_argument("--model", help="코드 판독 AI 모델")
    ap.add_argument("--reread", action="store_true", help="AI 판독을 다시 함")
    a = ap.parse_args()

    image = Path(a.image)
    if not image.exists():
        raise SystemExit(f"파일이 없습니다: {image}")

    e = sys.stderr
    ex, fresh = extraction_for(image, a.key, a.model, a.reread)
    print(("① 코드 판독 (AI 1회)" if fresh
           else "① 코드 판독 — 저장된 결과 재사용 (AI 호출 없음)"), file=e)

    # ── 원조성 ──
    import guesskey as GK
    chords = [c["text"] for s in ex["systems"] for c in s["chords"]]
    if a.key:
        src, why = a.key, "지정"
    else:
        src, conf = GK.guess(chords)
        why = f"코드에서 추론 (확신도 {conf})"
        # 원조성이 틀리면 코드도 음표도 전부 틀린 악보가 나온다. 확신도가
        # 낮으면 반드시 눈에 띄게 알린다 — 조용히 틀리는 게 가장 나쁘다.
        if conf < 0.55:
            print(f"⚠️  원조성 확신도 낮음 ({conf}). 악보의 조표를 보고 "
                  f"다르면 --key 로 지정하세요.", file=e)
    ex["meta"]["key"] = src
    print(f"② 원조성 {src} — {why} · 코드 {len(chords)}개", file=e)

    # ── 이동량 ──
    if a.to:
        import subprocess as sp
        r = sp.run(["node", "--experimental-strip-types",
                    str(HERE.parent / "src" / "cli.ts"),
                    "--from", src, "--to", a.to],
                   capture_output=True, text=True)
        # cli 출력에서 반음 수를 못 얻으면 파이썬 쪽 엔진으로 계산
        import render as R
        semis = None
        for n in range(-11, 12):
            if R.call_engine(src, n, [])["toKey"] == a.to:
                semis = n
                break
        if semis is None:
            raise SystemExit(f"{src} → {a.to} 로 가는 이동량을 못 찾았습니다")
    else:
        semis = a.semitones

    tmp = image.with_suffix(".key.json")
    tmp.write_text(json.dumps(ex, ensure_ascii=False), encoding="utf-8")

    tool = "chordchart.py" if a.chart else "render.py"
    suffix = "차트" if a.chart else "악보"
    import render as R
    to_key = R.call_engine(src, semis, [])["toKey"]
    out = Path(a.out) if a.out else image.with_name(
        f"{image.stem}_{to_key}키_{suffix}.png")

    print(f"③ {'코드차트' if a.chart else '악보'} 만드는 중…", file=e)
    cmd = [str(HERE / tool), str(image), str(tmp), "-s", str(semis),
           "-o", str(out)]
    if not a.chart:
        # 검출기가 있으면 **음표 자리를 지켜 달라고** 알려준다. 가사 띠는
        # 오선 바로 아래부터 잡히므로 아래로 이조하면 덧줄 음표가 그 안으로
        # 내려오는데, 띠를 원본으로 되돌릴 때 그 자리를 비켜가야 한다
        # (실측: 안 비켜가면 머리 115개 중 36개가 잉크 절반 이하, 비켜가면 4개).
        cmd += ["--protect-heads"]
    run(cmd)