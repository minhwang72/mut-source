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
