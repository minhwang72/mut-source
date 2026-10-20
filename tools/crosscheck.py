"""
**두 판독기 교차 검증** — 우리 struct 를 homr 결과와 마디 단위로 맞춘다.

규칙 기준(평가 eval/homr/ensemble.py, 105장): 교차하면 정답 통과가 8 → 11장,
11장 전부 원본과 일치. 독립된 두 판독기가 같게 읽은 마디는 거의 틀리지 않는다.

마디마다 (박이 맞다 = 음가 합이 한 마디):
  같게 읽음                → 확정. fit_page 가 찍은 표시(guessed)도 지운다 —
                             다른 판독기가 같은 답을 냈으면 찍은 게 아니다.
  우리만 안 맞고 homr 는 맞음 → homr 음가를 쓴다. **음높이는 우리 머리에서**
                             — 쉼표 아닌 음표 수가 같을 때만 짝지을 수 있다.
  둘 다 맞는데 다름          → 막는다(review). 우리가 머리를 또렷하게 본 자리를
                             homr 가 같은 길이 쉼표로 읽은 것만은 우리 쪽을 쓴다.
  그 밖                     → 우리 그대로.
단 수·마디 수가 서로 다르면 그 단은 비교하지 않는다(우리 판독 그대로).
"""
from __future__ import annotations

V = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}
NAME = {v: k for k, v in V.items()}


def _tok(n: dict) -> str:
    v = V[n["duration"]] * (1.5 if n.get("dotted") else 1.0)
    return ("r" if n.get("rest") else "") + f"{v:g}"


def _len(seq) -> float:
    return sum(float(t.lstrip("r")) for t in seq)


def _dur(tok: str):
    """'0.75' → ('eighth', True). 우리가 못 그리는 길이면 None."""
    v = float(tok.lstrip("r"))
    if v in NAME:
        return NAME[v], False
    if v / 1.5 in NAME:
        return NAME[v / 1.5], True
    return None


def _units(notes: list[dict]) -> list[list[dict]]:
    """박을 차지하는 음(앞장선 음)마다 [그 음, 화음 구성음…]."""
    out: list[list[dict]] = []
    for n in notes:
        if n.get("chord") and out:
            out[-1].append(n)
        else:
            out.append([n])
    return out


def _adopt(units: list[list[dict]], theirs: list[str], mi: int) -> list[dict] | None:
    """homr 음가를 우리 음표에 입힌다. 음표 수가 다르면 None."""
    heads = [u for u in units if not u[0].get("rest")]
    if len(heads) != sum(1 for t in theirs if not t.startswith("r")):
        return None
    if any(_dur(t) is None for t in theirs):
        return None
    out, k = [], 0
    for t in theirs:
        name, dot = _dur(t)
        if t.startswith("r"):
            out.append({"measure": mi, "duration": name, "dotted": dot, "rest": True,
                        "tie": False, "chord": False, "beamGroup": -1, "homrFixed": True})
            continue
        for x in heads[k]:
            x["duration"], x["dotted"] = name, dot
            x["homrFixed"], x["guessed"] = True, False
        out.extend(heads[k])
        k += 1
    return out


def merge(struct: dict, homr: list[list[list[str]]] | None) -> dict:
    """
    struct 를 제자리에서 고친다. 반환: 통계.

    **마디를 쪽 전체에서 순서대로 짝짓는다.** 처음엔 '같은 단 번호의 같은 마디
    번호'끼리만 비교해서, 한쪽이 단을 하나 더 찾거나 세로줄 하나를 놓치면 그 단
    (또는 쪽)이 통째로 빠졌다 — 단 수가 다른 장 25, 마디 수가 다른 단 87(105장).
    이제는 두 마디 목록을 정렬한다(_align): 같으면 짝, 한쪽 두 마디를 이은 것이
    다른 쪽 한 마디와 같으면 '세로줄을 놓친 같은 내용', 나머지는 비슷할 때만 짝.
    """
    stat = {"agree": 0, "homr": 0, "ours": 0, "conflict": 0, "skipped": 0}
    systems = struct.get("systems") or []
    pitch = hkey = None
    if isinstance(homr, dict):                 # {"dur", "pitch", "key"} — homr_runner.systems
        homr, pitch, hkey = homr.get("dur"), homr.get("pitch"), homr.get("key")
    if not homr:
        stat["skipped"] = len(systems)
        return stat
    full = float(struct.get("beats") or 4)
    ours_m = []                       # (단, 마디번호)
    for si, sys_ in enumerate(systems):
        for mi in sorted({n["measure"] for n in sys_.get("notes") or []}):
            ours_m.append((si, mi))
    seq_o = [[_tok(u[0]) for u in _units([n for n in systems[si]["notes"] if n["measure"] == mi])]
             for si, mi in ours_m]
    seq_t = [m for sysm in homr for m in sysm]
    pit_t = [m for sysm in pitch for m in sysm] if pitch else None
    key_t = [m for sysm in hkey for m in sysm] if hkey else None
    pairs, at = _align(seq_o, seq_t)   # 우리 마디 k → homr 토큰 목록 / homr 마디 번호
    allchecks: list[list] = []
    for si, sys_ in enumerate(systems):
        notes = sys_.get("notes") or []
        new: list[dict] = []
        checks = []                    # 박이 같게 읽힌 마디: (마디, 음표, homr 음높이, homr 조표)
        for mi in sorted({n["measure"] for n in notes}):
            mine = [n for n in notes if n["measure"] == mi]
            k = ours_m.index((si, mi))
            theirs = pairs.get(k)
            if theirs is None:
                stat["skipped"] += 1
                new += mine
                continue
            got = _decide(sys_, mi, mine, theirs, full, stat)
            if pit_t and k in at and [_tok(u[0]) for u in _units(got)] == theirs:
                checks.append((mi, got, pit_t[at[k]], key_t[at[k]] if key_t else None))
            new += got
        sys_["notes"] = new
        allchecks.append(checks)
    # 조표는 구간(같은 조표가 이어지는 단들) 단위로 맞춘다 — 단마다 따로 고치면
    # 대조할 음이 없는 단만 옛 값으로 남아 구간 안에서 조표가 들쭉날쭉해진다
    run: list[int] = []
    for si in range(len(systems) + 1):
        if run and (si == len(systems) or _fifths(systems[si], struct) != _fifths(systems[run[0]], struct)):
            _key_check([systems[i] for i in run], [allchecks[i] for i in run],
                       _fifths(systems[run[0]], struct), stat)
            run = []
        if si < len(systems):
            run.append(si)
    for sys_ in systems:
        _agreed_pickup(sys_, full, stat)
        _drop_stale_count_review(sys_, full)
    return stat


def _agreed_pickup(sys_: dict, full: float, stat: dict) -> None:
    """
    **단 첫 마디가 짧은데 두 판독이 똑같이 읽었으면 못갖춘마디다.**

    곡 첫머리의 여린박(실측 wish0809-7 등 4장: '16 16 8' 1박), 2번 도돌이 줄 첫
    마디(camp0814b-10: 1번 줄과 같은 2박), 구간을 다시 여는 여린박(wish0823-5)은
    짝지을 끝 마디가 없어 막혔다. 독립된 두 판독기가 같은 음가로 읽었으면 음을
    놓친 게 아니라 원래 짧은 마디다 — 게이트가 봐 주는 pickups 에 넣는다.
    """
    notes = sys_.get("notes") or []
    if not notes:
        return
    m0 = min(n["measure"] for n in notes)
    first = [n for n in notes if n["measure"] == m0]
    beats = sum(V[n["duration"]] * (1.5 if n.get("dotted") else 1.0)
                for n in first if not n.get("chord"))
    if 0 < beats < full - 1e-6 and all(n.get("crossChecked") for n in first):
        pk = sys_.setdefault("pickups", [])
        if m0 not in pk:
            pk.append(m0)
            stat["pickup"] = stat.get("pickup", 0) + 1


def _fifths(sys_: dict, struct: dict):
    """rebuild.js 와 같게 — 단별 값이 없으면 쪽 전체 값."""
    f = sys_.get("srcFifths")
    return struct.get("sourceFifths") if f is None else f


def _decide(sys_, mi, mine, theirs, full, stat) -> list[dict]:
    """짝지은 한 마디를 판정한다 — 규칙은 모듈 머리말."""
    units = _units(mine)
    ours = [_tok(u[0]) for u in units]
    ok_o, ok_t = abs(_len(ours) - full) < 1e-6, abs(_len(theirs) - full) < 1e-6
    if ours == theirs:
        stat["agree"] += 1
        for n in mine:
            n["guessed"] = False
            n["crossChecked"] = True
        return mine
    if ok_t and not ok_o:
        got = _adopt(units, theirs, mi)
        if got is not None:
            stat["homr"] += 1
            return got
    # **우리가 찍은 자리만 다르면 homr 가 골라 준 것이다.** fit_page 는 답이
    # 여럿일 때 하나를 찍고 guessed 를 붙인다. homr 가 찍지 않은 음표에서는 전부
    # 같고 찍은 음표에서만 다르면, 독립된 판독기가 후보 중 하나를 고른 셈이다 —
    # 그 답을 쓰고 표시를 지운다. 찍지 않은 음표에서도 다르면 아래에서 막는다.
    if ok_o and ok_t and len(ours) == len(theirs):
        diff = [i for i, (x, y) in enumerate(zip(ours, theirs)) if x != y]
        if diff and all(units[i][0].get("guessed")
                        and ours[i].startswith("r") == theirs[i].startswith("r")
                        for i in diff):
            for i in diff:
                d = _dur(theirs[i])
                if d is None:
                    break
            else:
                for i in diff:
                    name, dot = _dur(theirs[i])
                    for x in units[i]:
                        x["duration"], x["dotted"] = name, dot
                for n in mine:
                    n["guessed"] = False
                    n["crossChecked"] = True
                stat["resolved"] = stat.get("resolved", 0) + 1
                return mine
    # **둘 다 짧은데 다르게 읽은 마디도 막는다.** 단 끝에서 쪼개진 마디는 둘 다
    # 한 마디가 안 되는 게 정상이라 예전엔 비교 없이 우리 쪽을 썼다 — 그런데
    # 점4분쉼표를 4분쉼표로, 8분음표를 4분음표로 읽어 짝의 합(3+1)만 맞춘 오답이
    # 통과했다(실측 wish0823-5 단1 끝·단2 첫: homr 는 'r2 r1.5' · '0.5' 로 정답).
    both_short = _len(ours) < full - 1e-6 and _len(theirs) < full - 1e-6
    if ((ok_o and ok_t) or both_short) and not _ours_saw_heads(units, theirs):
        stat["conflict"] += 1
        sys_.setdefault("review", []).append(f"마디 {mi}: 두 판독이 다르게 읽었습니다")
    else:
        stat["ours"] += 1
    return mine


# 짝지을 만큼 비슷한가 — 음가 토큰 순서가 이 비율 이상 겹쳐야 한다(엉뚱한 마디와
# 짝지어 homr 음가를 입히지 않게)
SIMILAR = 0.5


def _align(a: list[list[str]], b: list[list[str]]) -> tuple[dict[int, list[str]], dict[int, int]]:
    """
    우리 마디 목록 a 와 homr 마디 목록 b 를 정렬해 a 의 자리마다 짝 토큰을 준다.

    비용: 같음 0 · 비슷함(SIMILAR 이상) 1 · 건너뛰기 1 · 두 마디↔한 마디 이음이
    같음 0.5. 이음으로 짝지은 경우는 둘 다 '같음'으로 본다(그 마디 토큰을 그대로).
    """
    import difflib
    n, m = len(a), len(b)
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0

    def sim(x, y):
        return x == y or difflib.SequenceMatcher(None, x, y).ratio() >= SIMILAR

    for i in range(n + 1):
        for j in range(m + 1):
            c = cost[i][j]
            if c == INF:
                continue
            steps = []
            if i < n and j < m:
                steps.append((i + 1, j + 1, 0.0 if a[i] == b[j] else (1.0 if sim(a[i], b[j]) else 1.9), "pair"))
            if i < n:
                steps.append((i + 1, j, 1.0, "skip_a"))
            if j < m:
                steps.append((i, j + 1, 1.0, "skip_b"))
            if i + 1 < n and j < m and a[i] + a[i + 1] == b[j]:
                steps.append((i + 2, j + 1, 0.5, "a2"))
            if i < n and j + 1 < m and a[i] == b[j] + b[j + 1]:
                steps.append((i + 1, j + 2, 0.5, "b2"))
            for i2, j2, w, how in steps:
                if c + w < cost[i2][j2]:
                    cost[i2][j2] = c + w
                    back[i2][j2] = (i, j, how)
    path = []
    i, j = n, m
    while (i, j) != (0, 0) and back[i][j] is not None:
        pi, pj, how = back[i][j]
        path.append((pi, pj, how))
        i, j = pi, pj
    diag = {(pi, pj) for pi, pj, how in path if how == "pair"}
    out: dict[int, list[str]] = {}
    at: dict[int, int] = {}            # 1:1 로 짝지은 자리만 — homr 마디 번호
    for pi, pj, how in path:
        if how == "pair":
            # 비슷하면 짝. 많이 달라도 **앞뒤가 1:1 로 짝지어진 자리**면 같은
            # 마디다 — 위치가 고정돼 엉뚱한 마디일 수 없다(실측 day2sb-1 단7:
            # 'r2 r8 4' 대 'r2. r8 8' — 바로 homr 가 고쳐야 할 마디였다).
            before = (pi, pj) == (0, 0) or (pi - 1, pj - 1) in diag
            after = (pi, pj) == (n - 1, m - 1) or (pi + 1, pj + 1) in diag
            if sim(a[pi], b[pj]) or (before and after):
                out[pi] = b[pj]
                at[pi] = pj
        elif how == "a2":
            out[pi], out[pi + 1] = a[pi], a[pi + 1]
        elif how == "b2":
            out[pi] = a[pi]
    return out, at


def _alter(n: dict, fifths: int, acc: dict, key: dict) -> int:
    """web/source-pitch.js 와 같은 규칙 — 임시표는 그 마디·그 옥타브, 붙임줄은 넘어간다."""
    base = n["pos"]
    explicit = 0 if n.get("natural") else n.get("accidental")
    if explicit is not None:
        acc[base] = explicit
    alt = acc.get(base)
    if alt is None and key["tie"] and key["tie"][0] == base:
        alt = key["tie"][1]
    if alt is None:
        order = "FCGDAEB" if fifths >= 0 else "BEADGCF"
        alt = (1 if fifths > 0 else -1) if base[0] in order[:abs(fifths)] else 0
    key["tie"] = (base, alt) if n.get("tie") else None
    return alt


def _compare(checks, fifths: int) -> tuple[int, list[int], list[str]]:
    """조표 fifths 로 읽었을 때 (맞은 음 수, 임시표가 다른 마디, 자리가 다른 음)."""
    agree, acc_bad, pos_bad = 0, [], []
    key = {"tie": None}
    for mi, got, theirs, _ in checks:
        acc: dict = {}
        for u, t in zip(_units(got), theirs):
            if u[0].get("rest") or t == "r" or any("pos" not in x for x in u):
                key["tie"] = None
                continue
            # 화음이면 homr 는 구성음 하나만 준다 — 같은 자리의 구성음과 맞춘다
            tie, alts = key["tie"], []
            for x in u:
                key["tie"] = tie
                alts.append(_alter(x, fifths, acc, key))
            base = t[0] + t.lstrip("ABCDEFG#b")
            hit = [a for x, a in zip(u, alts) if x["pos"] == base]
            if not hit:
                pos_bad.append((mi, f"{u[0]['pos']}/{t}"))
            elif hit[0] == t.count("#") - t[1:].count("b"):
                agree += 1
            else:
                acc_bad.append(mi)
    return agree, acc_bad, pos_bad


def _key_check(group: list[dict], checks: list[list], ours, stat) -> None:
    """
    **박이 같게 읽힌 마디에서 음높이를 맞춰 본다.** 음이름이 같은데 올림·내림이
    다르면 임시표나 조표를 잘못 읽은 것이다 — 조용히 틀린 음을 내지 않게 막는다
    (실측 camp0814b-02 단7: ♭ 를 ♮ 로 읽었고, 다른 ♭ 하나는 검출조차 안 됐다).

    **조표를 하나 덜(더) 센 것이면 고친다.** 조표 판독이 ±1 흔들린다(실측
    set0816-5: A장조 ♯3 을 ♯2 로). 같은 조표 구간 전체를 homr 가 읽은 조표나
    ±1 로 다시 맞춰 보고, 어긋남이 전부 사라지는 값이 하나뿐이면 그것을 쓴다.
    """
    if not isinstance(ours, int):
        return
    flat = [c for cs in checks for c in cs]
    if not flat:
        return

    def run(f):
        agree, pos, bad = 0, [], []
        for sys_, cs in zip(group, checks):
            a, b, p = _compare(cs, f)
            agree += a
            pos += [(sys_, mi, w) for mi, w in p]
            bad += [(sys_, mi) for mi in b]
        return agree, bad, pos

    agree, bad, pos = run(ours)
    # 어긋난 음이 하나뿐이면 조표가 아니라 그 음(임시표)일 수 있다 — 고치지 않고 막는다
    # (실측 wish0906-1: 대조 음 8개 중 1개로 ♭2 → 0 으로 바꿨는데 정답은 ♭1)
    if len(bad) >= 2:
        theirs = {c[3] for c in flat if isinstance(c[3], int)}
        cands = ({ours - 1, ours + 1} | theirs) - {ours}
        fits = [f for f in cands if abs(f) <= 7 and not run(f)[1]]
        if len(fits) == 1:
            agree2, _, pos = run(fits[0])
            if agree2 >= agree + len(bad):
                for sys_ in group:
                    sys_["srcFifths"] = fits[0]
                stat["keyFixed"] = stat.get("keyFixed", 0) + 1
                agree, bad = agree2, []
    stat["pitchAgree"] = stat.get("pitchAgree", 0) + agree
    stat["posDiff"] = stat.get("posDiff", 0) + len(pos)
    stat["accDiff"] = stat.get("accDiff", 0) + len(bad)
    # **음 자리가 다르면 막는다.** 머리 상자가 반 칸 위로 치우쳐 C5 를 D5 로 읽은
    # 일이 있었다(실측 wish0809-7 단2: 상자 중심이 줄·칸 경계 근처). 통과 14장은
    # 이 어긋남이 0 이라, 막아도 잃는 통과가 없다.
    for sys_, mi, w in pos:
        stat.setdefault("posWhere", []).append(f"{sys_.get('system')}:{mi} {w}")
        msg = f"마디 {mi}: 음 높이가 두 판독에서 다릅니다 — 원본 확인 필요"
        if msg not in sys_.setdefault("review", []):
            sys_["review"].append(msg)
    seen = set()
    for sys_, mi in bad:
        if (id(sys_), mi) in seen:
            continue
        seen.add((id(sys_), mi))
        stat.setdefault("accWhere", []).append(f"{sys_.get('system')}:{mi}")
        sys_.setdefault("review", []).append(
            f"마디 {mi}: 임시표가 두 판독에서 다릅니다 — 원본 확인 필요")


def _drop_stale_count_review(sys_: dict, full: float) -> None:
    """
    **박이 다 맞게 됐으면 '개수 판독 불일치' 경고를 거둔다.**

    detstruct 는 그 경고를 '검출대로 읽은 마디 합이 틀릴 때만' 붙인다 —
    합이 맞으면 LLM 개수가 틀린 쪽이라서다(실측 93%). 교차 검증이 박을 고친
    뒤에도 병합 전 경고가 남아 그 단을 막고 있었다(set0816-1 등 5장).
    """
    per: dict = {}
    for n in sys_["notes"]:
        if not n.get("chord"):
            per[n["measure"]] = per.get(n["measure"], 0.0) + \
                V[n["duration"]] * (1.5 if n.get("dotted") else 1.0)
    if per and _beats_ok(per, full):
        rv = [r for r in sys_.get("review") or [] if not r.startswith("기존 개수 판독")]
        if rv:
            sys_["review"] = rv
        else:
            sys_.pop("review", None)


def _ours_saw_heads(units, theirs) -> bool:
    """우리가 음표로, homr 가 같은 길이 쉼표로 읽은 차이뿐이고 그 머리를 우리가
    검출로 봤으면(되살린 머리가 아니면) 우리 쪽이 맞다(실측 camp0814a-3 첫 음)."""
    ours = [_tok(u[0]) for u in units]
    if len(ours) != len(theirs):
        return False
    for u, a, b in zip(units, ours, theirs):
        if a == b:
            continue
        if a.lstrip("r") != b.lstrip("r") or not b.startswith("r") or a.startswith("r"):
            return False
        if u[0].get("headPromoted") or not u[0].get("head"):
            return False
    return True


def _beats_ok(per: dict, full: float) -> bool:
    """마디 합이 다 한 마디인가 — 단의 첫·끝 마디가 짧은 건 쪼개진 짝이나
    못갖춘마디일 수 있어 여기서 따지지 않는다(게이트의 짝 검사가 본다)."""
    ks = sorted(per)
    return all(abs(per[k] - full) < 1e-6 or (k in (ks[0], ks[-1]) and per[k] < full)
               for k in ks)
