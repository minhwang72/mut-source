// **아바타는 사진 > 이름 두 글자 > 8분음표 순으로 보인다.**
// 두 가지로 깨졌던 적이 있어 그 둘을 소스에서 지킨다 — 화면 테스트 없이
// 잡을 수 있는 종류다.
import assert from 'node:assert';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const app = readFileSync(new URL('./app.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('./style.css', import.meta.url), 'utf8');

test('아바타 칸에 textContent 를 쓰지 않는다', () => {
  // 안에 든 <img id="acct-photo"> 를 통째로 지운다 — 큰 아바타는
  // 사진이 영영 안 떴고 늘 이름 두 글자만 보였다.
  assert.ok(!/\$\(["']acct-avatar["']\)\.textContent/.test(app),
    'acct-avatar 에 textContent 를 쓰면 사진 요소가 지워진다');
  assert.ok(!/\$\(["']who["']\)\.textContent/.test(app),
    'who 에 textContent 를 쓰면 사진 요소가 지워진다');
});

test('사진은 아바타 칸을 꽉 채운다', () => {
  // 바깥의 place-items:center 가 물려 내려오면 세로로 긴 사진이 제 비율대로
  // 서서 원 밖으로 삐져나온다(실측: 카카오 프로필 360×640 이 28px 원에서
  // 26×46px 로 그려졌다).
  const rule = css.match(/\.avatar img \{[^}]*\}/s);
  assert.ok(rule, '.avatar img 규칙이 없다');
  assert.match(rule[0], /place-self:\s*stretch/, '칸을 꽉 채우게 해야 한다');
  assert.match(rule[0], /object-fit:\s*cover/, '비율은 자르기로 맞춘다');
  assert.match(css, /\.avatar \{[^}]*overflow:\s*hidden/s,
    '마지막 방어선으로 칸이 넘치는 것을 잘라야 한다');
});

test('프로필 사진 주소는 https 로 올린다', () => {
  // 카카오·네이버 CDN 이 http 를 준다 — https 페이지에서 혼합 콘텐츠로 막힌다
  assert.match(app, /startsWith\(["']http:\/\/["']\)/,
    'paintAvatar 가 http 주소를 올려야 한다');
});
