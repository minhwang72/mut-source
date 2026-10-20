// **정책이 한 번 바뀌었다.** 전에는 못 푼 항목이 있으면 assertResolved 가
// 던져서 화면이 통째로 막혔다. 지금은 **그려서 보여주고 표시만** 하고,
// 저장·차감만 qualityGate(=report.unresolved 를 받아 needs_review)가 막는다.
// 그래서 이 파일은 "던지는가"가 아니라 **"사유가 report 에 남는가"**를 본다.
// 음높이를 못 정한 경우만 여전히 던진다 — 그건 그릴 수조차 없다.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {assemble, checkBeats} from '../web/rebuild.js';
import {sourcePitch, assertResolved} from '../web/source-pitch.js';
import {build} from '../web/musicxml.js';
import {planBySemitones, parseNote, transposeNote, formatNote} from '../web/engine/index.js';

const staff = {staffTop:100,staffBottom:140,spacing:10,left:0,right:200};
const head = (x:number, cy:number) => ({x,y:cy-2,w:4,h:4});
const st = () => ({measure:null,accidentals:new Map(),tie:null});

test('원조표를 음높이에 적용한 뒤 이조한다 (Bb→C의 Bb3는 C4)', () => {
  const pitch = sourcePitch('B3',{measure:1},-2,st());
  assert.equal(pitch,'Bb3');
  const plan = planBySemitones('Bb',2);
  assert.equal(formatNote(transposeNote(parseNote(pitch),plan.interval),{octave:true}),'C4');
});

test('임시표는 같은 옥타브의 마디 안에서 지속하고 다음 마디에서 초기화한다', () => {
  const state = st();
  const inputs = [['B4',1,0],['B4',1,undefined],['B5',1,undefined],['B4',2,undefined]];
  assert.deepEqual(inputs.map(([base,measure,accidental]) =>
    sourcePitch(base,{measure,accidental},-2,state)), ['B4','B4','Bb5','Bb4']);
});

test('마디를 넘는 붙임줄에 임시표 음높이를 유지한다', () => {
  const state = st();
  assert.equal(sourcePitch('F4',{measure:1,accidental:1,tie:true},0,state),'F#4');
  assert.equal(sourcePitch('F4',{measure:2},0,state),'F#4');
  assert.equal(sourcePitch('F4',{measure:2},0,state),'F4');
});

test('개수 불일치 때 뒤 음을 당기거나 마지막 음을 복제하지 않는다', () => {
  const struct = {sourceFifths:0,beats:4,systems:[{measures:1,notes:
    Array.from({length:4},()=>({measure:1,duration:'quarter'}))}]};
  const result = assemble(struct,{systems:[staff],heads:[head(10,120),head(50,110),head(70,105)]},{});
  assert.equal(checkBeats(struct).ok,1); // 리듬 합 통과가 정답 증명이 아님을 재현
  const notes = result.measures[0].notes;
  // 검출된 3개는 **자기 머리 그대로**. 뒤 마디 머리를 당겨오지 않는다.
  assert.deepEqual(notes.slice(0,3).map(n=>n.pitch),['B4','D5','E5']);
  // 남은 1개는 앞 음을 이어 그리되 **센다** — 이게 qualityGate 를 막는 근거다.
  assert.equal(result.report.missingPitch,1);
  assert.deepEqual(result.report.mismatch,[{system:0,detected:3,expected:4}]);
  assert.equal(result.report.unresolved.length,1);
  assert.match(result.report.unresolved[0].reason,/음표 수 불일치/);
});

test('검출기 구조는 각 음표의 좌표를 직접 사용한다', () => {
  const struct = {sourceFifths:0,beats:4,systems:[{measures:1,notes:[
    {measure:1,duration:'half',head:head(50,110)},
    {measure:1,duration:'half',head:head(70,105)}]}]};
  const result = assemble(struct,{systems:[staff],heads:[head(10,120),head(50,110),head(70,105)]},{});
  assert.deepEqual(result.measures[0].notes.map(n=>n.pitch),['D5','E5']);
});

test('6/8의 단 경계에서 쪼개진 마디는 3박으로 연결한다', () => {
  const struct = {sourceFifths:0,beats:3,systems:[
    {measures:1,notes:[{measure:1,duration:'quarter',dotted:true,rest:true}]},
    {measures:1,notes:[{measure:1,duration:'quarter',dotted:true,rest:true}]}]};
  const r=assemble(struct,{systems:[staff,{...staff,staffTop:200,staffBottom:240}],heads:[]},{});
  assert.equal(r.measures[0].noRightBar,true);
});

test('화음 미지원 구간과 미확정 원조표는 출력하지 않는다', () => {
  const struct = {sourceFifths:0,unreliable:{stacked:[0]},systems:[
    {measures:1,notes:[{measure:1,duration:'whole'}]}]};
  const r=assemble(struct,{systems:[staff],heads:[head(20,120)]},{});
  // 화음 구간은 그려 주되 사유를 남긴다 → qualityGate 가 저장을 막는다
  assert.ok(r.report.unresolved.some(u=>/동시 화음/.test(u.reason)));
  // 원조표 미확정은 음높이 계산 자체가 불가능해서 여전히 던진다
  assert.throws(()=>sourcePitch('C4',{measure:1},undefined,st()),/원조표/);
});

test('CLI와 웹의 조립 결과가 동일하다 (새 정규 경로)', () => {
  const struct = {sourceFifths:-2,systems:[{measures:1,notes:[{measure:1,duration:'whole'}]}]};
  const data = {struct,geometry:{systems:[staff],heads:[head(20,120)]},chords:{}};
  const cli=JSON.parse(execFileSync('python3',['-c',
    'import sys,json; sys.path.insert(0,"tools"); import rebuild; d=json.load(sys.stdin); m,r=rebuild.assemble_data(d["struct"],d["geometry"],d["chords"]); print(json.dumps({"measures":m,"report":r}))'
  ],{input:JSON.stringify(data),encoding:'utf8'}));
  assert.deepEqual(cli,assemble(data.struct,data.geometry,{}));
  assert.equal(cli.measures[0].notes[0].pitch,'Bb4');
});

test('빈 마디를 온쉼표로 만들어 출력하거나 없는 오선을 건너뛰지 않는다', () => {
  const struct={sourceFifths:0,systems:[{measures:2,notes:[{measure:1,duration:'whole',rest:true}]}]};
  const r=assemble(struct,{systems:[staff],heads:[]},{});
  assert.ok(r.report.unresolved.some(u=>/읽은 음표/.test(u.reason)));
  const missing=assemble(struct,{systems:[],heads:[]},{});
  assert.ok(missing.report.unresolved.some(u=>/단 수/.test(u.reason)));
});

test('박자합 불일치는 자동 보정하지 않고 확인 대상으로 남긴다', () => {
  const struct={sourceFifths:0,beats:4,systems:[{measures:1,notes:[{measure:1,duration:'quarter',rest:true}]}]};
  const r=assemble(struct,{systems:[staff],heads:[]},{});
  assert.equal(r.measures[0].notes[0].duration,'quarter');   // 자동 보정 안 함
  assert.ok(r.report.unresolved.some(u=>/음가 합 1박/.test(u.reason)));
  // 못갖춘마디로 선언하면 사유가 사라져야 한다 — 남으면 멀쩡한 악보가 막힌다
  struct.systems[0].pickups=[1];
  const pickup=assemble(struct,{systems:[staff],heads:[]},{});
  assert.deepEqual(pickup.report.unresolved,[]);
  assert.doesNotThrow(()=>assertResolved(pickup.measures,pickup.report));
});
