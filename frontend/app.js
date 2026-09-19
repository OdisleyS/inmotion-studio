const API = window.API_BASE || "http://127.0.0.1:8000";
const $ = (id) => document.getElementById(id);
const phases = ['script', 'image', 'audio', 'video'];

async function loadProviders() {
  try {
    const catalog = await fetch(`${API}/api/providers`).then(r => r.json());
    phases.forEach(phase => {
      const select = $(`${phase}-provider`);
      (catalog[phase] || []).forEach(provider => {
        const option = document.createElement('option'); option.value = provider.name;
        option.textContent = `${provider.label} · ${provider.status}`;
        option.disabled = !['ready', 'ready-manifest'].includes(provider.status);
        select.appendChild(option);
      });
      if (phase === 'script' && catalog.script.some(p => p.name === 'antigravity-cli' && p.status === 'ready')) select.value = 'antigravity-cli';
    });
    updateCapabilityHint();
  } catch (_) { $('capability-hint').textContent = 'Não foi possível ler o catálogo de capabilities.'; }
}

function updateCapabilityHint() {
  const style = $('style').value; const strategy = $('video-strategy').value;
  $('capability-hint').textContent = style === 'sketch_clone' || style === 'couples_fruits_2d' || style === 'dynamic_slideshow'
    ? 'Recomendação: frame por frame preserva melhor desenho, geometria e estilo. A montagem usa captions + áudio estéreo.'
    : strategy === 'direct_video' ? 'Vídeo nativo selecionado: use um provider com capability video.' : 'A estratégia automática será escolhida pelo estilo.';
}

function updateHistory() {
  const entries = JSON.parse(localStorage.getItem('studio-history') || '[]');
  $('history').innerHTML = entries.length ? `<p class="eyebrow" style="margin-top:25px">PRODUÇÕES RECENTES</p>${entries.slice(0, 4).map(item => `<div class="history-item"><span>${item.title}</span><a href="${API}${item.url}" target="_blank">abrir vídeo ↗</a></div>`).join('')}` : '';
}

function saveHistory(data) {
  if (!data.render?.url) return;
  const entries = JSON.parse(localStorage.getItem('studio-history') || '[]').filter(item => item.project_id !== data.project_id);
  entries.unshift({project_id: data.project_id, title: data.title, url: data.render.url});
  localStorage.setItem('studio-history', JSON.stringify(entries.slice(0, 8)));
  updateHistory();
}

async function checkHealth() {
  try { const data = await fetch(`${API}/api/health`).then(r => r.json()); const bridge = data.antigravity_cli?.enabled ? ' / agy connected' : ' / local'; $('health').textContent = `● ${data.status}${bridge}`; $('health').style.color = '#d5f36a'; }
  catch (_) { $('health').textContent = '○ API offline'; $('health').style.color = '#ff9d63'; }
}

function renderResult(data) {
  $('empty').hidden = true; $('result').hidden = false;
  saveHistory(data);
  const events = (data.events || []).map(e => `<div class="event"><b>${e.phase}</b> · ${e.provider} · ${e.status}</div>`).join('');
  const video = data.render?.url ? `<video class="preview" controls playsinline src="${API}${data.render.url}"></video>` : '';
  $('result').innerHTML = `${video}<div class="metric"><span>Status</span><strong class="${data.status === 'blocked' ? 'blocked' : ''}">${data.status}</strong></div><div class="metric"><span>Virality heuristic</span><strong>${data.virality_score}%</strong></div><div class="metric"><span>Render</span><strong>${data.render.aspect_ratio || '—'} ${data.render.width ? `${data.render.width}×${data.render.height}` : ''} · ${data.render.strategy || 'auto'}</strong></div><p class="muted small" style="margin-top:20px"><b>${data.title}</b><br>${data.script}</p><p class="eyebrow" style="margin-top:25px">FALLBACK LOG</p>${events}<p class="muted small" style="margin-top:16px">${(data.diagnostics || []).join(' ') || 'Pipeline concluído sem diagnósticos.'}</p>`;
}

$('studio-form').addEventListener('submit', async (event) => {
  event.preventDefault(); $('form-status').textContent = 'Orquestrando providers…';
  let sketches = [];
  const selectedFiles = Array.from($('sketch-files').files || []);
  if (selectedFiles.length) {
    const upload = new FormData(); selectedFiles.forEach(file => upload.append('files', file));
    const uploaded = await fetch(`${API}/api/uploads/sketches`, {method: 'POST', body: upload}).then(r => r.json());
    sketches = (uploaded.accepted || []).filter(item => item.status === 'accepted').map(item => item.filename);
    $('sketch-status').textContent = `${sketches.length} referência(s) carregada(s) localmente.`;
  }
  const payload = { mode: $('mode').value, style: $('style').value, topic: $('topic').value, script: $('script').value || null, sketch_filenames: sketches, video_strategy: $('video-strategy').value, narration_language: $('narration-language').value, provider_selection: Object.fromEntries(phases.map(phase => [phase, $(`${phase}-provider`).value])) };
  const progress = $('production-progress'); progress.hidden = false;
  try {
    const response = await fetch(`${API}/api/jobs`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const created = await response.json(); if (!response.ok) throw new Error(created.detail || 'Falha ao criar job');
    let job = created;
    while (!['completed', 'blocked', 'failed'].includes(job.status)) {
      $('progress-title').textContent = job.phase === 'queued' ? 'Na fila' : ({script:'Roteiro', image:'Imagens', audio:'Narração Piper', video:'Montagem MP4'}[job.phase] || job.phase);
      $('progress-detail').textContent = `${job.progress || 0}% · ${(job.events || []).at(-1)?.message || 'Processando…'}`;
      await new Promise(resolve => setTimeout(resolve, 700));
      job = await fetch(`${API}/api/jobs/${created.job_id}`).then(r => r.json());
    }
    progress.hidden = true;
    if (job.status === 'failed') throw new Error(job.error || 'Job falhou');
    renderResult(job.result || {status: job.status, title: 'Produção', script: '', virality_score: 0, render: {}, events: job.events, diagnostics: []}); $('form-status').textContent = job.status === 'completed' ? 'Pronto.' : 'Produção bloqueada; veja o diagnóstico.';
  } catch (error) { progress.hidden = true; $('form-status').textContent = `Erro: ${error.message}`; }
});

$('style').addEventListener('change', updateCapabilityHint); $('video-strategy').addEventListener('change', updateCapabilityHint);
checkHealth(); loadProviders();
updateHistory();
