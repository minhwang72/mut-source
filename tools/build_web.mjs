/**
 * src/*.ts → web/engine/*.js 브라우저용 ESM 빌드.
 *
 * 번들러를 쓰지 않는다. Node에 내장된 타입 스트리퍼로 타입만 지우고
 * import 경로의 `.ts`를 `.js`로 바꾸면 브라우저가 그대로 로드하는
 * 표준 ES 모듈이 된다. 의존성 0이 유지된다.
 *
 * 저작권 설계상 이조·렌더는 브라우저에서 돌아야 하므로, 이 빌드가
 * 서버 없이 동작하는 것 자체가 요건이다.
 *
 *   node tools/build_web.mjs
 */

import { readdirSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { stripTypeScriptTypes } from "node:module";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = join(repo, "src");
const outDir = join(repo, "web", "engine");

// CLI는 Node 전용(process·stdin)이므로 브라우저 번들에서 제외한다
const EXCLUDE = new Set(["cli.ts"]);

mkdirSync(outDir, { recursive: true });

const files = readdirSync(srcDir).filter(
  (f) => f.endsWith(".ts") && !EXCLUDE.has(f),
);

let total = 0;
for (const f of files) {
  const source = readFileSync(join(srcDir, f), "utf8");
  let js = stripTypeScriptTypes(source, { mode: "strip" });

  // import/export 경로의 확장자를 브라우저가 이해하는 .js로
  js = js.replace(/(from\s*["'])(\.[^"']*?)\.ts(["'])/g, "$1$2.js$3");

  const out = f.replace(/\.ts$/, ".js");
  writeFileSync(join(outDir, out), js);
  total += js.length;
  console.log(`  ${f} → web/engine/${out}  (${js.length}B)`);
}

// 브라우저에서 하나만 import 하면 되도록 진입점을 만든다
const barrel = files
  .map((f) => `export * from "./${f.replace(/\.ts$/, ".js")}";`)
  .join("\n");
writeFileSync(join(outDir, "index.js"), `${barrel}\n`);

console.log(`\n${files.length}개 모듈 · ${(total / 1024).toFixed(1)}KB → web/engine/`);
