// Exercise the activity's state transitions with a small DOM test double.
// No browser or JavaScript packages are needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(text=''){this.textContent=text;this.value='';this.hidden=false;this.disabled=false;this.children=[];this.attrs={};this.checked=false;this.classList={toggle(){}};}
  set innerHTML(html){
    this.html=html;
    this.children=[];
    for(const m of html.matchAll(/<button[^>]*>(.*?)<\/button>/g))this.children.push(new Element(m[1]));
    for(const m of html.matchAll(/<input[^>]*value="(\d+)"/g)){const e=new Element();e.value=m[1];this.children.push(e);}
  }
  get innerHTML(){return this.html;}
  querySelectorAll(selector){return selector==='input:checked'?this.children.filter(e=>e.checked):this.children;}
  setAttribute(k,v){this.attrs[k]=v;}
  focus(){}
}
const elements = new Map();
const get = id => {if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
get('stereo-level').value='1';
const pairs = JSON.parse(fs.readFileSync('stereo.json','utf8'));
const sandbox={document:{getElementById:get},progress:{log:[]},saveProgress(){},shuffle:a=>[...a]};
vm.createContext(sandbox);
const js=fs.readFileSync('stereo_activity.js','utf8').replace('__STEREO_JSON__',JSON.stringify(pairs));
vm.runInContext(js,sandbox);
const run = code => vm.runInContext(code,sandbox);
const click=id=>get('stereo-'+id).onclick();
const choose=text=>{const b=get('stereo-options').children.find(b=>b.textContent===text);assert.ok(b,text);b.onclick();};
for(const level of ['1','2','3']){
  get('stereo-level').value=level;
  run('stereoStart()');
  const n=run('stereoQueue.length');
  assert.equal(n,level==='3'?9:6);
  for(let i=0;i<n;i++){
    const q=run('stereoQueue[stereoIndex]');
    const before=sandbox.progress.log.length;
    click('check');
    assert.match(get('stereo-feedback').textContent,/Choose a relationship/);
    assert.equal(sandbox.progress.log.length,before);
    if(i===0)click('hint');
    const answer=level==='1'?(q.relation==='Identical'?'Same molecule':'Different molecules'):q.relation;
    choose(answer);
    for(const input of get('stereo-centers').children)input.checked=q.changed.includes(Number(input.value));
    click('check');click('check'); // repeated submits must not duplicate the result
    assert.equal(sandbox.progress.log.length,before+1);
    assert.match(get('stereo-feedback').textContent,/Your center selections are correct/);
    assert.equal(sandbox.progress.log.at(-1).ok,true);
    assert.equal(sandbox.progress.log.at(-1).gu,i===0);
    assert.equal(get('stereo-reveal').hidden,false);
    click('reveal');assert.equal(run('stereoRevealed'),true);
    assert.ok(get('stereo-pair').innerHTML.includes(q.revealA));
    click('reveal');assert.equal(run('stereoRevealed'),false);
    click('next');
  }
  assert.match(get('stereo-feedback').textContent,new RegExp(`Level complete: ${n-1} of ${n}`));
  click('next');assert.equal(run('stereoIndex'),0);assert.equal(run('stereoAnswered'),false);
}
assert.equal(sandbox.progress.log.length,21);
// Incorrect classifications and center selections get feedback and no score.
choose('Enantiomers'); // first two-center pair is identical
get('stereo-centers').children[0].checked=true;
click('check');
assert.equal(sandbox.progress.log.at(-1).ok,false);
assert.equal(run('stereoScore'),0);
assert.match(get('stereo-feedback').textContent,/Not quite/);
assert.match(get('stereo-feedback').textContent,/Check your center selections/);
// A correct classification with incorrect center selection keeps classification scoring separate.
run('stereoStart()');choose('Identical');get('stereo-centers').children[0].checked=true;click('check');
assert.equal(sandbox.progress.log.at(-1).ok,true);
assert.match(get('stereo-feedback').textContent,/Check your center selections/);
const html=fs.readFileSync('index.html','utf8');
assert.ok(!/__STEREO_|__DATA_JSON__|__SVGS_JSON__/.test(html));
assert.ok(!html.includes("document.querySelector('.quiz-card')"), "Quiz sets must target their own card after adding the activity card");
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
for(const script of scripts)new vm.Script(script[1]);
assert.ok(html.includes("if(cat === 'stereopairs'){showTab('stereopairs'); return;}"));
console.log('Passed: 21 guided questions, correct/incorrect answers, center feedback, assisted scoring, repeat-submit protection, R/S reveal, completion/restart, and built script syntax.');
