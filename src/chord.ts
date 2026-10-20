/**
 * 코드 심볼 파싱 · 이조
 *
 * 핵심 설계: 근음(과 분수코드의 베이스음)만 이조하고,
 * 코드 성질 문자열("maj7#11", "sus4", "m7b5" …)은 **그대로 통과**시킨다.
 * 성질을 해석하려 들면 표기 방언 때문에 반드시 깨진다. 이조에 필요한
 * 정보는 근음뿐이므로 해석할 이유도 없다.
 */

import {
  type Interval,
  type Note,
  formatNote,
  parseAccidental,
  parseNote,
  simplifyNote,
  transposeNote,
} from "./pitch.ts";

export interface ChordSymbol {
  root: Note;
  /** "m7", "maj7#11", "sus4", "" 등. 해석하지 않고 보존한다 */
  quality: string;
  /** 분수코드의 베이스음. 없으면 null */
  bass: Note | null;
  /** 코드를 감싼 문자, 예: "(", ")" */
  open: string;
  close: string;
}

const ACCIDENTAL = "(?:#{1,2}|b{1,2}|♯{1,2}|♭{1,2}|x|X)";

/**
 * 근음 + 성질. 근음 직후의 b는 **항상 임시표**로 본다.
 * b5·b9·b13 같은 변화음은 성질/숫자 뒤에만 오기 때문에
 * "Bb9"를 B + b9로 오독할 위험이 실제로는 없다.
 */
const HEAD_RE = new RegExp(`^([A-G])(${ACCIDENTAL})?(.*)$`);

/** 코드가 아니라 그대로 둬야 하는 표기 */
const PASSTHROUGH = new Set(["N.C.", "NC", "%", "-", "/", "|", "×", "x"]);

/**
 * 코드 심볼 파싱. 코드로 볼 수 없으면 null.
 * null은 오류가 아니라 "손대지 말라"는 신호다("N.C.", "%", 가사 등).
 */
export function parseChord(input: string): ChordSymbol | null {
  const trimmed = input.trim();
  if (trimmed === "" || PASSTHROUGH.has(trimmed) || PASSTHROUGH.has(trimmed.toUpperCase())) {
    return null;
  }

  // 감싼 괄호를 분리 — 리드시트에서 선택적 코드를 (Am)처럼 쓴다
  let open = "";
  let close = "";
  let body = trimmed;
  const wrapped = /^([([{])(.*)([)\]}])$/.exec(body);
  if (wrapped) {
    open = wrapped[1];
    body = wrapped[2].trim();
    close = wrapped[3];
  }

  // 분수코드: 마지막 '/' 기준으로 베이스음 분리.
  // 뒤쪽이 순수한 음이름일 때만 베이스로 인정한다.
  let bass: Note | null = null;
  const slash = body.lastIndexOf("/");
  if (slash > 0) {
    const tail = body.slice(slash + 1).trim();
    const candidate = /^[A-G]/.test(tail) ? parseNote(tail) : null;
    if (candidate) {
      bass = candidate;
      body = body.slice(0, slash).trim();
    }
  }

  const m = HEAD_RE.exec(body);
  if (!m) return null;
  const alter = parseAccidental(m[2] ?? "");
  if (alter === null) return null;
  const root = parseNote(m[1] + (m[2] ?? ""));
  if (!root) return null;

  return { root, quality: m[3], bass, open, close };
}

export interface FormatChordOptions {
  unicode?: boolean;
  /**
   * 어색한 표기(E#·B#·Fb·Cb·겹임시표)를 흔한 이름으로 바꿀 때 어느 쪽을
   * 고를지. 목표 조성이 ♭조성이면 true. 지정하지 않으면 바꾸지 않는다 —
   * 이론적으로 옳은 표기를 그대로 두는 쪽이 기본값이다.
   */
  preferFlat?: boolean;
  /** 어색한 표기를 실용 표기로 고칠지 (기본 false) */
  simplify?: boolean;
}

export function formatChord(c: ChordSymbol, opts: FormatChordOptions = {}): string {
  const root = formatNote(c.root, { unicode: opts.unicode });
  const bass = c.bass ? `/${formatNote(c.bass, { unicode: opts.unicode })}` : "";
  return `${c.open}${root}${c.quality}${bass}${c.close}`;
}

export function transposeChord(
  c: ChordSymbol,
  iv: Interval,
  opts: { simplify?: boolean; preferFlat?: boolean } = {},
): ChordSymbol {
  const fix = (n: Note) =>
    opts.simplify ? simplifyNote(n, !!opts.preferFlat) : n;
  return {
    ...c,
    root: fix(transposeNote(c.root, iv)),
    bass: c.bass ? fix(transposeNote(c.bass, iv)) : null,
  };
}

/**
 * 문자열 → 이조된 문자열. 코드로 인식되지 않으면 **원본을 그대로** 돌려준다.
 * 이 성질 덕분에 코드 트랙 전체에 무조건 적용해도 안전하다.
 */
export function transposeChordText(
  input: string,
  iv: Interval,
  opts: FormatChordOptions = {},
): string {
  const parsed = parseChord(input);
  if (!parsed) return input;
  return formatChord(transposeChord(parsed, iv, opts), opts);
}
