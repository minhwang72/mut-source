/**
 * 악보 픽셀 합성 — 파이썬 tools/sheetcv.py + keysig.py 의 캔버스 포팅.
 *
 * 저작권 설계상 **변환된 악보는 반드시 브라우저에서 만들어져야** 한다.
 * 서버는 좌표와 임계값(구조 데이터)만 주고, 픽셀을 옮기는 일은 여기서 한다.
 *
 * 영상처리를 JS로 다시 구현하지는 않았다. 오선 위치·잉크 임계값·조표 영역은
 * 서버가 이미 계산해 보내주므로, 여기서는 그 좌표대로 픽셀을 옮기고 지우고
 * 다시 그리기만 한다.
 *
 * 성능 원칙: 화소마다 getImageData/putImageData 를 부르면 안 된다. 호출마다
 * GPU 동기화가 걸려 수만 번 반복하면 사실상 끝나지 않는다(실측으로 확인).
 * 캔버스를 **한 번 읽어** 타입 배열에서 전부 처리하고 **한 번 쓴다.**
 */

/* ─────────────────────── 픽셀 버퍼 ─────────────────────── */

/** 캔버스와 원본을 각각 한 번만 읽어 버퍼로 들고 작업하는 헬퍼 */
class Sheet {
  constructor(ctx, original) {
    const { width: w, height: h } = ctx.canvas;
    this.ctx = ctx;
    this.w = w;
    this.h = h;
    this.img = ctx.getImageData(0, 0, w, h);
    this.buf = this.img.data;

    // 원본 화소 — 오선을 되돌릴 때 쓴다
    const oc = document.createElement("canvas");
    oc.width = w;
    oc.height = h;
    oc.getContext("2d").drawImage(original, 0, 0, w, h);
    this.orig = oc.getContext("2d").getImageData(0, 0, w, h).data;
  }

  /** 잉크 비트맵을 현재 버퍼에서 만든다 */
  inkMask(threshold) {
    const ink = new Uint8Array(this.w * this.h);
    const b = this.buf;
    for (let p = 0, i = 0; p < ink.length; p++, i += 4) {
      const g = 0.299 * b[i] + 0.587 * b[i + 1] + 0.114 * b[i + 2];
      ink[p] = g <= threshold ? 1 : 0;
    }
    return ink;
  }

  copyRow(srcY, dstY, x0, x1) {
    const s = (srcY * this.w + x0) * 4;
    const d = (dstY * this.w + x0) * 4;
    this.buf.copyWithin(d, s, s + (x1 - x0) * 4);
  }

  /** 원본에서 한 행 구간을 되살린다 */
  restoreRow(y, x0, x1) {
    const o = (y * this.w + x0) * 4;
    this.buf.set(this.orig.subarray(o, o + (x1 - x0) * 4), o);
  }

  setPixel(x, y, srcIdx) {
    const d = (y * this.w + x) * 4;
    this.buf[d] = this.buf[srcIdx];
    this.buf[d + 1] = this.buf[srcIdx + 1];
    this.buf[d + 2] = this.buf[srcIdx + 2];
    this.buf[d + 3] = 255;
  }

  flush() {
    this.ctx.putImageData(this.img, 0, 0);
  }
}

/* ─────────────────────── 멜로디 평행이동 ─────────────────────── */

/**
 * 이동량이 오선 간격의 정수배인지 — 온음계 짝수 단(3·5·7도)에서만 성립한다.
 * 홀수 단은 옮겨진 오선이 칸 가운데 내려앉아 쓸 수 없다.
 */
export function planShift(steps, spacing, staffEditOk) {
  if (!Number.isFinite(steps) || !Number.isFinite(spacing) || spacing <= 0) {
    return { mode: null, dy: 0, shifted: false, reason: "기하 정보가 없습니다." };
  }
  const dy = Math.round(-steps * (spacing / 2));
  if (dy === 0) {
    return { mode: null, dy, shifted: false,
      reason: "음표 위치는 그대로이고 임시표만 달라집니다" };
  }
  // 짝수 단(3·5·7도)과 홀수 단(2·4·6도)을 **같은 방법으로** 처리한다:
  // 오선 줄을 세로 런 길이로 지우고 dy만큼 옮긴 뒤 원본 오선을 되돌린다.
  // 오선을 통째로 제거하지 않으므로 해상도 게이트가 필요 없다
  // (파이썬 sheetcv.shift_notes_raster 주석 참고).
  return { mode: "resample", dy, shifted: true };
}

/** 예전 이름 — 호출부 호환용 */
export function canShiftRaster(steps, spacing) {
  const p = planShift(steps, spacing, false);
  return { ok: p.mode === "raster", dy: p.dy, lines: p.lines, reason: p.reason };
}

/* ── 오선 줄 지우기 ──────────────────────────────────────────────────
 * 판별자는 **그 열의 세로 런 길이**다. 순수한 오선은 줄 두께만큼만 이어지고,
 * 음표 머리·기둥·빔이 지나가는 열은 그보다 두껍다.
 * (파이썬 sheetcv.inpaint_staff_rows 와 같은 규칙 — 그쪽 주석에 실패한
 *  시도들의 실측치가 정리돼 있다.)
 */

/** 줄 범위를 회색조로 잰다 — 잉크 문턱 아래의 회색 헤일로까지 (JPEG 잔상) */
function expandLineSpansGray(sh, sys, margin = 6) {
  const x0 = Math.max(0, sys.left);
  const x1 = Math.min(sys.right + 1, sh.w);
  const spans = sys.lineSpans.map(([a, b]) => [a, b, b - a + 1]);
  if (x1 <= x0) return spans;
  const n = x1 - x0;
  const LIMIT = 1;   // 헤일로는 대개 1px. 넓게 잡으면 음표가 얇아진다

  // 행 평균이 아니라 **60분위수**. 평균은 음표가 있는 행도 끌어내려서
  // 오선 5줄이 한 덩어리로 확장된다(실측).
  // **필요한 행만** 계산한다 — 이미지 전체를 정렬하면 브라우저가 몇 초씩
  // 멈춘다(실측: 도구 호출이 30초 타임아웃).
  const cache = new Map();
  const tmp = new Float32Array(n);
  const pct = (y) => {
    if (y < 0 || y >= sh.h) return 255;
    let v = cache.get(y);
    if (v !== undefined) return v;
    for (let x = 0; x < n; x++) {
      const i = (y * sh.w + x0 + x) * 4;
      tmp[x] = 0.299 * sh.buf[i] + 0.587 * sh.buf[i + 1] + 0.114 * sh.buf[i + 2];
    }
    const sorted = Array.from(tmp).sort((p2, q) => p2 - q);
    v = sorted[Math.floor(n * 0.6)];
    cache.set(y, v);
    return v;
  };

  // 종이색 기준: 칸 가운데 행들 (줄 사이 중간점)에서 가장 밝은 쪽
  const mids = [];
  for (let i = 0; i + 1 < spans.length; i++) {
    mids.push(Math.round((spans[i][1] + spans[i + 1][0]) / 2));
  }
  const sampled = mids.map(pct).sort((a, b) => a - b);
  const paper = sampled.length ? sampled[sampled.length - 1] : 255;

  return spans.map(([a, b, core]) => {
    let a2 = a, b2 = b;
    while (a2 - 1 >= 0 && a - a2 < LIMIT && pct(a2 - 1) < paper - margin) a2--;
    while (b2 + 1 < sh.h && b2 - b < LIMIT && pct(b2 + 1) < paper - margin) b2++;
    return [a2, b2, core];
  });
}

/**
 * 음표를 dy만큼 세로 이동한다. 짝수 단·홀수 단 모두 이 한 경로를 쓴다.
 *
 * 순서: ① 오선 줄 지우기(세로 런 길이) ② 마디선·쉼표를 소스에서 제외
 *       ③ dy만큼 균일 이동 ④ 오선·고정객체·가사는 호출자가 원본에서 되돌린다
 *
 * 균일 정수 이동을 쓰는 이유: 구간별로 보간하면 오선 간격 편차만큼 행이
 * 복제·생략되어 빔이 두꺼워지고 머리가 뭉개진다(실측). 오선은 지웠다가
 * 원본에서 되돌리므로 맞출 대상이 없다.
 */
export function shiftNotes(ctx, geometry, dy, original, chordTops) {
  const { spacing } = geometry;
  const sh = new Sheet(ctx, original);
  let done = 0;

  for (const sys of geometry.systems) {
    const x0 = Math.min(sys.headEnd, sh.w - 1);
    const x1 = Math.min(sys.right + 1, sh.w);
    if (x1 - x0 <= 0) continue;

    // 창 상단은 **그 단의 코드 상자 바로 위**까지다. 오선에서 6칸을 그냥
    // 올라가면 첫 단에서 제목·작곡자 줄까지 창에 들어와 함께 밀린다
    // (실측: 'Russell Frager'가 3px 밀려 뭉개졌다).
    const defTop = sys.staffTop - Math.round(spacing * 6.0);
    const ct = chordTops ? chordTops[sys.index] : undefined;
    const top = Math.max(0, ct === undefined ? defTop : Math.max(ct, defTop));
    const bot = Math.min(sh.h, sys.staffBottom + Math.round(spacing * 4.0));
    if (bot - top <= Math.abs(dy)) continue;

    const wide = expandLineSpansGray(sh, sys);
    const W = x1 - x0;

    // 작업 범위는 **창과 그 소스 행만** 잡는다. 이미지 전체를 단마다 훑으면
    // 브라우저가 몇 초씩 멈춘다(실측: 도구 호출이 30초 타임아웃).
    const r0 = Math.max(0, Math.min(top, top - dy) - 2);
    const r1 = Math.min(sh.h, Math.max(bot, bot - dy) + 2);
    const RH = r1 - r0;
    if (RH <= 0) continue;

    const src = new Uint8ClampedArray(RH * W * 4);
    for (let y = 0; y < RH; y++) {
      const s0 = ((r0 + y) * sh.w + x0) * 4;
      src.set(sh.buf.subarray(s0, s0 + W * 4), y * W * 4);
    }
    const lum = new Float32Array(RH * W);
    for (let p = 0; p < RH * W; p++) {
      const i = p * 4;
      lum[p] = 0.299 * src[i] + 0.587 * src[i + 1] + 0.114 * src[i + 2];
    }

    // 세로 런 길이 (위로 이어진 수 + 아래로 이어진 수 - 1)
    const run = new Int32Array(RH * W);
    const col = new Int32Array(W);
    for (let y = 0; y < RH; y++) {
      for (let x = 0; x < W; x++) {
        const p = y * W + x;
        col[x] = lum[p] < 128 ? col[x] + 1 : 0;
        run[p] = col[x];
      }
    }
    col.fill(0);
    for (let y = RH - 1; y >= 0; y--) {
      for (let x = 0; x < W; x++) {
        const p = y * W + x;
        col[x] = lum[p] < 128 ? col[x] + 1 : 0;
        run[p] += col[x] - 1;
      }
    }

    // ① 오선 줄 지우기 — 두꺼운 잉크만 남기고 나머지는 위·아래 중 밝은 쪽으로
    for (const [a, b, core] of wide) {
      const tol = core + 1;
      const ai = Math.max(0, a - 1 - r0);
      const bi = Math.min(RH - 1, b + 1 - r0);
      for (let y = a - r0; y <= b - r0; y++) {
        if (y < 0 || y >= RH) continue;
        for (let x = 0; x < W; x++) {
          const p = y * W + x;
          if (lum[p] < 128 && run[p] > tol) continue;   // 음표 — 남긴다
          const i = p * 4;
          const ia = (ai * W + x) * 4;
          const ib = (bi * W + x) * 4;
          for (let c = 0; c < 3; c++) {
            src[i + c] = Math.max(src[ia + c], src[ib + c]);
          }
          src[i + 3] = 255;
        }
      }
    }

    // ② 마디선·쉼표는 이동 대상에서 뺀다. 함께 옮기면 밀려간 복사본이
    //    유령으로 남고, 그것을 지우려 복원 범위를 넓히면 그 자리에 온 음표를
    //    덮는다(실측).
    for (const o of sys.fixed || []) {
      const fy0 = Math.max(0, o.y - 1 - r0);
      const fy1 = Math.min(RH, o.y + o.h + 1 - r0);
      const fx0 = Math.max(0, o.x - 1 - x0);
      const fx1 = Math.min(W, o.x + o.w + 1 - x0);
      for (let y = fy0; y < fy1; y++) {
        for (let x = fx0; x < fx1; x++) {
          const i = (y * W + x) * 4;
          src[i] = 255; src[i + 1] = 255; src[i + 2] = 255; src[i + 3] = 255;
        }
      }
    }

    // ③ dy만큼 옮겨 찍는다 (창 밖은 종이색)
    for (let y = top; y < bot; y++) {
      const sy = y - dy - r0;
      const d0 = (y * sh.w + x0) * 4;
      if (sy < 0 || sy >= RH) {
        sh.buf.fill(255, d0, d0 + W * 4);
      } else {
        sh.buf.set(src.subarray(sy * W * 4, sy * W * 4 + W * 4), d0);
      }
    }
    done++;
  }

  sh.flush();
  return { staves: done, fixed: 0 };
}


export function restoreStaffLines(ctx, geometry, original, protect) {
  const sh = new Sheet(ctx, original);

  // 순서는 파이썬 렌더러와 같다: 가사 → 마디선·쉼표 → 오선.
  // 모두 **코드 오버레이 뒤에** 해야 한다 — 코드를 지우면 오선 맨 위 줄과
  // 마디선 윗부분이 뚫린다(실측: 잉크 118px 소실, 마디선 일치율 75~86%).
  // 가사 띠를 되돌린다. **음표 자리는 비켜간다** — 가사 띠는 오선 바로
  // 아래부터 잡히므로, 아래로 이조하면 덧줄 음표가 그 안으로 내려온다.
  // 통째로 덮으면 그 음표가 지워진다(실측: 머리 115개 중 36개가 잉크 절반
  // 이하, 비켜가면 4개). protect 는 이동 후 좌표의 상자 목록이다.
  const guards = protect || [];
  for (const sys of geometry.systems) {
    if (!sys.lyricBand) continue;
    const [a, b] = sys.lyricBand;
    for (let y = Math.max(0, a); y < Math.min(sh.h, b); y++) {
      // 이 행을 가로지르는 보호 상자들을 x순으로 모아 그 사이만 되돌린다
      const spans = [];
      for (const g of guards) {
        if (y >= g.y && y < g.y + g.h) {
          spans.push([Math.max(0, g.x), Math.min(sh.w, g.x + g.w)]);
        }
      }
      if (!spans.length) { sh.restoreRow(y, 0, sh.w); continue; }
      spans.sort((p, q) => p[0] - q[0]);
      let x = 0;
      for (const [gx0, gx1] of spans) {
        if (gx0 > x) sh.restoreRow(y, x, gx0);
        x = Math.max(x, gx1);
      }
      if (x < sh.w) sh.restoreRow(y, x, sh.w);
    }
  }

  for (const sys of geometry.systems) {
    for (const o of sys.fixed || []) {
      const y0 = Math.max(0, o.y - 1);
      const y1 = Math.min(sh.h, o.y + o.h + 1);
      const x0 = Math.max(0, o.x - 1);
      const x1 = Math.min(sh.w, o.x + o.w + 1);
      if (x1 <= x0) continue;
      for (let y = y0; y < y1; y++) sh.restoreRow(y, x0, x1);
    }
  }

  for (const sys of geometry.systems) {
    // 오선 전체 폭 — headEnd 왼쪽에 찍힌 코드가 뚫은 구멍까지 메운다
    const x0 = Math.max(0, sys.left);
    const x1 = Math.min(sys.right + 1, sh.w);
    if (x1 - x0 <= 0) continue;
    for (const [a, b] of sys.lineSpans) {
      for (let y = a; y <= b; y++) {
        // **덮어쓰지 않고 더 어두운 쪽을 택한다.** 원본으로 덮으면 그 줄
        // 자리로 옮겨온 음표 머리의 가운데가 얇은 선으로 바뀌어 잘린다
        // (실측: 오선 7px에서 머리 잉크 21~74%).
        for (let x = x0; x < x1; x++) {
          const i = (y * sh.w + x) * 4;
          for (let c = 0; c < 3; c++) {
            if (sh.orig[i + c] < sh.buf[i + c]) sh.buf[i + c] = sh.orig[i + c];
          }
        }
      }
    }
  }

  sh.flush();
}




/* ─────────────────────── 조표 교체 ─────────────────────── */

/* 높은음자리표 기준, 5선(맨 위)을 0으로 한 반칸 단위 위치 */
const SHARP_STEPS = [0, 3, -1, 2, 5, 1, 4]; // F# C# G# D# A# E# B#
const FLAT_STEPS = [4, 1, 5, 2, 6, 3, 7];   // Bb Eb Ab Db Gb Cb Fb

/**
 * 조표를 교체한다.
 *
 * 조표는 오선 안에 있으므로 지운 자리에 오선을 다시 그려야 한다.
 * ♭♯ 글리프는 유니코드로 그린다 — Times·Arial에는 ♭가 없어 두부 박스가
 * 나오므로 폰트 스택을 명시한다(실측).
 */
/** 그 행의 대표 색(중앙값)으로 오선을 다시 칠한다 — 파이썬 repaint_staff_lines */
function repaintStaffLines(ctx, sys, x0, x1, original) {
  const O = origData(original);
  const w = x1 - x0;
  if (w <= 0) return;
  const sx0 = Math.max(0, sys.left);
  const sx1 = Math.min(O.w, sys.right + 1);
  if (sx1 <= sx0) return;
  for (const [a, b] of sys.lineSpans) {
    for (let y = Math.max(0, a - 1); y <= Math.min(O.h - 1, b + 1); y++) {
      // 오선은 가로로 균일하므로 그 행 전체의 중앙값이 곧 선의 색이다.
      // 원본 화소를 그대로 되돌리면 그 자리에 있던 옛 임시표 조각이 함께
      // 돌아와 선이 점선처럼 끊긴다(실측).
      const ch = [0, 1, 2].map((c) => {
        const v = [];
        for (let x = sx0; x < sx1; x++) v.push(O.data[(y * O.w + x) * 4 + c]);
        v.sort((p2, q) => p2 - q);
        return v[Math.floor(v.length / 2)];
      });
      ctx.fillStyle = `rgb(${ch[0]},${ch[1]},${ch[2]})`;
      ctx.fillRect(x0, y, w, 1);
    }
  }
}

/**
 * 조표를 새 키로 교체한다. 계산은 파이썬 keysig.replace 와 같다:
 *   ① 쓸 수 있는 폭 = 조표 시작 ~ 다음 요소 (최소 0.6칸 띄움)
 *   ② 모자라면 박자표를 오른쪽으로 민다 (박자표일 때만)
 *   ③ 그래도 모자라면 글리프를 줄인다 (최소 8px까지)
 *   ④ 그래도 안 되면 **악보 전체를 건드리지 않는다** — 일부 단만 바뀐
 *      악보는 안 바뀐 악보보다 헷갈린다.
 */
export function replaceKeySignatures(ctx, geometry, fifthsFrom, fifthsTo, original) {
  if (!geometry.staffEditOk) {
    return { done: 0, reason: "해상도가 낮아 조표를 건드리지 않았습니다" };
  }
  if (fifthsFrom === fifthsTo) return { done: 0, reason: null };

  const { spacing } = geometry;
  const glyph = fifthsTo > 0 ? "♯" : "♭";
  const steps = (fifthsTo > 0 ? SHARP_STEPS : FLAT_STEPS).slice(0, Math.abs(fifthsTo));
  const slots = Math.max(Math.abs(fifthsFrom), Math.abs(fifthsTo));
  const basePx = Math.max(8, Math.round(spacing * 2.6));
  const fontOf = (px) =>
    `${px}px "Arial Unicode MS", "Apple Symbols", "Noto Music", sans-serif`;
  ctx.font = fontOf(basePx);
  const baseAdvance = Math.max(3, Math.round(ctx.measureText(glyph).width * 0.95));
  const minScale = Math.min(1, 8 / Math.max(1, spacing * 2.2));

  // **옛 조표 자리를 못 찾으면 새 조표를 그리지 않는다.** 예전에는 기본
  // 위치(오선 왼쪽 + 4.5칸)에 그냥 그렸는데, 그러면 옛 조표는 남고 새 조표가
  // 그 오른쪽에 겹쳐 찍혀 ♯1개짜리 악보가 ♯3개처럼 보였다(실측).
  // 서버는 여러 단이 동의할 때만 keysigRegion 을 채워 준다.
  if (fifthsFrom !== 0 &&
      geometry.systems.some((sys) => !sys.keysigRegion)) {
    return { done: 0, reason: "조표 자리를 찾지 못해 건드리지 않았습니다" };
  }

  // 단별 계획을 먼저 세운다 (전 단이 가능할 때만 실행)
  const plans = [];
  for (const sys of geometry.systems) {
    const r = sys.keysigRegion;
    const startX = r ? r.x : Math.round(sys.left + spacing * 4.5);
    const blk = sys.nextBlock;
    let advance = baseAdvance;
    let scale = 1;
    let move = 0;
    let avail = blk ? blk.x0 - Math.round(spacing * 0.6) - (startX - 2) : null;

    if (blk && avail !== null && slots * advance + 4 > avail && blk.pushable) {
      const room = Math.max(0, blk.next - Math.round(spacing * 0.6) - blk.x1);
      move = Math.min(slots * advance + 4 - avail, room);
      avail += move;
    }
    if (avail !== null && slots * advance + 4 > avail) {
      scale = Math.max(minScale, (avail - 4) / (slots * advance));
      advance = Math.max(3, Math.floor(advance * scale));
    }
    if (avail !== null && slots * advance + 4 > avail) {
      return { done: 0, reason: "조표가 늘어날 자리가 없습니다" };
    }
    plans.push({ sys, startX, blk, advance, scale, move, avail, r });
  }

  let done = 0;
  for (const p of plans) {
    const { sys, startX, blk, advance, scale, move, avail, r } = p;

    // 박자표 밀기
    if (move > 0 && blk) {
      const top = Math.max(0, sys.staffTop - Math.round(spacing * 2));
      const bot = Math.min(ctx.canvas.height, sys.staffBottom + Math.round(spacing * 2));
      const w = blk.x1 - blk.x0 + 1;
      const crop = ctx.getImageData(blk.x0, top, w, bot - top);
      const sample = ctx.getImageData(Math.max(0, startX - 3),
        Math.max(0, top - 2), 1, 1).data;
      ctx.fillStyle = `rgb(${sample[0]},${sample[1]},${sample[2]})`;
      ctx.fillRect(blk.x0, top, w + move, bot - top);
      repaintStaffLines(ctx, sys, blk.x0, blk.x1 + move + 1, original);
      ctx.putImageData(crop, blk.x0 + move, top);
    }

    let eraseW = Math.max(r ? r.w : 0, slots * advance) + 4;
    if (avail !== null) eraseW = Math.min(eraseW, Math.max(0, avail));
    const eraseTop = Math.max(0, sys.staffTop - Math.round(spacing * 1.6));
    const eraseBot = Math.min(ctx.canvas.height,
      sys.staffBottom + Math.round(spacing * 1.2));

    const sample = ctx.getImageData(
      Math.max(0, startX - 3), Math.max(0, eraseTop - 2), 1, 1).data;
    ctx.fillStyle = `rgb(${sample[0]},${sample[1]},${sample[2]})`;
    ctx.fillRect(startX - 2, eraseTop, eraseW, eraseBot - eraseTop);
    repaintStaffLines(ctx, sys, startX - 2, startX - 2 + eraseW, original);

    ctx.font = fontOf(Math.max(6, Math.round(basePx * scale)));
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#000";
    // y는 아래로 갈수록 커지므로 **맨 위 오선은 lineSpans[0]** 이다.
    const topLine = sys.lineSpans[0][0];
    let x = startX;
    for (const st of steps) {
      ctx.fillText(glyph, x, topLine + st * (spacing / 2));
      x += advance;
    }
    done++;
  }
  return { done, reason: null };
}

// ── 코드 잉크만 지우기 ────────────────────────────────────────────────
// 마스크는 **원본의 코드 상자**에서 뽑아 dy만큼 옮겨 지운다. 이동한 캔버스에서
// 덩어리를 찾아 지우려 하면, 위로 이조할 때 음표가 코드 글자에 닿아 한 덩어리가
// 되고 그 덩어리째 지워져 음표가 사라진다(실측: +2·+4키에서 음표 머리 잉크가
// 22~45%로 떨어졌다). 원본 상자 안의 잉크는 검출기가 보장한 대로 코드 글자뿐이다.
let _origCache = null;
function origData(original) {
  if (_origCache && _origCache.src === original) return _origCache;
  const oc = document.createElement("canvas");
  oc.width = original.naturalWidth || original.width;
  oc.height = original.naturalHeight || original.height;
  oc.getContext("2d").drawImage(original, 0, 0);
  _origCache = {
    src: original,
    w: oc.width,
    h: oc.height,
    data: oc.getContext("2d").getImageData(0, 0, oc.width, oc.height).data,
  };
  return _origCache;
}

export function eraseChordInk(ctx, original, box, dy, inkThreshold, paper) {
  const O = origData(original);
  const bx0 = Math.max(0, box.x - 1);
  const bx1 = Math.min(O.w, box.x + box.w + 1);
  const by0 = Math.max(0, box.y - 1);
  const by1 = Math.min(O.h, box.y + box.h + 1);
  if (bx1 <= bx0 || by1 <= by0) return;

  // 문턱은 **그 상자의 종이색 기준**으로 잡는다. Otsu 고정값으로 자르면
  // 글자의 회색 테두리가 남아 잔상이 되고(F²→D2), 215 고정으로 올리면
  // 종이색이 200 근처인 스캔 악보에서 상자 전체가 마스크가 되어 이동한
  // 자리의 음표 머리까지 지운다. 파이썬 erase_chord_ink 와 같은 규칙이다.
  const samp = [];
  for (let y = by0; y < by1; y++) {
    for (let x = bx0; x < bx1; x++) {
      const i = (y * O.w + x) * 4;
      samp.push(0.299 * O.data[i] + 0.587 * O.data[i + 1]
                + 0.114 * O.data[i + 2]);
    }
  }
  samp.sort((a, b) => a - b);
  const inkLv = samp.length ? samp[Math.floor(samp.length * 0.10)] : 30;
  const paperLv = samp.length ? samp[Math.floor(samp.length * 0.90)] : 240;
  const cut = Math.max(100, Math.min(inkLv + (paperLv - inkLv) * 0.72,
                                     paperLv - 12));

  const ty0 = by0 + dy;
  const bw = bx1 - bx0;
  const lo = Math.max(0, -ty0);
  const hi = (by1 - by0) - Math.max(0, ty0 + (by1 - by0) - O.h);
  if (hi <= lo) return;

  const dst = ctx.getImageData(bx0, ty0 + lo, bw, hi - lo);
  const d = dst.data;
  for (let r = lo; r < hi; r += 1) {
    for (let c = 0; c < bw; c += 1) {
      // 1화소 팽창 — 상자 경계의 안티에일리어싱 1px이 남지 않게 한다
      // (실측: 위로 이조할 때 코드 줄 위에 짧은 줄이 남았다).
      let hit = false;
      for (let ny = -1; ny <= 1 && !hit; ny += 1) {
        for (let nx = -1; nx <= 1 && !hit; nx += 1) {
          const yy = by0 + r + ny, xx = bx0 + c + nx;
          if (yy < 0 || yy >= O.h || xx < 0 || xx >= O.w) continue;
          const sp = (yy * O.w + xx) * 4;
          const g = (O.data[sp] * 299 + O.data[sp + 1] * 587
                     + O.data[sp + 2] * 114) / 1000;
          if (g <= cut) hit = true;
        }
      }
      if (!hit) continue;
      const q = ((r - lo) * bw + c) * 4;
      d[q] = paper[0];
      d[q + 1] = paper[1];
      d[q + 2] = paper[2];
      d[q + 3] = 255;
    }
  }
  ctx.putImageData(dst, bx0, ty0 + lo);
}
