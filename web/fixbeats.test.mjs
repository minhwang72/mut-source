// 고르개를 바꾸면 마디 합이 실제로 달라지는가 — 그것만 확인한다.
import assert from 'node:assert';
import { DUR } from './musicxml.js';
import { checkBeats } from './rebuild.js';

const n = (measure, duration, extra = {}) =>
  ({ measure, duration, dotted: false, rest: false, tie: false, ...extra });

// 마디1은 4박 정확, 마디2는 8분음표 하나가 4분으로 잘못 읽혀 4.5박
const struct = {
  beats: 4,
  systems: [{ system: 0, measures: 2, notes: [
    n(1, 'quarter'), n(1, 'quarter'), n(1, 'quarter'), n(1, 'quarter'),
    n(2, 'quarter'), n(2, 'quarter'), n(2, 'quarter'), n(2, 'quarter'),
    n(2, 'quarter'),
  ] }],
};

let cb = checkBeats(struct);
assert.equal(cb.over.length, 1, '마디2가 초과로 잡혀야 한다');
assert.deepEqual(cb.over[0].slice(0, 2), [0, 2]);
assert.equal(cb.over[0][2], 5);

// fixPanel 이 하는 일과 같은 수정: 4분 하나를 빼고 합을 맞춘다
struct.systems[0].notes.at(-1).duration = 'quarter';
struct.systems[0].notes[4].duration = 'eighth';
struct.systems[0].notes[5].duration = 'eighth';
cb = checkBeats(struct);
assert.equal(cb.over.length + cb.under.length, 0, '고친 뒤에는 안 맞는 마디가 없어야 한다');
assert.equal(cb.ok, 2);

// 붙임점도 합에 반영되는가
struct.systems[0].notes[0].dotted = true;
cb = checkBeats(struct);
assert.equal(cb.over.length, 1, '붙임점을 켜면 마디1이 초과여야 한다');
assert.equal(cb.over[0][2], 4.5);

console.log('ok');
