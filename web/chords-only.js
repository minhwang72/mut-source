/**
 * **코드만 바꾸기.** 원본 이미지 위에서 코드 글자만 새 키로 바꿔 쓴다.
 *
 * 음표·조표·가사는 원본 픽셀 그대로라 음표 판독 오류가 결과에 나올 수 없다.
 * 규칙은 데모(demo-app.js)의 "옮기지 않는" 경로와 같다: 옛 코드 상자를 종이색으로
 * 덮고, 한 장의 코드는 모두 같은 크기로(원본 글꼴 크기를 역산) 쓴다.
 */

const fontOf = (px) => `700 ${px}px Arial, Helvetica, sans-serif`;

/** 상자 둘레의 밝은 픽셀 평균 — 누런 스캔에 흰 상자가 뜨지 않게 */
function paperColor(ctx, box, pad = 3) {
  const x = Math.max(0, Math.round(box.x - pad));
  const y = Math.max(0, Math.round(box.y - pad));
  const w = Math.min(ctx.canvas.width - x, Math.round(box.w + pad * 2));
  const h = Math.min(ctx.canvas.height - y, Math.round(box.h + pad * 2));
  if (w <= 0 || h <= 0) return '#fff';
  const { data } = ctx.getImageData(x, y, w, h);
  const lum = [];
  for (let i = 0; i < data.length; i += 4) lum.push(data[i] + data[i + 1] + data[i + 2]);
  lum.sort((a, b) => a - b);
  const cut = lum[Math.floor(lum.length * 0.75)] ?? 765;
  let r = 0, g = 0, b = 0, n = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] + data[i + 1] + data[i + 2] >= cut) { r += data[i]; g += data[i + 1]; b += data[i + 2]; n++; }
  }
  return n ? `rgb(${Math.round(r / n)},${Math.round(g / n)},${Math.round(b / n)})` : '#fff';
}

/** 원본 글꼴 크기 역산 — 상자 높이는 잉크 높이라 em 크기와 다르다(데모 주석) */
function baseFontSize(ctx, chords) {
  const REF = 40;
  const inkH = (text, px) => {
    ctx.font = fontOf(px);
    const m = ctx.measureText(text);
    return (m.actualBoundingBoxAscent || 0) + (m.actualBoundingBoxDescent || 0);
  };
  const sizes = [];
  for (const c of chords) {
    const text = (c.text || '').trim();
    if (!text || c.box.h <= 0) continue;
    const base = inkH(text, REF);
    if (base <= 0) continue;
    let est = REF * c.box.h / base;
    const px2 = Math.max(6, Math.round(est));
    const ink2 = inkH(text, px2);
    if (ink2 > 0) est = px2 * c.box.h / ink2;
    sizes.push(est);
  }
  if (!sizes.length) return 12;
  sizes.sort((a, b) => a - b);
  return Math.max(7, Math.round(sizes[Math.floor(sizes.length / 2)]));
}

/**
 * @param items  [{ sys, chord }] — 지운(dropped) 코드는 빼고 넘긴다
 * @param mapped items 와 같은 순서의 새 키 코드 글자
 * @param mark   true 면 아직 확인 안 한 의심 코드를 노랗게 칠한다(저장은 그때 막혀 있다)
 */
export function drawChordsOnly(cv, image, items, mapped, spacing, mark) {
  cv.width = image.naturalWidth;
  cv.height = image.naturalHeight;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(image, 0, 0);
  const keep = Math.max(4, Math.round((spacing || 10) * 0.6));
  const avail = (f) => {
    const later = items.filter((o) => o.sys === f.sys && o.chord.box.x > f.chord.box.x)
      .map((o) => o.chord.box.x);
    return Math.max(8, (later.length ? Math.min(...later) : cv.width) - f.chord.box.x - keep);
  };
  // 종이색은 지우기 전에 다 재 둔다 — 지운 뒤에 재면 옆 상자의 색이 섞인다
  const papers = items.map((f) => paperColor(ctx, f.chord.box));
  // **한 장의 코드는 모두 같은 크기** — 안 들어가는 것 때문에 줄이면 전부 같이 줄인다
  let size = baseFontSize(ctx, items.map((f) => f.chord));
  items.forEach((f, i) => {
    let px = size;
    ctx.font = fontOf(px);
    while (px > 6 && ctx.measureText(mapped[i]).width > avail(f)) ctx.font = fontOf(--px);
    size = Math.min(size, px);
  });
  items.forEach((f, i) => {
    const b = f.chord.box;
    ctx.fillStyle = papers[i];
    ctx.fillRect(b.x - 1, b.y - 1, b.w + 2, b.h + 2);
    ctx.font = fontOf(size);
    if (mark && f.chord.doubt && !f.chord.checked) {
      ctx.fillStyle = 'rgba(255, 196, 0, 0.38)';
      const p = Math.round(b.h * 0.35);
      ctx.fillRect(b.x - p, b.y - p, Math.max(b.w, ctx.measureText(mapped[i]).width) + p * 2, b.h + p * 2);
    }
    ctx.fillStyle = '#000';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(mapped[i], b.x, b.y + b.h);
  });
}

/** 캔버스 좌표의 점이 닿은 코드 — 상자를 조금 넓혀 손가락으로도 눌리게 */
export function chordAt(items, x, y) {
  let best = null, bestD = Infinity;
  for (const f of items) {
    const b = f.chord.box, p = Math.max(6, b.h * 0.6);
    if (x < b.x - p || x > b.x + b.w + p * 2 || y < b.y - p || y > b.y + b.h + p) continue;
    const d = Math.abs(x - (b.x + b.w / 2)) + Math.abs(y - (b.y + b.h / 2));
    if (d < bestD) { best = f; bestD = d; }
  }
  return best;
}
