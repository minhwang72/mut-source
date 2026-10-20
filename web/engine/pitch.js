/**
 * 음높이 · 음정 기본 자료구조
 *
 * 설계 원칙: 반음 개수만으로 이조하지 않는다.
 * "C에서 2반음 위"는 D일 수도, C##일 수도 있다. 올바른 표기를 얻으려면
 * 항상 "온음계 단계(steps) + 반음(semitones)"을 쌍으로 가진 음정을 써야 한다.
 */

/** C=0, D=1, E=2, F=3, G=4, A=5, B=6 */
                                               

const LETTER_SEMITONE = [0, 2, 4, 5, 7, 9, 11]         ;
const LETTER_NAME = ["C", "D", "E", "F", "G", "A", "B"]         ;

                       
                 
                                                      
                
                                              
                 
 

                           
                                               
                
                     
                    
 

/** 항상 양수를 반환하는 나머지 연산 */
export function mod(n        , m        )         {
  return ((n % m) + m) % m;
}

/** MIDI 번호. C4 = 60 */
export function midi(note      )         {
  return LETTER_SEMITONE[note.letter] + note.alter + 12 * (note.octave + 1);
}

/** 옥타브를 무시한 음높이 계열 (0~11) */
export function pitchClass(note      )         {
  return mod(LETTER_SEMITONE[note.letter] + note.alter, 12);
}

const ACCIDENTAL_TO_ALTER                         = {
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
export function parseAccidental(s        )                {
  const alter = ACCIDENTAL_TO_ALTER[s];
  return alter === undefined ? null : alter;
}

export function formatAccidental(alter        , unicode = false)         {
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
export function parseNote(s        )              {
  const m = NOTE_RE.exec(s.trim());
  if (!m) return null;
  const letter = LETTER_NAME.indexOf(
    m[1].toUpperCase()                                ,
  )          ;
  const alter = parseAccidental(m[2] ?? "");
  if (alter === null) return null;
  const octave = m[3] === undefined ? 4 : Number.parseInt(m[3], 10);
  return { letter, alter, octave };
}

                                    
                                    
                   
                    
 

export function formatNote(note      , opts                    = {})         {
  const name = LETTER_NAME[note.letter] + formatAccidental(note.alter, opts.unicode);
  return opts.octave ? `${name}${note.octave}` : name;
}

/**
 * 음정 적용. 온음계 단계로 음이름을 옮긴 뒤, 반음 차이를 임시표로 메운다.
 * 이 순서가 올바른 이명동음 표기를 보장한다.
 */
export function transposeNote(note      , iv          )       {
  const absStep = note.letter + iv.steps;
  const letter = mod(absStep, 7)          ;
  const octave = note.octave + Math.floor(absStep / 7);
  const target = midi(note) + iv.semitones;
  const natural = LETTER_SEMITONE[letter] + 12 * (octave + 1);
  return { letter, alter: target - natural, octave };
}

/**
 * 두 음 사이의 음정. 옥타브를 무시하고 "위로 향하는" 최소 음정을 구한다
 * (동음이면 0). 조성 이조에서 쓰는 형태.
 */
export function intervalUp(from      , to      )           {
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
export function invertDown(iv          )           {
  if (iv.steps === 0 && iv.semitones === 0) return iv;
  return { steps: iv.steps - 7, semitones: iv.semitones - 12 };
}

/** 임시표가 겹올림/겹내림을 넘어가면 실무상 못 쓰는 표기다 */
export function isPlayable(note      )          {
  return note.alter >= -2 && note.alter <= 2;
}
