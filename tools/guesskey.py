#!/usr/bin/env python3
"""
코드 목록에서 **원조성을 추론**한다.

왜 코드로 하나: 조표를 세는 쪽이 직관적이지만 실측에서 틀렸다 — 학습
검출기로 조표를 세니 ♭2개짜리 악보(Bb장조)가 단마다 1개로 잡혀 F장조로
나왔다. 조표의 ♭들은 서로 붙어 있어 개수를 세기 어렵다.

코드는 이미 100% 정확하게 읽고 있으므로(실측 43/43), 거기서 추론하는 편이
낫다. 판단 근거는 둘이다:
  · 그 조성의 온음계 화음이 몇 개나 되는가 (많을수록 좋다)
  · 마지막 코드가 으뜸화음인가 (찬양 악보는 거의 항상 으뜸으로 끝난다)
비용 0이고 틀리면 --key 로 덮어쓸 수 있다.
"""

from __future__ import annotations

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# 장조 다이어토닉 화음의 근음 (으뜸에서 반음 거리)
DIATONIC = [0, 2, 4, 5, 7, 9, 11]
SHARP_KEYS = {7: "G", 2: "D", 9: "A", 4: "E", 11: "B"}
FLAT_KEYS = {5: "F", 10: "Bb", 3: "Eb", 8: "Ab", 1: "Db", 6: "Gb"}


def root_pc(sym: str) -> int | None:
    """코드 심볼의 근음 음높이 클래스. 못 읽으면 None."""
    if not sym or sym[0].upper() not in PC:
        return None
    v = PC[sym[0].upper()]
    i = 1
    while i < len(sym) and sym[i] in "#b♯♭":
        v += 1 if sym[i] in "#♯" else -1
        i += 1
    return v % 12


def name_for(pc: int, flat_hint: bool) -> str:
    if pc == 0:
        return "C"
    if flat_hint and pc in FLAT_KEYS:
        return FLAT_KEYS[pc]
    if pc in SHARP_KEYS:
        return SHARP_KEYS[pc]
    return FLAT_KEYS.get(pc, "C")


def is_minor(sym: str) -> bool | None:
    """코드가 단3화음인가. 판단이 안 서면 None (증·감·sus 등)."""
    i = 1
    while i < len(sym) and sym[i] in "#b♯♭":
        i += 1
    tail = sym[i:].split("/")[0]
    if tail.startswith("dim") or tail.startswith("aug") or tail.startswith("sus"):
        return None
    if tail.startswith("maj"):
        return False
    if tail.startswith("m") or tail.startswith("-"):
        return True
    return False


# 장조 각 음도의 화음 성질 (True=단3화음). vii도는 감화음이라 제외한다.
DEGREE_MINOR = {0: False, 2: True, 4: True, 5: False, 7: False, 9: True}


def guess(chords: list[str]) -> tuple[str, float]:
    """
    (조성 이름, 확신도 0~1)

    **성질(장/단)까지 본다.** 근음만 보면 C장조와 G장조가 거의 구별되지
    않는다 — 두 조성의 온음계 근음이 여섯 개나 겹치기 때문이다. 실측으로
    G장조 악보(G C Em7 D …)를 C장조로 잘못 판단해 악보 전체를 틀리게
    이조했다. 그 악보의 `D`는 장3화음이고, C장조라면 2도는 `Dm`이어야
    하므로 성질만 봤어도 갈렸다.
    """
    parsed = [(root_pc(c), is_minor(c)) for c in chords]
    parsed = [(r, m) for r, m in parsed if r is not None]
    if not parsed:
        return "C", 0.0
    flat_hint = sum(1 for c in chords if "b" in c[1:2]) >= \
        sum(1 for c in chords if "#" in c[1:2])

    scores = {}
    for tonic in range(12):
        pts = 0.0
        for r, minor in parsed:
            deg = (r - tonic) % 12
            if deg not in DEGREE_MINOR:
                continue                      # 온음계 밖 — 점수 없음
            if minor is None or minor == DEGREE_MINOR[deg]:
                pts += 1.0                    # 근음·성질 모두 맞음
            else:
                pts += 0.25                   # 근음만 맞음 (차용화음일 수 있다)
        fit = pts / len(parsed)
        if parsed[-1][0] == tonic:
            fit += 0.20
        if parsed[0][0] == tonic:
            fit += 0.15
        scores[tonic] = fit

    best = max(scores, key=lambda t: scores[t])
    ordered = sorted(scores.values(), reverse=True)
    margin = ordered[0] - ordered[1] if len(ordered) > 1 else 1.0
    return name_for(best, flat_hint), round(min(1.0, margin * 3.0), 2)


# fifths(조표의 ♯/♭ 개수, ♭은 음수) → 장조 이름
MAJOR_BY_FIFTHS = {0: "C", 1: "G", 2: "D", 3: "A", 4: "E", 5: "B", 6: "F#",
                   7: "C#", -1: "F", -2: "Bb", -3: "Eb", -4: "Ab", -5: "Db",
                   -6: "Gb", -7: "Cb"}


def keysig_fifths(counts: list[tuple[int, int]],
                  min_systems: int = 2) -> int | None:
    """
    단별 (♭ 개수, ♯ 개수)에서 조표의 fifths를 정한다. ♭이면 음수.

    **0이 아닌 단들의 최빈값을 쓰고, 동점이면 큰 쪽을 쓴다.**

    예전엔 최대값을 썼는데 과검출 하나에 끌려간다(실측: DAY2는 ♯1인데
    11단 중 3단이 ♯2로 나온다). 그렇다고 분위수로도 안 된다 — DAY2는
    ♯1:♯2 가 8:3인데 정답이 1이고, 예전에 잰 ♭2 악보는 6:3인데 정답이 2였다.
    **거의 같은 분포에 정답이 반대**라 개수 통계만으로는 갈릴 수 없다.
    (그 ♭2 측정은 배율 하나로만 보던 옛 판독기 것이라 지금은 다르게 나올 수
    있다 — 다시 재 봐야 한다.)

    그래서 개수는 최빈값으로 보수적으로 잡고, 갈리는 경우는 **코드가**
    정한다(guess_with_keysig). 조표는 후보를 좁히는 근거이지 단독 판정자가
    아니다.

    아무것도 못 본 단은 **판단에서 뺀다.** 조표가 아예 안 잡힌 단을 0으로
    세면 조표 있는 악보가 C키로 밀린다.
    """
    if not counts:
        return None
    nf = _mode([f for f, _s in counts if f > 0])
    ns = _mode([s for _f, s in counts if s > 0])
    if nf and ns:
        # 둘이 같이 나오면 더 많은 단에서 나온 쪽 — 조표는 하나뿐이다
        cf = sum(1 for f, _ in counts if f > 0)
        cs = sum(1 for _, s in counts if s > 0)
        return -nf if cf >= cs else ns
    if nf:
        return -nf
    if ns:
        return ns
    return 0


def _mode(vals: list[int]) -> int:
    """가장 많이 나온 값. 동점이면 큰 쪽 (임시표는 뭉쳐서 덜 세이곤 한다)."""
    if not vals:
        return 0
    from collections import Counter
    c = Counter(vals)
    top = max(c.values())
    return max(v for v, n in c.items() if n == top)


def guess_with_keysig(chords: list[str], fifths: int | None
                      ) -> tuple[str, float, str]:
    """
    조표를 **우선 근거로** 쓰고 장·단조는 코드로 고른다.

    왜: 코드 통계만으로는 조성이 갈린다. 실측(위싱 콘티): 코드가
    `Bb C F Gm F/A`인데 Bb키로 추정했다(확신도 0.13). 실제는 F키다 —
    F=I · Gm=ii · Bb=IV · C=V. 조표는 ♭ 하나로 명확했다.

    반환: (조성 이름, 확신도, 근거)
    """
    key, conf = guess(chords)
    if fifths is None:
        return key, conf, "코드"

    major = MAJOR_BY_FIFTHS.get(fifths)
    if major is None:
        return key, conf, "코드"
    # 같은 조표의 단조 (장조 으뜸음의 단3도 아래)
    minor_pc = (PC[major[0]] + (1 if major.endswith("#") else
                                -1 if major.endswith("b") else 0) - 3) % 12
    minor = name_for(minor_pc, fifths < 0) + "m"

    # 코드 추정이 이미 조표와 맞으면 그대로 둔다
    if key in (major, minor):
        return key, max(conf, 0.8), "조표+코드"

    # 조표에 맞는 두 후보 중 코드에 더 맞는 쪽을 고른다
    def fit(tonic_pc: int, want_minor: bool) -> float:
        pts = n = 0.0
        for c in chords:
            r = root_pc(c)
            if r is None:
                continue
            n += 1
            deg = (r - tonic_pc) % 12
            if deg in DEGREE_MINOR:
                pts += 1.0
        if not n:
            return 0.0
        base = pts / n
        # 마지막 코드가 으뜸음이면 가점
        last = root_pc(chords[-1]) if chords else None
        if last is not None and last == tonic_pc:
            base += 0.2 if not want_minor else 0.1
        return base

    maj_pc = (PC[major[0]] + (1 if major.endswith("#") else
                             -1 if major.endswith("b") else 0)) % 12
    pick = major if fit(maj_pc, False) >= fit(minor_pc, True) else minor
    return pick, 0.75, "조표"


if __name__ == "__main__":
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(description="원조성 추론")
    ap.add_argument("extraction", help="read_chords.py 출력 JSON")
    ap.add_argument("--image", help="조표를 세어 근거로 쓸 원본 악보")
    ap.add_argument("--model", default="models/omr.pt")
    a = ap.parse_args()

    with open(a.extraction, encoding="utf-8") as f:
        ex = json.load(f)
    ch = [c["text"] for sysd in ex["systems"] for c in sysd["chords"]
          if c.get("text")]

    fifths = None
    if a.image:
        # **조표가 코드 통계보다 확실하다.** 실측: `Bb C F Gm F/A`를 코드만으로는
        # Bb키로 봤는데(확신도 0.13) 조표는 ♭ 하나 — 실제는 F키다.
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
        from PIL import Image
        from ultralytics import YOLO

        import evaldet as E
        import probe as P
        big, _f = P.upscale(Image.open(a.image).convert("RGB"))
        counts = E.keysig_counts(YOLO(a.model), big)
        fifths = keysig_fifths(counts)
        print(f"조표: 단별 {counts} → fifths {fifths}")

    k, conf, why = guess_with_keysig(ch, fifths)
    print(f"추론 조성: {k} (확신도 {conf}, 근거 {why})"
          f"  · 파일 표기: {ex['meta'].get('key')}")


# 전조로 인정하는 조건. 단별 판독은 ±1로 흔들리므로(실측 5장:
#   마커스 [1×9] · 위싱샘플 [-1,-1,-1,0,-1,-1,0,0,0] ·
#   위싱검증 [1,2,3,2,1,1,1,2,2] · DAY2 [1,1,2,1,1,1,2,2,1,1,1])
# 그 흔들림을 전조로 오해하면 없는 조표 변경을 만들어 낸다.
# 진짜 전조는 fifths 차이가 크고(G→Bb 는 3) 여러 단에 걸쳐 지속된다.
MODULATION_MIN_JUMP = 2     # fifths 차이
MODULATION_MIN_RUN = 2      # 연속으로 같은 값이 나와야 하는 단 수


def keysig_sections(counts: list[tuple[int, int]],
                    min_jump: int = MODULATION_MIN_JUMP,
                    min_run: int = MODULATION_MIN_RUN) -> list[int]:
    """
    단별 조표 fifths. **지속된 큰 변화만 전조로 인정한다.**

    콘티 악보는 후반부에서 키를 올리는 경우가 흔하다(보내주신 「지금 여기
    우리」는 C 섹션부터 G→Bb). 그걸 못 읽으면 그 구간이 임시표투성이가 된다.

    반대로 단별 판독을 그대로 믿으면 **없는 전조를 만든다** — 조표 임시표는
    붙어 있어 뭉치거나 갈라져서 ±1 흔들린다. 그래서 두 조건을 함께 본다:
      · fifths 차이가 min_jump 이상 (±1 흔들림을 걸러 낸다)
      · 새 값이 min_run 단 이상 연속 (한 단짜리 오검출을 걸러 낸다)

    경계는 **뒤로 넓힌다.** 전조가 시작되는 첫 단은 조표가 막 바뀐 자리라
    판독이 흔들리기 쉽고, 그 한 단이 걸러지면 전조가 한 칸 늦게 잡힌다
    (실측: 「지금 여기 우리」는 단7부터 ♭2인데 단7이 -3으로 읽혀 단8로
    밀렸다). 그 단의 값이 **옛 값보다 새 값에 가까우면** 새 구간에 넣는다.

    반환: 단마다 하나씩, 그 단에서 쓸 fifths
    """
    if not counts:
        return []
    per = [(-f if f else s) for f, s in counts]
    base = keysig_fifths(counts) or 0
    out: list[int] = []
    cur = base
    i = 0
    while i < len(per):
        v = per[i]
        if v != cur and abs(v - cur) >= min_jump:
            run = 1
            while i + run < len(per) and per[i + run] == v:
                run += 1
            if run >= min_run:
                cur = v
        out.append(cur)
        i += 1

    # 경계를 뒤로 넓힌다
    for i in range(1, len(out)):
        if out[i] == out[i - 1]:
            continue
        new, old = out[i], out[i - 1]
        j = i - 1
        while j >= 0 and out[j] == old and \
                abs(per[j] - new) < abs(per[j] - old):
            out[j] = new
            j -= 1
    return out


def _diatonic(f: int) -> set[int] | None:
    """조표 fifths 의 장음계 음높이 집합."""
    major = MAJOR_BY_FIFTHS.get(f)
    if major is None:
        return None
    t = (PC[major[0]] + (1 if major.endswith("#") else
                         -1 if major.endswith("b") else 0)) % 12
    return {(t + d) % 12 for d in (0, 2, 4, 5, 7, 9, 11)}


def _chord_fit(texts: list[str], f: int) -> tuple[float, int]:
    """(음계 안에 드는 코드 비율, 으뜸음으로 쓰인 횟수)."""
    scale = _diatonic(f)
    if scale is None:
        return (-1.0, 0)
    major = MAJOR_BY_FIFTHS[f]
    tonic = (PC[major[0]] + (1 if major.endswith("#") else
                             -1 if major.endswith("b") else 0)) % 12
    roots = [r for r in (root_pc(t) for t in texts) if r is not None]
    if not roots:
        return (-1.0, 0)
    inside = sum(1 for r in roots if r in scale)
    return (inside / len(roots), sum(1 for r in roots if r == tonic))


def fix_sections_with_chords(sections: list[int],
                             chords_by_system: list[list[str]],
                             min_chords: int = 4) -> list[int]:
    """
    **구간별 원조표를 그 구간의 코드로 검증한다 — ±1 범위에서만.**

    왜: 조표의 임시표는 서로 붙어 있어 **덜 세이기 쉽다.** 실측
    「지금 여기 우리」 C 섹션은 Bb장조(♭2)인데 네 단 모두 ♭1 로 읽혔고,
    그대로 +2 이조해서 C장조여야 할 자리에 **♯1개(G장조) 조표**가 그려졌다.
    같은 구간 코드는 `Bb F/A Gm7 Fm7 Bb/D Eb` 로 Bb장조가 명백했다.

    12키를 다 뒤지지 않는다 — `guess` 단독은 코드가 적으면 흔들린다
    (위 6개로 'Eb' 확신도 0.15). 실패 양상이 **±1 어긋남**이므로 후보를
    셋으로 좁히고, 코드가 음계에 드는 비율로 고른다. 같으면 **으뜸음으로
    실제로 쓰인 횟수**가 가른다(Bb 2회 vs Eb 1회).
    """
    if not sections:
        return sections
    out = list(sections)
    i = 0
    while i < len(out):
        j = i
        while j + 1 < len(out) and out[j + 1] == out[i]:
            j += 1
        texts = [t for si in range(i, min(j + 1, len(chords_by_system)))
                 for t in (chords_by_system[si] or []) if t]
        if len(texts) >= min_chords:
            cur = out[i]
            best = max((cur - 1, cur, cur + 1),
                       key=lambda f: (_chord_fit(texts, f), f == cur))
            if best != cur and _chord_fit(texts, best) > _chord_fit(texts, cur):
                for k in range(i, j + 1):
                    out[k] = best
        i = j + 1
    return out
