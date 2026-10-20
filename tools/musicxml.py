#!/usr/bin/env python3
"""
추출한 데이터를 MusicXML로 조립한다.

왜 XML인가: 픽셀을 미는 방식은 **임시표를 다시 계산할 수 없다.** 조표가
바뀌면 ♯·♭·♮이 달라져야 하는데, 옛 글리프를 그대로 옮기면 반음이 틀린다.
XML은 음높이만 옮기면 조판 엔진이 임시표를 알아서 쓴다. 키를 몇 번 바꿔도
매번 새로 그리므로 누적 열화도 없다.

가사는 **넣지 않는다.** 한글 가사는 LLM이 지어내고(실측: "주 이름 찬양"을
"즐거운 찬란한"으로) OCR도 불안정하다. 원본 픽셀 조각을 오려 렌더 결과
위에 붙이는 쪽이 100%다. 여기서는 자리(음절이 붙을 음표)만 표시한다.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

# 8분음표를 4로 잡는다 — 16분음표(2)와 점8분음표(6)가 정수로 떨어진다
DIVISIONS = 8
DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
STEPS = "CDEFGAB"


def parse_pitch(name: str) -> tuple[str, int, int]:
    """'F#4' → ('F', 1, 4).  ('Bb3' → ('B', -1, 3))"""
    step = name[0].upper()
    i = 1
    alter = 0
    while i < len(name) and name[i] in "#b♯♭":
        alter += 1 if name[i] in "#♯" else -1
        i += 1
    return step, alter, int(name[i:] or 4)


def split_root(sym: str) -> tuple[str, int, str]:
    """'Ebmaj7' → ('E', -1, 'maj7').  근음 글자와 임시표만 떼어낸다."""
    step = sym[0].upper()
    i = 1
    alter = 0
    while i < len(sym) and sym[i] in "#b♯♭":
        alter += 1 if sym[i] in "#♯" else -1
        i += 1
    return step, alter, sym[i:]


def _harmony(text: str, offset: int = 0) -> str:
    """코드 심볼을 <harmony>로. 못 읽는 형태는 그대로 텍스트로 남긴다."""
    body = text.split("/")
    step, alter, tail = split_root(body[0])
    kind = "major"
    if tail.startswith("m") and not tail.startswith("maj"):
        kind = "minor-seventh" if "7" in tail else "minor"
    elif tail.startswith("maj"):
        kind = "major-seventh"
    elif "7" in tail:
        kind = "dominant"
    elif tail.startswith("sus"):
        kind = "suspended-fourth"
    out = ["  <harmony>", "   <root>", f"    <root-step>{step}</root-step>"]
    if alter:
        out.append(f"    <root-alter>{alter}</root-alter>")
    out += ["   </root>", f'   <kind text="{escape(tail)}">{kind}</kind>']
    if len(body) == 2:
        bs, ba, _ = split_root(body[1])
        out += ["   <bass>", f"    <bass-step>{bs}</bass-step>"]
        if ba:
            out.append(f"    <bass-alter>{ba}</bass-alter>")
        out.append("   </bass>")
    # **가로 위치.** 한 마디에 코드가 둘 이상인 경우가 흔하다(실측: 마커스
    # 43개 중 8개가 마디당 1개 규칙에서 유실됐다). `<offset>`은 마디 첫머리
    # 기준 이동량(divisions)이다.
    #
    # 마디 중간에 `<harmony>`를 끼워 넣는 방법은 쓰지 않는다 — Verovio가
    # 위치마다 세로 공간을 따로 잡아 코드가 오선 위 별도 띠로 밀려나고
    # 서로 겹쳤다(직접 확인).
    if offset:
        out.append(f"   <offset>{offset}</offset>")
    out.append("  </harmony>")
    return "\n".join(out)


BEAMABLE = {"eighth": 1, "16th": 2}


def add_beams(notes: list[dict]) -> None:
    """
    이어진 8·16분음표를 **빔으로 묶는다.** 쉼표·4분음표 이상에서 끊긴다.

    빔이 없으면 Verovio가 전부 깃발로 그려 실제 악보와 전혀 다른 그림이 된다
    (실측: 위싱 콘티를 재조판했더니 원본의 빔 묶음이 모두 깃발로 나왔다).
    **원본에서 검출한 빔이 있으면 그걸 그대로 쓴다**(`beamGroup`). 목표는
    "키만 바뀐 같은 악보"인데, 묶음을 지어내면 꼬리 연결이 제멋대로여서
    다른 악보로 보인다. 검출값이 없을 때만(합성 데이터·미검출) 2~4개씩
    끊는 조판 관행으로 물러난다.

    gendata(학습 데이터)와 rebuild(실제 변환)가 **같은 함수를 쓴다.** 학습
    데이터에만 빔이 있고 변환 결과에 없으면 그림이 어긋난다.
    """
    run: list[dict] = []

    def flush() -> None:
        if len(run) < 2:
            run.clear()
            return
        for i, n in enumerate(run):
            lvl = BEAMABLE[n["duration"]]
            kind = ("begin" if i == 0
                    else ("end" if i == len(run) - 1 else "continue"))
            n["beams"] = [kind] * lvl
        run.clear()

    prev_group = None
    for n in notes:
        if n.get("pitch") is None or n["duration"] not in BEAMABLE:
            flush()
            prev_group = None
            continue
        group = n.get("beamGroup")
        if group is not None and group >= 0:
            # 원본 빔이 바뀌면 거기서 끊는다 — 개수로 자르지 않는다
            if prev_group is not None and group != prev_group:
                flush()
            run.append(n)
            prev_group = group
            continue
        # 검출값이 없는 음표: 원본 묶음과 섞지 않는다
        if prev_group is not None:
            flush()
            prev_group = None
        run.append(n)
        if len(run) >= 4:
            flush()
    flush()


def build(measures: list[dict], fifths: int, beats=4, beat_type=4,
          title: str = "", subtitle: str = "", composer: str = "") -> str:
    """
    measures: [{"chords": ["Bb/D", ...],
                "notes": [{"pitch": "C5"|None(쉼표),
                           "duration": "quarter", "dotted": bool,
                           "tie": bool}]}]
    """
    x = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN"'
         ' "http://www.musicxml.org/dtds/partwise.dtd">',
         '<score-partwise version="4.0">']
    if title:
        x.append(f" <work><work-title>{escape(title)}</work-title></work>")
    # 작곡자·부제는 원본 악보에 있던 것을 그대로 옮긴다 — 개인 연습용
    # 출력물에서 원저작자 표기를 지우지 않는다(저작권 설계).
    if composer or subtitle:
        x.append(" <identification>")
        if composer:
            x.append(f'  <creator type="composer">{escape(composer)}'
                     f'</creator>')
        if subtitle:
            x.append(f'  <creator type="lyricist">{escape(subtitle)}'
                     f'</creator>')
        x.append(" </identification>")
    # **파트 이름을 찍지 않는다.** 멜로디 한 줄짜리 콘티 악보에 "melody"가
    # 왼쪽에 붙으면 원본에 없던 글자가 생긴다.
    x += [' <part-list><score-part id="P1">'
          '<part-name print-object="no">melody</part-name>'
          '</score-part></part-list>',
          ' <part id="P1">']
    cur_fifths = fifths          # 지금까지 유효한 조표
    for mi, m in enumerate(measures):
        x.append(f'  <measure number="{mi + 1}">')
        # **단 나누기를 원본과 똑같이 강제한다.** 조판이 달라지면 콘티로 못
        # 쓴다 — 찬양팀은 "3단 두 번째 마디부터"처럼 위치로 소통하고, 한
        # 페이지에 들어가던 곡이 두 장이 되면 넘기며 연주해야 한다.
        # Verovio 는 breaks="encoded" 로 이 지시를 그대로 따른다.
        if m.get("newSystem") and mi > 0:
            x.append('   <print new-system="yes"/>')
        if m.get("newPage") and mi > 0:
            x.append('   <print new-page="yes"/>')
        # **도돌이표 시작·볼타 시작은 마디 왼쪽에 온다.** 콘티는 반복으로
        # 곡을 적으므로 이게 없으면 형식을 따라갈 수 없다(실측: 위싱 콘티에
        # 도돌이표와 1./2. 볼타가 있다).
        if m.get("repeatStart") or m.get("voltaStart"):
            x.append('   <barline location="left">')
            if m.get("repeatStart"):
                x.append("    <bar-style>heavy-light</bar-style>")
            if m.get("voltaStart"):
                x.append(f'    <ending number="{escape(m["voltaStart"])}"'
                         f' type="start"/>')
            if m.get("repeatStart"):
                x.append('    <repeat direction="forward"/>')
            x.append("   </barline>")
        if mi == 0:
            # **마디 번호를 찍지 않는다.** 원본 콘티 악보에는 없다.
            # Verovio의 mnumInterval=0 은 "끄기"가 아니라 "기본값"이라
            # 안 먹힌다 — MusicXML 쪽에서 끈다.
            x.append("   <print><measure-numbering>none"
                     "</measure-numbering></print>")
            x += ["   <attributes>",
                  f"    <divisions>{DIVISIONS}</divisions>",
                  f"    <key><fifths>{fifths}</fifths></key>",
                  f"    <time><beats>{beats}</beats>"
                  f"<beat-type>{beat_type}</beat-type></time>",
                  "    <clef><sign>G</sign><line>2</line></clef>",
                  "   </attributes>"]
        elif m.get("fifths") is not None and int(m["fifths"]) != cur_fifths:
            # **곡 중간의 조표 변경(전조).** 콘티는 후반부에서 키를 올리는
            # 경우가 흔하다. 조표를 바꿔 주지 않으면 그 구간이 임시표투성이가
            # 된다 — 실측: 「지금 여기 우리」는 C 섹션부터 G → Bb 로 바뀌는데
            # 한 조표로 그렸더니 겹올림표(C×·F×)까지 나왔다.
            x += ["   <attributes>",
                  f"    <key><fifths>{int(m['fifths'])}</fifths></key>",
                  "   </attributes>"]
            cur_fifths = int(m["fifths"])
        # 코드는 전부 마디 첫머리에 적고 `<offset>`으로 자리를 잡는다.
        # 문자열이면 offset 0, {"text":..., "offset":...} 이면 그 값을 쓴다.
        for c in m.get("chords", []):
            if isinstance(c, dict):
                x.append(_harmony(c["text"], int(c.get("offset", 0))))
            else:
                x.append(_harmony(c))
        for n in m["notes"]:
            if n.get("unresolved"):
                raise ValueError("미확정 음표를 쉼표로 바꾸어 출력할 수 없습니다")
            d = DUR[n["duration"]]
            if n.get("dotted"):
                d = d * 3 // 2
            x.append("   <note>")
            # **화음.** 둘째 음부터 <chord/> 를 달면 같은 시각에 쌓여 그려지고
            # 박도 앞으로 가지 않는다. 콘티의 간주 스트립이 이 모양이다.
            if n.get("chord"):
                x.append("    <chord/>")
            if n["pitch"] is None:
                x.append("    <rest/>")
            else:
                s, a, o = parse_pitch(n["pitch"])
                x.append("    <pitch>")
                x.append(f"     <step>{s}</step>")
                if a:
                    x.append(f"     <alter>{a}</alter>")
                x.append(f"     <octave>{o}</octave>")
                x.append("    </pitch>")
            x.append(f"    <duration>{d}</duration>")
            x.append(f"    <type>{n['duration']}</type>")
            if n.get("dotted"):
                x.append("    <dot/>")
            # 자연표(♮)는 alter로 표현할 수 없다 — 조표를 취소한다는 **표기**라
            # <accidental>로 명시해야 그려진다. 학습 데이터에 ♮ 표본을 넣기
            # 위해 쓴다.
            if n.get("natural"):
                x.append("    <accidental>natural</accidental>")
            # 빔(beam). 없으면 Verovio가 8·16분음표를 전부 **깃발**로 그린다.
            # 실제 악보는 빔으로 묶인 묶음이 대부분이므로, 빔 없는 학습
            # 데이터로는 검출기가 빔을 처음 보게 되어 굵은 가로 막대를
            # 음표 머리로 오검출한다(실측: 마커스 단0에서 D5·E5 오검출).
            for lvl, kind in enumerate(n.get("beams") or [], start=1):
                x.append(f'    <beam number="{lvl}">{kind}</beam>')
            if n.get("tie"):
                x.append('    <tie type="start"/>')
            if n.get("tie_stop"):
                x.append('    <tie type="stop"/>')
            # 가사는 **학습 데이터 생성용**으로만 넣는다. 실제 변환 경로에서는
            # 원본 픽셀 조각을 붙이므로 여기에 텍스트를 쓰지 않는다
            # (모듈 첫머리 주석 참고).
            if n.get("lyric"):
                # **이음표·늘임줄까지 낸다.** 한 낱말이 여러 음에 걸리면
                # 음절 사이에 하이픈이, 늘임줄에는 긴 가로줄이 그려진다.
                # 이 가로줄들이 빔과 똑같이 생겨서, 학습 데이터에 없으면
                # 검출기가 겹빔으로 오인한다(실측: 위싱 악보에서 beam2
                # 오검출 2개, 점수 0.64·0.67).
                syl = n.get("syllabic") or "single"
                x.append("    <lyric>")
                x.append(f"     <syllabic>{syl}</syllabic>")
                x.append(f"     <text>{escape(str(n['lyric']))}</text>")
                if n.get("extend"):
                    x.append("     <extend/>")
                x.append("    </lyric>")
            # 슬러는 붙임줄과 **똑같은 곡선**으로 그려진다. 학습 데이터에
            # 붙임줄만 있으면 검출기가 실제 악보의 슬러를 못 다룬다 —
            # 둘 다 같은 클래스로 배우고, 어느 쪽인지는 **양 끝 음높이가
            # 같은가**로 가른다(붙임줄의 정의다).
            # **열쇠 이름은 JS 쪽(rebuild.js)과 같아야 한다.** 조립은
            # assemble.mjs 하나로 돌므로, 여기서 다른 이름을 보면 슬러가
            # 조용히 사라진다 — 옛 이름도 함께 받는다.
            slur_a = n.get("slurStart") or n.get("slur")
            slur_b = n.get("slurStop") or n.get("slur_stop")
            if n.get("tie") or n.get("tie_stop") or slur_a or slur_b:
                x.append("    <notations>")
                if n.get("tie_stop"):
                    x.append('     <tied type="stop"/>')
                if n.get("tie"):
                    x.append('     <tied type="start"/>')
                if slur_b:
                    x.append('     <slur type="stop" number="1"/>')
                if slur_a:
                    x.append('     <slur type="start" number="1"/>')
                x.append("    </notations>")
            x.append("   </note>")
        # **줄막대 없애기.** 악보는 마디 중간에서 줄을 바꾸기도 한다. 그때는
        # 한 마디를 두 조각으로 적고 사이 줄막대를 지운다 — MusicXML은
        # 마디 중간 줄바꿈을 직접 못 쓰기 때문이다(`<print>`는 마디 첫머리에만
        # 온다). 이걸 안 하면 **없는 줄막대가 하나 생긴다.**
        if m.get("noRightBar"):
            x.append("   <barline location=\"right\">")
            x.append("    <bar-style>none</bar-style>")
            x.append("   </barline>")
        elif m.get("repeatEnd") or m.get("voltaEnd"):
            x.append('   <barline location="right">')
            if m.get("repeatEnd"):
                x.append("    <bar-style>light-heavy</bar-style>")
            if m.get("voltaEnd"):
                x.append(f'    <ending number="{escape(m["voltaEnd"])}"'
                         f' type="stop"/>')
            if m.get("repeatEnd"):
                x.append('    <repeat direction="backward"/>')
            x.append("   </barline>")
        x.append("  </measure>")
    x += [" </part>", "</score-partwise>"]
    return "\n".join(x)


NAT = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def transpose(name: str, steps: int, semitones: int) -> str:
    """
    음이름을 **온음계 단수와 반음 수 두 개로** 옮긴다.

    반음 수만으로 옮기면 이명동음(F# vs Gb)을 고를 수 없다. 온음계 단수가
    글자를, 반음 수가 임시표를 정한다 — 이조의 정의 그대로다.
    XML은 이 계산 하나로 임시표가 끝난다. 픽셀 방식이 못 하던 부분이다.
    """
    step, alter, octave = parse_pitch(name)
    idx = STEPS.index(step) + steps
    new_step = STEPS[idx % 7]
    new_oct = octave + idx // 7
    abs_semi = NAT[step] + alter + (octave + 1) * 12 + semitones
    new_alter = abs_semi - (NAT[new_step] + (new_oct + 1) * 12)
    acc = "#" * new_alter if new_alter > 0 else "b" * (-new_alter)
    return f"{new_step}{acc}{new_oct}"
