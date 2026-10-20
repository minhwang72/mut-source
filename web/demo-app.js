/* ── demo-app ──
 * 데모용 앱 로직. 판독 단계가 없고(미리 구운 DEMO 데이터를 쓴다) 나머지
 * 파이프라인은 실제 앱과 같은 코드를 그대로 쓴다.
 *
 * 다운로드는 Artifact 샌드박스에서 <a download>가 막히므로 `downloads`
 * 기능으로 뷰어에게 저장을 제안한다. 없으면 버튼을 감춘다.
 */

const $ = (id) => document.getElementById(id);
const SEMI = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5];

const state = { semitones: -3, showOriginal: false, image: null, downloads: null };

const FROM_KEY = DEMO.meta.key;

function chordList() {
  return DEMO.systems.flatMap((s) => s.chords.map((c) => ({ sys: s.index, chord: c })));
}

/** "#rrggbb" → [r,g,b] */
function rgbOf(css) {
  const m = /^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i.exec(css);
  if (m) return [+m[1], +m[2], +m[3]];
  const h = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(css);
  if (h) return [parseInt(h[1],16), parseInt(h[2],16), parseInt(h[3],16)];
  return [255, 255, 255];
}

/* ── 코드 오버레이 (app.js와 동일한 규칙) ── */

function paperColor(ctx, box, pad = 3) {
  const x = Math.max(0, box.x - pad);
  const y = Math.max(0, box.y - pad);
  const w = Math.min(ctx.canvas.width - x, box.w + pad * 2);
  const h = Math.min(ctx.canvas.height - y, box.h + pad * 2);
  if (w <= 0 || h <= 0) return "#ffffff";
  const { data } = ctx.getImageData(x, y, w, h);
  const lum = [];
  for (let i = 0; i < data.length; i += 4) lum.push(data[i] + data[i + 1] + data[i + 2]);
  lum.sort((a, b) => a - b);
  const cut = lum[Math.floor(lum.length * 0.75)] ?? 765;
  let r = 0, g = 0, b = 0, n = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] + data[i + 1] + data[i + 2] >= cut) {
      r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
    }
  }
  return n ? `rgb(${Math.round(r / n)},${Math.round(g / n)},${Math.round(b / n)})` : "#fff";
}

const fontOf = (px) => `700 ${px}px Arial, Helvetica, sans-serif`;

/** 단별 코드 상자 윗변 — 이동 창이 그 위(제목·작곡자)를 건드리지 않게 한다 */
function chordTops() {
  const src = (typeof DEMO !== "undefined" ? DEMO : state.extraction);
  const out = {};
  for (const s of src.systems) {
    const ys = s.chords.map((c) => c.box.y);
    if (ys.length) out[s.index] = Math.min(...ys) - 2;
  }
  return out;
}

function baseFontSize(ctx, chords) {
  // 크기는 **원본 글꼴 크기를 역산해서** 정한다. 상자 높이에 고정 계수를
  // 곱하면 안 된다 — 상자 높이는 잉크 높이인데 글꼴 크기는 em 크기라서,
  // 0.78을 곱하면 실제로 원본의 58% 크기로 그려진다(실측).
  const REF = 40;
  const inkH = (text, px) => {
    ctx.font = fontOf(px);
    const m = ctx.measureText(text);
    return (m.actualBoundingBoxAscent || 0) + (m.actualBoundingBoxDescent || 0);
  };
  const sizes = [];
  for (const c of chords) {
    const text = (c.text || "").trim();
    const h = c.box.h;
    if (!text || h <= 0) continue;
    const base = inkH(text, REF);
    if (base <= 0) continue;
    let est = REF * h / base;
    const px2 = Math.max(6, Math.round(est));
    const ink2 = inkH(text, px2);
    if (ink2 > 0) est = px2 * h / ink2;
    sizes.push(est);
  }
  if (!sizes.length) return 12;
  sizes.sort((a, b) => a - b);
  return Math.max(7, Math.round(sizes[Math.floor(sizes.length / 2)]));
}

/* ── 렌더 ── */

function render() {
  const plan = planBySemitones(FROM_KEY, state.semitones);
  const live = chordList();
  const mapped = transposeChords(live.map((f) => f.chord.text), plan);

  const cv = $("out");
  cv.width = DEMO.imageSize.w;
  cv.height = DEMO.imageSize.h;
  const ctx = cv.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(state.image, 0, 0);

  const geo = DEMO.geometry;
  let melodyShifted = false;
  let shiftReason = null;
  let ksDone = false;

  if (!state.showOriginal) {
    const shift = planShift(plan.interval.steps, geo.spacing, geo.staffEditOk);
    if (shift.shifted) {
      shiftNotes(ctx, geo, shift.dy, state.image, chordTops());
      melodyShifted = true;
    }
    shiftReason = shift.reason || null;

    const ks = replaceKeySignatures(
      ctx, geo, fifths(plan.fromKey), fifths(plan.toKey), state.image);
    ksDone = ks.done > 0 || fifths(plan.fromKey) === fifths(plan.toKey);

    // 다음 코드와 **최소 간격**을 남긴다. 2px만 두면 겹치진 않아도 붙어 보인다.
    const keep = Math.max(4, Math.round(geo.spacing * 0.6));
    const availFor = (f, box) => {
      const later = live
        .filter((o) => o.sys === f.sys && o.chord.box.x > box.x)
        .map((o) => o.chord.box.x);
      const limit = later.length ? Math.min(...later) : cv.width;
      return Math.max(8, limit - box.x - keep);
    };

    // **한 장의 코드는 모두 같은 크기다.** 안 들어가는 것만 줄이면 크기가
    // 들쭉날쭉해져 원본의 균일한 조판과 어긋난다(실측: 43개 중 15개만 줄어
    // 큰 글자와 작은 글자가 섞였다).
    let size = baseFontSize(ctx, live.map((f) => f.chord));
    live.forEach((f, i) => {
      const av = availFor(f, f.chord.box);
      let px = size;
      ctx.font = fontOf(px);
      while (px > 6 && ctx.measureText(mapped[i]).width > av) {
        px -= 1;
        ctx.font = fontOf(px);
      }
      size = Math.min(size, px);
    });
    live.forEach((f, i) => {
      const box = f.chord.box;
      const avail = availFor(f, box);

      // 옛 코드는 **원본 마스크를 이동량만큼 옮겨** 지운다 (app.js와 동일).
      // 사각형을 통째로 칠하면 오선 위 음표 머리를 같이 지운다.
      const paper = paperColor(ctx, box);
      if (shift.shifted) {
        eraseChordInk(ctx, state.image, box, shift.dy || 0,
          DEMO.geometry.inkThreshold, rgbOf(paper));
      } else {
        ctx.fillStyle = paper;
        ctx.fillRect(box.x - 1, box.y - 1, box.w + 2, box.h + 2);
      }

      let px = size;
      ctx.font = `700 ${px}px Arial, Helvetica, sans-serif`;
      while (px > 6 && ctx.measureText(mapped[i]).width > avail) {
        px -= 1;
        ctx.font = `700 ${px}px Arial, Helvetica, sans-serif`;
      }
      ctx.fillStyle = "#000";
      ctx.textBaseline = "alphabetic";
      ctx.fillText(mapped[i], box.x, box.y + box.h);
    });

    // 오선 복원은 코드 오버레이 **뒤**에, 두 이동 방식 모두 (app.js와 동일).
    // halfstep의 자체 복원은 코드보다 앞이라 여기서 다시 해야 한다
    // (실측: -5키에서 맨 위 줄 잉크가 1041 → 910으로 줄었다).
    if (shift.shifted) restoreStaffLines(ctx, geo, state.image);
  }

  $("key-badge").textContent = state.showOriginal
    ? `원본 · ${formatKey(plan.fromKey)}키`
    : `${formatKey(plan.toKey)}키`;
  $("t-orig").classList.toggle("on", state.showOriginal);
  $("t-new").classList.toggle("on", !state.showOriginal);

  // 상태 문구는 콘티를 쓰는 사람의 말로 쓴다. "온음계 1단은 정수배가 아닙니다"
  // 같은 내부 사정은 사용자가 알 필요가 없다 — 무엇이 바뀌었고 무엇을 쓰면
  // 되는지만 알려준다.
  const st = $("status");
  const toKey = formatKey(plan.toKey);
  if (state.showOriginal) {
    st.className = "alert info";
    st.textContent = `원본 ${formatKey(plan.fromKey)}키입니다.`;
  } else if (state.semitones === 0) {
    st.className = "alert info";
    st.textContent = `원키 ${toKey} 그대로입니다.`;
  } else if (melodyShifted) {
    st.className = "alert info";
    // 조표 교체는 오선 안에 글리프를 새로 그려야 해서 해상도 게이트가 걸린다.
    // 바뀌지 않았는데 "조표 모두"라고 쓰면 거짓말이 된다.
    // 조표는 자리가 없으면 건너뛴다(늘어날 폭이 없는 저해상도). 바뀌지
    // 않았는데 "조표 모두"라고 쓰면 거짓말이 된다.
    st.textContent = ksDone
      ? `악보 전체가 ${toKey}로 바뀌었습니다 — 코드·멜로디·조표 모두.`
      : `코드와 음표가 ${toKey}로 바뀌었습니다. 조표(맨 앞 ♯♭)는 원본 그대로이니 ` +
        `연주할 때 ${toKey}로 읽으세요.`;
  } else {
    st.className = "alert";
    st.textContent =
      `코드는 ${toKey}로 바뀌었습니다. 악보의 음표는 원키 그대로이니 ` +
      `왼쪽 코드 진행표를 쓰세요.` + (shiftReason ? ` (${shiftReason})` : "");
  }
}

/* ── UI ── */

function buildChips() {
  const box = $("chips");
  box.innerHTML = "";
  for (const n of SEMI) {
    let label;
    try { label = formatKey(planBySemitones(FROM_KEY, n).toKey); } catch { continue; }
    const b = document.createElement("button");
    b.className = "chip";
    b.dataset.semi = String(n);
    b.innerHTML = `${n === 0 ? "원키" : (n > 0 ? `+${n}` : n)}<small>${label}</small>`;
    b.addEventListener("click", () => select(n));
    box.appendChild(b);
  }
}

function select(n) {
  state.semitones = n;
  state.showOriginal = false;
  for (const c of $("chips").children) {
    c.classList.toggle("on", Number(c.dataset.semi) === n);
  }
  renderHeader();
  renderProgression();
  render();
}

/* 콘티의 한 줄: 원키 → 바꾼 키, 그리고 인도자가 쓰는 말("3키 내림") */
function renderHeader() {
  const plan = planBySemitones(FROM_KEY, state.semitones);
  $("k-from").textContent = `${formatKey(plan.fromKey)}키`;
  $("k-to").textContent = `${formatKey(plan.toKey)}키`;
  const n = state.semitones;
  $("k-delta").textContent =
    n === 0 ? "원키" : `${Math.abs(n)}키 ${n > 0 ? "올림" : "내림"}`;
}

/**
 * 코드 진행 표 — 콘티의 본문.
 *
 * 악보 이미지가 없어도 코드만으로 반주가 가능하므로, 단별로 한 줄씩
 * 마디 순서대로 보여준다. 인쇄물에서 손으로 옮겨 적는 그 형태다.
 */
function renderProgression() {
  const plan = planBySemitones(FROM_KEY, state.semitones);
  const box = $("prog");
  box.innerHTML = "";
  for (const sys of DEMO.systems) {
    const mapped = transposeChords(sys.chords.map((c) => c.text), plan);
    const row = document.createElement("div");
    row.className = "prog-row";
    const num = document.createElement("span");
    num.className = "prog-n";
    num.textContent = String(sys.index + 1);
    const bars = document.createElement("div");
    bars.className = "prog-bars";
    for (const t of mapped) {
      const b = document.createElement("span");
      b.className = "prog-bar";
      b.textContent = t;
      bars.appendChild(b);
    }
    row.append(num, bars);
    box.appendChild(row);
  }
}

/** 코드 진행을 텍스트로 — 카톡·메모로 팀에 그대로 붙일 수 있게 */
function progressionText() {
  const plan = planBySemitones(FROM_KEY, state.semitones);
  const head = `${DEMO.meta.title || "악보"} · ` +
    `${formatKey(plan.fromKey)} → ${formatKey(plan.toKey)}`;
  const lines = DEMO.systems.map((sys, i) => {
    const mapped = transposeChords(sys.chords.map((c) => c.text), plan);
    return `${i + 1}. ${mapped.join(" | ")}`;
  });
  return [head, ...lines].join("\n");
}

/* ── 내보내기 ── */

function pageCanvas(plan) {
  const src = $("out");
  const scale = src.width / 640;
  const pad = Math.round(10 * scale);
  const line = Math.round(13 * scale);
  const notice = [
    `${formatKey(plan.fromKey)}키 → ${formatKey(plan.toKey)}키 · 개인 연습용 · 재배포 금지`,
    DEMO.meta.note || "",
  ].filter(Boolean);

  const page = document.createElement("canvas");
  page.width = src.width;
  page.height = src.height + pad * 2 + line * notice.length;
  const ctx = page.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, page.width, page.height);
  ctx.drawImage(src, 0, 0);
  ctx.fillStyle = "#6b6b78";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const avail = page.width - pad * 2;
  const base = Math.max(7, Math.round(9.5 * scale));
  notice.forEach((t, i) => {
    let size = base;
    ctx.font = `${size}px Manrope, "Pretendard Variable", sans-serif`;
    while (size > 5 && ctx.measureText(t).width > avail) {
      size -= 1;
      ctx.font = `${size}px Manrope, "Pretendard Variable", sans-serif`;
    }
    ctx.fillText(t, page.width / 2, src.height + pad + i * line);
  });
  return page;
}

async function offer(blob, filename) {
  if (!state.downloads) return;
  const buf = new Uint8Array(await blob.arrayBuffer());
  await state.downloads.save({ filename, data: buf });
}

function wireExport() {
  $("dl-pdf").addEventListener("click", async () => {
    const btn = $("dl-pdf");
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "PDF 만드는 중…";
    try {
      const plan = planBySemitones(FROM_KEY, state.semitones);
      const page = await canvasToJpeg(pageCanvas(plan));
      await offer(buildPdf([page]), `mut_${formatKey(plan.toKey)}키.pdf`);
    } catch (err) {
      $("status").className = "alert";
      $("status").textContent = `PDF를 만들지 못했습니다: ${err.message}`;
    } finally {
      btn.disabled = false;
      btn.textContent = label;
    }
  });

  $("dl-png").addEventListener("click", async () => {
    const plan = planBySemitones(FROM_KEY, state.semitones);
    const blob = await new Promise((r) => pageCanvas(plan).toBlob(r, "image/png"));
    await offer(blob, `mut_${formatKey(plan.toKey)}키.png`);
  });
}

/* ── 시작 ── */

(async () => {
  // Artifact 런타임 밖(로컬 서버 등)에서는 claude 전역이 없다.
  // 기능 유무는 use()가 null로 알려주지만, 전역 자체가 없을 수 있으므로
  // 그것만 확인한다.
  state.downloads = typeof claude !== "undefined"
    ? await claude.use("downloads")
    : null;
  if (!state.downloads) {
    // 저장을 제안할 수 없으면 버튼을 감춘다 — 눌러도 아무 일 없는 버튼은 두지 않는다
    $("dl-pdf").hidden = true;
    $("dl-png").hidden = true;
  }

  state.image = await new Promise((ok, no) => {
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = () => no(new Error("샘플 악보를 열 수 없습니다."));
    img.src = DEMO.imageDataUri;
  });

  $("song-name").textContent = DEMO.meta.title || "악보";
  const bars = DEMO.systems.reduce((n, s) => n + s.chords.length, 0);
  $("song-sub").textContent =
    `${DEMO.systems.length}단 · 코드 ${bars}개 · ${DEMO.meta.timeSignature || "4/4"}`;
  $("demo-note").textContent =
    "데모 — 실제 앱에서는 본인 악보를 올리면 AI가 코드를 읽어 같은 방식으로 변환합니다. "
    + (DEMO.meta.note || "");

  $("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(progressionText());
      const b = $("copy");
      b.textContent = "복사됨";
      setTimeout(() => { b.textContent = "복사"; }, 1400);
    } catch {
      $("status").className = "alert";
      $("status").textContent = "복사할 수 없습니다. 코드를 직접 선택해 주세요.";
    }
  });
  $("t-orig").addEventListener("click", () => { state.showOriginal = true; render(); });
  $("t-new").addEventListener("click", () => { state.showOriginal = false; render(); });

  buildChips();
  wireExport();
  select(state.semitones);
})();
