// 서버가 준 구조 데이터로 **마디 목록을 조립한다.** tools/rebuild.py 의 짝.
//
// 역할 분담(실측 근거):
//   음높이 → 검출기가 준 머리 좌표에서 뺄셈. 상자가 맞으면 0% 틀린다.
//   음가·마디·쉼표·이음줄 → LLM. 음높이는 LLM이 82%로 못 믿는다.
//   가사 → 원본 픽셀 조각. LLM은 한글 가사를 지어낸다
//          (실측: "주 이름 찬양" → "즐거운 찬란한").

import { DUR } from './musicxml.js';
import { sourcePitch } from './source-pitch.js';

const STEPS = 'CDEFGAB';
// 한 마디의 기본 길이(4/4). 구조가 `beats` 를 주면 그걸 쓴다 —
// 콘티 73쪽 중 13쪽(18%)이 4박이 아니었다(6/8·3/4).
const FULL = DUR.quarter * 4;

/**
 * 머리 상자의 세로 위치를 음이름으로. **뺄셈이라 틀릴 수가 없다** —
 * 상자만 맞으면 된다.
 *
 * 높은음자리표에서 오선 첫 줄(맨 위)이 F5다. 한 칸(spacing/2)마다 한 음.
 */
export function pitchOf(head, sys) {
  const cy = head.y + head.h / 2;
  const top = sys.lineSpans?.length
    ? (sys.lineSpans[0][0] + sys.lineSpans[0][1]) / 2
    : sys.staffTop;
  const sp = sys.spacing;
  const steps = Math.round((cy - top) / (sp / 2));   // 아래로 갈수록 +
  // F5 = 자리표 기준 0. 아래로 한 칸 = 한 음 낮다.
  const F5 = STEPS.indexOf('F') + 5 * 7;             // 절대 음도
  const abs = F5 - steps;
  const oct = Math.floor(abs / 7);
  return STEPS[((abs % 7) + 7) % 7] + oct;
}

/** 단마다 {마디번호: 음가합}. tools/checkbeats.py 와 같은 계산. */
/** 한 마디의 음가 합(내부 단위). 구조가 알려 주면 그 값을 쓴다. */
export function fullOf(struct) {
  const b = Number(struct && struct.beats);
  return Number.isFinite(b) && b > 0 ? Math.round(DUR.quarter * b) : FULL;
}

export function beatsPerMeasure(struct) {
  return struct.systems.map((s) => {
    const per = {};
    for (const n of (s.notes || [])) {
      if (n.chord) continue;        // 화음 구성음은 박을 차지하지 않는다
      let v = DUR[n.duration] ?? 0;
      if (n.dotted) v = Math.floor(v * 3 / 2);
      per[n.measure] = (per[n.measure] || 0) + v;
    }
    return per;
  });
}

/**
 * **단 경계에서 쪼개진 마디**를 찾는다.
 *
 * 악보는 마디 중간에서 줄을 바꾸기도 한다. 앞 단의 마지막 마디와 뒷 단의
 * 첫 마디가 각각 반쪽이 되는데, 합이 한 마디면 원래 한 마디다
 * (실측: 마커스 악보 단7 마디4가 2박, 단8 마디1이 2박).
 * 이걸 모르면 **없는 줄막대를 하나 그린다.**
 */
export function splits(per, FULL_ = FULL) {
  const out = [];
  for (let i = 0; i < per.length - 1; i += 1) {
    const a = per[i], b = per[i + 1];
    const ka = Object.keys(a).map(Number), kb = Object.keys(b).map(Number);
    if (!ka.length || !kb.length) continue;
    const la = Math.max(...ka), fb = Math.min(...kb);
    if (a[la] < FULL_ && b[fb] < FULL_ && a[la] + b[fb] === FULL_) {
      out.push([i, la, fb]);
    }
  }
  return out;
}

/**
 * **확인 권장 마디** — 짐작한 음표가 있거나 두 판독기가 갈린 마디(1부터 센 번호).
 * 노란색으로 그려 사용자가 원본과 한 번 비교하게 한다(server quality_gate 'marked').
 */
const SOFT_REVIEW = /^마디 (\d+): (두 판독이 다르게|음 높이가 두 판독|임시표가 두 판독)/;
export function flaggedMeasures(sysd) {
  const out = new Set();
  for (const r of (sysd.review || [])) {
    const m = SOFT_REVIEW.exec(r);
    if (m) out.add(Number(m[1]));
  }
  for (const n of (sysd.notes || [])) if (n.guessed) out.add(n.measure);
  return out;
}

/** 박자 검산. 반환: {ok, over:[...], under:[...], splits:[...]} */
export function checkBeats(struct) {
  const full = fullOf(struct);
  const per = beatsPerMeasure(struct);
  const sp = splits(per, full);
  const skip = new Set();
  for (const [i, la, fb] of sp) { skip.add(`${i}:${la}`); skip.add(`${i + 1}:${fb}`); }
  const over = [], under = [];
  let ok = sp.length;
  per.forEach((pm, i) => {
    for (const m of Object.keys(pm).map(Number).sort((x, y) => x - y)) {
      if (skip.has(`${i}:${m}`)) continue;
      const v = pm[m];
      if (v === full) ok += 1;
      else if (v > full) over.push([i, m, v / DUR.quarter]);
      else under.push([i, m, v / DUR.quarter]);
    }
  });
  return { ok, over, under, splits: sp };
}

/**
 * 8·16분음표 묶음에 빔을 매긴다. 없으면 Verovio가 전부 깃발로 그린다.
 *
 * **원본에서 검출한 빔(beamGroup)이 있으면 그걸 그대로 쓴다.** 목표는
 * "키만 바뀐 같은 악보"인데 묶음을 지어내면 꼬리 연결이 제멋대로여서 다른
 * 악보로 보인다. 검출값이 없을 때만 2~4개씩 끊는 조판 관행으로 물러난다.
 *
 * `musicxml.add_beams`(파이썬)와 **같은 결과**를 내야 한다 — CLI로 확인한
 * 그림이 웹에서 달라지면 문제를 못 찾는다. `npm test`가 지킨다.
 */
export function addBeams(notes) {
  const LVL = { eighth: 1, '16th': 2 };
  const run = [];
  let prevGroup = null;
  const flush = () => {
    if (run.length >= 2) {
      run.forEach((n, i) => {
        const kind = i === 0 ? 'begin' : (i === run.length - 1 ? 'end' : 'continue');
        n.beams = Array.from({ length: LVL[n.duration] }, () => kind);
      });
    }
    run.length = 0;
  };
  for (const n of notes) {
    if (n.pitch == null || !LVL[n.duration]) { flush(); prevGroup = null; continue; }
    const g = n.beamGroup;
    if (g != null && g >= 0) {
      if (prevGroup != null && g !== prevGroup) flush();
      run.push(n); prevGroup = g; continue;
    }
    if (prevGroup != null) { flush(); prevGroup = null; }
    run.push(n);
    if (run.length >= 4) flush();
  }
  flush();
}

/**
 * 구조 + 머리 상자 → 마디 목록.
 *
 * 반환: {measures, report:{notes, missingPitch, systems, measures}}
 */
export function assemble(struct, geometry, chordsBySystem) {
  const per = beatsPerMeasure(struct);
  const splitPairs = splits(per, fullOf(struct));
  const splitAfter = new Set(splitPairs.map(([i]) => i));
  // **단 경계에서 쪼개진 마디는 한 마디다** — 임시표도 뒤 반쪽까지 간다.
  // 마디 번호는 단 안에서만 세므로 `단:마디` 로 구분하되, 쪼개진 마디의
  // 뒤 반쪽은 앞 반쪽의 이름을 쓴다. 줄막대를 지울지 정하는 판단과 **같은**
  // 근거를 써야 한 마디로 그려 놓고 임시표만 따로 노는 일이 없다.
  const continues = new Map(splitPairs.map(([i, la, fb]) => [i + 1, { first: fb, id: `${i}:${la}` }]));
  const heads = geometry.heads || [];
  const systems = geometry.systems || [];

  const measures = [];
  let missing = 0, total = 0, chordsKept = 0;
  const mismatch = [];
  const unresolved = [];
  if (systems.length !== struct.systems.length) {
    unresolved.push({system: 0, reason: '오선과 구조의 단 수가 달라 일부 악보가 누락될 수 있습니다'});
  }
  const pitchState = {measure: null, accidentals: new Map(), tie: null};
  // **붙임줄은 단 경계에서 끊기지 않는다.** 단마다 초기화하면 단의 마지막
  // 음에서 시작한 붙임줄이 짝 없는 `tie start` 로 남아 MusicXML 이 깨진다.
  // 음높이 쪽(`pitchState.tie`)은 이미 단을 넘어 이어지고 있었다.
  let prevTie = false;

  struct.systems.forEach((sysd, si) => {
    const sys = systems[si];
    if (!sys) return;
    const mid = (sys.staffTop + sys.staffBottom) / 2;
    const half = (sys.staffBottom - sys.staffTop) * 1.4;
    const mine = heads
      .filter((b) => Math.abs(b.y + b.h / 2 - mid) < half)
      .sort((a, b) => a.x - b.x);

    const llm = sysd.notes || [];
    total += llm.filter((n) => !n.rest).length;

    // **쉼표는 머리를 소비하지 않는다.** 쉼표에 음높이를 붙이면 그 뒤
    // 음표들이 한 칸씩 밀려 멜로디 전체가 어긋난다.
    const want = llm.filter((n) => !n.rest).length;
    const anchored = llm.filter(n => !n.rest).every(n => n.head);
    const unsafe = [];
    if (!llm.length) unsafe.push('이 단의 음악 구조를 읽지 못했습니다');
    if (!anchored && mine.length !== want) unsafe.push(`음표 수 불일치 (검출 ${mine.length}, 판독 ${want})`);
    for (const [kind, label] of [['stacked', '동시 화음 미지원'], ['slashOnly', '리듬 표기 미지원'],
                                  ['accidentals', '멜로디 임시표 확인 필요']]) {
      if (struct.unreliable?.[kind]?.includes(si)) unsafe.push(label);
    }
    if (sysd.review?.length) unsafe.push(...sysd.review);
    if (sys.clef && sys.clef !== 'G') unsafe.push('음자리표 미지원');
    const srcFifths = sysd.srcFifths ?? struct.sourceFifths;
    if (!Number.isInteger(srcFifths) || Math.abs(srcFifths) > 7) unsafe.push('원조표 미확정');
    unsafe.forEach(reason => unresolved.push({system: si, reason}));
    // A count mismatch cannot locate the missing note. Keep the whole system
    // unresolved, rather than shifting every subsequent pitch or inventing one.
    const cont = continues.get(si);
    const measureId = (m) => (cont && m === cont.first ? cont.id : `${si}:${m}`);
    // **개수가 안 맞아도 단 전체를 버리지 않는다.** 순서대로만 짝지으면
    // 한 마디에서 하나 어긋난 뒤 그 단의 나머지가 통째로 밀린다 — 그래서
    // 예전엔 단 전체를 포기했는데, 그러면 한 단에서 음높이 수십 개를 잃는다
    // (실측: 한 장에서 162개). 막대선이 이미 있으므로 **마디 안에서만**
    // 짝지으면 어긋남이 그 마디에 갇힌다.
    const mBars = Array.isArray(sys.bars) ? sys.bars : [];
    const mEdges = [sys.left ?? 0, ...mBars, sys.right ?? (sys.left ?? 0)];
    const nMeas = Math.max(1, sysd.measures || 1);
    const measureOf = (x) => {
      let mi = 0;
      for (let i = 0; i < mEdges.length - 1; i += 1) if (x >= mEdges[i]) mi = i;
      return Math.min(mi, nMeas - 1);
    };
    const byMeasure = Array.from({length: nMeas}, () => []);
    if (mBars.length) for (const h of mine) byMeasure[measureOf(h.x)].push(h);
    const cursor = new Array(nMeas).fill(0);

    // 음자리표·원조표가 틀리면 음높이 계산 자체가 무의미하다 — 이건 마디로
    // 나눠도 못 고친다. 개수 불일치·화음 같은 건 마디 단위로 가둔다.
    const pitchBroken = unsafe.some((u) =>
      u.includes('음자리표') || u.includes('원조표') || u.includes('구조를 읽지'));

    let k = 0;
    // **못 정한 음높이는 앞 음을 잇는다.** null 로 두면 변환 전체가 멈춘다
    // (assertResolved). 이어 쓴 자리는 missing 으로 세어 경고에 적히고,
    // 저장·차감은 qualityGate 가 따로 막는다.
    let last = 'B4';
    const pitches = llm.map((n) => {
      if (n.rest) { pitchState.tie = null; return null; }
      const mi = Math.min(nMeas, Math.max(1, n.measure || 1)) - 1;
      let head = n.head;
      if (!head && mBars.length) {
        // 막대선이 있으면 **그 마디 안에서만** 찾는다. 없으면 없는 대로 둔다 —
        // 순서대로 하나 끌어오면 다음 마디 머리를 당겨와 밀림이 다시 번진다.
        head = byMeasure[mi][cursor[mi]++];
      } else if (!head) {
        head = mine[k];
      }
      k += 1;
      if (pitchBroken || !head) { missing += 1; pitchState.tie = null; return last; }
      try {
        last = sourcePitch(pitchOf(head, sys), n, srcFifths, pitchState, measureId(n.measure));
        return last;
      } catch (err) {
        missing += 1;
        unresolved.push({system: si, measure: n.measure, reason: err.message});
        return last;
      }
    });
    // **단별 개수 차이를 기록한다.** 합계만 알려 주면 사용자가 어디를 봐야
    // 할지 모른다. 검출과 판독이 다른 단은 음높이가 밀렸을 수 있다
    // (실측: 회색 옵션 음표와 괄호 코드가 있는 단에서 검출이 1개 많았다).
    // **LLM이 읽은 음표 수와 비교한다.** `k`는 실제로 소비한 머리 수라 검출
    // 수와 같아질 수밖에 없어서, 그걸로 비교하면 "LLM이 더 많이 읽은" 쪽을
    // 못 잡는다(실측: LLM 138개 · 검출 130개인데 경고가 안 났다).
    if (mine.length !== want) {
      mismatch.push({ system: si, detected: mine.length, expected: want });
    }

    const nmeas = Math.max(1, sysd.measures || 1);
    const buckets = Array.from({ length: nmeas }, () => []);
    llm.forEach((n, i) => {
      const mi = Math.min(nmeas, Math.max(1, n.measure || 1)) - 1;
      buckets[mi].push({
        pitch: pitches[i], duration: n.duration,
        dotted: !!n.dotted, tie: !!n.tie, tie_stop: prevTie,
        // **슬러.** 붙임줄과 달리 여러 음표를 건너뛰므로 시작·끝을 따로
        // 싣는다. 없으면 「Pra——ise」 같은 긴 아치가 통째로 사라진다.
        ...(n.slurStart ? { slurStart: true } : {}),
        ...(n.slurStop ? { slurStop: true } : {}),
        // **원본 빔 묶음을 그대로 옮긴다.** 여기서 빠뜨리면 addBeams 가
        // 다시 지어내고, 꼬리 연결이 원본과 달라진다.
        ...(Number.isInteger(n.beamGroup) && n.beamGroup >= 0
            ? { beamGroup: n.beamGroup } : {}),
        // 화음 구성음 — musicxml 이 <chord/> 로 쌓아 그린다
        ...(n.chord ? { chord: true } : {}),
        ...(!n.rest && pitches[i] == null ? {unresolved: true} : {}),
      });
      prevTie = !!n.tie && !n.rest;
    });

    // 음표 k번째 → (마디, 마디 안 순서)
    const flatPos = [];
    buckets.forEach((notes, mi) => {
      notes.forEach((nn, j) => { if (nn.pitch != null) flatPos.push([mi, j]); });
    });
    // 마디마다 첫머리부터의 누적 음가
    const offsets = buckets.map((notes) => {
      let acc = 0;
      return notes.map((nn) => {
        const cur = acc;
        const d = DUR[nn.duration] ?? DUR.quarter;
        acc += nn.dotted ? Math.floor(d * 3 / 2) : d;
        return cur;
      });
    });

    // **코드를 막대선으로 잘린 마디 구간에 배정한다.**
    // 음표에 직접 붙이면 쉼표만 있는 마디의 코드가 갈 곳이 없어 다음 마디로
    // 몰린다(실측: 마커스 단0은 앞 4마디가 전부 쉼표라 코드 5개가 한 마디에
    // 쌓였다). 막대선은 서버가 LLM 마디 수에 맞춰 골라 보내 준다.
    const sp = sys.spacing;
    const bars = Array.isArray(sys.bars) ? sys.bars : [];
    const edges = [sys.left ?? 0, ...bars, sys.right ?? (sys.left ?? 0)];
    const chords = [...(chordsBySystem[si] || [])]
      .sort((a, b) => (a.x ?? 0) - (b.x ?? 0));
    const perMeasure = {};
    for (const c of chords) {
      let mi = 0;
      for (let i = 0; i < edges.length - 1; i += 1) {
        if ((c.x ?? 0) >= edges[i] - sp) mi = i;
      }
      mi = Math.min(mi, nmeas - 1);
      let off = 0;
      for (let idx = 0; idx < flatPos.length; idx += 1) {
        const [mm, j] = flatPos[idx];
        if (mm !== mi || idx >= mine.length) continue;
        if (mine[idx].x >= (c.x ?? 0) - sp * 1.2) { off = offsets[mi][j]; break; }
      }
      (perMeasure[mi] = perMeasure[mi] || []).push({ text: c.text, offset: off });
    }

    // **코드가 둘 이상인 마디는 쪼갠다.**
    // Verovio는 한 마디에 `<harmony>`가 여러 개면 세로로 쌓는다 — 코드 띠가
    // 커져 단 간격이 156px → 193~377px로 널뛰고 코드가 서로 겹친다
    // (직접 확인). 마디를 쪼개 마디당 하나로 만들고 사이 줄막대를 지운다.
    const HALVE = { whole: 'half', half: 'quarter', quarter: 'eighth', eighth: '16th' };
    // 반복 기호·볼타는 원래 마디 경계에 있다 — 코드 때문에 쪼갠 조각의
    // 처음/끝에 붙인다.
    const markBy = {};
    for (const mk of (sysd.marks || [])) markBy[mk.measure] = mk;
    const flagged = flaggedMeasures(sysd);
    buckets.forEach((notes0, mi) => {
      if (!notes0.length) unresolved.push({system: si, measure: mi + 1,
        reason: '읽은 음표·쉼표가 없어 원본 확인 필요'});
      // **빈 마디는 온쉼표로 채운다.** 이건 못 그리는 게 아니라 못 읽은
      // 것이라, 그리기를 막을 이유가 없다 — 위에서 unresolved 로 기록해
      // 화면이 짚어 준다. unresolved 표시를 음표에 남기면 음높이를 못 정한
      // 경우와 구분이 안 되어 변환 전체가 멈춘다.
      let notes = notes0.length ? notes0 : [{ pitch: null, duration: 'whole' }];
      const chs = (perMeasure[mi] || []).sort((a, b) => a.offset - b.offset);
      let cuts = [];
      if (chs.length > 1) {
        let acc = 0;
        const pos = notes.map((nn) => {
          const cur = acc;
          const d = DUR[nn.duration] ?? DUR.quarter;
          acc += nn.dotted ? Math.floor(d * 3 / 2) : d;
          return cur;
        });
        for (const c of chs.slice(1)) {
          const idx = pos.findIndex((v) => v >= c.offset);
          if (idx > 0 && idx < notes.length) cuts.push(idx);
        }
        cuts = [...new Set(cuts)].sort((x, y) => x - y);
        const need = chs.length - 1;
        if (cuts.length < need && notes.length > 1) {
          // 두 코드가 같은 음표로 해석되면 자를 자리가 안 나온다 — 균등히 나눈다
          const nPc = Math.min(chs.length, notes.length);
          cuts = [...new Set(Array.from({ length: nPc - 1 },
            (_, i) => Math.round((i + 1) * notes.length / nPc))
            .filter((c) => c > 0 && c < notes.length))].sort((x, y) => x - y);
        } else if (cuts.length < need && notes.length === 1
                   && notes[0].pitch == null && chs.length === 2
                   && HALVE[notes[0].duration]) {
          // **쉼표만 있는 마디는 쉼표를 나눈다.** 쪼갤 음표가 없어 코드가
          // 겹쳐 그려졌다(실측: 마커스 단0 앞 4마디).
          const h = HALVE[notes[0].duration];
          notes = [{ ...notes[0], duration: h }, { ...notes[0], duration: h }];
          cuts = [1];
        }
      }

      const pieces = [];
      let start = 0;
      for (const cut of cuts) { pieces.push(notes.slice(start, cut)); start = cut; }
      pieces.push(notes.slice(start));
      const parts = pieces.filter((pc) => pc.length);
      const use = parts.length ? parts : [notes];

      const mk = markBy[mi + 1] || {};
      use.forEach((pc, pi) => {
        addBeams(pc);
        const m = { notes: pc };
        if (flagged.has(mi + 1)) m.flag = true;
        if (mi === 0 && pi === 0) m.newSystem = true;
        // **단별 원조 조표(전조).** 구조 데이터가 주면 실어 둔다 —
        // 목표 조표로 옮기는 것은 redraw 가 한다(간격 차이를 더한다).
        if (sysd.srcFifths != null) m.srcFifths = Number(sysd.srcFifths);
        if (pi < chs.length) { m.chords = [chs[pi].text]; chordsKept += 1; }
        if (pi === 0) {
          if (mk.repeatStart) m.repeatStart = true;
          if (mk.volta) m.voltaStart = mk.volta;
        }
        if (pi === use.length - 1) {
          if (mk.repeatEnd) m.repeatEnd = true;
          if (mk.volta) m.voltaEnd = mk.volta;
        }
        if (pi < use.length - 1) m.noRightBar = true;
        measures.push(m);
      });
      if (chs.length > use.length) {
        const extra = chs.slice(use.length).map((c) => c.text);
        const m = measures[measures.length - 1];
        m.chords = (m.chords || []).concat(extra);
        chordsKept += extra.length;
      }
    });

    if (splitAfter.has(si) && measures.length) {
      measures[measures.length - 1].noRightBar = true;
    }
  });

  // Beat validation is a rejection signal, not a recipe for inventing durations.
  // Explicit pickups may be short; split measures were already paired above.
  const checked = checkBeats(struct);
  for (const [si, mi, beats] of [...checked.over, ...checked.under]) {
    if (struct.systems[si]?.pickups?.includes(mi) && beats < fullOf(struct) / DUR.quarter) continue;
    unresolved.push({system: si, measure: mi,
      reason: `음가 합 ${beats}박 — 기준 ${fullOf(struct) / DUR.quarter}박과 달라 원본 확인 필요`});
  }
  return {
    measures,
    report: {
      notes: total, missingPitch: missing, mismatch, unresolved,
      systems: struct.systems.length, measures: measures.length,
      chords: chordsKept,
    },
  };
}
