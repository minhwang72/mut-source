/**
 * 조성 · 조표 · 이명동음 선택
 *
 * 이조에서 가장 자주 틀리는 부분이 목표 조성의 표기 선택이다.
 * F#장조(#6개)와 Gb장조(b6개)는 같은 소리지만 악보가 전혀 다르다.
 * 여기서는 5도권 위치의 절대값(= 조표 개수)이 작은 쪽을 고른다.
 */

import {
                
              
            
  formatNote,
  intervalUp,
  invertDown,
  mod,
  parseNote,
  pitchClass,
} from "./pitch.js";

                                     

                      
              
             
 

/** 5도권에서 각 음이름의 위치. F=-1, C=0, G=1, D=2, A=3, E=4, B=5 */
const LETTER_FIFTHS                         = { 0: 0, 1: 2, 2: 4, 3: -1, 4: 1, 5: 3, 6: 5 };

/**
 * 조표 개수. 양수 = 올림표 개수, 음수 = 내림표 개수.
 * 예) C장조 0, G장조 +1, Eb장조 -3, a단조 0, c단조 -3
 */
export function fifths(key     )         {
  const base = LETTER_FIFTHS[key.tonic.letter] + 7 * key.tonic.alter;
  return key.mode === "minor" ? base - 3 : base;
}

/** 조표에 쓰이는 임시표 개수 (표기 복잡도) */
export function accidentalCount(key     )         {
  return Math.abs(fifths(key));
}

const KEY_RE = /^\s*([A-Ga-g](?:#{1,2}|b{1,2}|♯{1,2}|♭{1,2}|x|X)?)\s*(.*)$/;

const MINOR_TOKENS = new Set(["m", "min", "minor", "단조", "-"]);
const MAJOR_TOKENS = new Set(["", "M", "maj", "major", "장조"]);

/**
 * "C", "Am", "Bb", "f# minor", "Eb장조" 등을 파싱.
 * 모드 표기가 없으면 장조로 본다(소문자만으로 단조로 해석하지 않는다 —
 * 사용자가 "c"라고 쓴 게 C장조인 경우가 압도적으로 많다).
 */
export function parseKey(s        )             {
  const m = KEY_RE.exec(s);
  if (!m) return null;
  const tonic = parseNote(m[1]);
  if (!tonic) return null;
  const rest = m[2].trim();
  if (MINOR_TOKENS.has(rest)) return { tonic, mode: "minor" };
  if (MAJOR_TOKENS.has(rest)) return { tonic, mode: "major" };
  return null;
}

export function formatKey(key     , unicode = false)         {
  const name = formatNote(key.tonic, { unicode });
  return key.mode === "minor" ? `${name}m` : name;
}

/** 조성의 으뜸음 음높이 계열 */
export function keyPitchClass(key     )         {
  return pitchClass(key.tonic);
}

/**
 * 주어진 음높이 계열을 으뜸음으로 하는 모든 실용 표기를 5도권 위치가
 * 단순한 순으로 반환한다. |조표| > 7 인 표기(예: G#장조 = #8)는 제외한다.
 */
export function spellingsFor(pc        , mode      )        {
  const out        = [];
  for (let letter = 0          ; letter <= 6; letter = (letter + 1)          ) {
    for (let alter = -2; alter <= 2; alter++) {
      const key      = { tonic: { letter, alter, octave: 4 }, mode };
      if (keyPitchClass(key) !== mod(pc, 12)) continue;
      if (accidentalCount(key) > 7) continue;
      out.push(key);
    }
  }
  return out.sort((a, b) => {
    const d = accidentalCount(a) - accidentalCount(b);
    if (d !== 0) return d;
    // 동수일 때(예: F#장조 #6 vs Gb장조 b6)는 올림표 쪽.
    // 기타·대중음악 리드시트에서 더 흔한 표기다.
    return fifths(b) - fifths(a);
  });
}

                                 
                                      
                            
 

/**
 * 원조성에서 n반음 이조한 목표 조성을 고른다.
 * n은 부호 있는 반음 수(양수 = 위로).
 */
export function keyAfterSemitones(from     , n        , opts                 = {})      {
  const candidates = spellingsFor(keyPitchClass(from) + n, from.mode);
  if (candidates.length === 0) {
    throw new Error(`이조 결과를 표기할 수 없습니다: ${formatKey(from)} ${n >= 0 ? "+" : ""}${n}`);
  }
  if (opts.prefer === "flat") {
    const best = accidentalCount(candidates[0]);
    const tied = candidates.filter((k) => accidentalCount(k) === best);
    return tied.reduce((a, b) => (fifths(a) < fifths(b) ? a : b));
  }
  return candidates[0];
}

/**
 * 두 조성 사이의 이조 음정.
 * direction: "up" | "down" | "nearest" (기본) — nearest는 6반음 이하 쪽으로.
 */
export function keyInterval(
  from     ,
  to     ,
  direction                            = "nearest",
)           {
  const up = intervalUp(from.tonic, to.tonic);
  if (direction === "up") return up;
  const down = invertDown(up);
  if (direction === "down") return down;
  return Math.abs(up.semitones) <= Math.abs(down.semitones) ? up : down;
}

/** 원조성에서 목표 조성까지 몇 반음인지 (nearest 기준, -6..+6) */
export function semitonesBetween(from     , to     )         {
  return keyInterval(from, to, "nearest").semitones;
}
