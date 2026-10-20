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
