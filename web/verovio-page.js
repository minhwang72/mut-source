// Verovio(WASM)로 **악보를 새로 그린다.** 픽셀을 옮기는 대신 다시 조판한다.
//
// 왜 바꿨나(실측): 픽셀 이동은 회색 띠·코드 잔상·음표 손상(115개 중 4~48개)이
// 계속 남았고, 임시표는 아예 못 고쳤다. 새로 그리면 그 문제군이 통째로
// 사라진다. 대신 원본과 **같은 배치**를 지켜야 한다 — 콘티는 한 장이어야 한다.
//
// 배치 보존의 핵심: `breaks:'encoded'` + 마디마다 `<print new-system="yes">`.
// 이게 없으면 Verovio가 9단을 6단으로 흘려버린다(실측).

let _tk = null;

/** Verovio 툴킷을 한 번만 만든다. WASM 7MB라 두 번 만들 이유가 없다. */
export async function toolkit() {
  if (_tk) return _tk;
  const { VerovioToolkit } = await import('./vendor/verovio.mjs');
  const createModule = (await import('./vendor/verovio-module.mjs')).default;
  _tk = new VerovioToolkit(await createModule());
  return _tk;
}

/** SVG 좌표 → 출력 픽셀 배율. Verovio viewBox 단위는 픽셀의 10배쯤이다. */
export function viewScale(svg, pageW) {
  const m = svg.match(/viewBox="\s*[\d.-]+\s+[\d.-]+\s+([\d.]+)/);
  return m ? pageW / parseFloat(m[1]) : 1;
}

/**
 * 조상들의 `translate(x, y)` 합. Verovio 는 본문을 `g.page-margin`
 * `translate(500, 500)` 안에 넣는다 — 이걸 빼먹으면 모든 좌표가 50px씩
 * 어긋난다(실측: 가사가 오선 위로 올라붙고, 오려 붙인 글자가 왼쪽으로
 * 밀렸다). 경로의 y 는 그 그룹 **안쪽** 좌표다.
 */
function originOf(el) {
  let tx = 0, ty = 0;
  for (let n = el; n && n.getAttribute; n = n.parentNode) {
    const t = n.getAttribute('transform');
    const m = t && /translate\(\s*(-?[\d.]+)(?:[\s,]+(-?[\d.]+))?/.exec(t);
    if (m) { tx += parseFloat(m[1]); ty += parseFloat(m[2] || 0); }
  }
  return { tx, ty };
}


/**
 * 단마다 (오선 위·아래, 음표 머리 최저점)을 뽑는다.
 *
 * 가사 자리는 **오선 아래끝이 아니라 음표 최저점** 기준으로 잡아야 한다.
 * 오선 아래로 내려간 음표가 있으면 오선 기준으로는 가사가 음표를 덮는다.
 */
export function staffRows(svgText) {
  const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');
  const rows = [];
  for (const sysEl of doc.querySelectorAll('g.system')) {
    const { ty } = originOf(sysEl);
    const ys = [], lows = [];
    for (const g of sysEl.querySelectorAll('g.staff, g.note')) {
      const isNote = g.classList.contains('note');
      for (const el of g.querySelectorAll('path')) {
        const d = el.getAttribute('d') || '';
        for (const mm of d.matchAll(/[ML]\s*(-?\d+)\s+(-?\d+)/g)) {
          const y = parseInt(mm[2], 10) + ty;
          ys.push(y);
          if (isNote) lows.push(y);
        }
      }
    }
    if (!ys.length) continue;
    // **오선 다섯 줄만의 위끝.** top/bottom 은 음표까지 포함하므로 기둥이
    // 길게 내려간 단에서는 오선보다 한참 넓다 — 그걸 한 칸으로 환산해
    // 오선 위 표기를 올리면 앞 단까지 날아간다(실측: 「Verse 1」이 단1이
    // 아니라 단0 위에 붙었다).
    const lineYs = [];
    for (const stEl of sysEl.querySelectorAll('g.staff')) {
      for (const el of stEl.querySelectorAll(':scope > path')) {
        const d = el.getAttribute('d') || '';
        for (const mm of d.matchAll(/[ML]\s*(-?\d+)\s+(-?\d+)/g)) {
          lineYs.push(parseInt(mm[2], 10) + ty);
        }
      }
    }
    rows.push({
      top: Math.min(...ys), bottom: Math.max(...ys),
      low: lows.length ? Math.max(...lows) : Math.max(...ys),
      staffTop: lineYs.length ? Math.min(...lineYs) : Math.min(...ys),
      staffBottom: lineYs.length ? Math.max(...lineYs) : Math.max(...ys),
    });
  }
  return rows;
}

/**
 * **원본의 비율을 그대로 재현한다.**
 *
 * 원본을 폭 pageW로 늘렸다고 보고 오선 간격과 단 간격을 맞춘다. Verovio의
 * `scale`은 오선 간격에 비례하므로 한 번 그려 재고 한 번 더 그린다
 * (실측: scale 38에서 26.3px이 나왔는데 원본 비율로는 18.4px이어야 했다 —
 * 43% 크게 그려져 가사가 다음 단 코드와 겹쳤다).
 */
export async function renderFitted(xml, src, opts = {}) {
  const pageW = opts.pageW ?? 1650;
  const font = opts.font ?? 'Leipzig';
  const BASE = 38;
  const tk = await toolkit();
  // 머리글 자리를 빼고 그린다. Verovio의 pageMarginTop 은 breaks="encoded"
  // 에서 무시된다(실측: 0~400 어느 값이든 첫 단 top 이 36px 고정).
  const reserve = Math.max(0, opts.reserveTop ?? 0);
  const pageH = Math.max(200,
    Math.round(src.height * (pageW / src.width)) - reserve);
  const f = pageW / src.width;

  const draw = (scale, sysSpace, h) => {
    const o = {
      pageWidth: pageW, pageHeight: h ?? pageH, scale, font,
      breaks: 'encoded', adjustPageHeight: false, svgBoundingBoxes: true,
      header: 'none', footer: 'none',
      // **마디 번호를 찍지 않는다.** 원본 콘티 악보에는 없다.
      mnumInterval: 0,
    };
    if (sysSpace != null) o.spacingSystem = sysSpace;
    tk.setOptions(o);
    if (!tk.loadData(xml)) throw new Error('Verovio가 MusicXML을 못 읽었습니다');
    return tk.renderToSVG(1);
  };

  let svg = draw(BASE, null);
  let outH = pageH;
  const rows0 = staffRows(svg);
  if (rows0.length) {
    const k = viewScale(svg, pageW);
    // **오선 줄만으로 잰다.** top/bottom 은 기둥·덧줄까지 포함하므로 첫 단에
    // 오선 밖 음표가 있으면 한 칸이 부풀어 악보 전체가 작게 그려진다.
    const got = (rows0[0].staffBottom - rows0[0].staffTop) * k / 4;
    const wantSp = src.spacing * f;
    const wantGap = src.gap * f;
    const scale = got > 0 ? BASE * wantSp / got : BASE;
    let sysSpace = Math.max(3, Math.min(24, wantGap / wantSp));
    svg = draw(scale, sysSpace);

    // **단 간격도 재고 한 번 더 그린다.** `spacingSystem` 이 그대로 px 로
    // 나오지 않는다 — 230 을 요청해 207 이 나왔고, 그 23px 때문에 앞 단
    // 가사와 다음 단 구간 표시(「Verse 2」)가 겹쳤다. 배율을 잡을 때와
    // 같은 방법으로 **재서 고친다** — 가장 좁은 간격을 기준으로 한다.
    const r1 = staffRows(svg);
    if (r1.length > 1) {
      const k1 = viewScale(svg, pageW);
      let gotGap = Infinity;
      for (let i = 0; i < r1.length - 1; i += 1) {
        gotGap = Math.min(gotGap, (r1[i + 1].staffTop - r1[i].staffBottom) * k1);
      }
      if (gotGap > 0 && Number.isFinite(gotGap)
          && Math.abs(gotGap - wantGap) > wantSp * 0.25) {
        sysSpace = Math.max(3, Math.min(24, sysSpace * wantGap / gotGap));
        svg = draw(scale, sysSpace);
      }
    }

    // **내용이 페이지보다 길면 페이지를 늘린다.**
    // `breaks:'encoded'`는 지시받은 단을 모두 한 페이지에 그린다 — 페이지가
    // 짧아도 2페이지로 나누지 않고 아래로 넘긴다. 그 높이만큼만 그리면
    // 아래 단이 **조용히 잘린다**(직접 겪었다: 10단 악보에서 마지막 3단의
    // 오선이 사라지고 가사만 떴다).
    const rows = staffRows(svg);
    if (rows.length) {
      const kk = viewScale(svg, pageW);
      const bottom = Math.max(...rows.map((r) => r.bottom)) * kk + wantSp * 4;
      if (bottom > outH) {
        outH = Math.round(bottom);
        svg = draw(scale, sysSpace, outH);
      }
    }
  }
  return { svg, pageW, pageH: outH, pages: tk.getPageCount(), gap: src.gap };
}

/**
 * 그린 페이지에 **원본 가사 픽셀**을 옮겨 붙인다.
 *
 * 가사는 LLM에 묻지 않는다 — 한글 가사를 그럴듯하게 지어낸다
 * (실측: "주 이름 찬양" → "즐거운 찬란한"). 원본 조각을 그대로 쓴다.
 *
 * canvas: 이미 SVG가 그려진 2D 컨텍스트
 * orig: 원본 이미지가 그려진 캔버스(또는 ImageBitmap을 그린 것)
 * lyrics: [{system, band:[y0,y1], syllables:[[x0,x1], ...]}]
 */
/**
 * 가사가 차지할 **마지막 y**를 미리 잰다.
 *
 * 왜 필요한가: 머리글을 넣으면 본문이 짧아지고, 원본 비율로 잡은 가사 위치가
 * 페이지 아래를 벗어난다. 그때 조용히 버리면 마지막 단 가사가 사라진다
 * (실측: 위싱 콘티에서 165개 중 113개만 남았다). 캔버스를 그만큼 키운다.
 */
export function lyricBottom(svgText, lyrics, geo, pageW, drop = 1.0,
                            headH = 0, origW = 0) {
  const rows = staffRows(svgText);
  const k = viewScale(svgText, pageW);
  const fx = origW ? pageW / origW : 1;
  let bot = 0;
  for (const L of lyrics) {
    const R = rows[L.system];
    const sys = geo.systems[L.system];
    if (!R || !sys) continue;
    // **오선 줄만으로 잰다.** R.top/R.bottom 은 기둥·덧줄까지 품으므로
    // 한 칸이 부풀고, 그만큼 가사가 원본보다 아래로 밀려 다음 단의
    // 구간 표시(「Verse 2」)와 겹쳤다(실측).
    const rsp = (R.staffBottom - R.staffTop) * k / 4;
    const off = (L.band[0] - sys.staffBottom) / sys.spacing;
    let y = headH + Math.round(R.staffBottom * k + rsp * off);
    y = Math.max(y, headH + Math.round(R.low * k + rsp * drop));
    bot = Math.max(bot, y + Math.round((L.band[1] - L.band[0]) * fx));
  }
  return bot;
}

/**
 * 단별 **출력 음표 x** (SVG 좌표, 정렬). 없으면 빈 배열.
 *
 * 왜 필요한가(실측): 가사를 원본 x 를 비율 변환한 자리에 붙였더니 음표와
 * 어긋났다. Verovio 는 음가에 따라 간격을 자기 기준으로 다시 잡기 때문이다 —
 * 마커스에서 단4~7 이 통째로 중앙 0.7~1.7칸(최대 6.4칸) 밀렸고, 음표 머리
 * 폭이 1.2칸이니 **한 칸 옆 음표 자리**로 간 셈이다.
 */
export function noteCols(svgText) {
  const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');
  const out = [];
  for (const sys of doc.querySelectorAll('g.system')) {
    // `system bounding-box` 도 같이 걸린다 — 그러면 빈 단이 끼어 단 수가
    // 두 배가 되고 짝이 어긋나 재정렬이 통째로 취소된다(실측: 18단으로 셌다).
    if (sys.classList.contains('bounding-box')) continue;
    const { tx } = originOf(sys);
    const xs = [];
    for (const g of sys.querySelectorAll('g.note')) {
      if (g.classList.contains('bounding-box')) continue;
      const bb = g.querySelector(':scope > g.bounding-box > rect');
      if (!bb) continue;
      xs.push(Number(bb.getAttribute('x')) + tx
        + Number(bb.getAttribute('width') || 0) / 2);
    }
    if (xs.length) out.push(xs.sort((a, b) => a - b));
  }
  return out;
}


/**
 * 음절을 **그 음절이 붙은 음표가 출력에서 간 자리**로 옮기는 양(페이지 px).
 *
 * 원본 음표와 출력 음표를 순서대로 짝지어 밀린 양을 재고, 음절마다 가장
 * 가까운 원본 음표의 밀림을 쓴다. 개수가 다르면 **손대지 않는다** — 짝이
 * 어긋난 채로 옮기면 더 나빠진다.
 */
export function noteShift(srcX, outX, k, fx) {
  if (!srcX || !outX || srcX.length < 2 || srcX.length !== outX.length) {
    return null;
  }
  return srcX.map((sx, i) => outX[i] * k - sx * fx);
}


/** 단별 **원본 음표 x** — geo.heads 를 단에 나눠 담는다. */
function srcNoteCols(geo, heads) {
  if (!heads || !geo.systems) return [];
  return geo.systems.map((sys) => {
    const half = (sys.staffBottom - sys.staffTop) * 1.4;
    const mid = (sys.staffTop + sys.staffBottom) / 2;
    return heads
      .filter((h) => Math.abs(h.y + h.h / 2 - mid) < half)
      .map((h) => h.x + h.w / 2)
      .sort((a, b) => a - b);
  });
}

/**
 * **오선 위 띠를 원본에서 오려 붙인다** — 구간 표시("Verse 1"·"Chorus 1"
 * 상자), 마디 번호, 손글씨("X2").
 *
 * 왜 다시 만들지 않나: 이 표기는 구조 데이터에 없고(검출 클래스도 없다),
 * LLM에 물으면 지어낸다. 찬양팀은 구간 표시를 보고 콘티를 따라가므로
 * 사라지면 악보를 못 쓴다 — 머리글·가사와 같은 판단이다.
 *
 * 코드 기호는 서버가 띠에서 이미 지웠다(다시 그려지므로).
 */
export function pasteTopMarks(ctx, svgText, orig, geo, pageW, headH = 0,
                              offX = 0, heads = null) {
  const rows = staffRows(svgText);
  const k = viewScale(svgText, pageW);
  const fx = pageW / orig.width;
  const outCols = noteCols(svgText);
  const srcCols = srcNoteCols(geo, heads);
  let n = 0, dropped = 0;
  (geo.systems || []).forEach((sys, si) => {
    const band = sys.topBand;
    const items = sys.topItems || [];
    const R = rows[si];
    if (!band || !R || !items.length) return;
    const sx = srcCols[si];
    const shift = noteShift(sx, outCols[si], k, fx);
    for (const [x0, x1, iy0, iy1] of items) {
      // **원본이 오선 위 몇 px 에 뒀는지 재서 페이지 배율로 옮긴다.**
      // 칸 수로 환산하지 않는다 — renderFitted 가 원본 비율을 그대로
      // 재현하므로 fx 하나로 자리와 크기가 같이 맞고, 글자 비율도 안 깨진다.
      const y = headH
        + Math.round(R.staffTop * k - (sys.staffTop - iy0) * fx);
      const h = Math.max(1, Math.round((iy1 - iy0) * fx));
      if (y < headH) { dropped += 1; continue; }
      const w = Math.max(1, Math.round((x1 - x0) * fx));
      // 표시가 붙은 자리의 음표가 출력에서 간 만큼 같이 옮긴다
      let dx = 0;
      if (shift) {
        const cx = (x0 + x1) / 2;
        let j = 0, best = Infinity;
        for (let t = 0; t < sx.length; t += 1) {
          const d = Math.abs(sx[t] - cx);
          if (d < best) { best = d; j = t; }
        }
        dx = Math.round(shift[j]);
      }
      const px = Math.max(0, Math.min(pageW - w, Math.round(x0 * fx) + dx));
      ctx.globalCompositeOperation = 'darken';
      ctx.drawImage(orig, x0, iy0, x1 - x0, iy1 - iy0, offX + px, y, w, h);
      n += 1;
    }
  });
  ctx.globalCompositeOperation = 'source-over';
  if (dropped) {
    console.warn(`구간 표시 ${dropped}개가 자리를 못 찾아 빠졌습니다`);
  }
  return n;
}


export function pasteLyrics(ctx, svgText, orig, lyrics, geo, pageW, pageH,
                            drop = 1.0, headH = 0, offX = 0, heads = null) {
  const rows = staffRows(svgText);
  const k = viewScale(svgText, pageW);
  const fx = pageW / orig.width;
  const cols = noteCols(svgText);
  const srcCols = srcNoteCols(geo, heads);
  let n = 0, dropped = 0, shifted = 0;
  for (const L of lyrics) {
    const R = rows[L.system];
    const sys = geo.systems[L.system];
    if (!R || !sys) continue;
    // **오선 줄만으로 잰다.** R.top/R.bottom 은 기둥·덧줄까지 품으므로
    // 한 칸이 부풀고, 그만큼 가사가 원본보다 아래로 밀려 다음 단의
    // 구간 표시(「Verse 2」)와 겹쳤다(실측).
    const rsp = (R.staffBottom - R.staffTop) * k / 4;
    // **원본이 가사를 오선 아래 몇 칸에 뒀는지 재서 그대로 쓴다.**
    // 상수로 두면 조판마다 어긋난다 — 원본이 정답을 갖고 있다.
    const off = (L.band[0] - sys.staffBottom) / sys.spacing;
    let y = headH + Math.round(R.staffBottom * k + rsp * off);
    y = Math.max(y, headH + Math.round(R.low * k + rsp * drop));
    const bh = L.band[1] - L.band[0];
    const sx = srcCols[L.system];
    const shift = noteShift(sx, cols[L.system], k, fx);
    for (const [x0, x1] of L.syllables) {
      const w = Math.max(1, Math.round((x1 - x0) * fx));
      const h = Math.max(1, Math.round(bh * fx));
      if (y + h > pageH) { dropped += 1; continue; }
      // 어두운 쪽만 남긴다 — 흰 배경이 오선을 덮지 않도록
      ctx.globalCompositeOperation = 'darken';
      // **음절을 그 음표가 간 자리로 옮긴다.**
      let dx = 0;
      if (shift) {
        const cx = (x0 + x1) / 2;
        let j = 0, best = Infinity;
        for (let t = 0; t < sx.length; t += 1) {
          const d = Math.abs(sx[t] - cx);
          if (d < best) { best = d; j = t; }
        }
        dx = Math.round(shift[j]);
        if (dx) shifted += 1;
      }
      const px = Math.max(0, Math.min(pageW - w, Math.round(x0 * fx) + dx));
      ctx.drawImage(orig, x0, L.band[0], x1 - x0, bh,
                    offX + px, y, w, h);
      n += 1;
    }
  }
  ctx.globalCompositeOperation = 'source-over';
  if (dropped) {
    console.warn(`가사 ${dropped}개가 페이지를 벗어나 빠졌습니다`);
  }
  if (shifted) {
    console.info(`가사 ${shifted}개를 출력 음표 자리로 옮겼습니다`);
  }
  return n;
}
