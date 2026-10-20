// 자동 판독의 **의미 계층** 회귀 — 임시표의 적용 범위와 붙임줄의 근거.
//
// 여기서 지키는 불변식: 한 마디로 그려 놓은 구간은 임시표도 한 마디로 취급한다.
// 마디는 단(오선) 경계에서 쪼개질 수 있는데, 예전에는 단이 바뀔 때마다 임시표를
// 무조건 초기화해서 **뒤 반쪽만 임시표가 사라졌다** — 줄막대는 지워 한 마디로
// 그려 놓고 음높이는 두 마디처럼 읽는 모순이었다.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {assemble} from '../web/rebuild.js';
import {sourcePitch} from '../web/source-pitch.js';

const staffA = {staffTop:100,staffBottom:140,spacing:10,left:0,right:200};
const staffB = {...staffA,staffTop:200,staffBottom:240};
const head = (x:number, cy:number) => ({x,y:cy-2,w:4,h:4});
const st = () => ({measure:null,accidentals:new Map(),tie:null});

// 맨 윗줄(staffTop)이 F5 이고, 5px(반 칸) 내려갈 때마다 한 음 낮다.
// A단은 100, B단은 200 에서 센다.
const F5a = (x:number) => head(x,100);
const D5a = (x:number) => head(x,110);
const F4a = (x:number) => head(x,135);
const F5b = (x:number) => head(x,200);
const F4b = (x:number) => head(x,235);

const note = (measure:number, duration:string, h:any, extra:any = {}) =>
  ({measure,duration,rest:false,dotted:false,tie:false,head:h,...extra});

const pitches = (r:any) => r.measures.map((m:any) => m.notes.map((n:any) => n.pitch));

test('measureId 가 같으면 임시표가 유지되고, 달라지면 초기화한다', () => {
  const state = st();
  assert.equal(sourcePitch('F4',{measure:9,accidental:1},0,state,'0:3'),'F#4');
  // 마디 번호는 달라도 같은 마디로 지목하면 임시표가 살아 있다
  assert.equal(sourcePitch('F4',{measure:1},0,state,'0:3'),'F#4');
  assert.equal(sourcePitch('F4',{measure:1},0,state,'1:1'),'F4');
});

test('단 경계에서 쪼개진 마디는 임시표를 뒤 반쪽까지 끌고 간다', () => {
  // 단0: 4박 마디 + 2박 / 단1: 2박 + 4박 마디 → 가운데 두 조각이 한 마디다
  const struct = {sourceFifths:0,beats:4,systems:[
    {measures:2,notes:[
      note(1,'whole',D5a(20)),
      note(2,'quarter',F5a(60),{accidental:1}),
      note(2,'quarter',F4a(80)),
    ]},
    {measures:2,notes:[
      note(1,'quarter',F5b(20)),
      note(1,'quarter',F4b(40)),
      note(2,'whole',F5b(120)),
    ]},
  ]};
  const heads = [D5a(20),F5a(60),F4a(80),F5b(20),F4b(40),F5b(120)];
  const r = assemble(struct,{systems:[staffA,staffB],heads},{});

  assert.deepEqual(pitches(r),[
    ['D5'],
    ['F#5','F4'],   // 임시표는 그 옥타브에만 — F4 는 원조표 그대로
    ['F#5','F4'],   // 단이 바뀌어도 같은 마디이므로 여전히 F#5
    ['F5'],         // 진짜 다음 마디에서 초기화
  ]);
  // 한 마디로 그렸다는 근거(줄막대 제거)와 임시표 유지가 같은 판단에서 나온다
  assert.equal(r.measures[1].noRightBar,true);
  assert.deepEqual(r.report.unresolved,[]);
});

test('쪼개진 마디가 아니면 단이 바뀔 때 임시표를 초기화한다', () => {
  // 단0 의 마지막 마디(2박)와 단1 의 첫 마디(1박)는 합쳐도 한 마디가 아니다
  const struct = {sourceFifths:0,beats:4,systems:[
    {measures:1,notes:[
      note(1,'quarter',F5a(60),{accidental:1}),
      note(1,'quarter',F4a(80)),
    ]},
    {measures:1,notes:[note(1,'quarter',F5b(20))]},
  ]};
  const r = assemble(struct,{systems:[staffA,staffB],heads:[F5a(60),F4a(80),F5b(20)]},{});
  assert.deepEqual(pitches(r),[['F#5','F4'],['F5']]);
  assert.ok(!r.measures[0].noRightBar);
  // 합이 4박이 아닌 두 마디는 그대로 확인 대상으로 남는다 (보정하지 않는다)
  assert.deepEqual(r.report.unresolved.map((i:any)=>i.system),[0,1]);
});

test('단을 넘는 붙임줄은 임시표가 붙은 음높이를 그대로 잇는다', () => {
  const struct = {sourceFifths:0,beats:4,systems:[
    {measures:1,notes:[
      note(1,'half',D5a(20)),
      note(1,'half',F5a(60),{accidental:1,tie:true}),
    ]},
    {measures:2,notes:[note(1,'whole',F5b(20)),note(2,'whole',F5b(120))]},
  ]};
  const r = assemble(struct,{systems:[staffA,staffB],heads:[D5a(20),F5a(60),F5b(20),F5b(120)]},{});
  assert.deepEqual(pitches(r),[['D5','F#5'],['F#5'],['F5']]);
  assert.equal(r.measures[0].notes[1].tie,true);
  assert.equal(r.measures[1].notes[0].tie_stop,true);
  assert.deepEqual(r.report.unresolved,[]);
});

test('붙임줄은 음가를 소비하지 않는다 — 박자 검산이 붙임줄에 흔들리지 않는다', () => {
  // 붙임줄은 표기일 뿐이라 마디 합에 아무 영향이 없어야 한다.
  const base = {sourceFifths:0,beats:4,systems:[{measures:1,notes:[
    note(1,'half',D5a(20)),note(1,'half',D5a(60))]}]};
  const tied = {...base,systems:[{...base.systems[0],notes:[
    note(1,'half',D5a(20),{tie:true}),note(1,'half',D5a(60))]}]};
  const geo = {systems:[staffA],heads:[D5a(20),D5a(60)]};
  assert.deepEqual(assemble(base,geo,{}).report.unresolved,[]);
  assert.deepEqual(assemble(tied,geo,{}).report.unresolved,[]);
});
