/**
 * 데모 HTML 번들러 — 전부 한 파일에 인라인한다.
 *
 * Artifact는 외부 호스트 요청이 CSP로 차단되므로 CSS·JS·이미지를 모두
 * 인라인해야 한다. 번들러는 쓰지 않는다: ESM 모듈들의 import/export만
 * 벗겨 한 스코프에 이어 붙이면 된다(전부 서로 다른 이름을 쓴다).
 *
 *   node tools/bundle_demo.mjs <demo-data.json> <출력.html>
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const [dataPath, outPath] = process.argv.slice(2);
if (!dataPath || !outPath) {
  throw new Error("사용법: node tools/bundle_demo.mjs <demo-data.json> <출력.html>");
}

/** import 줄과 export 키워드를 벗겨 한 스코프에 이어 붙일 수 있게 만든다 */
function strip(src) {
  return src
    .replace(/^import[\s\S]*?from\s*["'][^"']+["'];?\s*$/gm, "")
    .replace(/^export\s+\{[^}]*\}\s*from\s*["'][^"']+["'];?\s*$/gm, "")
    .replace(/^export\s+/gm, "");
}

const read = (p) => readFileSync(join(repo, p), "utf8");

// 의존성 순서대로 — pitch → key → chord → transpose
const engine = ["pitch", "key", "chord", "transpose"]
  .map((m) => `/* ── engine/${m} ── */\n${strip(read(`web/engine/${m}.js`))}`)
  .join("\n");

const render = `/* ── sheet-render ── */\n${strip(read("web/sheet-render.js"))}`;
const pdf = `/* ── pdf ── */\n${strip(read("web/pdf.js"))}`;
const css = read("web/style.css");
const data = readFileSync(resolve(dataPath), "utf8");
const app = read("web/demo-app.js");

// Artifact는 <!doctype>/<html>/<head>/<body> 스켈레톤을 발행 시점에 감싸주므로
// 그 태그를 직접 쓰면 안 된다. 대신 title·link·style을 그대로 앞에 두고
// 콘텐츠를 .demo 래퍼로 감싼다(body 클래스를 쓸 수 없으므로).
const artifact = process.argv.includes("--artifact");

const head = `<title>뮤트</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&family=Noto+Serif+KR:wght@700&display=swap" rel="stylesheet">
<style>
${css}
</style>`;

const body = `<div class="demo">
${read("web/demo-body.html")}
</div>
<script type="module">
const DEMO = ${data};
${engine}
${render}
${pdf}
${app}
</script>`;

const html = artifact
  ? `${head}\n${body}\n`
  : `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
${head}
</head>
<body>
${body}
</body>
</html>
`;

writeFileSync(resolve(outPath), html);
const kb = Math.round(Buffer.byteLength(html) / 1024);
console.log(`→ ${outPath} (${kb}KB)`);
