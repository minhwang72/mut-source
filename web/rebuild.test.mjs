// 개수가 안 맞는 마디가 있어도 **그 마디만** 잃는가.
// 예전에는 단 하나가 어긋나면 그 단의 음높이를 통째로 버렸다(실측 한 장 162개).
import assert from 'node:assert';
import { assemble } from './rebuild.js';

const SP = 10, TOP = 100, BOT = 140;
// 마디 3개, 마디마다 음표 2개 — 그런데 2번째 마디는 머리가 하나만 검출됐다
const head = (x) => ({ x, y: TOP + 20, w: 8, h: 6 });
const heads = [head(20), head(40),   head(80),   head(140), head(160)];
const note = (measure) => ({ measure, duration: 'quarter', dotted: false, rest: false, tie: false });

const struct = {
  beats: 4, sourceFifths: 0,
  systems: [{ system: 0, measures: 3, notes: [
    note(1), note(1), note(2), note(2), note(3), note(3),
  ] }],
};
const geometry = { systems: [{
  staffTop: TOP, staffBottom: BOT, spacing: SP, left: 0, right: 200,
  lineSpans: [], bars: [60, 120],
}], heads };

const { measures, report } = assemble(struct, geometry, {});
// 마디2에서 하나 모자라므로 정확히 1개만 못 채워야 한다 — 6개 전부가 아니라
assert.equal(report.missingPitch, 1,
  `마디 하나의 어긋남이 단 전체로 번졌다 (missing=${report.missingPitch})`);

// 마디1·3의 음높이는 검출된 머리에서 제대로 나와야 한다
const m1 = measures.find((m) => m.notes.length && m.notes[0].pitch);
assert.ok(m1, '마디1의 음높이가 비었다');

// 막대선이 없으면 예전처럼 순서대로 짝짓는다 (뒤로 물러나도 터지지 않는가)
const noBars = { systems: [{ ...geometry.systems[0], bars: [] }], heads };
const r2 = assemble(struct, noBars, {});
assert.ok(r2.report.missingPitch >= 1, '막대선 없는 경로가 깨졌다');

console.log('ok');

// 코드 없는 단이 목록에서 빠져도 뒤 단 코드가 당겨지지 않는가(camp0814b-10 단8)
{
  const { chordsByStaff } = await import('./rebuild.js');
  const systems = [0, 1, 3].map((i) => ({ index: i, chords: [{ text: `C${i}`, box: { x: 5 } }] }));
  const got = chordsByStaff(systems, ['X0', 'X1', 'X3']);
  assert.deepStrictEqual(Object.keys(got), ['0', '1', '3']);
  assert.strictEqual(got[3][0].text, 'X3');
  assert.throws(() => chordsByStaff(systems, ['X0']));
}

// 화음 붙임줄: 앞 화음에서 시작한 음높이마다 다음 화음 같은 음높이가 끝(wish0906-3 단8)
{
  const h = (x, cy) => ({ x, y: cy - 3, w: 8, h: 6 });
  const n = (measure, x, cy, chord, tie) => ({ measure, duration: 'whole', dotted: false,
    rest: false, tie, chord, head: h(x, cy) });
  const st = { beats: 4, sourceFifths: 0, systems: [{ system: 0, measures: 2, notes: [
    n(1, 20, 115, false, true), n(1, 20, 105, true, true),     // C5+E5 ~
    n(2, 80, 115, false, false), n(2, 80, 105, true, false),   // C5+E5
  ] }] };
  const geo = { systems: [{ staffTop: TOP, staffBottom: BOT, spacing: SP, left: 0, right: 200,
    lineSpans: [], bars: [60] }], heads: [] };
  const { measures: ms } = assemble(st, geo, {});
  const [a, b] = ms.map((m) => m.notes);
  assert.deepStrictEqual(a.map((x) => [x.pitch, x.tie, x.tie_stop]), [['C5', true, false], ['E5', true, false]]);
  assert.deepStrictEqual(b.map((x) => [x.pitch, x.tie_stop]), [['C5', true], ['E5', true]]);
}

// 온쉼표 하나뿐인 마디는 6/8 에서도 한 마디(t026-2)
{
  const { beatsPerMeasure } = await import('./rebuild.js');
  const { build } = await import('./musicxml.js');
  const struct = { beats: 3, systems: [{ notes: [
    { measure: 1, duration: 'whole', rest: true },
    { measure: 2, duration: 'quarter', dotted: true }, { measure: 2, duration: 'quarter', dotted: true },
    { measure: 3, duration: 'whole', rest: true }, { measure: 3, duration: 'eighth' },
  ] }] };
  const per = beatsPerMeasure(struct)[0];
  assert.equal(per[1], 24);
  assert.equal(per[2], 24);
  assert.equal(per[3], 36);                     // 다른 음이 같이 있으면 온쉼표 그대로
  const xml = build([{ notes: [{ pitch: null, duration: 'whole' }] }], 0, { beats: 6, beatType: 8 });
  assert.match(xml, /<rest measure="yes"\/>\s*<duration>24<\/duration>/);
}

// 마디줄에 걸친 긴 코드는 글자 가운데로 다음 마디에 붙는다(now0918-11 Bbm/Db)
{
  const { chordsByStaff } = await import('./rebuild.js');
  const got = chordsByStaff([{ index: 0, chords: [{ text: 'Bbm/Db', box: { x: 895, w: 150 } }] }], ['Bbm/Db']);
  assert.strictEqual(got[0][0].x, 970);
}

// ── 확인할 마디(report.flags)와 사람이 고친 음 자리(base) ──
{
  const { assemble } = await import('./rebuild.js');
  const h = (x, cy = 115) => ({ x, y: cy - 3, w: 8, h: 6 });
  const q = (measure, x, extra = {}) => ({ measure, duration: 'quarter', dotted: false, rest: false,
    tie: false, head: h(x), ...extra });
  const geo = { systems: [{ staffTop: TOP, staffBottom: BOT, spacing: SP, left: 0, right: 400,
    lineSpans: [], bars: [200] }], heads: [] };
  const four = (m, x0) => [0, 1, 2, 3].map((i) => q(m, x0 + i * 40));

  // 마디2 가 3박 → 그 마디만 확인할 마디. 사유는 박자
  const st = { beats: 4, sourceFifths: 0, systems: [{ measures: 2,
    notes: [...four(1, 20), ...four(2, 220).slice(0, 3)] }] };
  let r = assemble(st, geo, {}).report;
  assert.deepStrictEqual(r.flags.map((f) => [f.system, f.measure]), [[0, 2]]);
  assert.match(r.flags[0].reasons[0].text, /박자 합이 3박/);

  // 사람이 확인하면 빠진다
  st.systems[0].confirmed = [2];
  r = assemble(st, geo, {}).report;
  assert.deepStrictEqual(r.flags, []);
  delete st.systems[0].confirmed;

  // "마디 N:" 사유는 그 마디만, 마디를 모르는 사유는 단 전체(wide)
  st.systems[0].notes.push(q(2, 340));
  st.systems[0].review = ['마디 1: 음 높이가 두 판독에서 다릅니다 — 원본 확인 필요'];
  r = assemble(st, geo, {}).report;
  assert.deepStrictEqual(r.flags.map((f) => [f.measure, f.reasons[0].wide]), [[1, false]]);
  st.systems[0].review = ['코드가 두 판독에서 다릅니다 — 원본 확인 필요'];
  r = assemble(st, geo, {}).report;
  assert.deepStrictEqual(r.flags.map((f) => [f.measure, f.reasons[0].wide]), [[1, true], [2, true]]);
  delete st.systems[0].review;

  // base 는 머리 좌표보다 앞서고, 머리 없이 넣은 음표는 다른 음의 머리를 빼앗지 않는다
  const n0 = st.systems[0].notes[0];
  const before = assemble(st, geo, {}).measures[0].notes[0].pitch;
  n0.base = 'G4';
  assert.equal(assemble(st, geo, {}).measures[0].notes[0].pitch, 'G4');
  assert.notEqual(before, 'G4');
  delete n0.base;
  st.systems[0].notes.splice(1, 0, { measure: 1, duration: 'quarter', rest: false, base: 'A4' });
  const m1 = assemble(st, geo, {}).measures[0].notes.map((n) => n.pitch);
  assert.equal(m1[1], 'A4');
  assert.equal(m1[2], before);                       // 뒤 음표 음높이는 그대로
}

// 막대선이 음표와 어긋나면 머리 사이로 옮긴다(t009-3 단4: 조표 뒤 가짜 막대선)
{
  const { measureEdges } = await import('./rebuild.js');
  const hd = (m, x) => ({ measure: m, head: { x, y: 0, w: 8, h: 6 } });
  const sys = { left: 10, right: 900, bars: [60, 600] };
  const sd = { measures: 3, notes: [hd(1, 120), hd(1, 280), hd(2, 360), hd(2, 520), hd(3, 640)] };
  assert.deepStrictEqual(measureEdges(sys, sd), [10, 324, 600, 900]);
  // 맞는 막대선은 그대로, 개수가 다르면 손대지 않는다
  assert.deepStrictEqual(measureEdges({ ...sys, bars: [300, 600] }, sd), [10, 300, 600, 900]);
  assert.deepStrictEqual(measureEdges({ ...sys, bars: [60] }, sd), [10, 60, 900]);
}
