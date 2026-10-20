/**
 * 상위 API — 뮤트의 키 변환 코어
 *
 * 이 모듈은 순수 함수뿐이다. 파일·네트워크·DOM 접근이 없다.
 * 저작권 설계상 이 코드는 **사용자 브라우저에서** 실행되어야 하고,
 * 그래서 서버 의존이 하나도 없어야 한다.
 */

import {
  type Interval,
  type Note,
  formatNote,
  midi,
  parseNote,
  transposeNote,
} from "./pitch.ts";
import {
  fifths,
  type Key,
  type Mode,
  accidentalCount,
  formatKey,
  keyAfterSemitones,
  keyInterval,
  parseKey,
} from "./key.ts";
import { type FormatChordOptions, transposeChordText } from "./chord.ts";

export type KeyInput = Key | string;

function asKey(k: KeyInput): Key {
  if (typeof k !== "string") return k;
  const parsed = parseKey(k);
  if (!parsed) throw new Error(`조성을 해석할 수 없습니다: "${k}"`);
  return parsed;
}

function asMidi(n: string | number): number {
  if (typeof n === "number") return n;
  const note = parseNote(n);
  if (!note) throw new Error(`음이름을 해석할 수 없습니다: "${n}"`);
  return midi(note);
}

export interface TransposePlan {
  fromKey: Key;
  toKey: Key;
  interval: Interval;
  /** 부호 있는 반음 수. 양수 = 위로 */
  semitones: number;
  accidentalsFrom: number;
  accidentalsTo: number;
}

export interface PlanOptions {
  prefer?: "sharp" | "flat";
}

/** 반음 수로 이조 계획 수립 */
export function planBySemitones(
  fromKey: KeyInput,
  semitones: number,
  opts: PlanOptions = {},
): TransposePlan {
  const from = asKey(fromKey);
  const to = keyAfterSemitones(from, semitones, opts);
  // 요청한 방향을 그대로 지킨다. 사용자가 "3키 내려"라고 했으면
  // 최단거리가 위쪽이더라도 아래로 내려야 한다.
  const interval = keyInterval(from, to, semitones >= 0 ? "up" : "down");
  return {
    fromKey: from,
    toKey: to,
    interval,
    semitones,
    accidentalsFrom: accidentalCount(from),
    accidentalsTo: accidentalCount(to),
  };
}

/** 목표 조성을 직접 지정해 이조 계획 수립 */
export function planByKey(
  fromKey: KeyInput,
  toKey: KeyInput,
  direction: "up" | "down" | "nearest" = "nearest",
): TransposePlan {
  const from = asKey(fromKey);
  const to = asKey(toKey);
  if (from.mode !== to.mode) {
    throw new Error(
      `장·단조가 다릅니다(${formatKey(from)} → ${formatKey(to)}). 이조는 조성을 바꾸지 않습니다.`,
    );
  }
  const interval = keyInterval(from, to, direction);
  return {
    fromKey: from,
    toKey: to,
    interval,
    semitones: interval.semitones,
    accidentalsFrom: accidentalCount(from),
    accidentalsTo: accidentalCount(to),
  };
}

/** 코드 심볼 목록 이조. 코드가 아닌 항목은 원본 유지 */
export function transposeChords(
  chords: readonly string[],
  plan: TransposePlan,
  opts: FormatChordOptions = {},
): string[] {
  // **여기서는 표기를 손대지 않는다.** 이조는 수학적으로 뒤집을 수 있어야
  // 하는데(왕복 불변), E#→F 같은 실용 표기 보정은 그 성질을 깬다
  // (실측: F#m7b5 를 왕복시키면 Gbm7b5 가 됐다).
  // 실용 표기는 **보여주기 직전**에 cli 층에서 적용한다.
  // 목표 조성이 ♭조성이면 ♭쪽을 고르도록 기본값만 채워 준다.
  const preferFlat = fifths(plan.toKey) < 0;
  return chords.map((c) =>
    transposeChordText(c, plan.interval, { preferFlat, ...opts }),
  );
}

/** 음이름 목록 이조 (멜로디) */
export function transposeNoteNames(
  notes: readonly string[],
  plan: TransposePlan,
  opts: { unicode?: boolean } = {},
): string[] {
  return notes.map((n) => {
    const note = parseNote(n);
    if (!note) return n;
    return formatNote(transposeNote(note, plan.interval), {
      octave: /\d/.test(n),
      unicode: opts.unicode,
    });
  });
}

export function describePlan(plan: TransposePlan): string {
  const dir = plan.semitones === 0 ? "그대로" : plan.semitones > 0 ? "올림" : "내림";
  const n = Math.abs(plan.semitones);
  const sig = (count: number) => (count === 0 ? "없음" : `${count}개`);
  return (
    `${formatKey(plan.fromKey)} → ${formatKey(plan.toKey)}` +
    ` (${n === 0 ? dir : `${n}반음 ${dir}`}, ` +
    `조표 ${sig(plan.accidentalsFrom)} → ${sig(plan.accidentalsTo)})`
  );
}

/* ------------------------------------------------------------------ */
/* 기타 카포                                                           */
/* ------------------------------------------------------------------ */

/** 오픈 코드로 잡기 편한 조성 (CAGED + 흔한 단조) */
const OPEN_FRIENDLY: Record<Mode, string[]> = {
  major: ["C", "G", "D", "A", "E"],
  minor: ["Am", "Em", "Dm"],
};

export interface CapoSuggestion {
  /** 카포 위치. 0 = 카포 없음 */
  capo: number;
  /** 실제로 잡는 코드 폼의 조성 */
  shapeKey: Key;
}

/**
 * 목표 조성을 카포로 편하게 치는 방법.
 * 카포 f프렛에서 잡는 폼은 목표 조성을 f반음 **내린** 조성이다.
 */
export function suggestCapo(target: KeyInput, maxFret = 7): CapoSuggestion[] {
  const key = asKey(target);
  const friendly = OPEN_FRIENDLY[key.mode];
  const out: CapoSuggestion[] = [];
  for (let capo = 0; capo <= maxFret; capo++) {
    const shapeKey = keyAfterSemitones(key, -capo);
    if (friendly.includes(formatKey(shapeKey))) out.push({ capo, shapeKey });
  }
  return out;
}

export function describeCapo(s: CapoSuggestion): string {
  return s.capo === 0
    ? `카포 없이 ${formatKey(s.shapeKey)} 폼`
    : `카포 ${s.capo}프렛 + ${formatKey(s.shapeKey)} 폼`;
}

/* ------------------------------------------------------------------ */
/* 음역 기반 키 추천                                                    */
/* ------------------------------------------------------------------ */

export interface RangeRequest {
  fromKey: KeyInput;
  /** 악보 멜로디의 최저음·최고음 (음이름 또는 MIDI 번호) */
  melodyLow: string | number;
  melodyHigh: string | number;
  /** 부르는 사람이 편한 음역 */
  singerLow: string | number;
  singerHigh: string | number;
  /** 탐색할 이조 범위. 기본 ±7반음 */
  maxShift?: number;
  prefer?: "sharp" | "flat";
}

export interface KeyCandidate {
  semitones: number;
  key: Key;
  /** 음역 안에 완전히 들어오는지 */
  fits: boolean;
  /** 최저음이 음역 하한보다 몇 반음 위인지 (음수면 벗어남) */
  headroomLow: number;
  /** 최고음이 음역 상한보다 몇 반음 아래인지 (음수면 벗어남) */
  headroomHigh: number;
  /** 음역을 벗어난 총 반음 수. 0이면 fits */
  overflow: number;
  accidentals: number;
  capo: CapoSuggestion[];
}

/**
 * 부르는 사람의 음역에 맞는 조성을 순위대로 추천.
 *
 * "몇 키 내릴까?"를 사람이 감으로 정하는 대신 계산으로 답한다.
 * 멜로디 음역은 악보 판독 단계에서 이미 얻어지므로 추가 비용이 없다.
 */
export function suggestKeysForRange(req: RangeRequest): KeyCandidate[] {
  const from = asKey(req.fromKey);
  const mLow = asMidi(req.melodyLow);
  const mHigh = asMidi(req.melodyHigh);
  const sLow = asMidi(req.singerLow);
  const sHigh = asMidi(req.singerHigh);
  const maxShift = req.maxShift ?? 7;

  if (mLow > mHigh) throw new Error("멜로디 최저음이 최고음보다 높습니다.");
  if (sLow > sHigh) throw new Error("음역 하한이 상한보다 높습니다.");

  const out: KeyCandidate[] = [];
  for (let n = -maxShift; n <= maxShift; n++) {
    let key: Key;
    try {
      key = keyAfterSemitones(from, n, { prefer: req.prefer });
    } catch {
      continue; // 표기 불가능한 조성은 건너뛴다
    }
    const low = mLow + n;
    const high = mHigh + n;
    const headroomLow = low - sLow;
    const headroomHigh = sHigh - high;
    const overflow = Math.max(0, -headroomLow) + Math.max(0, -headroomHigh);
    out.push({
      semitones: n,
      key,
      fits: overflow === 0,
      headroomLow,
      headroomHigh,
      overflow,
      accidentals: accidentalCount(key),
      capo: suggestCapo(key),
    });
  }

  return out.sort((a, b) => {
    if (a.fits !== b.fits) return a.fits ? -1 : 1;
    if (a.overflow !== b.overflow) return a.overflow - b.overflow;
    // 위아래 여유를 균등하게 — 한쪽에 몰리면 부르기 힘들다
    const balA = Math.abs(a.headroomLow - a.headroomHigh);
    const balB = Math.abs(b.headroomLow - b.headroomHigh);
    if (balA !== balB) return balA - balB;
    if (a.accidentals !== b.accidentals) return a.accidentals - b.accidentals;
    return Math.abs(a.semitones) - Math.abs(b.semitones);
  });
}

/** 멜로디 음역이 애초에 부를 수 있는 폭인지 */
export function rangeFeasible(req: RangeRequest): boolean {
  const span = asMidi(req.melodyHigh) - asMidi(req.melodyLow);
  const capacity = asMidi(req.singerHigh) - asMidi(req.singerLow);
  return span <= capacity;
}
