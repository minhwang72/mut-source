#!/usr/bin/env python3
"""
**재조판한 MusicXML의 음높이가 검출 결과와 일치하는지 감사한다.**

왜 필요한가: 지금까지 "상자 몇 개를 찾았나"만 셌다. 그런데 상자를 다 찾아도
음높이가 틀릴 수 있다 — 쉼표가 순서를 밀거나, LLM 음표 순서와 검출 순서가
어긋나거나, 마디 쪼개기가 음표를 잘못 옮기면 그렇다. **개수는 맞고 음이
틀린** 악보가 가장 위험하다: 연주자가 틀린 걸 모른다.

무엇을 재는가: 검출기가 읽은 음높이가 XML에 **그대로 실렸는가**(배관 검사).
검출 자체가 맞았는지는 재지 않는다 — 그건 정답 악보가 있어야 안다.

처음엔 그린 결과를 다시 검출해 비교했는데, 그 방식은 **감사 도구 자체의
검출 실패를 오류로 셌다**(실측: 단1에서 XML은 맞는데 렌더 재검출이 한 개를
놓쳐 5개가 틀린 것처럼 나왔다). 그래서 XML을 직접 읽는다.

  python tools/auditpitch.py 원본.jpg 재조판.musicxml --struct <악보>.struct.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_MEASURE = re.compile(r"<measure .*?</measure>", re.S)
_NOTE = re.compile(r"<note>.*?</note>", re.S)


def xml_systems(xml: str) -> list[list[str]]:
    """단별 음표 이름 목록 (쉼표 제외). `<print new-system>`으로 단을 가른다."""
    out: list[list[str]] = []
    cur: list[str] = []
    for i, m in enumerate(_MEASURE.findall(xml)):
        if i and "new-system" in m:
            out.append(cur)
            cur = []
        for note in _NOTE.findall(m):
            if "<rest/>" in note:
                continue
            st = re.search(r"<step>(\w)</step>", note)
            oc = re.search(r"<octave>(-?\d+)</octave>", note)
            if not st or not oc:
                continue
            al = re.search(r"<alter>(-?\d+)</alter>", note)
            acc = ""
            if al:
                v = int(al.group(1))
                acc = "#" * v if v > 0 else "b" * (-v)
            cur.append(f"{st.group(1)}{acc}{oc.group(1)}")
    out.append(cur)
    return out


def detected(img, model, expect) -> tuple[list[list[str]], float]:
    """단별로 검출된 음높이 이름 (x 순)."""
    import evaldet as E
    import notes as N
    import sheetcv as cv

    _ink, staves = cv.find_staves_best(img)
    if not staves:
        return [], 0.0
    sp = cv.median_spacing(staves)
    boxes, _m = (E.detect_guided(model, img, expect, conf_hi=0.50) if expect
                 else E.detect_by_staff(model, img, 0.50))
    out = []
    for st in staves:
        mid = (st.top + st.bottom) / 2.0
        half = (st.bottom - st.top) * 1.4
        hs = sorted((b for b in boxes
                     if b["class"].startswith("notehead")
                     and abs(b["y"] + b["h"] / 2.0 - mid) < half),
                    key=lambda b: b["x"])
        out.append([N.step_name(N.pitch_step(b["y"] + b["h"] / 2.0, st, sp))
                    for b in hs])
    return out, sp


def audit_transpose(base_xml: str, moved_xml: str, from_key: str,
                    semitones: int) -> tuple[int, int, list[str]]:
    """
    **이조 자체가 맞는지 본다.** 0반음 판과 이조한 판을 음표 하나씩 대조해,
    모든 음이 정확히 (온음계 단수 + 반음)만큼 움직였는지 확인한다.

    이게 없어서 큰 버그를 오래 못 봤다: 음이름에 이미 옥타브가 붙어 있는데
    `pitch + "4"` 로 다시 붙이고 뒤를 자르는 코드가 남아 있어 "B3"이 "B34"
    (34옥타브)로 해석됐다. 글자는 맞고 **옥타브만 틀려서** 눈으로도 잘
    안 보였다(실측: -3반음에서 D4가 B3 대신 B4).

    반환: (일치, 전체, 어긋난 것 몇 개)
    """
    import render as R

    plan = R.call_engine(from_key, semitones, [])
    steps = plan["steps"]
    a = [p for sysv in xml_systems(base_xml) for p in sysv]
    b = [p for sysv in xml_systems(moved_xml) for p in sysv]
    if len(a) != len(b):
        return 0, max(len(a), len(b)), [f"음표 수 다름 {len(a)} vs {len(b)}"]
    bad = []
    same = 0
    for k, (x, y) in enumerate(zip(a, b)):
        import musicxml as M
        want = M.transpose(x, steps, semitones)
        if want == y:
            same += 1
        elif len(bad) < 6:
            bad.append(f"{k+1}번({x}→{y}, 기대 {want})")
    return same, len(a), bad


def main() -> None:
    ap = argparse.ArgumentParser(description="재조판 음높이 배관 감사")
    ap.add_argument("original")
    ap.add_argument("musicxml")
    ap.add_argument("--model", default="models/omr.pt")
    ap.add_argument("--struct", required=True)
    # **음수로 시작하는 인수는 argparse가 옵션으로 오해한다.** `-3=파일`도
    # 마찬가지다. 부호를 `m`(minus)으로 적게 한다 — `m3=파일`, `p2=파일`.
    ap.add_argument("--moved", nargs="*", metavar="m3=파일",
                    help="이조한 판도 검사한다. 내림은 m, 올림은 p "
                         "(예: --moved m3=g.musicxml p2=c.musicxml)")
    ap.add_argument("--key", default="Bb", help="--moved 검사용 원조성")
    a = ap.parse_args()

    from PIL import Image
    from ultralytics import YOLO

    d = json.loads(Path(a.struct).read_text(encoding="utf-8"))
    expect = [sum(1 for n in s.get("notes", []) if not n.get("rest"))
              for s in d["systems"]]

    # **재조립과 똑같은 이미지에서 검출해야 한다.** rebuild는 확대본에서
    # 검출하는데 감사가 원본에서 검출하면, 크기 차이로 생긴 판독 차이를
    # 배관 오류로 오해한다(실측: 그 때문에 2개가 틀린 것처럼 나왔다).
    import probe as P

    big, factor = P.upscale(Image.open(a.original).convert("RGB"))
    if factor > 1.001:
        print(f"확대 {factor:.2f}배에서 검출 (재조립과 동일)")
    det, sp = detected(big.convert("L"), YOLO(a.model), expect)
    xs = xml_systems(Path(a.musicxml).read_text(encoding="utf-8"))

    print(f"원본 {len(det)}단(간격 {sp:.1f}px) · XML {len(xs)}단")
    if len(det) != len(xs):
        print("⚠️  단 수가 다릅니다 — 비교를 건너뜁니다")
        raise SystemExit(1)

    same = diff = padded = 0
    for i, (dv, xv) in enumerate(zip(det, xs)):
        bad = []
        n = min(len(dv), len(xv))
        for k in range(n):
            if dv[k] == xv[k]:
                same += 1
            else:
                diff += 1
                if len(bad) < 6:
                    bad.append(f"{k+1}번({dv[k]}→{xv[k]})")
        # XML이 더 길면 검출이 모자라 앞 음높이를 이어 쓴 자리다
        pad = len(xv) - len(dv)
        padded += max(0, pad)
        mark = "✓" if not bad else "✗"
        note = f" · 채움 {pad}개" if pad > 0 else (
            f" · ⚠ 검출이 {-pad}개 더 많음" if pad < 0 else "")
        print(f"  {mark} 단{i}: {n - len(bad)}/{n}{note}"
              + (f" · 어긋남 {', '.join(bad)}" if bad else ""))

    tot = same + diff
    print(f"\n배관 일치 {same}/{tot} = {same / max(1, tot) * 100:.1f}%"
          f" · 음높이 못 채운 자리 {padded}개")

    # **조표도 검사한다.** 음높이가 다 맞아도 조표가 틀리면 연주자가 전부
    # 다른 음으로 읽는다. 실측: 원조성 기본값 "C"가 그대로 들어가 F키 악보를
    # -3반음 옮겼더니 C→A로 계산되어 ♯3(A장조)로 그려졌다 — D장조는 ♯2다.
    # 코드는 음정 차이만 쓰므로 맞았고, 그래서 눈에 잘 안 보였다.
    ks_bad = 0
    if a.moved:
        import render as R
        for item in a.moved:
            semi_s, _, path = item.partition("=")
            semi = int(semi_s.replace("m", "-").replace("p", "+"))
            want = R.call_engine(a.key, semi, [])["fifthsTo"]
            m = re.search(r"<fifths>(-?\d+)</fifths>",
                          Path(path).read_text(encoding="utf-8"))
            got = int(m.group(1)) if m else None
            mark = "✓" if got == want else "✗"
            if got != want:
                ks_bad += 1
            print(f"\n조표 검사")
            print(f"  {mark} {semi:+d}반음: fifths {got} "
                  f"(기대 {want}, {a.key}키 → "
                  f"{R.call_engine(a.key, semi, [])['toKey']}키)")

    tr_bad = 0
    if a.moved:
        base = Path(a.musicxml).read_text(encoding="utf-8")
        print("\n이조 검사 (0반음 판 대비)")
        for item in a.moved:
            semi_s, _, path = item.partition("=")
            semi_s = semi_s.replace("m", "-").replace("p", "+")
            ok, n, bad = audit_transpose(
                base, Path(path).read_text(encoding="utf-8"),
                a.key, int(semi_s))
            tr_bad += len(bad)
            mark = "✓" if not bad else "✗"
            print(f"  {mark} {int(semi_s):+d}반음: {ok}/{n}"
                  + (f" · {', '.join(bad)}" if bad else ""))

    raise SystemExit(0 if diff == 0 and tr_bad == 0 and ks_bad == 0 else 1)


if __name__ == "__main__":
    main()
