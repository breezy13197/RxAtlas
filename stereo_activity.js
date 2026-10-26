// Curated structures and RDKit-assigned CIP labels are embedded at build time.
const STEREO_PAIRS = __STEREO_JSON__;
let stereoQueue = [], stereoIndex = 0, stereoChoice = null, stereoAnswered = false;
let stereoAssisted = false, stereoRevealed = false, stereoScore = 0, stereoComplete = false;
const stereoEl = id => document.getElementById('stereo-' + id);
function stereoStart(){
  const level = Number(stereoEl('level').value);
  stereoQueue = shuffle(STEREO_PAIRS.filter(p => level === 3 ? p.centers === 2 : p.centers === 1));
  stereoIndex = 0; stereoScore = 0; stereoComplete = false;
  stereoRender();
}
function stereoDraw(){
  const p = stereoQueue[stereoIndex];
  stereoEl('pair').innerHTML = ['A','B'].map(side => `<figure><figcaption>Structure ${side}</figcaption><div role="img" aria-label="Structure ${side}, ${p.centers} numbered stereocenters">${p[stereoRevealed ? 'reveal'+side : side.toLowerCase()]}</div></figure>`).join('');
}
function stereoRender(){
  stereoChoice = null; stereoAnswered = false; stereoAssisted = false; stereoRevealed = false;
  const p = stereoQueue[stereoIndex];
  stereoEl('status').textContent = `Pair ${stereoIndex+1} of ${stereoQueue.length} · ${stereoScore} classifications correct without hints`;
  stereoEl('stem').textContent = 'How are these two structures related?';
  stereoDraw();
  const choices = stereoEl('level').value === '1' ? ['Same molecule','Different molecules'] : p.centers === 1 ? ['Identical','Enantiomers'] : ['Identical','Enantiomers','Diastereomers'];
  stereoEl('options').innerHTML = choices.map(c => `<button class="opt-btn" aria-pressed="false">${c}</button>`).join('');
  stereoEl('options').querySelectorAll('button').forEach(b => b.onclick = () => {
    stereoChoice = b.textContent;
    stereoEl('options').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed',String(x===b)));
  });
  stereoEl('centers').innerHTML = '<legend>Which numbered centers have opposite configurations? Select all that apply; leave unchecked for none.</legend>' + Array.from({length:p.centers},(_,i)=>`<label><input type="checkbox" value="${i+1}"> Center ${i+1}</label>`).join('');
  stereoEl('feedback').textContent = '';
  stereoEl('hint-text').hidden = true;
  stereoEl('check').disabled = false; stereoEl('hint').disabled = false;
  stereoEl('reveal').hidden = true; stereoEl('reveal').textContent = 'Show R/S labels';
  stereoEl('next').hidden = true;
  stereoEl('next').textContent = stereoIndex+1 === stereoQueue.length ? 'Finish level →' : 'Next pair →';
}
stereoEl('check').onclick = () => {
  if(stereoAnswered) return;
  if(!stereoChoice){stereoEl('feedback').textContent = 'Choose a relationship before checking your answer.';return;}
  stereoAnswered = true;
  const p = stereoQueue[stereoIndex];
  const expected = stereoEl('level').value === '1' ? (p.relation==='Identical' ? 'Same molecule' : 'Different molecules') : p.relation;
  const right = stereoChoice === expected;
  if(right && !stereoAssisted) stereoScore++;
  const selected = [...stereoEl('centers').querySelectorAll('input:checked')].map(x=>Number(x.value));
  const centersRight = JSON.stringify(selected) === JSON.stringify(p.changed);
  const detail = p.relation === 'Identical' ? 'Both structures have the same connectivity and configuration. Rotating a drawing does not change the molecule.' : p.relation === 'Enantiomers' ? 'Every numbered center has opposite configuration. These are non-superimposable mirror images.' : 'Some, but not all, numbered centers have opposite configurations. These are diastereomers.';
  stereoEl('feedback').textContent = `${right ? 'Correct' : 'Not quite'} — ${expected}. ${detail} ${centersRight ? 'Your center selections are correct.' : 'Check your center selections.'} Opposite configurations: ${p.changed.length ? p.changed.map(n=>'center '+n).join(' and ') : 'none'}. ${p.labelsA.map((a,i)=>`Center ${i+1}: ${a} in A → ${p.labelsB[i]} in B.`).join(' ')}${stereoAssisted ? ' Hint used; recorded as assisted.' : ''}`;
  progress.log.push({t:Date.now(),c:'stereopairs',g:null,s:p.id,ok:right,gu:stereoAssisted});
  saveProgress();
  stereoEl('status').textContent = `Pair ${stereoIndex+1} of ${stereoQueue.length} · ${stereoScore} classifications correct without hints`;
  stereoEl('options').querySelectorAll('button').forEach(b=>{
    b.disabled=true;
    b.classList.toggle('correct', b.textContent===expected);
    b.classList.toggle('wrong', b.textContent===stereoChoice && !right);
  });
  stereoEl('centers').querySelectorAll('input').forEach(b=>b.disabled=true);
  stereoEl('check').disabled = true; stereoEl('hint').disabled = true;
  stereoEl('reveal').hidden = false; stereoEl('next').hidden = false;
};
stereoEl('hint').onclick = () => {stereoAssisted = true; stereoEl('hint-text').hidden = false;};
stereoEl('reveal').onclick = () => {
  stereoRevealed = !stereoRevealed; stereoDraw();
  stereoEl('reveal').textContent = stereoRevealed ? 'Hide R/S labels' : 'Show R/S labels';
};
stereoEl('next').onclick = () => {
  if(stereoComplete){stereoStart();return;}
  if(!stereoAnswered) return;
  if(stereoIndex+1 < stereoQueue.length){stereoIndex++;stereoRender();stereoEl('stem').focus();return;}
  stereoEl('feedback').textContent = `Level complete: ${stereoScore} of ${stereoQueue.length} classifications correct without hints. Choose another level above or practice this level again.`;
  stereoEl('next').textContent = 'Practice this level again';
  stereoComplete = true;
};
stereoEl('level').onchange = stereoStart;
