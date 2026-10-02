const doc = JSON.parse(document.getElementById('data').textContent);
const orders = doc.segments.map(() => []);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function renderPage() {
  const badge = document.getElementById('sample-badge');
  if (badge) badge.style.display = doc.sample ? 'inline-block' : 'none';
  document.getElementById('content').innerHTML = doc.segments.map((s, si) => `
    <div class="segment">
      <div class="meta"><b>旁白:</b> ${esc(s.narration)} | <b>视觉要求:</b> ${esc(s.visual_requirement)}</div>
      <div class="candidates">${s.candidates.map((c, ci) => `
        <div class="card">
          <video controls src="${esc(c.preview)}" id="vid-${si}-${ci}"></video>
          <label><input type="checkbox" onchange="toggleChoice(${si},${ci},this.checked)"> 选择</label>
          入点: <input type="number" id="in-${si}-${ci}" value="${c.start_sec}" step="0.04" onchange="renderTimeline()">
          出点: <input type="number" id="out-${si}-${ci}" value="${c.end_sec}" step="0.04" onchange="renderTimeline()">
          <button type="button" onclick="moveShot(${si},'${esc(c.shot_id)}',-1)">↑</button>
          <button type="button" onclick="moveShot(${si},'${esc(c.shot_id)}',1)">↓</button>
        </div>`).join('')}</div>
    </div>`).join('');

  doc.segments.forEach((s, si) => s.candidates.forEach((c, ci) => {
    const v = document.getElementById(`vid-${si}-${ci}`);
    v.onplay = () => {
      const i = +document.getElementById(`in-${si}-${ci}`).value, o = +document.getElementById(`out-${si}-${ci}`).value;
      if (Number.isFinite(i) && Number.isFinite(o) && i >= c.start_sec && o <= c.end_sec && i < o) {
        v.currentTime = Math.max(0, i - c.start_sec);
      }
    };
    v.ontimeupdate = () => {
      const o = +document.getElementById(`out-${si}-${ci}`).value;
      if (Number.isFinite(o) && v.currentTime >= o - c.start_sec) v.pause();
    };
  }));
  renderTimeline();
}

function toggleChoice(si, ci, checked) {
  const id = doc.segments[si].candidates[ci].shot_id;
  orders[si] = checked ? [...orders[si], id] : orders[si].filter(x => x !== id);
  renderTimeline();
}

function moveShot(si, shot_id, dir) {
  const arr = orders[si], idx = arr.indexOf(shot_id), target = idx + dir;
  if (idx >= 0 && target >= 0 && target < arr.length) {
    [arr[idx], arr[target]] = [arr[target], arr[idx]];
    renderTimeline();
  }
}

function validateAndGetShot(si, shot_id) {
  const ci = doc.segments[si].candidates.findIndex(c => c.shot_id === shot_id);
  const cand = doc.segments[si].candidates[ci];
  const inVal = document.getElementById(`in-${si}-${ci}`).value.trim();
  const outVal = document.getElementById(`out-${si}-${ci}`).value.trim();
  const in_sec = parseFloat(inVal), out_sec = parseFloat(outVal);
  if (!inVal || !outVal || !Number.isFinite(in_sec) || !Number.isFinite(out_sec) || in_sec < cand.start_sec || out_sec > cand.end_sec || in_sec >= out_sec) {
    throw new Error(`片段 ${si + 1} 镜头 ${shot_id} 的入点/出点必须在 [${cand.start_sec}, ${cand.end_sec}] 范围内且入点小于出点`);
  }
  return { shot_id, in_sec, out_sec, dur: out_sec - in_sec };
}

function renderTimeline() {
  const errEl = document.getElementById('error'), tlEl = document.getElementById('timeline');
  if (errEl) errEl.textContent = '';
  try {
    let cum = 0, items = [];
    orders.forEach((shots, si) => shots.forEach(id => {
      const s = validateAndGetShot(si, id);
      cum += s.dur;
      items.push(`[${s.shot_id}] 时长: ${s.dur.toFixed(2)}s (累计: ${cum.toFixed(2)}s)`);
    }));
    if (tlEl) tlEl.textContent = `总累计时长: ${cum.toFixed(2)}s | 时间轴: 尚未配音\n${items.join(' -> ')}`;
  } catch (err) {
    if (errEl) errEl.textContent = err.message;
  }
}

function buildSelection() {
  return {
    sample: doc.sample,
    document_sha256: doc.document_sha256,
    segments: doc.segments.map((seg, si) => {
      if (!orders[si].length) throw new Error(`分段 ${si + 1} 至少需要选择一个候选镜头`);
      return { id: seg.id, shots: orders[si].map(id => {
        const { shot_id, in_sec, out_sec } = validateAndGetShot(si, id);
        return { shot_id, in_sec, out_sec };
      })};
    })
  };
}

function exportSelection() {
  try {
    const blob = new Blob([JSON.stringify(buildSelection(), null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob), a = Object.assign(document.createElement('a'), { href: url, download: 'selection.json' });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    const errEl = document.getElementById('error');
    if (errEl) errEl.textContent = err.message;
  }
}

renderPage();
