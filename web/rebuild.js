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
  const full = fullOf(struct);
  return struct.systems.map((s) => {
    const per = {}, only = {};
    for (const n of (s.notes || [])) {
      if (n.chord) continue;        // 화음 구성음은 박을 차지하지 않는다
      let v = DUR[n.duration] ?? 0;
      if (n.dotted) v = Math.floor(v * 3 / 2);
      per[n.measure] = (per[n.measure] || 0) + v;
      only[n.measure] = only[n.measure] === undefined ? n : null;
    }
    // **온쉼표 하나뿐인 마디는 박자와 상관없이 한 마디 쉼**(6/8·3/4 에서도).
    // 4박으로 세어 6/8 장이 막혔다(실측 t026-2).
    for (const [m, n] of Object.entries(only)) {
      if (isMeasureRest(n)) per[m] = full;
    }
    return per;
  });
}

export function isMeasureRest(n) {
  return !!n && !!n.rest && n.duration === 'whole' && !n.dotted;
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
 * 판독기가 단 `review` 에 남긴 말을 화면 문구로. "마디 N:" 이 붙은 것은 그 마디,
 * 아닌 것은 단 전체의 사유다(어느 마디인지 판독기도 모른다).
 */
const REVIEW_TEXT = [
  [/두 판독이 다르게/, '리듬을 두 판독기가 다르게 읽었어요'],
  [/음 높이가 두 판독/, '음 높이를 두 판독기가 다르게 읽었어요'],
  [/임시표가 두 판독/, '임시표를 두 판독기가 다르게 읽었어요'],
  [/붙임줄이 흐리게/, '붙임줄이 흐릿해요 — 이어지는지 확인해 주세요'],
  [/앞에 마디가 하나 빠졌/, '바로 앞에 마디가 하나 빠졌을 수 있어요 — 원본에서 이 마디 앞을 봐 주세요'],
  [/마디가 하나 빠졌/, '이 단에 마디가 하나 빠졌을 수 있어요'],
  [/코드가 두 판독/, '코드를 두 번 읽은 결과가 달라요'],
  [/교차 확인하지 못했/, '음 높이를 두 번째 판독기로 확인하지 못했어요'],
  [/임시표/, '임시표가 어느 음표에 붙는지 확인이 필요해요'],
  [/기존 개수 판독/, '판독기마다 음표 개수가 달라요'],
];
export function reviewText(raw) {
  for (const [re, t] of REVIEW_TEXT) if (re.test(raw)) return t;
  return String(raw).replace(/\s*—\s*원본 확인 필요$/, '');
}

/**
 * 빔으로 묶인 음표가 8분 박 격자에서 안 끝나는 마디 — 붙임점 하나가 옆 음으로
 * 옮겨 붙으면 마디 합은 그대로라 박자 검산을 통과한다(실측 day2conti-2).
 * server/local_reader.broken_beam_groups 와 같은 기준이고, 마디 번호를 돌려준다.
 */
export function brokenBeamMeasures(sysd) {
  const pos = {}, ends = new Map();
  for (const n of (sysd.notes || [])) {
    if (n.chord) continue;
    const v = DUR[n.duration] ?? DUR.quarter;
    pos[n.measure] = (pos[n.measure] || 0) + (n.dotted ? Math.floor(v * 3 / 2) : v);
    const g = n.beamGroup;
    if (Number.isInteger(g) && g >= 0 && !n.rest) ends.set(`${n.measure}:${g}`, [n.measure, pos[n.measure]]);
  }
  return new Set([...ends.values()].filter(([, p]) => p % DUR.eighth).map(([m]) => m));
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
/**
 * 코드를 단별로 되돌려 놓는다 — assemble이 마디마다 하나씩 꺼내 쓴다.
 *
 * **필터 조건이 호출부와 한 글자도 달라선 안 된다.** chordTexts는 호출부가
 * `!chord.dropped`로 걸러 이조한 결과이고, 여기서 세는 순서가 그것과
 * 어긋나면 코드가 **엉뚱한 마디에 붙는다.** 그래서 조건을 같게 두고,
 * 개수가 안 맞으면 조용히 넘어가지 않고 오류를 낸다.
 * **x좌표를 함께 넘긴다.** assemble이 막대선으로 잘린 마디 구간에
 * 배정하는 데 쓴다 — 마디당 하나씩 나눠 주면 19%를 버린다(실측).
 * **단 번호는 index 로.** 코드가 하나도 없는 단은 목록에서 빠지므로 순서로
 * 세면 그 뒤 단의 코드가 전부 한 단씩 당겨진다(실측 camp0814b-10: 단8 이
 * 빠져 단8~11 코드가 한 줄씩 위로 — 과금 장이었다).
 */
export function chordsByStaff(systems, chordTexts) {
  const out = {};
  let ci = 0;
  let last = null;                  // 바로 앞의 온전한 코드(베이스 뺀 것)
  (systems || []).forEach((sysd, i) => {
    const list = [];
    for (const c of (sysd.chords || [])) {
      if (c.dropped) continue;
      // **베이스만 적은 코드("G /A /B /C")는 앞 코드에 붙인다** — G/A 와 같은 뜻이고,
      // 근음 없이는 악보에 그릴 수 없다(실측 처음 보는 악보 33장 중 3장이 여기서 멈췄다)
      let text = chordTexts[ci] ?? c.text;
      const bassOnly = /^\s*\/\s*([A-G][#b♯♭]?)\s*$/.exec(text);
      if (bassOnly && last) text = `${last}/${bassOnly[1]}`;
      else if (/^[A-G]/.test(text)) last = text.split('/')[0];
      // **글자 가운데로 자리를 잡는다.** 긴 코드(Bbm/Db, B(sus4)/D#)는 다음 마디 첫 박
      // 위에 가운데 맞춰 찍혀 왼쪽 끝이 마디줄을 넘어온다 — 왼쪽 끝으로 재면 앞 마디에
      // 붙었다(실측 now0918-11·wish0809-6·t060-1, 과금 장 포함)
      list.push({ text, x: c.box ? c.box.x + (c.box.w || 0) / 2 : 0, left: c.box?.x });
      ci += 1;
    }
    out[sysd.index ?? i] = list;
  });
  if (ci !== chordTexts.length) {
    throw new Error(`코드 개수가 맞지 않습니다 (${ci} vs ${chordTexts.length}) `
      + '— 이조된 코드가 엉뚱한 마디에 붙을 수 있어 멈췄습니다');
  }
  return out;
}

/**
 * 단의 마디 경계 [왼끝, 막대선…, 오른끝]. **막대선이 음표 머리와 어긋나면 머리에 맞춘다.**
 *
 * 막대선은 판독이 마디 수에 맞춰 고른 것이라 하나가 엉뚱한 데 잡히기도 한다(실측
 * t009-3 단4: 첫 막대선이 조표 바로 뒤 x=222, 마디1 음표는 299~600). 그러면 코드가
 * 옆 마디에 붙는다. 마디 번호는 음표가 들고 있으므로, 앞 마디 마지막 머리와 뒷 마디
 * 첫 머리 사이에 없는 막대선만 그 가운데로 옮긴다. 개수가 안 맞거나 고친 뒤 순서가
 * 꼬이면 손대지 않는다.
 */
export function measureEdges(sys, sysd) {
  const left = sys.left ?? 0, right = sys.right ?? left;
  const bars = Array.isArray(sys.bars) ? [...sys.bars] : [];
  const n = Math.max(1, sysd?.measures || 1);
  if (bars.length !== n - 1 || !bars.length) return [left, ...bars, right];
  const lo = {}, hi = {};
  for (const nn of (sysd.notes || [])) {
    const h = nn.head;
    if (!h) continue;
    const m = nn.measure;
    lo[m] = Math.min(lo[m] ?? Infinity, h.x);
    hi[m] = Math.max(hi[m] ?? -Infinity, h.x + (h.w || 0));
  }
  let moved = false;
  for (let i = 0; i < bars.length; i += 1) {
    const a = hi[i + 1], b = lo[i + 2];
    if (a == null || b == null || a >= b) continue;
    if (bars[i] < a || bars[i] > b) { bars[i] = (a + b) / 2; moved = true; }
  }
  const out = [left, ...bars, right];
  if (moved && out.some((x, i) => i && x <= out[i - 1])) return [left, ...sys.bars, right];
  return out;
}

/** 마디 안 음표마다 시작 박(내부 단위). 화음 구성음은 바탕음과 같은 자리다. */
function starts(notes) {
  let acc = 0, at = 0;
  return notes.map((nn) => {
    if (nn.chord) return at;
    at = acc;
    const d = DUR[nn.duration] ?? DUR.quarter;
    acc += nn.dotted ? Math.floor(d * 3 / 2) : d;
    return at;
  });
}

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
  // **화음 붙임줄은 음높이로 짝짓는다.** 바로 앞 음표만 보면 붙임줄을 시작한
  // 화음 바탕음 다음의 **구성음**이 끝으로 잡히고, 다음 화음의 구성음은 끝을
  // 못 받는다(실측 wish0906-3 단8: E5+C5 화음이 다음 마디 화음으로 이어진다).
  // 앞 화음에서 붙임줄을 시작한 음높이 → 다음 화음의 같은 음높이가 끝.
  let prevTies = new Set(), curTies = new Set();

  const tieStop = (n, pitch) => {
    if (!n.chord) { prevTies = curTies; curTies = new Set(); }
    return pitch != null && prevTies.has(pitch);
  };

  // **확인할 마디.** 사람이 원본과 비교해 확인하거나 고칠 자리 — 단·쪽 전체를
  // 막는 대신 마디로 좁힌다. 어느 마디인지 모르는 사유는 그 단의 마디 전부에
  // 단다(wide). 사용자가 확인한 마디(sysd.confirmed)는 빼서, 화면이 다 확인됐는지
  // 이것 하나로 안다. 그릴 수 없는 악보(높은음자리표 아님 등)는 blockers.
  const full = fullOf(struct);
  const checked = checkBeats(struct);
  const flags = new Map();
  const blockers = [];
  const flag = (si, mi, text, wide = false) => {
    if ((struct.systems[si]?.confirmed || []).includes(mi)) return;
    const k = `${si}:${mi}`;
    let f = flags.get(k);
    if (!f) flags.set(k, f = { system: si, measure: mi, reasons: [] });
    if (!f.reasons.some((r) => r.text === text)) f.reasons.push({ text, wide });
  };
  /** 판독이 정한 음높이 바탕(오선 위 자리) — 편집기가 올리고 내리는 출발점 */
  const bases = new Map();

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
    // 사람이 넣은 음표(머리 없이 음 자리만 있는 것)도 머리를 찾지 않는다.
    const added = (n) => !!n.base && !n.head;
    const want = llm.filter((n) => !n.rest && !added(n)).length;
    const anchored = llm.filter(n => !n.rest).every(n => n.head || n.base);
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
    const mEdges = measureEdges(sys, sysd);
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

    // ── 확인할 마디를 단다 ──
    const clampM = (m) => Math.min(nMeas, Math.max(1, m || 1));
    const allM = Array.from({ length: nMeas }, (_, i) => i + 1);
    // 조건에 맞는 음표가 있는 마디. 없으면 어느 마디인지 모르므로 단 전체.
    const where = (pred) => {
      const s = [...new Set(llm.filter(pred).map((n) => clampM(n.measure)))];
      return s.length ? s : allM;
    };
    const mark = (list, text) => list.forEach((m) => flag(si, m, text, list === allM));
    const beatBad = [...checked.over, ...checked.under]
      .filter(([s, m, v]) => s === si && !(sysd.pickups?.includes(m) && v < full / DUR.quarter))
      .map(([, m]) => clampM(m));
    const hasAcc = (n) => n.accidental != null || !!n.natural;
    if (sys.clef && sys.clef !== 'G') blockers.push('높은음자리표가 아닌 악보는 아직 지원하지 않아요');
    if (!Number.isInteger(srcFifths) || Math.abs(srcFifths) > 7) blockers.push('조표를 확인하지 못했어요');
    if (!llm.length) {
      // 코드만 적힌 줄(간주·전주)은 음표가 없는 게 맞다 — 그래도 한 번은 본다
      mark(allM, (chordsBySystem[si] || []).length
        ? '음표 없이 코드만 있는 단이에요 — 간주라면 그대로 두세요'
        : '이 단의 음표를 읽지 못했어요');
    }
    if (llm.length && !anchored && mine.length !== want) {
      // 마디마다 머리 수와 읽은 음표 수를 대 본다 — 다른 마디만
      const diff = mBars.length ? allM.filter((m) =>
        byMeasure[m - 1].length !== llm.filter((n) => !n.rest && !added(n) && clampM(n.measure) === m).length) : [];
      mark(diff.length ? diff : allM, '찾은 음표 수와 읽은 음표 수가 달라요');
    }
    if (struct.unreliable?.stacked?.includes(si)) mark(where((n) => n.chord), '화음(동시에 울리는 음)이 있어요');
    if (struct.unreliable?.slashOnly?.includes(si)) mark(allM, '음 높이 없이 리듬만 적힌 표기는 읽지 못했어요');
    if (struct.unreliable?.accidentals?.includes(si)) mark(where(hasAcc), reviewText('임시표'));
    for (const r of (sysd.review || [])) {
      const m = /^마디 (\d+): (.+)$/.exec(r);
      if (m) { flag(si, clampM(Number(m[1])), reviewText(m[2])); continue; }
      if (r.startsWith('기존 개수 판독')) mark(beatBad.length ? beatBad : allM, reviewText(r));
      else if (r.includes('교차 확인하지 못했')) mark(where((n) => !n.rest && !n.pos), reviewText(r));
      else if (r.includes('임시표')) mark(where(hasAcc), reviewText(r));
      else mark(allM, reviewText(r));
    }
    for (const n of llm) if (n.guessed) flag(si, clampM(n.measure), '박자를 맞추려고 음가를 짐작했어요');
    for (const m of brokenBeamMeasures(sysd)) {
      flag(si, clampM(m), '빔으로 묶인 음표의 박이 맞지 않아요 — 붙임점을 확인해 주세요');
    }

    let k = 0;
    // **못 정한 음높이는 앞 음을 잇는다.** null 로 두면 변환 전체가 멈춘다
    // (assertResolved). 이어 쓴 자리는 missing 으로 세어 경고에 적히고,
    // 그 마디는 확인할 마디가 된다.
    let last = 'B4';
    const xs = llm.map(() => null);     // 음표마다 머리 x — 코드를 어느 음 위에 둘지
    const pitches = llm.map((n, i) => {
      if (n.rest) { pitchState.tie = null; return null; }
      const mi = clampM(n.measure) - 1;
      let head = n.head;
      if (!head && !n.base && mBars.length) {
        // 막대선이 있으면 **그 마디 안에서만** 찾는다. 없으면 없는 대로 둔다 —
        // 순서대로 하나 끌어오면 다음 마디 머리를 당겨와 밀림이 다시 번진다.
        head = byMeasure[mi][cursor[mi]++];
      } else if (!head && !n.base) {
        head = mine[k];
      }
      if (!added(n)) k += 1;
      if (head) xs[i] = head.x + (head.w || 0) / 2;
      if (pitchBroken || (!head && !n.base)) {
        missing += 1; pitchState.tie = null;
        if (!pitchBroken) flag(si, mi + 1, '음 높이를 정하지 못했어요');
        return last;
      }
      try {
        // 사람이 고친 음 자리(base)가 있으면 그것이 머리 좌표보다 앞선다
        const base = n.base || pitchOf(head, sys);
        bases.set(n, base);
        last = sourcePitch(base, n, srcFifths, pitchState, measureId(n.measure));
        return last;
      } catch (err) {
        missing += 1;
        unresolved.push({system: si, measure: n.measure, reason: err.message});
        flag(si, mi + 1, '음 높이를 정하지 못했어요');
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

    const nmeas = nMeas;
    const buckets = Array.from({ length: nmeas }, () => []);
    const idxs = Array.from({ length: nmeas }, () => []);
    llm.forEach((n, i) => {
      const mi = clampM(n.measure) - 1;
      idxs[mi].push(i);
      buckets[mi].push({
        pitch: pitches[i], duration: n.duration,
        dotted: !!n.dotted, tie: !!n.tie, tie_stop: tieStop(n, pitches[i]),
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
      if (n.tie && !n.rest && pitches[i] != null) curTies.add(pitches[i]);
    });

    // **쉼표 자리를 앞뒤 음표 사이로 짐작한다.** 쉼표엔 머리가 없어 코드 자리를 잴 수
    // 없었다 — 3박 쉼표 위 코드가 4박 음표에 붙었다(처음 보는 악보 대조: t023-6·t002-2·
    // t012-4). 연달은 쉼표는 사이를 고르게 나눈다. 기준이 없으면 음표에서 3칸씩.
    idxs.forEach((list, mi) => {
      const run = [];
      // 마디 안에서 앞(뒤) 음표가 없으면 마디줄을 기준으로 — 단 첫 마디 왼끝은 음자리표·
      // 조표까지 품고 있어 쓰지 않는다
      const flush = (next0) => {
        if (!run.length) return;
        const prev = run.prev ?? (mi > 0 ? mEdges[mi] : null);
        const next = next0 ?? mEdges[mi + 1] ?? null;
        run.forEach((i, t) => {
          if (prev != null && next != null) xs[i] = prev + (next - prev) * (t + 1) / (run.length + 1);
          else if (next != null) xs[i] = next - sys.spacing * 3 * (run.length - t);
          else if (prev != null) xs[i] = prev + sys.spacing * 3 * (t + 1);
          else xs[i] = (mEdges[mi] + (mEdges[mi + 1] ?? mEdges[mi])) / 2;
        });
        run.length = 0;
      };
      let last = null;
      for (const i of list) {
        if (llm[i].chord) continue;
        if (xs[i] == null && llm[i].rest) { if (!run.length) run.prev = last ?? undefined; run.push(i); continue; }
        if (xs[i] != null) { flush(xs[i]); last = xs[i]; }
      }
      flush(null);
    });

    // 마디마다 첫머리부터의 누적 음가. **화음 구성음은 시간을 쓰지 않는다** —
    // 바탕음과 같은 자리다.
    const offsets = buckets.map(starts);

    // **코드를 막대선으로 잘린 마디 구간에 배정한다.**
    // 음표에 직접 붙이면 쉼표만 있는 마디의 코드가 갈 곳이 없어 다음 마디로
    // 몰린다(실측: 마커스 단0은 앞 4마디가 전부 쉼표라 코드 5개가 한 마디에
    // 쌓였다). 막대선은 서버가 LLM 마디 수에 맞춰 골라 보내 준다.
    const sp = sys.spacing;
    const edges = mEdges;
    const chords = [...(chordsBySystem[si] || [])]
      .sort((a, b) => (a.x ?? 0) - (b.x ?? 0));
    const perMeasure = {};
    for (const c of chords) {
      let mi = 0;
      for (let i = 0; i < edges.length - 1; i += 1) {
        if ((c.x ?? 0) >= edges[i] - sp * 0.5) mi = i;
      }
      mi = Math.min(mi, nmeas - 1);
      // **코드 글자 왼쪽 끝 근처에서 가장 가까운 음표·쉼표의 박에 둔다.** 코드는 대개
      // 음표 머리에 왼쪽을 맞춰 적는다 — 가운데로 재면 긴 코드(Bm7/E)가 다음 음표로
      // 넘어가고, "가운데보다 오른쪽 첫 음표"로 재면 쉼표 위 코드가 다음 음표로 갔다.
      // 가운데에 맞춰 적은 짧은 코드도 잡히도록 가운데와 (왼쪽+1칸) 중 왼쪽 것을 쓴다.
      const at = c.left != null ? Math.min(c.x ?? 0, c.left + sp) : (c.x ?? 0);
      let off = 0, best = Infinity;
      for (let j = 0; j < idxs[mi].length; j += 1) {
        const x = xs[idxs[mi][j]];
        if (x != null && Math.abs(x - at) < best) { best = Math.abs(x - at); off = offsets[mi][j]; }
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
    // **두 이름을 다 읽는다.** 지금 판독(readcounts)은 repeat_start 로 보내는데 여기는
    // repeatStart 만 읽어서, 판독이 찾은 도돌이표가 한 번도 그려지지 않았다(처음 보는
    // 악보 33장 중 19장에 65개). 괄호 번호 '1.'·'1.2.' 는 MusicXML 형식 '1'·'1, 2' 로.
    for (const mk of (sysd.marks || [])) {
      const volta = (String(mk.volta ?? '').match(/\d+/g) || []).join(', ');
      markBy[mk.measure] = {
        repeatStart: !!(mk.repeatStart ?? mk.repeat_start),
        repeatEnd: !!(mk.repeatEnd ?? mk.repeat_end),
        volta,
      };
    }
    buckets.forEach((notes0, mi) => {
      if (!notes0.length) {
        unresolved.push({system: si, measure: mi + 1, reason: '읽은 음표·쉼표가 없어 원본 확인 필요'});
        if (llm.length) flag(si, mi + 1, '이 마디의 음표를 읽지 못했어요');
      }
      // **빈 마디는 온쉼표로 채운다.** 이건 못 그리는 게 아니라 못 읽은
      // 것이라, 그리기를 막을 이유가 없다 — 위에서 unresolved 로 기록해
      // 화면이 짚어 준다. unresolved 표시를 음표에 남기면 음높이를 못 정한
      // 경우와 구분이 안 되어 변환 전체가 멈춘다.
      let notes = notes0.length ? notes0 : [{ pitch: null, duration: 'whole' }];
      const chs = (perMeasure[mi] || []).sort((a, b) => a.offset - b.offset);
      let cuts = [];
      // **첫 코드가 마디 첫 박이 아니면 그 앞을 코드 없는 조각으로 뗀다.** 예전엔 코드가
      // 하나뿐이면 박 자리를 버리고 마디 첫머리에 그렸다 — 3박·4박에 걸린 코드가
      // 1박으로 갔다(처음 보는 악보 대조 t063-02 D/F# 5곳 등)
      let lead = 0;
      if (chs.length && chs[0].offset > 0 && notes.length > 1) {
        let idx = starts(notes).findIndex((v) => v >= chs[0].offset);
        while (idx > 0 && idx < notes.length && notes[idx].chord) idx += 1;
        if (idx > 0 && idx < notes.length) lead = idx;
      }
      let even = false;
      if (chs.length > 1) {
        const pos = starts(notes);
        for (const c of chs.slice(1)) {
          const idx = pos.findIndex((v) => v >= c.offset);
          if (idx > 0 && idx < notes.length) cuts.push(idx);
        }
        cuts = [...new Set(cuts)].sort((x, y) => x - y);
        const need = chs.length - 1;
        if (cuts.length < need && notes.length > 1) {
          even = true;
          // 두 코드가 같은 음표로 해석되면 자를 자리가 안 나온다 — 균등히 나눈다
          const nPc = Math.min(chs.length, notes.length);
          cuts = [...new Set(Array.from({ length: nPc - 1 },
            (_, i) => Math.round((i + 1) * notes.length / nPc))
            .filter((c) => c > 0 && c < notes.length))].sort((x, y) => x - y);
          // 화음 구성음 앞에서 자르면 바탕음과 갈라진다 — 뒤로 민다
          cuts = [...new Set(cuts.map((c) => { while (c < notes.length && notes[c].chord) c += 1; return c; })
            .filter((c) => c < notes.length))];
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

      if (lead && !even && !cuts.includes(lead)) cuts = [lead, ...cuts].sort((x, y) => x - y);
      else lead = 0;
      const pieces = [];
      let start = 0;
      for (const cut of cuts) { pieces.push(notes.slice(start, cut)); start = cut; }
      pieces.push(notes.slice(start));
      const parts = pieces.filter((pc) => pc.length);
      const use = parts.length ? parts : [notes];

      const mk = markBy[mi + 1] || {};
      use.forEach((pc, pi) => {
        addBeams(pc);
        // src: 원래 (단, 마디) — 화면이 그린 마디를 눌러 고칠 때 되짚는다
        const m = { notes: pc, src: [si, mi + 1] };
        if (mi === 0 && pi === 0) m.newSystem = true;
        // **단별 원조 조표(전조).** 구조 데이터가 주면 실어 둔다 —
        // 목표 조표로 옮기는 것은 redraw 가 한다(간격 차이를 더한다).
        if (sysd.srcFifths != null) m.srcFifths = Number(sysd.srcFifths);
        const ci = pi - (lead ? 1 : 0);
        if (ci >= 0 && ci < chs.length) { m.chords = [chs[ci].text]; chordsKept += 1; }
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
      if (chs.length > use.length - (lead ? 1 : 0)) {
        const extra = chs.slice(use.length - (lead ? 1 : 0)).map((c) => c.text);
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
  for (const [si, mi, beats] of [...checked.over, ...checked.under]) {
    if (struct.systems[si]?.pickups?.includes(mi) && beats < full / DUR.quarter) continue;
    unresolved.push({system: si, measure: mi,
      reason: `음가 합 ${beats}박 — 기준 ${full / DUR.quarter}박과 달라 원본 확인 필요`});
    const n = struct.systems[si]?.measures || 1;
    flag(si, Math.min(n, Math.max(1, mi)), `박자 합이 ${+beats.toFixed(2)}박이에요 (한 마디 ${full / DUR.quarter}박)`);
  }
  return {
    measures,
    report: {
      notes: total, missingPitch: missing, mismatch, unresolved,
      systems: struct.systems.length, measures: measures.length,
      chords: chordsKept,
      flags: [...flags.values()].sort((a, b) => (a.system - b.system) || (a.measure - b.measure)),
      blockers: [...new Set(blockers)],
    },
    bases,
  };
}
