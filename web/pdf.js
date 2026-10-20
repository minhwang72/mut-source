/**
 * 최소 PDF 라이터 — 의존성 0.
 *
 * 저작권 설계상 결과물은 브라우저에서 만들어져야 하므로 서버 렌더링이나
 * 외부 PDF 서비스를 쓸 수 없다. 라이브러리도 필요 없다: 이미지 한 장을
 * 페이지에 앉히는 PDF는 객체 5개면 끝난다.
 *
 * 이미지는 JPEG를 그대로 넣는다(`/DCTDecode`). PDF가 baseline JPEG를 그대로
 * 받아주므로 재압축·색공간 변환이 필요 없고, 원본이 이미 JPEG 사진인 경우가
 * 많아 크기도 작다. 무손실 Flate로 넣으면 3024×4032 사진이 18MB가 된다.
 *
 * 페이지는 A4(72dpi 기준 595.28×841.89pt)에 비율을 지켜 맞춘다.
 * "입력 N장 = 출력 N장"을 지키기 위해 여러 장을 받을 수 있게 만들었다.
 */

const A4 = { w: 595.28, h: 841.89 };
const MARGIN = 18; // pt (약 6mm)

const enc = new TextEncoder();

/** PDF 문법은 전부 ASCII다. 바이너리(JPEG)와 섞어 쓰므로 바이트로 다룬다. */
function bytes(str) {
  return enc.encode(str);
}

/**
 * 이미지들을 각각 한 페이지에 담은 PDF를 만든다.
 * @param {Array<{jpeg: Uint8Array, w: number, h: number}>} pages
 * @returns {Blob}
 */
export function buildPdf(pages) {
  if (!pages.length) throw new Error("페이지가 없습니다.");

  const chunks = [];
  const offsets = []; // 객체 번호 → 바이트 오프셋
  let length = 0;

  const push = (data) => {
    const b = data instanceof Uint8Array ? data : bytes(data);
    chunks.push(b);
    length += b.length;
  };
  const startObj = (num) => {
    offsets[num] = length;
    push(`${num} 0 obj\n`);
  };
  const endObj = () => push("endobj\n");

  push("%PDF-1.4\n");
  // 바이너리 스트림이 들어 있음을 알리는 관례적 주석
  push(new Uint8Array([0x25, 0xe2, 0xe3, 0xcf, 0xd3, 0x0a]));

  // 객체 번호 배치: 1 = 카탈로그, 2 = Pages,
  // 페이지 i 마다 (page, image, content) 3개
  const pageObj = (i) => 3 + i * 3;
  const imgObj = (i) => 4 + i * 3;
  const contentObj = (i) => 5 + i * 3;
  const total = 2 + pages.length * 3;

  startObj(1);
  push("<< /Type /Catalog /Pages 2 0 R >>\n");
  endObj();

  startObj(2);
  const kids = pages.map((_, i) => `${pageObj(i)} 0 R`).join(" ");
  push(`<< /Type /Pages /Kids [${kids}] /Count ${pages.length} >>\n`);
  endObj();

  pages.forEach((p, i) => {
    // 비율을 지켜 A4 안쪽에 맞춘다
    const maxW = A4.w - MARGIN * 2;
    const maxH = A4.h - MARGIN * 2;
    const scale = Math.min(maxW / p.w, maxH / p.h);
    const dw = p.w * scale;
    const dh = p.h * scale;
    const dx = (A4.w - dw) / 2;
    const dy = (A4.h - dh) / 2;

    startObj(pageObj(i));
    push(
      `<< /Type /Page /Parent 2 0 R ` +
        `/MediaBox [0 0 ${A4.w.toFixed(2)} ${A4.h.toFixed(2)}] ` +
        `/Resources << /XObject << /Im0 ${imgObj(i)} 0 R >> >> ` +
        `/Contents ${contentObj(i)} 0 R >>\n`,
    );
    endObj();

    startObj(imgObj(i));
    push(
      `<< /Type /XObject /Subtype /Image /Width ${p.w} /Height ${p.h} ` +
        `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode ` +
        `/Length ${p.jpeg.length} >>\nstream\n`,
    );
    push(p.jpeg);
    push("\nendstream\n");
    endObj();

    const draw =
      `q\n${dw.toFixed(2)} 0 0 ${dh.toFixed(2)} ${dx.toFixed(2)} ${dy.toFixed(2)} cm\n` +
      `/Im0 Do\nQ\n`;
    startObj(contentObj(i));
    push(`<< /Length ${draw.length} >>\nstream\n${draw}endstream\n`);
    endObj();
  });

  const xrefAt = length;
  push(`xref\n0 ${total + 1}\n`);
  push("0000000000 65535 f \n");
  for (let n = 1; n <= total; n++) {
    push(`${String(offsets[n]).padStart(10, "0")} 00000 n \n`);
  }
  push(`trailer\n<< /Size ${total + 1} /Root 1 0 R >>\nstartxref\n${xrefAt}\n%%EOF\n`);

  return new Blob(chunks, { type: "application/pdf" });
}

/** 캔버스를 JPEG 바이트로 — PDF에 그대로 넣는다 */
export async function canvasToJpeg(canvas, quality = 0.95) {
  const blob = await new Promise((res) =>
    canvas.toBlob(res, "image/jpeg", quality));
  if (!blob) throw new Error("이미지를 만들 수 없습니다.");
  return {
    jpeg: new Uint8Array(await blob.arrayBuffer()),
    w: canvas.width,
    h: canvas.height,
  };
}
