/**
 * 음높이 · 음정 기본 자료구조
 *
 * 설계 원칙: 반음 개수만으로 이조하지 않는다.
 * "C에서 2반음 위"는 D일 수도, C##일 수도 있다. 올바른 표기를 얻으려면
 * 항상 "온음계 단계(steps) + 반음(semitones)"을 쌍으로 가진 음정을 써야 한다.
 */

/** C=0, D=1, E=2, F=3, G=4, A=5, B=6 */
export type Letter = 0 | 1 | 2 | 3 | 4 | 5 | 6;

const LETTER_SEMITONE = [0, 2, 4, 5, 7, 9, 11] as const;
const LETTER_NAME = ["C", "D", "E", "F", "G", "A", "B"] as const;

export interface Note {
  letter: Letter;
  /** -2 = 겹내림, -1 = 내림, 0 = 제자리, +1 = 올림, +2 = 겹올림 */
  alter: number;
  /** 가온다 = C4. 코드 심볼처럼 옥타브가 무의미한 경우 4로 둔다. */
  octave: number;
}

export interface Interval {
  /** 온음계 단계. 0 = 동음, 1 = 2도, 2 = 3도 … 부호 있음 */
  steps: number;
  /** 반음 개수. 부호 있음 */
  semitones: number;
}

/** 항상 양수를 반환하는 나머지 연산 */
export function mod(n: number, m: number): number {
  return ((n % m) + m) % m;
}

/** MIDI 번호. C4 = 60 */
export function midi(note: Note): number {
  return LETTER_SEMITONE[note.letter] + note.alter + 12 * (note.octave + 1);
}

/** 옥타브를 무시한 음높이 계열 (0~11) */
export function pitchClass(note: Note): number {
  return mod(LETTER_SEMITONE[note.letter] + note.alter, 12);
}

const ACCIDENTAL_TO_ALTER: Record<string, number> = {
  "": 0,
  "#": 1,
  "♯": 1,
  "##": 2,
  "♯♯": 2,
  x: 2,
  X: 2,
  "𝄪": 2,
  b: -1,
  "♭": -1,
  bb: -2,
  "♭♭": -2,
  "𝄫": -2,
};

/** 음이름 문자열의 임시표 부분을 alter 값으로. 인식 불가면 null */
export function parseAccidental(s: string): number | null {
  const alter = ACCIDENTAL_TO_ALTER[s];
  return alter === undefined ? null : alter;
}

export function formatAccidental(alter: number, unicode = false): string {
  const sharp = unicode ? "♯" : "#";
  const flat = unicode ? "♭" : "b";
  if (alter === 0) return "";
  return alter > 0 ? sharp.repeat(alter) : flat.repeat(-alter);
}

const NOTE_RE = /^([A-Ga-g])(#{1,2}|b{1,2}|♯{1,2}|♭{1,2}|x|X|𝄪|𝄫)?(-?\d+)?$/;

/**
 * "C", "Bb", "F#4", "Eb3" 등을 파싱. 옥타브 생략 시 4.
 * 소문자 음이름도 받아들인다(단, 조성의 장/단 구분에는 쓰지 않는다).
 */
export function parseNote(s: string): Note | null {
  const m = NOTE_RE.exec(s.trim());
  if (!m) return null;
  const letter = LETTER_NAME.indexOf(
    m[1].toUpperCase() as (typeof LETTER_NAME)[number],
  ) as Letter;
  const alter = parseAccidental(m[2] ?? "");
  if (alter === null) return null;
  const octave = m[3] === undefined ? 4 : Number.parseInt(m[3], 10);
  return { letter, alter, octave };
}

export interface FormatNoteOptions {
  /** 옥타브 숫자를 붙일지. 코드 심볼에서는 false */
  octave?: boolean;
  unicode?: boolean;
}

export function formatNote(note: Note, opts: FormatNoteOptions = {}): string {
  const name = LETTER_NAME[note.letter] + formatAccidental(note.alter, opts.unicode);
  return opts.octave ? `${name}${note.octave}` : name;
}

/**
 * 음정 적용. 온음계 단계로 음이름을 옮긴 뒤, 반음 차이를 임시표로 메운다.
 * 이 순서가 올바른 이명동음 표기를 보장한다.
 */
export function transposeNote(note: Note, iv: Interval): Note {
  const absStep = note.letter + iv.steps;
  const letter = mod(absStep, 7) as Letter;
  const octave = note.octave + Math.floor(absStep / 7);
  const target = midi(note) + iv.semitones;
  const natural = LETTER_SEMITONE[letter] + 12 * (octave + 1);
  return { letter, alter: target - natural, octave };
}

/**
 * **실용 표기로 고친다.** 온음계 이조는 이론상 옳은 표기를 내지만, 조성에
 * 속하지 않는 코드(Bb장조의 F#m7 같은 차용화음)를 옮기면 실제 악보에서
 * 쓰지 않는 이름이 나온다 — 실측: Bb → A 이조에서 F#m7 이 `E#m7` 이 됐다.
 * 겹임시표(##, bb)와 E#·B#·Fb·Cb 는 같은 소리의 흔한 이름으로 바꾼다.
 *
 * 방향은 목표 조성을 따른다. ♯ 조성이면 ♯쪽, ♭ 조성이면 ♭쪽을 고른다.
 * 그래야 조표와 코드 표기가 어긋나지 않는다.
 */
const SHARP_NAMES: [Letter, number][] = [
  [0, 0], [0, 1], [1, 0], [2, -1], [2, 0], [3, 0],
  [3, 1], [4, 0], [4, 1], [5, 0], [5, 1], [6, 0],
];
const FLAT_NAMES: [Letter, number][] = [
  [0, 0], [1, -1], [1, 0], [2, -1], [2, 0], [3, 0],
  [4, -1], [4, 0], [5, -1], [5, 0], [6, -1], [6, 0],
];

/** 실제 악보에서 거의 쓰지 않는 표기인가 */
export function isAwkward(note: Note): boolean {
  if (Math.abs(note.alter) >= 2) return true;
  // 글자 번호는 C=0 D=1 E=2 F=3 G=4 A=5 B=6 이다.
  // 흔히 쓰지 않는 것은 E#(2,+1) B#(6,+1) Fb(3,-1) Cb(0,-1) 넷뿐이다.
  // (G#·F#·Bb 같은 것은 정상 표기이므로 건드리면 안 된다 —
  //  실측: 잘못 잡아서 F#m7b5 가 Gbm7b5 로 바뀌어 테스트가 깨졌다.)
  if (note.alter === 1 && (note.letter === 2 || note.letter === 6)) return true;
  if (note.alter === -1 && (note.letter === 3 || note.letter === 0)) return true;
  return false;
}

/** 어색한 표기만 같은 소리의 흔한 이름으로 바꾼다. 아니면 그대로. */
export function simplifyNote(note: Note, preferFlat: boolean): Note {
  if (!isAwkward(note)) return note;
  const table = preferFlat ? FLAT_NAMES : SHARP_NAMES;
  const [letter, alter] = table[mod(pitchClass(note), 12)];
  // 옥타브는 소리를 유지하도록 다시 맞춘다
  const target = midi(note);
  const natural = LETTER_SEMITONE[letter] + alter;
  const octave = Math.round((target - natural) / 12) - 1;
  return { letter, alter, octave };
}

/**
 * 두 음 사이의 음정. 옥타브를 무시하고 "위로 향하는" 최소 음정을 구한다
 * (동음이면 0). 조성 이조에서 쓰는 형태.
 */
export function intervalUp(from: Note, to: Note): Interval {
  const steps = mod(to.letter - from.letter, 7);
  let semitones = mod(pitchClass(to) - pitchClass(from), 12);
  // steps와 semitones의 정합성 확인: 단계에 대응하는 자연 반음수와 2 이상
  // 벌어지면 옥타브 경계를 잘못 잡은 것이므로 보정한다.
  const natural = LETTER_SEMITONE[steps];
  while (semitones - natural > 6) semitones -= 12;
  while (natural - semitones > 6) semitones += 12;
  return { steps, semitones };
}

/** 음정의 방향을 아래로 뒤집는다 (한 옥타브 내림) */
export function invertDown(iv: Interval): Interval {
  if (iv.steps === 0 && iv.semitones === 0) return iv;
  return { steps: iv.steps - 7, semitones: iv.semitones - 12 };
}

/** 임시표가 겹올림/겹내림을 넘어가면 실무상 못 쓰는 표기다 */
export function isPlayable(note: Note): boolean {
  return note.alter >= -2 && note.alter <= 2;
}
