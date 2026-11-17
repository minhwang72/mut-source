// **새로 그리는 경로.** 픽셀을 옮기는 대신 MusicXML로 다시 조판한다.
//
// 왜 바꿨나(실측): 픽셀 이동은 회색 띠·코드 잔상·음표 손상이 계속 남았고
// (머리 115개 중 4~48개), 임시표는 아예 못 고쳤다. 새로 그리면 그 문제군이
// 통째로 사라지고, 임시표는 이조 계산 하나로 끝난다.
//
// 지켜야 하는 것: **원본과 같은 배치.** 콘티는 한 장이어야 하고 단별 마디
// 수가 같아야 한다. `breaks:'encoded'` + 마디마다 `<print new-system>` 으로
// 보장한다(실측: 이게 없으면 9단이 6단으로 흘렀다).
//
// 서버는 여전히 악보 이미지를 만들지 않는다 — 구조 데이터만 준다.

import { build } from './musicxml.js';
import { assemble, checkBeats, chordsByStaff } from './rebuild.js';
import { assertResolved } from './source-pitch.js';
import {
  fifths, formatNote, parseNote, transposeNote,
} from './engine/index.js';
import {
  lyricBottom, measureBoxes, pasteLyrics, pasteTopMarks, renderFitted, staffRows, viewScale,
} from './verovio-page.js';

/** 음이름을 (온음계 단수 + 반음)으로 옮긴다. 코어의 transposeNote를 쓴다. */
function shiftPitch(name, iv) {
  const n = parseNote(name);
  if (!n) return name;
  return formatNote(transposeNote(n, iv), { octave: true });
}

/** 서버 geometry에서 가사 조각 목록을 뽑는다. */
// 워터마크로 볼 최소 밝기. 실측: 워터마크 229~247 · 가사 잉크 대부분 <190.
const LYRIC_WHITE = 225;

/** 밝은 회색을 흰색으로 올린 사본. 원본은 건드리지 않는다. */
function whitenLight(img, threshold) {
  const w = img.naturalWidth || img.width;
  const h = img.naturalHeight || img.height;
  if (!w || !h) return img;
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const c = cv.getContext('2d', { willReadFrequently: true });
  c.drawImage(img, 0, 0);
  let d;
  try {
    d = c.getImageData(0, 0, w, h);
  } catch {
    return img;                      // 캔버스가 오염됐으면 원본 그대로
  }
  const p = d.data;
  for (let i = 0; i < p.length; i += 4) {
    // 밝기(휘도)로 판단한다 — 색이 있는 표기는 대개 더 어둡다
    const y = 0.299 * p[i] + 0.587 * p[i + 1] + 0.114 * p[i + 2];
    if (y >= threshold) { p[i] = 255; p[i + 1] = 255; p[i + 2] = 255; }
  }
  c.putImageData(d, 0, 0);
  return cv;
}

/**
 * **가사 띠가 다음 단 코드 줄까지 내려오면 자른다.**
 *
 * 가사가 없는 단에서 판독이 다음 단의 코드 줄을 가사 띠로 잡는다(실측 처음 보는
 * 악보 33장 중 9장 — t009-3 단1: 띠 842~897 = 단2 코드 줄 842~). 그 띠를 원본 가사로
 * 오려 붙이면 코드가 한 줄 더 찍힌다. 가사는 다음 단 코드보다 위에 있을 수밖에
 * 없으므로 거기서 자르고, 남는 것이 한 칸이 안 되면 가사가 없는 단이다.
 */
export function clipLyricBands(geo, systems) {
  const tops = {};
  for (const sd of systems || []) {
    const ys = (sd.chords || []).filter((c) => !c.dropped && c.box).map((c) => c.box.y);
    if (ys.length) tops[sd.index] = Math.min(...ys);
  }
  return {
    ...geo,
    systems: (geo.systems || []).map((s, i) => {
      const b = s.lyricBand, t = tops[i + 1];
      if (!b || b.length !== 2 || t == null || b[1] <= t - 2) return s;
      const end = t - 2;
      if (end - b[0] < (s.spacing || 0) * 0.8) {
        const { lyricBand, syllables, ...rest } = s;
        return rest;
      }
      return { ...s, lyricBand: [b[0], end] };
    }),
  };
}

/**
 * **다시 그리는 것은 오려 붙일 원본에서 지운다.** 가사·구간 표시는 원본 픽셀을
 * 붙이는데, 그 띠에 음표 머리(아래 덧줄 음)나 코드 글자가 걸리면 같이 따라와 유령
 * 음표·두 번 찍힌 코드가 된다(처음 보는 악보 대조: t013-3·t034-4·t060-1 머리,
 * t018-9·t030-2·t057-1 코드). 머리와 코드 상자를 흰색으로 칠한 사본에서 오린다.
 */
function maskRedrawn(canvas, struct, geo, systems) {
  const g = canvas.getContext?.('2d');
  if (!g) return;
  g.fillStyle = '#fff';
  // 머리는 **실제 음표로 쓴 것만** — 검출 전체를 지우면 가사 'ㅇ' 같은 오검출과 함께
  // 가사 획이 지워진다
  for (const s of (struct?.systems || [])) {
    for (const n of (s.notes || [])) {
      const h = n.head;
      if (h) g.fillRect(h.x - 2, h.y - 2, h.w + 4, h.h + 4);
    }
  }
  // 코드는 글자 높이 정도의 상자만 — 띠 높이로 늘린 상자(코드 재판독)는 위치가 거칠다
  for (const sd of systems) {
    const gs = geo.systems?.[sd.index];
    const sp = gs?.spacing || 0;
    for (const c of (sd.chords || [])) {
      const b = c.box;
      if (c.dropped || !b) continue;
      // 검출 상자는 글자 가장자리(♯·꼬리)를 조금 놓친다 — 0.4칸 넓혀 지운다
      const p = Math.max(2, sp * 0.4);
      if (b.h <= sp * 3.5) { g.fillRect(b.x - p, b.y - p, b.w + p * 2, b.h + p * 2); continue; }
      // 띠 높이로 늘린 상자(코드 재판독)는 위치가 거칠다 — 그 단 오선 바로 위 코드 줄
      // (오선 위 4칸)만 지운다. 위로 더 지우면 앞 단 가사가 지워진다(t030-2 이중 코드)
      if (gs) {
        const y0 = Math.max(b.y, gs.staffTop - sp * 4), y1 = Math.min(b.y + b.h, gs.staffTop - sp * 0.2);
        if (y1 > y0) g.fillRect(b.x - p, y0, b.w + p * 2, y1 - y0);
      }
    }
  }
}

function lyricsOf(geo) {
  const out = [];
  (geo.systems || []).forEach((sys, i) => {
    if (sys.lyricBand && sys.syllables && sys.syllables.length) {
      out.push({ system: i, band: sys.lyricBand, syllables: sys.syllables });
    }
  });
  return out;
}

/** 이 악보를 새로 그릴 수 있나. 못 하면 예전 픽셀 경로로 물러난다. */
export function whyNoRedraw(ex) {
  const st = ex?.struct;
  const geo = ex?.geometry;
  if (st?.error) return `구조 판독 실패: ${st.error}`;
  if (!st?.systems?.length) return "구조 데이터가 없습니다";
  if (!geo?.systems?.length) return "오선 좌표가 없습니다";
  // 단 수가 어긋나면 코드·가사가 엉뚱한 단에 붙는다
  if (st.systems.length !== geo.systems.length) {
    return `단 수가 다릅니다 (구조 ${st.systems.length} vs 오선 ${geo.systems.length})`;
  }
  // 음표 머리가 없으면 음높이를 못 낸다
  if (!(geo.heads || []).length) return "음표 머리를 찾지 못했습니다";
  // 음표가 없는 단(간주처럼 코드만 있는 줄, 또는 못 읽은 줄)은 막지 않는다 —
  // 조립이 온쉼표로 채우고 그 마디들을 확인할 마디로 짚는다(rebuild.assemble).
  // 예전엔 여기서 장 전체를 막아, 서버가 내준 장(t012-4·t017-1)이 화면에서 안 열렸다.
  return null;
}

export function canRedraw(ex) {
  return whyNoRedraw(ex) === null;
}

/**
 * 새로 그린 악보를 canvas에 채운다.
 *
 * 반환: {notes:[...경고 문구], report:{...}}
 */
export async function redraw(canvas, ex, plan, chordTexts, origImage) {
  const geo = clipLyricBands(ex.geometry, ex.systems);
  const struct = ex.struct;

  const chordsBySystem = chordsByStaff(ex.systems, chordTexts);

  // The user-confirmed key is the fallback when no per-system signature exists.
  const { measures, report } = assemble(
    {...struct, sourceFifths: fifths(plan.fromKey)}, geo, chordsBySystem);
  const unresolved = assertResolved(measures, report);

  // 음높이를 옮긴다. **반음 수만으로는 이명동음을 못 고른다** — 온음계
  // 단수가 글자를, 반음 수가 임시표를 정한다. 이조의 정의 그대로다.
  const iv = plan.interval;
  if (iv.steps || iv.semitones) {
    for (const m of measures) {
      for (const n of m.notes) {
        if (n.pitch) n.pitch = shiftPitch(n.pitch, iv);
      }
    }
  }

  // **조표는 `fifths(plan.toKey)`로 구한다.** `plan`에는 `fifthsTo`가 없다 —
  // 파이썬 `render.call_engine`이 따로 넣어 주는 값이라 JS 코어에는 없다.
  // `plan.fifthsTo ?? 0`으로 두면 **조표가 늘 C장조(0)로 그려진다**
  // (직접 확인: F키 -3반음에서 D장조(♯2)여야 하는데 0이 들어갔다).
  // **전조: 단별 원조 조표를 목표 조표로 옮긴다.**
  // 이조는 하나의 음악적 간격이라 fifths 변화량이 일정하다 —
  // G(1)→F#(6) 이면 +5 이고 같은 곡의 Bb(-2) 구간은 A(3) 이 된다.
  // 그래서 구간마다 다시 계산하지 않고 **차이를 더한다.**
  //
  // **기준은 plan 의 원조성이 아니라 첫 단의 실제 조표다.** 코드로 추정한
  // 원조성과 조표 판독이 다를 수 있고, 그때 plan 기준으로 재면 모든 마디에
  // 조표 변경이 붙는다(실측: 마커스 50마디에 `<key>` 50개).
  // **옮기는 양은 이조 간격으로 잰다** — 목표 조성과 첫 단 조표의 차이로 재면, 원조성
  // 추정(meta.key)이 실제 조표와 다를 때 음은 그대로인데 조표만 옮겨졌다(처음 보는 악보
  // 대조 t029-09: 원키 그대로인데 D♭장조 ♭5 가 ♭1 로). 음높이를 옮기는 것과 같은 간격이다.
  const fTo = fifths(plan.toKey);
  const delta = fTo - fifths(plan.fromKey);
  let nMod = 0, prevF = null;
  for (const m of measures) {
    if (m.srcFifths == null) continue;
    let f = Number(m.srcFifths) + delta;
    while (f > 7) f -= 12;
    while (f < -7) f += 12;
    m.fifths = f;
    if (prevF !== null && f !== prevF) nMod += 1;
    prevF = f;
  }

  // **박자표.** 4/4 를 전제하면 6/8·3/4 악보의 검산·역산이 어긋난다
  // (실측: 콘티 73쪽 중 13쪽이 4박이 아니었다).
  // 구조의 `beats` 는 4분음표 환산이라 6/8 도 3.0 이다. 악보에 적을 숫자는
  // 판독이 글자로 읽어 온 `timeSignature` 를 쓴다.
  const q = Number(struct?.beats) || 4;
  const m = /^(\d+)\/(\d+)$/.exec(String(struct?.timeSignature || ''));
  const beats = m ? Number(m[1]) : (q === 3 ? 3 : q === 2 ? 2 : 4);
  const beatType = m ? Number(m[2]) : 4;
  // 첫 조표는 첫 마디의 것(단별 조표가 있으면) — 아니면 첫 마디부터 조표 바꿈이 붙는다
  const xml = build(measures, measures.find((m) => m.fifths != null)?.fifths ?? fTo, {
    title: ex.meta?.title || '',
    subtitle: ex.meta?.subtitle || '',
    composer: ex.meta?.composer || '',
    beats, beatType,
  });

  // 원본 비율을 재현하려면 원본의 오선 간격과 단 간격이 필요하다
  const sysList = geo.systems;
  const gaps = [];
  for (let i = 0; i < sysList.length - 1; i += 1) {
    gaps.push(sysList[i + 1].staffTop - sysList[i].staffBottom);
  }
  gaps.sort((a, b) => a - b);
  // **가사 띠가 들어갈 만큼은 벌린다.** 단 간격을 원본 중앙값으로만 잡으면
  // 1·2절 두 줄짜리 단에서 아래 줄이 다음 단 코드 줄과 겹친다 — 실측
  // now0918-1: 띠가 6.5칸인데 중앙값 간격으로는 자리가 모자라 2절 가사가
  // 잘려 보였다. 가장 두꺼운 띠에 코드 줄 몫(약 2칸)을 더해 하한으로 둔다.
  let tallest = 0;
  for (const sys of sysList) {
    const b = sys.lyricBand;
    if (b && b.length === 2) tallest = Math.max(tallest, b[1] - b[0]);
  }
  // **가사 띠와 다음 단의 구간 표시 띠는 같은 간격 안에 들어간다.** 둘을
  // 따로 재면 간격이 모자라 「Verse 2」가 앞 단 가사 위에 겹친다(실측).
  let stack = 0;
  for (let i = 0; i < sysList.length - 1; i += 1) {
    const lb = sysList[i].lyricBand;
    const tb = sysList[i + 1].topBand;
    stack = Math.max(stack,
      (lb && lb.length === 2 ? lb[1] - lb[0] : 0)
      + (tb && tb.length === 2 ? tb[1] - tb[0] : 0));
  }
  const median = gaps.length ? gaps[Math.floor(gaps.length / 2)] : geo.spacing * 5;
  // **반복 괄호(1. 2.)는 다음 단 코드 줄 위에 한 줄 더 선다.** 그 자리를 안 잡으면
  // 여러 절 가사의 아래 줄을 덮는다(t031-3 단2: 4절 가사 위에 다음 단 괄호)
  const volta = measures.some((m) => m.voltaStart) ? geo.spacing * 2.5 : 0;
  // **단마다 실제로 필요한 간격**: 오선 아래 가사 끝까지(띠 높이만이 아니라 오선과의
  // 거리까지) + 다음 단 코드 줄 + 괄호 + 여유. 띠 높이만 재면 4절 가사가 다음 단 코드에
  // 닿았다(t031-3 — 절 띠를 넓힌 뒤 드러났다)
  const chordTop = {};
  for (const sd of (ex.systems || [])) {
    const ys = (sd.chords || []).filter((c) => !c.dropped && c.box).map((c) => c.box.y);
    if (ys.length) chordTop[sd.index] = Math.min(...ys);
  }
  let gapNeed = 0;
  for (let i = 0; i < sysList.length - 1; i += 1) {
    const lb = sysList[i].lyricBand;
    const below = lb && lb.length === 2 ? lb[1] - sysList[i].staffBottom : 0;
    const nt = sysList[i + 1];
    // 다음 단 위에 붙는 것 중 가장 높은 것 — 코드 줄, 원본에서 오려 붙이는 구간 표시
    // (반복 괄호·Verse 상자도 원본 픽셀이다 — t031-3 단3 '1.' '2.' 괄호)
    const tops = [chordTop[i + 1], ...((nt.topItems || []).map((it) => it[2]))]
      .filter((y) => Number.isFinite(y));
    const above = tops.length ? Math.max(0, nt.staffTop - Math.min(...tops)) : geo.spacing * 2;
    gapNeed = Math.max(gapNeed, below + above + volta + geo.spacing);
  }
  const src = {
    width: ex.imageSize.w, height: ex.imageSize.h,
    spacing: geo.spacing,
    gap: Math.max(median, tallest + geo.spacing * 2 + volta,
                   stack + geo.spacing * 1.5 + volta, gapNeed),
  };

  // **머리글을 원본에서 옮긴다.** 제목·부제·작곡자·저작권 표기는 물론이고
  // 콘티에는 **송폼**이 적혀 있다("Intro(8) - A1 - A'1 - B - …"). 찬양팀이
  // 그걸 보고 연주하므로 사라지면 악보를 못 쓴다. 다시 조판해 만들 수 없으니
  // 픽셀을 그대로 오려 붙인다 — 가사와 같은 이유다.
  // **출력 폭은 원본(확대본)을 따라간다.** 1650 으로 고정하면 원본이 클수록
  // 더 많이 줄어든다 — 가사·머리글은 원본 픽셀을 오려 붙이는 것이라 그만큼
  // 흐려진다(실측: 「지금 여기 우리」는 확대본 2400px 를 1650 으로 0.69배
  // 축소, 「내마음다해」는 1746px 를 0.95배 — 같은 설정인데 선명도가 갈렸다).
  // fx 가 1 에 가까울수록 오려 붙인 픽셀이 원본 그대로 남는다.
  // 위아래 한계는 캔버스 메모리(폭×약 2배 높이 RGBA)를 감당할 범위다.
  const PAGE_W = Math.min(2600, Math.max(1400, Math.round(src.width)));
  const fx = PAGE_W / src.width;

  // **구역 표시(A2·B·C) 자리를 먼저 잡아 페이지를 넓힌다.** Verovio는 오선을
  // 페이지 왼쪽 끝부터 그리고 `pageMarginLeft`가 듣지 않는다(실측: 0~300
  // 어느 값이든 오선 left 가 0). 페이지를 넓혀 본문을 오른쪽으로 밀면 가로
  // 배율은 그대로여서 가사 정렬을 다시 잡을 필요가 없다.
  const marks = Array.isArray(geo.marks) ? geo.marks : [];
  const markW = marks.length
    ? Math.round(Math.max(...marks.map((m) => m.w)) * fx)
      + Math.round(geo.spacing * fx * 0.6)
    : 0;

  let headCut = Math.max(0, Number(geo.headerCut) || 0);
  // 첫 단 코드보다 위에서 자른다 — 코드는 다시 그려진다
  const firstChordY = Math.min(...((ex.systems || [])
    .filter((sd) => sd.index === 0)
    .flatMap((sd) => (sd.chords || []).map((c) => c.box?.y ?? Infinity))),
    Infinity);
  if (Number.isFinite(firstChordY)) {
    headCut = Math.min(headCut, Math.round(firstChordY - geo.spacing * 0.8));
  }
  headCut = Math.max(0, headCut);
  const headH = headCut > 2 ? Math.round(headCut * fx) : 0;

  // 원본 마지막 단이 다른 단만큼 꽉 차 있으면 마지막 단도 편다
  const widths = sysList.map((s) => (s.right ?? 0) - (s.left ?? 0)).sort((a, b) => a - b);
  const lastW = sysList.length ? (sysList[sysList.length - 1].right ?? 0) - (sysList[sysList.length - 1].left ?? 0) : 0;
  const justifyLast = widths.length > 1 && lastW >= widths[Math.floor(widths.length / 2)] * 0.85;
  const { svg, pageW, pageH, pages } = await renderFitted(xml, src,
    { pageW: PAGE_W, reserveTop: headH, justifyLast });

  // SVG → 캔버스. 배경을 **명시적으로 흰색**으로 깔아야 한다 — 투명하게
  // 두면 저장·PDF에서 검게 나온다.
  // **가사가 들어갈 높이를 미리 재서 캔버스를 키운다.** 머리글을 넣으면
  // 본문이 짧아지고 원본 비율로 잡은 가사가 페이지를 벗어난다 — 조용히
  // 버리면 마지막 단 가사가 사라진다(실측: 165개 중 113개만 남았다).
  const lyr = lyricsOf(geo);
  const need = lyricBottom(svg, lyr, geo, pageW, 1.0, headH, src.width)
    + Math.round(geo.spacing * fx * 0.4);
  // **바닥 고지(저작권 표기)도 원본에서 옮긴다.** 머리글과 같은 이유다 —
  // "Copyright … All rights reserved." 는 다시 만들 수 없다. 캔버스를 그
  // 높이만큼 더 키우고 맨 아래에 붙인다.
  const footCut = Math.max(0, Number(geo.footerCut) || 0);
  const footSrcH = footCut > 0 ? Math.max(0, src.height - footCut) : 0;
  const footH = footSrcH > 2 ? Math.round(footSrcH * fx) : 0;
  const fullH = Math.max(Math.round(src.height * fx), headH + pageH, need)
    + footH;
  canvas.width = pageW + markW;
  canvas.height = fullH;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, canvas.width, fullH);
  ctx.save();
  ctx.translate(markW, headH);
  await drawSvg(ctx, svg, pageW, pageH);
  ctx.restore();

  // **마디 상자(캔버스 좌표).** 화면이 확인할 마디를 짚고, 눌러서 고칠 자리다.
  // 캔버스에 칠하지 않는다 — 저장되는 그림은 깨끗해야 한다.
  const kb = viewScale(svg, pageW);
  const byKey = new Map();
  measureBoxes(svg).forEach((b, i) => {
    const src = measures[i]?.src;
    if (!b || !src) return;
    const r = { x: markW + b.x * kb, y: headH + b.y * kb, w: b.w * kb, h: b.h * kb };
    const k = src.join(':');
    const o = byKey.get(k);
    byKey.set(k, o ? {
      src, x: Math.min(o.x, r.x), y: Math.min(o.y, r.y),
      w: Math.max(o.x + o.w, r.x + r.w) - Math.min(o.x, r.x),
      h: Math.max(o.y + o.h, r.y + r.h) - Math.min(o.y, r.y),
    } : { src, ...r });
  });
  const boxes = [...byKey.values()];
  if (headH > 0) {
    ctx.drawImage(origImage, 0, 0, src.width, headCut, markW, 0, pageW, headH);
  }

  // **워터마크를 지우고 붙인다.** 가사는 원본 픽셀을 오려 붙이는데, 악보에
  // 박힌 워터마크가 같이 따라와 글자 밑에 회색 덩어리로 남는다(실측
  // 「지금 여기 우리」). 워터마크는 밝기 229~247 의 연회색이고 가사 잉크는
  // 대부분 190 미만이라 갈린다 — 그 위쪽만 흰색으로 올린다.
  const clean = whitenLight(origImage, LYRIC_WHITE);
  maskRedrawn(clean, struct, geo, ex.systems || []);
  const nLyric = pasteLyrics(ctx, svg, clean, lyr, geo,
                             pageW, fullH - footH, 1.0, headH, markW,
                             geo.heads || null);
  if (footH > 0) {
    ctx.drawImage(origImage, 0, footCut, src.width, footSrcH,
                  markW, fullH - footH, pageW, footH);
  }

  // 구간 표시·마디 번호·손글씨를 오선 위에 되돌린다
  const nTop = pasteTopMarks(ctx, svg, clean, geo, pageW, headH, markW,
                             geo.heads || null);

  // 구역 표시를 오선 왼쪽에 붙인다
  const rows = staffRows(svg);
  const kk = viewScale(svg, pageW);
  let nMark = 0;
  for (const m of marks) {
    const R = rows[m.system];
    if (!R) continue;
    const pw = Math.max(1, Math.round(m.w * fx));
    const ph = Math.max(1, Math.round(m.h * fx));
    const cy = headH + Math.round((R.top + R.bottom) / 2 * kk);
    const px = Math.max(0, markW - pw - Math.round(geo.spacing * fx * 0.3));
    if (cy - ph / 2 < 0 || cy + ph / 2 > fullH) continue;
    ctx.globalCompositeOperation = 'darken';
    ctx.drawImage(origImage, m.x, m.y, m.w, m.h,
                  px, Math.round(cy - ph / 2), pw, ph);
    nMark += 1;
  }
  ctx.globalCompositeOperation = 'source-over';

  const notes = [];
  if (pages !== 1) {
    notes.push(`⚠️ ${pages}페이지로 나왔습니다 — 원본은 1페이지입니다`);
  }
  for (const mm of (report.mismatch || [])) {
    notes.push(`⚠️ 단${mm.system + 1}: 검출 ${mm.detected}개 vs `
      + `판독 ${mm.expected}개 — 그 단은 음높이가 밀렸을 수 있습니다`);
  }
  if (report.missingPitch) {
    notes.push(`⚠️ 음높이를 못 채운 음표 ${report.missingPitch}개 — `
      + '원본 확인이 필요합니다');
  }
  // **박자 검산.** 정답 악보가 없어도 이건 잡을 수 있다 — 4/4박이면
  // 마디마다 음가 합이 정확히 맞아야 한다.
  const cb = checkBeats(struct);
  const bad = cb.over.length + cb.under.length;
  if (bad) notes.push(beatNote(cb));
  // **지원하지 않는 표기가 있는 단을 먼저 알린다.** 화음과 × 머리는 리듬이
  // 틀린 마디를 만들어 위 박자 경고까지 오염시키므로, 원인을 먼저 밝혀야
  // 사용자가 엉뚱한 마디를 뒤지지 않는다.
  if (unresolved.length) {
    const head = unresolved.slice(0, 6).map(
      (i) => `${i.system + 1}단${i.measure != null ? ` ${i.measure}마디` : ''}`).join(' · ');
    notes.push(`⚠️ 원본 확인이 필요한 구간 ${unresolved.length}개 — ${head}`
      + (unresolved.length > 6 ? ` 외 ${unresolved.length - 6}개` : '')
      + '\n   저장과 크레딧 차감은 보류됩니다');
  }
  const un = struct.unreliable || {};
  if (un.stacked && un.stacked.length) {
    notes.push(`⚠️ 화음이 쌓인 ${un.stacked.map((i) => `단${i + 1}`).join(' · ')} — `
      + '동시에 울리는 음은 지원하지 않아 멜로디 한 줄로 폈습니다. '
      + '그 단의 리듬은 원본과 다를 수 있습니다');
  }
  if (un.slashOnly && un.slashOnly.length) {
    notes.push(`⚠️ 리듬 표기(× 머리) ${un.slashOnly.map((i) => `단${i + 1}`).join(' · ')} — `
      + '음높이 없이 리듬만 적은 부분은 읽지 못해 비어 있습니다');
  }
  notes.push(`${report.systems}단 · ${report.measures}마디 · `
    + `음표 ${report.notes}개 · 코드 ${report.chords}개 · 가사 ${nLyric}개`
    + (nMark ? ` · 구역 표시 ${nMark}개` : '')
    + (nTop ? ` · 구간 표시 ${nTop}개` : ''));

  return { notes, report, xml, beats: cb, unresolved, boxes, pages };
}

/**
 * 박자가 안 맞는 마디를 **어디인지** 적는다.
 *
 * 개수만 알려 주면("4개") 어느 마디를 봐야 할지 알 수 없어 악보 전체를
 * 다시 훑어야 한다. 검산은 이미 단·마디 번호를 갖고 있으므로 그대로 쓴다.
 * 단·마디 번호는 화면 다른 곳과 같이 **1부터** 센다.
 */
function beatNote(cb) {
  const items = [...cb.over.map((v) => [...v, '초과']),
                 ...cb.under.map((v) => [...v, '미달'])]
    .sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
  const SHOW = 8;
  const txt = items.slice(0, SHOW)
    .map(([sy, me, beats, kind]) =>
      `단${sy + 1} 마디${me}(${(+beats).toFixed(2).replace(/\.?0+$/, '')}박 ${kind})`)
    .join(' · ');
  const more = items.length > SHOW ? ` 외 ${items.length - SHOW}개` : '';
  return `⚠️ 박자가 안 맞는 마디 ${items.length}개 — 그 마디를 확인하세요\n`
    + `   ${txt}${more}`;
}


/** SVG 문자열을 캔버스에 그린다. */
function drawSvg(ctx, svg, w, h) {
  return new Promise((ok, no) => {
    const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      ctx.drawImage(img, 0, 0, w, h);
      URL.revokeObjectURL(url);
      ok();
    };
    img.onerror = () => { URL.revokeObjectURL(url); no(new Error('SVG 그리기 실패')); };
    img.src = url;
  });
}
