// Run the shipped editor logic against a small DOM stub; this is not a browser rendering test.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const guard = setTimeout(() => { process.exitCode = 1; process.exit(); }, 60000);
process.on('exit', () => clearTimeout(guard));
try {
  const doc = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const elements = {};
  for (const id of ['data', 'content', 'sample-badge', 'timeline', 'error']) elements[id] = {textContent:'',innerHTML:'',style:{}};
  elements.data.textContent = JSON.stringify(doc);
  doc.segments.forEach((s, si) => s.candidates.forEach((c, ci) => {
    elements[`in-${si}-${ci}`] = {value:String(c.start_sec)};
    elements[`out-${si}-${ci}`] = {value:String(c.end_sec)};
    elements[`vid-${si}-${ci}`] = {currentTime:0,pause(){this.paused=true;}};
  }));
  let clicked = false, revoked = false, downloaded;
  const context = vm.createContext({
    document:{getElementById:id=>elements[id], createElement:()=>({click(){clicked=true;}})},
    Blob:class{constructor(parts){downloaded=JSON.parse(parts.join(''));}},
    URL:{createObjectURL:()=> 'blob:test',revokeObjectURL:()=> {revoked=true;}},
    setTimeout:fn=>fn(),
  });
  vm.runInContext(fs.readFileSync('src/vmv/production_editor.js','utf8'),context,{timeout:1000});
  assert.throws(()=>context.buildSelection());
  assert.ok(elements.content.innerHTML.includes(doc.segments[0].narration));
  context.toggleChoice(0,0,true); context.toggleChoice(0,1,true);
  const start = doc.segments[0].candidates[0].start_sec;
  elements['in-0-0'].value = String(start+0.5);
  context.moveShot(0,doc.segments[0].candidates[1].shot_id,-1);
  let result = JSON.parse(JSON.stringify(context.buildSelection()));
  assert.equal(result.segments[0].shots[0].shot_id,doc.segments[0].candidates[1].shot_id);
  assert.equal(result.segments[0].shots[1].in_sec,start+0.5);
  elements['in-0-0'].value = '';
  assert.throws(()=>context.buildSelection());
  elements['in-0-0'].value = String(start-1);
  assert.throws(()=>context.buildSelection());
  elements['in-0-0'].value = String(start);
  context.moveShot(0,doc.segments[0].candidates[0].shot_id,-1);
  context.exportSelection();
  assert.ok(clicked && revoked);
  assert.equal(downloaded.document_sha256,doc.document_sha256);
  assert.equal(downloaded.sample,doc.sample);
  assert.equal(downloaded.segments[0].shots[0].shot_id,doc.segments[0].candidates[0].shot_id);
  if (process.argv[3]) fs.writeFileSync(process.argv[3],JSON.stringify(downloaded,null,2));
  console.log('Editor logic: selection, trim, reorder, rejection and export passed');
} finally {clearTimeout(guard);}
