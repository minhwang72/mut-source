#!/usr/bin/env python3
"""
**박자로 음가를 역산한다.**

검출기는 음가를 84%까지 맞힌다(빔 겹수를 세는 방식). 남는 오류는 거의
16분음표를 8분음표로 보는 것이다 — 겹빔이 한 겹으로 보이기 때문이다.

그런데 **한 마디의 음가 합은 박자표와 정확히 같아야 한다.** 그러니 합이
안 맞는 마디에서 "어느 음표를 한 단계 옮기면 딱 맞는가"를 찾으면 된다.
검출기가 준 값에서 **가장 적게 고치는** 조합을 고른다 — 검출을 존중하되
음악적으로 불가능한 마디를 남기지 않는다.

같은 합을 만드는 조합이 여럿이면 포기한다(찍지 않는다). 조용히 틀린
악보를 주는 것보다 "모르겠다"가 낫다.
"""
from __future__ import annotations

import itertools

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
# 찍기를 허용하면 조합을 끝까지 뒤질 이유가 없다 — 첫 후보를 쓰므로
MAX_FOUND = 8
# 한 단계 이웃 — 검출이 헷갈리는 방향
NEIGHBOR = {
    "16th": ["16th", "eighth"],
    "eighth": ["eighth", "16th", "quarter"],
    "quarter": ["quarter", "eighth", "half"],
    "half": ["half", "quarter", "whole"],
    "whole": ["whole", "half"],
}


def value(d: str, dotted: bool = False) -> int:
    v = DUR.get(d, 8)
    return v * 3 // 2 if dotted else v


def fit_measure(dets: list[str], fixed: int, target: int,
                dotted: list[bool] | None = None,
                guess: bool = False,
                allowed=None) -> tuple[list[str], bool] | None:
    """
    dets   : 검출기가 준 음표 음가 (마디 안 순서)
    fixed  : 이 마디에서 이미 정해진 값 (쉼표 등)
    target : 한 마디의 총 음가 (4/4면 32)
    guess  : 답이 여럿일 때 찍을 것인가
    allowed: (자리, 새 음가) → 화소가 그 음가를 허락하나. 없으면 전부 허락
    반환   : (고친 음가 목록, 찍었나). 답이 없으면 None

    **화소가 막는 답은 쓰지 않는다 — 그러나 거른 덕에 하나 남았다고
    "읽었다"가 되지는 않는다.** 빔에 묶인 음을 4분으로, 꽉 찬 머리를 2분
    으로 바꾸는 답은 그림과 모순이라 버린다(실측 camp0814a-3: 유일한 답이
    "8분 둘 → 4분 둘"이었고 틀렸다). 하지만 남은 답은 "반증이 없다"일 뿐
    긍정 증거가 아니다 — 놓친 점처럼 후보 공간 밖의 정답이 흔하다(Codex
    재현: 점4분 둘을 놓친 마디가 거른 뒤 유일해져 짐작 표시 없이 통과).
    그래서 **짐작이 아닌 것은 거르기 전에도 답이 하나였고 그 답이 살아남은
    경우뿐**이다.

    **왜 찍기를 허용하게 됐나.** 원래는 답이 여럿이면 포기했다 — 조용히
    틀린 악보를 주느니 낫다는 판단이었고, 고칠 화면이 없던 때는 맞았다.
    지금은 수정 패널이 있으므로 전제가 바뀌었다: 깨진 마디를 그대로 내면
    사용자가 직접 고쳐야 하지만, 찍고 표시하면 훑어보고 넘기면 된다.
    실측 근거: 안 맞는 마디 94개 중 54개(57%)가 음가 **한 단계** 차이였다.
    """
    if not dets:
        return None
    dotted = dotted or [False] * len(dets)
    need = target - fixed
    if need <= 0:
        return None
    base = sum(value(d, dt) for d, dt in zip(dets, dotted))
    if base == need:
        return list(dets), False               # 이미 맞다

    raw = _search(dets, dotted, need, None)
    kept = raw if allowed is None else _search(dets, dotted, need, allowed)
    if not kept:
        return None
    sure = len(raw) == 1 and kept[0] == raw[0]
    if not sure and not guess:
        return None                            # 여럿이면 찍지 않는다
    # ponytail: 동점이면 앞 음표를 고치는 후보를 쓴다. 어느 쪽이 맞는지
    # 가릴 신호가 여기 없다. 표시가 붙으므로 사용자가 바로잡을 수 있다.
    return kept[0], not sure


def _search(dets, dotted, need, allowed) -> list[list[str]]:
    """고치는 개수를 늘려 가며 찾는다 — 적게 고치는 답을 먼저. 가장 적게
    고친 단계의 답들을 MAX_FOUND 개까지 돌려준다."""
    n = len(dets)
    for k in range(1, min(4, n) + 1):
        found = []
        for idx in itertools.combinations(range(n), k):
            choices = [[c for c in NEIGHBOR.get(dets[i], [dets[i]])
                        if c != dets[i] and (allowed is None or allowed(i, c))]
                       for i in idx]
            for combo in itertools.product(*choices):
                cand = list(dets)
                for i, c in zip(idx, combo):
                    cand[i] = c
                if sum(value(d, dt) for d, dt in zip(cand, dotted)) == need:
                    found.append(cand)
                    if len(found) >= MAX_FOUND:
                        return found           # 다 뒤질 필요 없다
        if found:
            return found
    return []


# 4박에서 이만큼 안쪽이면 "온전한 마디를 잘못 읽었다"로 본다.
# 못갖춘마디(마커스 단5 = 1박)와 쪼개진 반쪽(2박)은 이 범위 밖이라
# 손대지 않는다 — 4박을 강요하면 맞는 음가를 망친다(실측: 96.9% → 94.7%).
NEAR = 1.0


def _beats(m) -> float:
    # 화음 구성음은 박을 차지하지 않는다 — 기둥 하나에 한 박이다
    v = sum(value(n["duration"], n.get("dotted"))
            for n in m["notes"] if not n.get("chord"))
    return (v + m["rest"] * 8) / 8.0


def _apply(m, target_units: int, guess: bool = True) -> bool:
    """마디 하나(또는 합친 반쪽 둘)를 target에 맞춘다.

    **박을 차지하는 음표만 맞춘다.** 화음 구성음까지 넣으면 _beats(구성음을
    빼고 센다)와 다른 합을 보게 되어 수리가 영영 성공하지 못한다 — 실측:
    화음 쌍으로만 이뤄진 마디가 4박에서 2박으로 떨어진 채 그대로 남았다
    (wish0809-4 단2 마디4 등 11마디). 구성음은 맞춘 뒤 기둥 값을 따라간다.
    """
    ns = m["notes"]
    lead = [n for n in ns if not n.get("chord")]
    # **쉼표도 고친다.** 전에는 쉼표 합을 고정값으로 두고 음표만 맞췄다.
    # 그런데 쉼표도 똑같이 오독된다 — 4분쉼표(𝄽)와 8분쉼표(𝄾)는 글리프가
    # 닮았고, `fix_rest_class` 는 온/2분만 자리로 가른다. 고정으로 두면
    # 그 마디는 영영 못 고친다(실측 camp0814b-07 단4 마디4: 4분쉼표 자리에
    # 2분쉼표가 들어가 5박). 음표와 같은 후보 목록으로 함께 맞춘다.
    rests = [i for i in (m.get("items") or []) if i.get("rest")]
    seq = sorted(lead + rests, key=lambda n: n.get("x", 0.0))
    if not seq:
        return False
    # 같은 빔 묶음에서 2차 빔을 나누는 음 수 — _pixels_allow 가 쓴다
    l2: dict[int, int] = {}
    for x in lead:
        if int(x.get("level") or 0) >= 2 and int(x.get("beamGroup", -1)) >= 0:
            l2[x["beamGroup"]] = l2.get(x["beamGroup"], 0) + 1
    for x in lead:
        x["_l2peers"] = l2.get(int(x.get("beamGroup", -1)), 0)
    r = fit_measure([n["duration"] for n in seq],
                    0 if rests else int(m["rest"] * 8),
                    target_units, [bool(n.get("dotted")) for n in seq],
                    guess=guess, allowed=lambda i, d: _pixels_allow(seq[i], d))
    if not r:
        return False
    fix, guessed = r
    for n, d in zip(seq, fix):
        if n["duration"] != d:
            # **손댄 자리는 두 단계로 표시한다.** 합이 맞는다고 원본과 같다는
            # 증거는 아니므로 고친 건 다 남기되(fitted), 답이 여럿이라 고른
            # 것만 따로 표시한다(guessed). 화면이 주의를 요구하는 건 후자다 —
            # 전부 똑같이 띄우면 장당 8.6개가 되어 아무도 안 본다.
            n["fitted"] = True
            if guessed:
                n["guessed"] = True
        n["duration"] = d
    if rests:
        # 쉼표 합을 다시 센다 — _beats 가 이 값을 쓴다
        m["rest"] = sum(value(x["duration"], x.get("dotted")) for x in rests) / 8.0
    _sync_chords(ns)
    return True


LONG = {"quarter", "half", "whole"}       # 빔에 묶일 수 없는 음가
REST_SURE = 0.70                          # 이 이상 확신한 쉼표 글리프는 고정
HOLLOW_DUR = {"half", "whole"}            # 속이 빈 머리


def _pixels_allow(n: dict, new: str) -> bool:
    """
    이 음표를 `new` 로 바꾸는 것을 그림이 허락하나.

    확실한 증거만 쓴다 — 모르면 허락한다(그러면 예전처럼 찍고 표시한다).
      · 빔에 묶인 음은 8분 이하다. 4분 이상으로 못 바꾼다.
      · 속이 꽉 찬 머리(≤HOLLOW_FILLED)는 2분·온음표가 아니다.
      · 속이 빈 머리(≥HOLLOW_MIN)는 2분·온음표다.
    쉼표는 머리가 없으니 손대지 않는다.
    """
    if n.get("rest"):
        # 또렷하게 검출된 쉼표 글리프는 바꾸지 않는다(실측 day2sb-1 단6 끝
        # 마디: 확신 0.80 의 8분쉼표를 4분쉼표로 늘려 합을 맞췄다 — 틀림).
        # 흐린 것(4분·8분쉼표는 닮았다)만 박자로 고칠 수 있다.
        return n.get("conf", 0.0) < REST_SURE
    if new in LONG and int(n.get("beamGroup", -1)) >= 0:
        return False
    # 2차 빔이 실제로 보인 음은 16분이다 — 8분 이상으로 못 늘린다(실측
    # day2sb-1 단6 마디3: 확신 0.91 의 2차 빔 아래 16분 둘을 8분으로).
    # **같은 묶음에서 둘 이상이 2차 빔을 나눌 때만.** 한 음에만 걸친 조각은
    # 형광펜 띠가 빔을 두껍게 보이게 한 것일 수 있다(실측 wish0809-7 단0:
    # [8,8,8,16] — 묶음이 박 격자에서 안 끝난다).
    if (int(n.get("level") or 0) >= 2 and int(n.get("beamGroup", -1)) >= 0
            and n.get("_l2peers", 0) >= 2 and new != "16th"):
        return False
    h = n.get("hollow")
    if h is None:
        return True
    if new in HOLLOW_DUR and h <= HOLLOW_FILLED:
        return False
    if new not in HOLLOW_DUR and h >= HOLLOW_MIN:
        return False
    return True


def _sync_chords(ns: list[dict]) -> None:
    """화음 구성음의 음가를 자기 기둥(앞의 비-화음 음표)에 맞춘다.

    한 기둥에 달린 머리는 같은 음가다. 검출은 빔이 닿은 머리만 8분으로 읽고
    나머지를 4분으로 남기곤 하는데(실측 141묶음 중 11개), 그대로 두면
    화음이 서로 다른 음가로 그려진다."""
    cur = None
    for n in ns:
        if n.get("chord"):
            if cur is not None:
                n["duration"] = cur["duration"]
                n["dotted"] = bool(cur.get("dotted"))
        else:
            cur = n


# 회색지대 붙임점을 마디 합으로 심판한다.
#
# **0.40 을 내리지 않는다 — 재 보고 눈으로 확인한 결과다.**
#
# 0.30 으로 내리면 지표는 좋아진다: 깨진 마디 809 -> 730(-79), 맞던 마디가
# 깨진 경우 0. 숫자만 보면 켜야 할 것처럼 보인다.
#
# 그런데 **박자 지표는 "합이 맞는가"만 본다.** 엉뚱한 음표에 점을 붙여도
# 합은 맞으므로 지표는 통과시킨다. 그래서 0.30~0.40 구간에서만 승격된
# 붙임점 26개를 잘라 화소를 직접 봤다 — **점이 실제로 있는 것은 2~3개**
# 였다. 나머지는 지어낸 점이고, 우연히 합이 맞았을 뿐이다.
#
# 0.40 위는 정반대다. 승격기는 그 구간을 전부 처리했고(승격 실패 0%)
# 나빠진 마디가 없었다. 잉크가 실제로 있는 경계가 거기다.
#
# 남은 붙임점의 36%는 점수가 정확히 0 — 스캔에 자국이 없다. 문턱으로는
# 못 잡는 천장이고, 잡으려면 검출 자체를 바꿔야 한다.
import os as _os
DOT_GRAY = float(_os.environ.get("MUTE_DOT_GRAY", "0.40"))
DOT_SURE = 0.55
# 쉼표 붙임점의 문턱 — 오선 지운 그림에서 점 모양 잉크가 하나라도 잡히면
# 후보다. 점수 자체로는 완전히 안 갈리므로(0 초과 21개 중 진짜 7개)
# 판정은 박자가 한다.
# 탐색 자리가 9곳에서 20곳으로 늘어 "한 곳"이 0.11 에서 0.05 가 됐다.
# 뜻은 그대로 — 점 모양 잉크가 한 곳이라도 잡히면 후보다(Codex 재현:
# 0.10 을 그대로 두자 작은 진짜 점이 떨어졌다).
REST_DOT_MIN = 0.01
# 검출기가 **상자로** 본 붙임점은 화소 점수와 독립된 증거라 거두지 않는다
# (read_durations 가 그때만 1.0 을 적는다).
DOT_CERTAIN = 1.0
MAX_CAND = 12   # 조합 폭발 방지
# 붙임점 조합 둘의 점수 합 차이가 이보다 작으면 잉크로 갈린 게 아니다
DOT_MARGIN = 0.05
# regroup_dots 가 옮길 수 있는 점 — 이보다 또렷하면 그 자리에 있는 것이다
# (실측 day2sb-1 의 잘못 붙은 점 0.552·0.558 · 진짜 점은 대개 0.7 이상)
REGROUP_MAX = 0.65


def _whole_groups(m: dict, dotted_now) -> int:
    """
    점을 `dotted_now` 에 붙였을 때 **8분 박자 격자에서 끝나는 빔 묶음 수**.

    합이 아니라 **끝나는 자리**를 본다. 16분쉼표 뒤 [16,16,16] 은 합이 0.75박
    이지만 1박에서 끝나 정상이고, 마디를 넘는 빔의 앞 조각은 마디 끝에서
    끝난다(Codex 재현 — 합으로 재면 둘 다 막혔다). 8+16 으로 박 머리에서
    시작한 묶음은 0.75박에서 끝나 어긋난다 — 점이 빠졌다는 뜻이다.
    """
    add = {id(x) for x in dotted_now}
    seq = sorted([x for x in m["notes"] if not x.get("chord")]
                 + [x for x in (m.get("items") or []) if x.get("rest")],
                 key=lambda x: x.get("x", 0.0))
    pos, ends = 0, {}
    for x in seq:
        pos += value(x["duration"], x.get("dotted") or id(x) in add)
        g = x.get("beamGroup")
        if g is not None and g >= 0 and not x.get("rest"):
            ends[g] = pos
    return sum(1 for v in ends.values() if v % DUR["eighth"] == 0)
MAX_PICK = 3


def _split_locked(systems: list[list[dict]], beats: float) -> set:
    """쪼개진 마디 짝 + 못갖춘마디 짝 — 둘 다 반쪽인 게 정상이다."""
    sp = _split_pairs(systems, beats)
    return sp | pickup_pair(systems, beats, sp)


def _split_pairs(systems: list[list[dict]], beats: float) -> set:
    """
    **이미 짝이 맞는 쪼개진 마디**의 (단, 마디) 좌표.

    줄바꿈에서 쪼개진 마디는 반쪽인 게 정상이다. 혼자 채우면 짝이 깨져
    뒷 단 첫 마디가 고아가 된다 — 실측: 쉼표를 수리 대상에 넣자 3.0+1.0 ·
    3.5+0.5 짝 9개가 이렇게 깨졌다. promote_dots · fit_page 둘 다 걸어야
    한다(점으로 먼저 채워도 똑같이 깨진다).
    """
    def edge(ms, last):
        """빈 마디를 건너뛰고 실제 끝/시작 마디의 (자리, 박)을 낸다."""
        rng = range(len(ms) - 1, -1, -1) if last else range(len(ms))
        for j in rng:
            v = _beats(ms[j])
            if v > 0:
                return j, v
        return None, 0.0

    locked = set()
    for i in range(len(systems) - 1):
        a, b = systems[i], systems[i + 1]
        if not a or not b:
            continue
        ja, va = edge(a, True)
        jb, vb = edge(b, False)
        if ja is None or jb is None:
            continue
        if va < beats and vb < beats and abs(va + vb - beats) < 1e-6:
            locked.add((i, ja))
            locked.add((i + 1, jb))
    return locked


def pickup_pair(systems: list[list[dict]], beats: float = 4.0,
                splits: set | None = None) -> set:
    """
    **곡의 첫 마디와 끝 마디가 합쳐 한 마디면 못갖춘마디 짝이다.**

    못갖춘마디로 시작한 곡은 끝 마디가 그만큼 짧다 — 조판 관행이다.
    둘 중 하나만 짧으면 판독이 음표를 놓쳤을 수도 있으므로 인정하지 않는다.
    **서로 떨어진 두 마디가 정확히 한 마디를 이룰 때만** 짝으로 본다.

    실측 wish0823-3: 3박 끝 마디를 fit_page 가 8분 둘 → 4분 둘로 늘려
    4박을 만들었다. 합은 맞고 악보는 틀린 채 과금됐다.
    반환: {(단, 마디)} 두 개, 아니면 빈 집합
    """
    full = int(beats * 8)
    filled = [(si, mi) for si, ms in enumerate(systems)
              for mi, m in enumerate(ms) if _beats(m) > 0]
    if len(filled) < 2:
        return set()
    (fs, fm), (ls, lm) = filled[0], filled[-1]
    # **줄바꿈으로 쪼개진 조각은 이미 짝이 있다.** 첫 단이 1박 한 마디뿐이면
    # 그건 다음 단 첫 마디와 짝인데, 끝 마디와 또 묶으면 잘못 읽은 끝
    # 마디가 잠겨 검산을 빠져나간다(Codex 재현).
    if splits is None:
        splits = _split_pairs(systems, beats)
    if (fs, fm) in splits or (ls, lm) in splits:
        return set()
    a = round(_beats(systems[fs][fm]) * 8)
    b = round(_beats(systems[ls][lm]) * 8)
    # **끝 마디에 덜 읽었다는 증거가 있으면 짝이 아니다.** 1박 못갖춘마디로
    # 시작해 다음 쪽으로 이어지는 곡은 끝 마디가 온전한데, 그걸 3박으로
    # 잘못 읽으면 우연히 짝이 맞아 잠긴다(실측 wish0809-7: 끝 마디 2분음표를
    # 4분으로 읽어 3박 — 속 비움 0.32 로 빈 머리였다).
    if any(x["duration"] in UP and (x.get("hollow") or 0.0) >= HOLLOW_MIN
           for x in systems[ls][lm]["notes"] if not x.get("chord")):
        return set()
    if 0 < a < full and 0 < b < full and a + b == full:
        return {(fs, fm), (ls, lm)}
    return set()


def promote_dots(systems: list[list[dict]], beats: float = 4.0) -> int:
    """
    **합이 모자란 마디에서만** 회색지대 음표에 붙임점을 인정한다.

    붙임점 점수는 잉크 농도로 재는데, 저해상도 스캔에서는 진짜 점도
    문턱(0.55)을 못 넘는다. 문턱을 통째로 낮추면 선명한 악보에 오탐이
    생기므로(DAY2 마디 45→43), 대신 **박자를 심판으로 쓴다**: 마디 합이
    모자랄 때, 점을 붙이면 정확히 채워지는 회색지대 음표를 찾는다.
    합이 이미 맞는 마디는 후보조차 만들지 않으므로 오탐이 늘지 않는다.

    같은 합을 만드는 조합이 여럿이면 **점수가 높은 쪽**을 고른다 — 여기는
    fit_measure 와 달리 잉크라는 증거가 있으므로 찍는 게 아니다.

    fit_page 보다 **먼저** 돌려야 한다. 안 그러면 fitdur 가 음가를 먼저
    비틀어 붙임점 자리를 지워버린다.
    """
    full = int(beats * 8)
    hit = 0
    locked = _split_locked(systems, beats)
    for si, ms in enumerate(systems):
        n = len(ms)
        for mi, m in enumerate(ms):
            if (si, mi) in locked:
                continue
            cur = _beats(m) * 8
            short = full - round(cur)
            if short <= 0:
                continue
            edge = mi == 0 or mi == n - 1
            if edge and abs(_beats(m) - beats) > NEAR:
                continue
            # 화음 구성음은 후보에서 뺀다 — _beats 가 안 세므로 점을 붙여도
            # 합이 그대로다. 두면 "채웠다"고 세어 놓고 마디는 여전히 모자란다.
            cand = [x for x in m["notes"]
                    if not x.get("chord") and not x.get("dotted")
                    and DOT_GRAY <= x.get("dotScore", 0.0) < DOT_SURE]
            # **쉼표도 후보다.** 𝄼. 를 𝄼 로 읽으면 그 마디가 1박 모자라다.
            # 쉼표의 점수는 오선을 지운 그림에서 센 비율이라 눈금이 다르다 —
            # 머리의 회색지대(0.40~0.55) 대신 제 문턱을 쓴다
            # (durations.rest_dot_score 참고).
            cand += [x for x in (m.get("items") or [])
                     if x.get("rest") and not x.get("dotted")
                     and x.get("dotScore", 0.0) >= REST_DOT_MIN]
            cand.sort(key=lambda x: -x["dotScore"])
            cand = cand[:MAX_CAND]
            if not cand:
                continue
            best = None
            for k in range(1, min(MAX_PICK, len(cand)) + 1):
                # **한 마디에 점 붙은 쉼표는 하나까지.** 둘을 한꺼번에
                # 붙이면 합은 맞출 수 있어도 실제로 그런 마디는 드물고,
                # 손글씨가 많은 장에서 가짜 둘이 짝을 맞춘다(실측
                # wish0809-3 단2 마디1: 빨간 표시 위에 점 두 개).
                sets = [c for c in itertools.combinations(cand, k)
                        if sum(value(x["duration"]) // 2 for x in c) == short
                        and sum(1 for x in c if x.get("rest")) <= 1]
                if not sets:
                    continue
                # **빔 묶음이 먼저, 잉크 점수는 그다음.** 저해상도 스캔에서는
                # 점수가 다 비슷하다(실측 day2conti-2 단1: 0.45~0.49) — 그걸로
                # 고르면 점이 엉뚱한 음에 붙고 합은 맞아 그대로 과금됐다.
                # 빔 묶음은 8분 단위로 끝나므로 8+16(0.75박)은 미완성이고
                # 8.+16 이면 맞는다. 맞는 묶음이 많아지는 조합을 고른다.
                def key(c):
                    return (_whole_groups(m, c), sum(x["dotScore"] for x in c))
                sets.sort(key=key, reverse=True)
                best = sets[0]
                # 찍은 것이면 표시해 과금을 막는다 — "잉크라는 증거가 있다"로
                # 넘기면 안 된다. 둘 중 하나면 찍은 것이다:
                #   · 묶음으로도 못 가르고 점수 차가 작다
                #   · 묶음 규칙이 잉크를 크게 뒤집었다 — 두 증거가 다툰다
                #     (Codex 재현: .54 대신 .40 에 붙이고 표시 없이 통과)
                inked = max(sum(x["dotScore"] for x in c) for c in sets)
                if len(sets) > 1:
                    a, b = key(sets[0]), key(sets[1])
                    unsure = a[0] == b[0] and a[1] - b[1] < DOT_MARGIN
                else:
                    unsure = False
                unsure = unsure or inked - key(best)[1] >= DOT_MARGIN
                break
            if not best:
                continue
            for x in best:
                x["dotted"] = True
                x["dotPromoted"] = True
                if unsure:
                    x["guessed"] = True
            # 쉼표에 점이 붙었으면 마디의 쉼표 합을 다시 센다 — `_beats` 가
            # 이 값을 쓰므로, 안 고치면 뒤따르는 수리가 옛 합을 본다.
            if any(x.get("rest") for x in best):
                rs = [x for x in (m.get("items") or []) if x.get("rest")]
                m["rest"] = sum(value(x["duration"], x.get("dotted"))
                                for x in rs) / 8.0
            hit += len(best)
    return hit


def _groups(m: dict) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for x in m["notes"]:
        g = x.get("beamGroup")
        if g is not None and g >= 0 and not x.get("chord") and not x.get("rest"):
            out.setdefault(g, []).append(x)
    return out


def regroup_dots(systems: list[list[dict]], beats: float = 4.0) -> int:
    """
    **점이 옆 묶음으로 잘못 붙었으면 옮긴다 — 빔 묶음이 둘 다 맞을 때만.**

    저해상도 스캔은 붙임점 점수가 음마다 비슷해서(실측 day2sb-1 단3:
    0.44~0.58) 문턱을 겨우 넘은 엉뚱한 음에 점이 붙고 진짜 점은 빠진다.
    합은 그대로라 게이트를 통과해 틀린 채 과금됐다.

    빔 묶음은 8분 단위로 끝난다. [8,16](0.75박) 옆에 [8,8.](1.25박)이 있으면
    점 하나를 옮겨 둘 다 1박이 된다 — 서로 다른 두 묶음이 동시에 맞는 것은
    우연이 아니다. **같은 음가끼리만** 옮기므로 마디 합은 변하지 않는다.
    옮겨서 모든 묶음이 맞는 방법이 하나뿐일 때만 옮기고, 여럿이면
    `guessed` 로 표시해 과금을 막는다. 검출기가 상자로 본 점(DOT_CERTAIN)은
    옮기지 않는다.
    """
    moved = 0
    for ms in systems:
        for m in ms:
            gs = _groups(m)
            if not gs or _whole_groups(m, ()) == len(gs):
                continue
            notes = [x for g in gs.values() for x in g]
            # 점을 뺄 수 있는 쪽은 마디 안 어느 음이든 — 꼬리 달린 8분에
            # 잘못 붙은 점이 옆 묶음의 것인 경우가 있다(day2conti-2 단3).
            donors = [x for x in m["notes"] if not x.get("chord")]
            ways = []
            for a in donors:
                # 주는 쪽: 문턱 근처에서 붙은 점만 — 또렷한 점은 옮기지 않는다
                if not a.get("dotted") or a.get("dotScore", 0.0) >= REGROUP_MAX:
                    continue
                for b in notes:
                    if b is a or b.get("dotted") or b["duration"] != a["duration"]:
                        continue
                    # 받는 쪽도 점 같은 잉크가 있어야 한다 — 묶음만으로 점을
                    # 지어내지 않는다(Codex 재현: 잉크 0 인 음으로 옮겼다)
                    if b.get("dotScore", 0.0) < DOT_GRAY:
                        continue
                    a["dotted"], b["dotted"] = False, True
                    if _whole_groups(m, ()) == len(gs):
                        ways.append((a, b))
                    a["dotted"], b["dotted"] = True, False
            if not ways:
                continue
            a, b = max(ways, key=lambda w: w[1].get("dotScore", 0.0)
                       - w[0].get("dotScore", 0.0))
            a["dotted"], b["dotted"] = False, True
            a["dotDemoted"] = b["dotPromoted"] = True
            if len(ways) > 1:
                a["guessed"] = b["guessed"] = True
            _sync_chords(m["notes"])          # 화음 구성음도 같이 옮긴다
            moved += 1
    return moved


# 머리 속이 이만큼 비어 있으면 **2분·온음표 후보**로 본다.
# 실측 5장(검출 클래스별): 꽉 찬 머리 556개 중 550개가 0.0 이고 0.2 이상은
# 5개(0.9%)뿐 · 빈 머리는 0.1~0.9 에 퍼진다.
HOLLOW_MIN = 0.20
# **속 비움이 가르는 것은 2분·온음표뿐이다.** 4분·8분·16분은 전부 꽉 차
# 있어서, 그 사이 단계를 속 비움으로 정당화하면 fit_page 와 똑같은 찍기다
# (실측: 내린 머리 5개가 전부 8분·16분이었다 — 머리는 맞게 찼는데 음가를
# 바꿨다). 증거가 실제로 말해 주는 두 단계만 쓴다.
UP = {"quarter": "half", "half": "whole"}


def promote_hollow(systems: list[list[dict]], beats: float = 4.0) -> int:
    """
    **합이 모자란 마디에서만** 속이 빈 머리를 한 단계 긴 음가로 되돌린다.

    검출기가 빈 머리를 찬 머리로 부르면 2분음표가 4분음표가 되어 마디가
    1박 모자라다. 속 비움으로 **통째로** 되돌리는 것은 전에 재서 버렸다
    (103장에서 깨진 마디 804 → 826, 나빠진 마디 41개 — durations.py 주석).
    흐린 스캔의 찬 머리도 가운데가 밝게 나오기 때문이다.

    그래서 `promote_dots` 와 같은 틀로 가둔다 — **박자가 모자란다고 말하는
    마디에서, 한 단계 올리면 정확히 채워질 때만.** 이미 맞는 마디는 후보조차
    만들지 않으므로 맞던 게 틀려질 수 없다. 화소(속 비움)와 박자, 두 축이
    같은 답을 가리킬 때만 움직이는 것이라 찍기가 아니다.

    fit_page 보다 **먼저** 돌려야 한다 — 안 그러면 음가를 먼저 비틀어
    증거를 지운다.
    """
    full = int(beats * 8)
    hit = 0
    locked = _split_locked(systems, beats)
    for si, ms in enumerate(systems):
        n = len(ms)
        for mi, m in enumerate(ms):
            if (si, mi) in locked:
                continue
            short = full - round(_beats(m) * 8)
            if short <= 0:
                continue
            edge = mi == 0 or mi == n - 1
            if edge and abs(_beats(m) - beats) > NEAR:
                continue
            cand = [x for x in m["notes"]
                    if not x.get("chord") and UP.get(x["duration"])
                    and (x.get("hollow") or 0.0) >= HOLLOW_MIN]
            cand.sort(key=lambda x: -x["hollow"])
            cand = cand[:MAX_CAND]
            if not cand:
                continue

            def gain(x):
                d = bool(x.get("dotted"))
                return value(UP[x["duration"]], d) - value(x["duration"], d)

            best = None
            for k in range(1, min(MAX_PICK, len(cand)) + 1):
                sets = [c for c in itertools.combinations(cand, k)
                        if sum(gain(x) for x in c) == short]
                if not sets:
                    continue
                best = max(sets,
                           key=lambda c: sum(x["hollow"] for x in c))
                break
            if not best:
                continue
            for x in best:
                x["duration"] = UP[x["duration"]]
                x["hollowPromoted"] = True
            hit += len(best)
    return hit


# 머리 속이 이보다 덜 비었으면 **꽉 찬 머리**로 본다 — 2분·온음표가
# 아니다. 실측 5장: 검출기가 notehead_half 라 부른 것도 0.1 아래는 하나뿐.
HOLLOW_FILLED = 0.05
DOWN = {v: k for k, v in UP.items()}


def demote_hollow(systems: list[list[dict]], beats: float = 4.0) -> int:
    """
    **합이 넘치는 마디에서만** 꽉 찬 머리를 한 단계 짧은 음가로 내린다.
    `promote_hollow` 의 거울상이다.

    왜(실측 40장 164마디): "한 단계 내리면 맞는" 마디가 23개인데 그중
    19개의 머리가 **속비움 0.00** 이었다 — 꽉 찬 머리를 2분음표로 읽은
    것이다. 화소가 "이건 찬 머리다"라고 말하고 박자가 "한 단계 짧다"고
    말하면 두 축이 같은 답을 가리킨다.

    올리는 쪽과 같은 가드를 쓴다 — 이미 맞는 마디는 후보조차 안 되고,
    fit_page 보다 먼저 돈다.
    """
    full = int(beats * 8)
    hit = 0
    locked = _split_locked(systems, beats)
    for si, ms in enumerate(systems):
        n = len(ms)
        for mi, m in enumerate(ms):
            if (si, mi) in locked:
                continue
            over = round(_beats(m) * 8) - full
            if over <= 0:
                continue
            edge = mi == 0 or mi == n - 1
            if edge and abs(_beats(m) - beats) > NEAR:
                continue
            cand = [x for x in m["notes"]
                    if not x.get("chord") and DOWN.get(x["duration"])
                    # 잴 수 없었던 머리(None)는 꽉 찼다는 증거가 아니다
                    and x.get("hollow") is not None
                    and x["hollow"] <= HOLLOW_FILLED]
            cand.sort(key=lambda x: x["hollow"])
            cand = cand[:MAX_CAND]
            if not cand:
                continue

            def loss(x):
                d = bool(x.get("dotted"))
                return value(x["duration"], d) - value(DOWN[x["duration"]], d)

            best = None
            for k in range(1, min(MAX_PICK, len(cand)) + 1):
                sets = [c for c in itertools.combinations(cand, k)
                        if sum(loss(x) for x in c) == over]
                if not sets:
                    continue
                best = min(sets,
                           key=lambda c: sum(x["hollow"] for x in c))
                break
            if not best:
                continue
            for x in best:
                x["duration"] = DOWN[x["duration"]]
                x["hollowDemoted"] = True
            hit += len(best)
    return hit


def demote_dots(systems: list[list[dict]], beats: float = 4.0) -> int:
    """
    **합이 넘치는 마디에서만** 화소로 찍은 붙임점을 거둬들인다.
    `promote_dots` 의 거울상이다 — 심판도 같은 박자다.

    왜 필요한가(실측 day2sb-1 단5 마디2): 길고 납작한 이음줄이 머리 오른쪽
    붙임점 자리를 지나가면 그 잉크가 점으로 읽힌다(점수 0.565). 그 2분음표가
    점2분음표가 되자 마디가 5박이 됐고, fit_page 가 **멀쩡한 4분음표 두 개를
    8분음표로 비틀어** 4박을 맞췄다 — 합이 맞으니 게이트는 통과시킨다.
    점 하나를 거두면 그 마디가 정확히 4박이다.

    모양으로 점과 선을 가르는 길도 재 봤지만 못 쓴다 — 붙임점 자리의 잉크
    가로폭은 오선 줄이 같이 들어와 172개 중 131개가 창 끝까지 이어졌다.
    **박자가 더 날카로운 심판이다.**

    검출기가 상자로 본 점(dotScore 1.0)은 건드리지 않는다 — 화소 점수와
    달리 독립된 증거다. 답이 여럿이면 **점수가 낮은 쪽**을 거둔다.

    fit_page 보다 **먼저** 돌려야 한다 — 안 그러면 fitdur 가 음가를 먼저
    비틀어 증거를 지운다.
    """
    full = int(beats * 8)
    hit = 0
    locked = _split_locked(systems, beats)
    for si, ms in enumerate(systems):
        n = len(ms)
        for mi, m in enumerate(ms):
            if (si, mi) in locked:
                continue
            over = round(_beats(m) * 8) - full
            if over <= 0:
                continue
            edge = mi == 0 or mi == n - 1
            if edge and abs(_beats(m) - beats) > NEAR:
                continue
            cand = [x for x in m["notes"]
                    if not x.get("chord") and x.get("dotted")
                    and x.get("dotScore", 1.0) < DOT_CERTAIN]
            cand.sort(key=lambda x: x.get("dotScore", 1.0))
            cand = cand[:MAX_CAND]
            if not cand:
                continue
            best = None
            for k in range(1, min(MAX_PICK, len(cand)) + 1):
                sets = [c for c in itertools.combinations(cand, k)
                        if sum(value(x["duration"]) // 2 for x in c) == over]
                if not sets:
                    continue
                best = min(sets,
                           key=lambda c: sum(x.get("dotScore", 1.0) for x in c))
                break
            if not best:
                continue
            for x in best:
                x["dotted"] = False
                x["dotDemoted"] = True
            hit += len(best)
    return hit


def fit_page(systems: list[list[dict]], beats: float = 4.0) -> dict:
    """
    한 장 전체를 박자로 역산한다.

    systems: 단마다 마디 목록. 마디는 {"notes": [{duration, dotted}],
             "rest": 쉼표 박수}. notes 를 제자리에서 고친다.

    세 가지를 본다:
      ① **단 안쪽 마디** — 반쪽일 수 없으니 편차와 무관하게 혼자 맞춘다.
      ①' **단의 첫·마지막 마디** — 반쪽이거나 못갖춘마디일 수 있으므로
         4박에서 NEAR 안쪽일 때만 맞춘다. 마커스 단5의 1박 못갖춘마디는
         이 문턱 밖이라 손대지 않는다.
      ② **줄바꿈에서 쪼개진 마디** — 앞 단의 마지막과 뒷 단의 첫 마디는
         합이 정확히 한 마디여야 한다(실측: 마커스 단7 마디4 2박 + 단8 마디1
         2박 = 4박). 합이 안 맞으면 **둘을 합쳐** 한 마디로 역산한다.
         앞 단 마지막이 이미 온전하면 뒷 단 첫 마디는 반쪽이 아니므로
         (못갖춘마디일 수 있어) 건드리지 않는다.

    반환: {"alone": 혼자 고친 마디 수, "joined": 합쳐서 고친 쌍 수}
    """
    full = int(beats * 8)
    alone = joined = 0

    locked = _split_locked(systems, beats)

    for si, ms in enumerate(systems):
        n = len(ms)
        for mi, m in enumerate(ms):
            if (si, mi) in locked:
                continue
            b = _beats(m)
            if abs(b - beats) < 1e-6:
                continue
            edge = mi == 0 or mi == n - 1
            if edge and abs(b - beats) > NEAR:
                # NEAR 는 못갖춘마디와 쪼개진 반쪽을 지키려고 둔 문턱인데,
                # 그 둘은 이제 각자 막는다 — 못갖춘마디는 곡의 첫 마디뿐이고
                # (checkbeats 도 거기만 면제한다), 쪼개진 짝은 _split_locked
                # 가 잠근다. 남은 NEAR 밖 edge 마디는 **온전한 마디를 크게
                # 잘못 읽은 것**이다. 실측 105장: 안 고쳐진 미달 마디 중
                # ±1단계로 채워지는 38개가 **전부** edge 였고 32개는 답이
                # 유일했다. 그래서 **찍지 않고(guess=False) 유일할 때만**
                # 고친다 — 답이 갈리면 그대로 두고 사용자가 본다.
                if si == 0 and mi == 0:
                    continue                 # 곡의 첫 마디 = 못갖춘마디
                if _apply(m, full, guess=False):
                    alone += 1
                continue
            if _apply(m, full):
                alone += 1

    for i in range(len(systems) - 1):
        a, b = systems[i], systems[i + 1]
        if not a or not b:
            continue
        la, fb = a[-1], b[0]
        va, vb = _beats(la), _beats(fb)
        if abs(va - beats) < 1e-6:      # 앞 단이 온전하면 쪼개진 게 아니다
            continue
        if abs(va + vb - beats) < 1e-6:  # 이미 합이 한 마디 — 정상
            continue
        pair = {"notes": la["notes"] + fb["notes"],
                "rest": la["rest"] + fb["rest"]}
        if _apply(pair, full):
            joined += 1

    return {"alone": alone, "joined": joined}
