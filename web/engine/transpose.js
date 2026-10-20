/**
 * 상위 API — 뮤트의 키 변환 코어
 *
 * 이 모듈은 순수 함수뿐이다. 파일·네트워크·DOM 접근이 없다.
 * 저작권 설계상 이 코드는 **사용자 브라우저에서** 실행되어야 하고,
 * 그래서 서버 의존이 하나도 없어야 한다.
 */

import {
                
            
  formatNote,
  midi,
  parseNote,
  transposeNote,
} from "./pitch.js";
import {
           
            
  accidentalCount,
  formatKey,
  keyAfterSemitones,
  keyInterval,
  parseKey,
} from "./key.js";
import {                          transposeChordText } from "./chord.js";

                                    

function asKey(k          )      {
  if (typeof k !== "string") return k;
  const parsed = parseKey(k);
  if (!parsed) throw new Error(`조성을 해석할 수 없습니다: "${k}"`);
  return parsed;
}

function asMidi(n                 )         {
  if (typeof n === "number") return n;
  const note = parseNote(n);
  if (!note) throw new Error(`음이름을 해석할 수 없습니다: "${n}"`);
  return midi(note);
}

                                
               
             
                     
                            
                    
                          
                        
 

                              
                            
 

/** 반음 수로 이조 계획 수립 */
export function planBySemitones(
  fromKey          ,
  semitones        ,
  opts              = {},
)                {
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
  fromKey          ,
  toKey          ,
  direction                            = "nearest",
)                {
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
  chords                   ,
  plan               ,
  opts                     = {},
)           {
  return chords.map((c) => transposeChordText(c, plan.interval, opts));
}

/** 음이름 목록 이조 (멜로디) */
export function transposeNoteNames(
  notes                   ,
  plan               ,
  opts                        = {},
)           {
  return notes.map((n) => {
    const note = parseNote(n);
    if (!note) return n;
    return formatNote(transposeNote(note, plan.interval), {
      octave: /\d/.test(n),
      unicode: opts.unicode,
    });
  });
}

export function describePlan(plan               )         {
  const dir = plan.semitones === 0 ? "그대로" : plan.semitones > 0 ? "올림" : "내림";
  const n = Math.abs(plan.semitones);
  const sig = (count        ) => (count === 0 ? "없음" : `${count}개`);
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
const OPEN_FRIENDLY                         = {
  major: ["C", "G", "D", "A", "E"],
  minor: ["Am", "Em", "Dm"],
};

                                 
                         
               
                        
                
 

/**
 * 목표 조성을 카포로 편하게 치는 방법.
 * 카포 f프렛에서 잡는 폼은 목표 조성을 f반음 **내린** 조성이다.
 */
export function suggestCapo(target          , maxFret = 7)                   {
  const key = asKey(target);
  const friendly = OPEN_FRIENDLY[key.mode];
  const out                   = [];
  for (let capo = 0; capo <= maxFret; capo++) {
    const shapeKey = keyAfterSemitones(key, -capo);
    if (friendly.includes(formatKey(shapeKey))) out.push({ capo, shapeKey });
  }
  return out;
}

export function describeCapo(s                )         {
  return s.capo === 0
    ? `카포 없이 ${formatKey(s.shapeKey)} 폼`
    : `카포 ${s.capo}프렛 + ${formatKey(s.shapeKey)} 폼`;
}

/* ------------------------------------------------------------------ */
/* 음역 기반 키 추천                                                    */
/* ------------------------------------------------------------------ */

                               
                    
                                         
                             
                              
                      
                             
                              
                           
                    
                            
 

                               
                    
           
                        
                
                                        
                      
                                         
                       
                                 
                   
                      
                         
 

/**
 * 부르는 사람의 음역에 맞는 조성을 순위대로 추천.
 *
 * "몇 키 내릴까?"를 사람이 감으로 정하는 대신 계산으로 답한다.
 * 멜로디 음역은 악보 판독 단계에서 이미 얻어지므로 추가 비용이 없다.
 */
export function suggestKeysForRange(req              )                 {
  const from = asKey(req.fromKey);
  const mLow = asMidi(req.melodyLow);
  const mHigh = asMidi(req.melodyHigh);
  const sLow = asMidi(req.singerLow);
  const sHigh = asMidi(req.singerHigh);
  const maxShift = req.maxShift ?? 7;

  if (mLow > mHigh) throw new Error("멜로디 최저음이 최고음보다 높습니다.");
  if (sLow > sHigh) throw new Error("음역 하한이 상한보다 높습니다.");

  const out                 = [];
  for (let n = -maxShift; n <= maxShift; n++) {
    let key     ;
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
export function rangeFeasible(req              )          {
  const span = asMidi(req.melodyHigh) - asMidi(req.melodyLow);
  const capacity = asMidi(req.singerHigh) - asMidi(req.singerLow);
  return span <= capacity;
}
