// MusicXML 만들기 — tools/musicxml.py 를 그대로 옮긴 것.
//
// 왜 브라우저에 있나: 변환·렌더는 100% 사용자 브라우저에서 한다는 원칙 때문에
// 서버는 구조 데이터(음가·마디·코드·머리 좌표)만 주고, 악보를 만드는 일은
// 여기서 한다. 서버는 악보 이미지를 절대 만들지 않는다.
//
// 파이썬 쪽과 **한 글자도 다르면 안 된다** — 같은 입력에서 같은 XML이 나와야
// CLI로 잡은 문제를 웹에서 재현할 수 있다.

export const DIVISIONS = 8;

export const DUR = {
  whole: 32, half: 16, quarter: 8, eighth: 4, '16th': 2,
};

const STEPS = 'CDEFGAB';

function escapeXml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** 'F#4' → {step:'F', alter:1, octave:4} */
export function parsePitch(name) {
  const step = name[0].toUpperCase();
  let i = 1, alter = 0;
  while (i < name.length && '#b♯♭'.includes(name[i])) {
    alter += (name[i] === '#' || name[i] === '♯') ? 1 : -1;
    i += 1;
  }
  return { step, alter, octave: parseInt(name.slice(i) || '4', 10) };
}

/** 'Ebmaj7' → ['E', -1, 'maj7'] */
export function splitRoot(sym) {
  const step = sym[0].toUpperCase();
  let i = 1, alter = 0;
  while (i < sym.length && '#b♯♭'.includes(sym[i])) {
    alter += (sym[i] === '#' || sym[i] === '♯') ? 1 : -1;
    i += 1;
  }
  return [step, alter, sym.slice(i)];
}

function harmony(text, offset = 0) {
  const body = String(text).split('/');
  const [step, alter, tail] = splitRoot(body[0]);
  let kind = 'major';
  if (tail.startsWith('m') && !tail.startsWith('maj')) {
    kind = tail.includes('7') ? 'minor-seventh' : 'minor';
  } else if (tail.startsWith('maj')) kind = 'major-seventh';
  else if (tail.includes('7')) kind = 'dominant';
  else if (tail.startsWith('sus')) kind = 'suspended-fourth';

  const out = ['  <harmony>', '   <root>', `    <root-step>${step}</root-step>`];
  if (alter) out.push(`    <root-alter>${alter}</root-alter>`);
  out.push('   </root>', `   <kind text="${escapeXml(tail)}">${kind}</kind>`);
  if (body.length === 2) {
    const [bs, ba] = splitRoot(body[1]);
    out.push('   <bass>', `    <bass-step>${bs}</bass-step>`);
    if (ba) out.push(`    <bass-alter>${ba}</bass-alter>`);
    out.push('   </bass>');
  }
  // **가로 위치.** 한 마디에 코드가 둘 이상인 경우가 흔하다. `<offset>`은
  // 마디 첫머리 기준 이동량(divisions)이다. 마디 중간에 `<harmony>`를 끼워
  // 넣으면 Verovio가 위치마다 세로 공간을 따로 잡아 코드가 별도 띠로 밀려나고
  // 서로 겹친다(직접 확인).
  if (offset) out.push(`   <offset>${offset}</offset>`);
  out.push('  </harmony>');
  return out.join('\n');
}

/**
 * measures: [{chords:[...], notes:[{pitch:'C5'|null, duration:'quarter',
 *            dotted, tie, tie_stop, beams:['begin',...], natural}],
 *            newSystem, newPage, noRightBar}]
 */
export function build(measures, fifths, opts = {}) {
  const beats = opts.beats ?? 4;
  const beatType = opts.beatType ?? 4;
  const title = opts.title ?? '';
  const x = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN"'
    + ' "http://www.musicxml.org/dtds/partwise.dtd">',
    '<score-partwise version="4.0">',
  ];
  const subtitle = opts.subtitle ?? '';
  const composer = opts.composer ?? '';
  if (title) x.push(` <work><work-title>${escapeXml(title)}</work-title></work>`);
  // 작곡자·부제는 원본에 있던 것을 그대로 옮긴다 — 개인 연습용 출력물에서
  // 원저작자 표기를 지우지 않는다(저작권 설계).
  if (composer || subtitle) {
    x.push(' <identification>');
    if (composer) {
      x.push(`  <creator type="composer">${escapeXml(composer)}</creator>`);
    }
    if (subtitle) {
      x.push(`  <creator type="lyricist">${escapeXml(subtitle)}</creator>`);
    }
    x.push(' </identification>');
  }
  // **파트 이름을 찍지 않는다.** 멜로디 한 줄짜리 콘티 악보에 "melody"가
  // 왼쪽에 붙으면 원본에 없던 글자가 생긴다.
  x.push(' <part-list><score-part id="P1">'
    + '<part-name print-object="no">melody</part-name>'
    + '</score-part></part-list>', ' <part id="P1">');

  let curFifths = fifths;        // 지금까지 유효한 조표
  measures.forEach((m, mi) => {
    x.push(`  <measure number="${mi + 1}">`);
    // 단·쪽 나누기는 마디 첫머리에만 올 수 있다 (MusicXML 규칙)
    if (m.newSystem && mi > 0) x.push('   <print new-system="yes"/>');
    if (m.newPage && mi > 0) x.push('   <print new-page="yes"/>');
    // **도돌이표 시작·볼타 시작은 마디 왼쪽에 온다.** 콘티는 반복으로 곡을
    // 적으므로 이게 없으면 형식을 따라갈 수 없다.
    if (m.repeatStart || m.voltaStart) {
      x.push('   <barline location="left">');
      if (m.repeatStart) x.push('    <bar-style>heavy-light</bar-style>');
      if (m.voltaStart) {
        x.push(`    <ending number="${escapeXml(m.voltaStart)}" type="start"/>`);
      }
      if (m.repeatStart) x.push('    <repeat direction="forward"/>');
      x.push('   </barline>');
    }
    if (mi === 0) {
      // **마디 번호를 찍지 않는다.** 원본 콘티 악보에는 없다.
      // Verovio의 mnumInterval=0 은 "끄기"가 아니라 "기본값"이라 안 먹힌다.
      x.push('   <print><measure-numbering>none</measure-numbering></print>');
      x.push('   <attributes>',
        `    <divisions>${DIVISIONS}</divisions>`,
        `    <key><fifths>${fifths}</fifths></key>`,
        `    <time><beats>${beats}</beats>`
        + `<beat-type>${beatType}</beat-type></time>`,
        '    <clef><sign>G</sign><line>2</line></clef>',
        '   </attributes>');
    } else if (m.fifths != null && Number(m.fifths) !== curFifths) {
      // **곡 중간의 조표 변경(전조).** 콘티는 후반부에서 키를 올리는 경우가
      // 흔하다. 조표를 바꿔 주지 않으면 그 구간이 임시표투성이가 된다 —
      // 실측: 「지금 여기 우리」는 C 섹션부터 G → Bb 로 바뀌는데 한 조표로
      // 그렸더니 겹올림표(C×·F×)까지 나왔다.
      x.push('   <attributes>',
        `    <key><fifths>${Number(m.fifths)}</fifths></key>`,
        '   </attributes>');
      curFifths = Number(m.fifths);
    }
    // 코드는 전부 마디 첫머리에 적고 `<offset>`으로 자리를 잡는다
    for (const c of (m.chords || [])) {
      x.push(typeof c === 'string' ? harmony(c)
        : harmony(c.text, Number(c.offset) || 0));
    }

    for (const n of m.notes) {
      if (n.unresolved) throw new Error('미확정 음표를 쉼표로 바꾸어 출력할 수 없습니다');
      const dur = DUR[n.duration] ?? DUR.quarter;
      const d = n.dotted ? Math.floor(dur * 3 / 2) : dur;
      x.push('   <note>');
      // **화음.** 둘째 음부터 <chord/> 를 달면 같은 시각에 쌓여 그려지고
      // 박도 앞으로 가지 않는다. 콘티의 간주 스트립이 이 모양이다.
      if (n.chord) x.push('    <chord/>');
      if (n.pitch == null) {
        x.push('    <rest/>');
      } else {
        const p = parsePitch(n.pitch);
        x.push('    <pitch>', `     <step>${p.step}</step>`);
        if (p.alter) x.push(`     <alter>${p.alter}</alter>`);
        x.push(`     <octave>${p.octave}</octave>`, '    </pitch>');
      }
      x.push(`    <duration>${d}</duration>`, `    <type>${n.duration}</type>`);
      if (n.dotted) x.push('    <dot/>');
      if (n.natural) x.push('    <accidental>natural</accidental>');
      // 빔이 없으면 Verovio가 8·16분음표를 전부 깃발로 그린다
      (n.beams || []).forEach((kind, i) => {
        x.push(`    <beam number="${i + 1}">${kind}</beam>`);
      });
      if (n.tie) x.push('    <tie type="start"/>');
      if (n.tie_stop) x.push('    <tie type="stop"/>');
      // **슬러는 <notations> 안에서 붙임줄과 같이 적는다.** 번호는 하나만
      // 쓴다 — 구조가 겹치지 않는 슬러만 싣는다(detstruct._slurs).
      // 끝을 먼저 적어야 한 음표에서 끝나고 바로 시작하는 경우가 산다.
      if (n.tie || n.tie_stop || n.slurStart || n.slurStop) {
        x.push('    <notations>');
        if (n.tie_stop) x.push('     <tied type="stop"/>');
        if (n.tie) x.push('     <tied type="start"/>');
        if (n.slurStop) x.push('     <slur number="1" type="stop"/>');
        if (n.slurStart) x.push('     <slur number="1" type="start"/>');
        x.push('    </notations>');
      }
      x.push('   </note>');
    }
    // 마디 중간 줄바꿈은 MusicXML로 직접 못 쓴다(`<print>`는 마디 첫머리
    // 전용). 한 마디를 두 조각으로 적고 사이 줄막대를 지운다.
    if (m.noRightBar) {
      x.push('   <barline location="right">',
        '    <bar-style>none</bar-style>', '   </barline>');
    } else if (m.repeatEnd || m.voltaEnd) {
      x.push('   <barline location="right">');
      if (m.repeatEnd) x.push('    <bar-style>light-heavy</bar-style>');
      if (m.voltaEnd) {
        x.push(`    <ending number="${escapeXml(m.voltaEnd)}" type="stop"/>`);
      }
      if (m.repeatEnd) x.push('    <repeat direction="backward"/>');
      x.push('   </barline>');
    }
    x.push('  </measure>');
  });
  x.push(' </part>', '</score-partwise>');
  // 끝 줄바꿈을 붙이지 않는다 — tools/musicxml.py 와 **바이트 단위로 같아야**
  // CLI에서 잡은 문제를 웹에서 그대로 재현할 수 있다.
  return x.join('\n');
}
