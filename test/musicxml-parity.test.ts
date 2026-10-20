// JS 생성기가 파이썬(tools/musicxml.py)과 **바이트 단위로 같은 XML**을 내는지
// 지킨다.
//
// 왜 이게 필요한가: 변환·렌더는 브라우저에서 하지만, 문제를 파고들 때는 CLI가
// 훨씬 빠르다. 두 경로가 조금이라도 다르면 "CLI에서는 되는데 웹에서는 안 되는"
// 상황이 생기고, 그때 원인을 못 찾는다. 실측으로 걸린 차이: 끝 줄바꿈 1바이트.
//
// 파이썬이 없는 환경에서는 조용히 건너뛴다 — 코어 테스트를 막지 않는다.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { build } from '../web/musicxml.js';

const CASE = {
  fifths: -2,
  title: '동등성 시험',
  subtitle: 'parity subtitle',
  composer: 'Russell Frager',
  measures: [
    {
      newSystem: true, chords: ['Bb', 'Gm7'],
      notes: [
        { pitch: 'C5', duration: 'quarter', beams: [] },
        { pitch: 'F#4', duration: 'eighth', beams: ['begin'], tie: true },
        { pitch: 'F#4', duration: 'eighth', beams: ['end'], tie_stop: true },
        { pitch: null, duration: 'half' },
      ],
    },
    {
      chords: ['Ebmaj7/G'], noRightBar: true,
      notes: [
        {
          pitch: 'Bb3', duration: '16th', dotted: true, natural: true,
          beams: ['begin', 'begin'],
        },
        { pitch: 'D5', duration: 'whole' },
      ],
    },
    { newSystem: true, notes: [{ pitch: 'E4', duration: 'quarter' }] },
    // 반복 기호·볼타 — 콘티는 반복으로 곡을 적는다
    {
      repeatStart: true, voltaStart: '1.', repeatEnd: true, voltaEnd: '1.',
      notes: [{ pitch: 'G4', duration: 'half' }],
    },
    { repeatEnd: true, notes: [{ pitch: 'A4', duration: 'whole' }] },
  ],
};

test('MusicXML 생성기가 파이썬과 같은 출력을 낸다', () => {
  if (!existsSync('tools/musicxml.py')) return;
  let py: string;
  try {
    py = execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, "tools")
import musicxml as M
d = json.loads(sys.stdin.read())
sys.stdout.write(M.build(d["measures"], fifths=d["fifths"], title=d["title"],
                         subtitle=d["subtitle"], composer=d["composer"]))
`], { input: JSON.stringify(CASE), encoding: 'utf8' });
  } catch {
    return;                      // 파이썬·의존성 없음 — 건너뜀
  }
  const js = build(CASE.measures as never, CASE.fifths, {
    title: CASE.title, subtitle: CASE.subtitle, composer: CASE.composer,
  });
  assert.equal(js, py);
});

// 빔 묶기도 파이썬과 같아야 한다. 학습 데이터(gendata)와 실제 변환(rebuild)이
// 같은 규칙을 쓰도록 합쳤는데, 웹이 어긋나면 같은 악보가 다르게 그려진다.
const BEAM_CASES = [
  ['eighth', 'eighth', 'quarter', '16th', '16th', 'eighth'],
  ['eighth', 'eighth', 'eighth', 'eighth', 'eighth'],
  ['16th', 'eighth', '16th', 'half', 'eighth', 'eighth'],
  ['eighth'],
  ['quarter', 'whole'],
];

test('빔 묶기가 파이썬과 같다', async () => {
  if (!existsSync('tools/musicxml.py')) return;
  const { addBeams } = await import('../web/rebuild.js');
  let py: string;
  try {
    py = execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, "tools")
import musicxml as M
out = []
for case in json.loads(sys.stdin.read()):
    ns = [{"pitch": "C5", "duration": d} for d in case]
    M.add_beams(ns)
    out.append([n.get("beams") for n in ns])
print(json.dumps(out))
`], { input: JSON.stringify(BEAM_CASES), encoding: 'utf8' });
  } catch {
    return;
  }
  const js = BEAM_CASES.map((case_) => {
    const ns = case_.map((d) => ({ pitch: 'C5', duration: d }));
    addBeams(ns as never);
    return ns.map((n) => (n as never as { beams?: string[] }).beams ?? null);
  });
  assert.deepEqual(js, JSON.parse(py));
});

// **원본에서 검출한 빔 묶음(beamGroup)을 그대로 쓰는가.**
// 목표는 "키만 바뀐 같은 악보"다 — 묶음을 지어내면 꼬리 연결이 원본과 달라져
// 다른 악보로 보인다. 검출값이 있으면 개수 규칙(2~4개)을 무시해야 하고,
// 없는 음표와 섞여서도 안 된다.
const GROUP_CASES: (number | null)[][] = [
  [0, 0, 0, 0, 0, 0],          // 여섯 개가 한 빔 — 4개에서 끊으면 안 된다
  [0, 0, 1, 1],                // 빔이 바뀌면 거기서 끊는다
  [0, 0, null, null],          // 검출값 있는 것과 없는 것을 섞지 않는다
  [null, null, null, null, null],  // 전부 미검출 → 옛 규칙(4개)
  [3, 3, 3],                   // 번호는 아무 값이나 될 수 있다
];

test('검출한 빔 묶음을 파이썬·JS가 같게 쓴다', async () => {
  if (!existsSync('tools/musicxml.py')) return;
  const { addBeams } = await import('../web/rebuild.js');
  let py: string;
  try {
    py = execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, "tools")
import musicxml as M
out = []
for case in json.loads(sys.stdin.read()):
    ns = [{"pitch": "C5", "duration": "eighth",
           **({} if g is None else {"beamGroup": g})} for g in case]
    M.add_beams(ns)
    out.append([n.get("beams") for n in ns])
print(json.dumps(out))
`], { input: JSON.stringify(GROUP_CASES), encoding: 'utf8' });
  } catch {
    return;
  }
  const js = GROUP_CASES.map((case_) => {
    const ns = case_.map((g) => (g === null
      ? { pitch: 'C5', duration: 'eighth' }
      : { pitch: 'C5', duration: 'eighth', beamGroup: g }));
    addBeams(ns as never);
    return ns.map((n) => (n as never as { beams?: string[] }).beams ?? null);
  });
  assert.deepEqual(js, JSON.parse(py));
  // 여섯 개가 한 빔이면 begin·continue×4·end 여야 한다 (4개에서 안 끊긴다)
  assert.deepEqual(js[0].map((b) => (b ? b[0] : null)),
    ['begin', 'continue', 'continue', 'continue', 'continue', 'end']);
  // 묶음이 바뀌면 둘로 갈린다
  assert.deepEqual(js[1].map((b) => (b ? b[0] : null)),
    ['begin', 'end', 'begin', 'end']);
});

// **음이름 이조가 파이썬과 같아야 한다.**
// CLI 쪽에 `pitch + "4"` 로 옥타브를 덧붙이고 뒤를 자르는 옛 코드가 남아
// "B3" → "B34"(34옥타브)로 해석되는 버그가 있었다. 글자는 맞고 옥타브만
// 틀려서 눈으로 잘 안 보였다(실측: -3반음에서 D4가 B3 대신 B4).
const PITCHES = ['B3', 'D4', 'F4', 'G4', 'C5', 'D5', 'E4', 'A3',
                 'F#4', 'Bb4', 'E5', 'G3'];
const MOVES: Array<[number, number]> = [
  [-3, -2], [-5, -3], [-1, -1], [1, 1], [2, 1], [5, 3],
];

test('음이름 이조가 파이썬과 같다', async () => {
  if (!existsSync('tools/musicxml.py')) return;
  const { parseNote, formatNote, transposeNote } = await import('../web/engine/index.js');
  let py: string;
  try {
    py = execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, "tools")
import musicxml as M
d = json.loads(sys.stdin.read())
print(json.dumps([[M.transpose(p, st, se) for p in d["pitches"]]
                  for se, st in d["moves"]]))
`], { input: JSON.stringify({ pitches: PITCHES, moves: MOVES }), encoding: 'utf8' });
  } catch {
    return;
  }
  const js = MOVES.map(([semitones, steps]) => PITCHES.map((p) => {
    const n = parseNote(p);
    assert.ok(n, `parseNote 실패: ${p}`);
    return formatNote(transposeNote(n, { steps, semitones }), { octave: true });
  }));
  assert.deepEqual(js, JSON.parse(py));
});

// **조표(fifths)가 파이썬과 같아야 한다.**
// `plan`에는 `fifthsTo`가 없다 — 파이썬 `render.call_engine`이 따로 넣어 주는
// 값이라 JS 코어에는 없다. `plan.fifthsTo ?? 0` 으로 두면 조표가 늘 C장조(0)로
// 그려진다(직접 겪었다: F키 -3반음에서 D장조(♯2)여야 하는데 0이 들어갔다).
const KEY_MOVES: Array<[string, number]> = [
  ['F', -3], ['Bb', -3], ['C', -3], ['F', 2], ['G', -5],
  ['Eb', 4], ['A', -1], ['Db', 3],
];

test('조표가 파이썬과 같다', async () => {
  if (!existsSync('tools/render.py')) return;
  const { planBySemitones, fifths } = await import('../web/engine/index.js');
  let py: string;
  try {
    py = execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, "tools")
import render as R
d = json.loads(sys.stdin.read())
print(json.dumps([R.call_engine(k, s, [])["fifthsTo"] for k, s in d]))
`], { input: JSON.stringify(KEY_MOVES), encoding: 'utf8' });
  } catch {
    return;
  }
  const js = KEY_MOVES.map(([k, s]) => fifths(planBySemitones(k, s).toKey));
  assert.deepEqual(js, JSON.parse(py));
});
