const dexBtn     = document.getElementById('dex-btn');
const dexPanel   = document.getElementById('dex-panel');
const dexSearch  = document.getElementById('dex-search');
const dexList    = document.getElementById('dex-list');

let allPokemonNames = [];

async function loadPokemonNames() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return [];
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: 'MAIN',
    func: () => {
      const species = JSON.parse(localStorage.getItem('pkrl_species_list') || '[]');
      return species.map(s => s.name).filter(Boolean).sort();
    }
  });
  return results?.[0]?.result || [];
}

function renderDexList(filter) {
  const q = filter.toLowerCase();
  const matches = q
    ? allPokemonNames.filter(n => n.toLowerCase().includes(q))
    : allPokemonNames;

  if (!matches.length) {
    dexList.innerHTML = `<div class="dex-empty">${allPokemonNames.length ? 'No matches' : 'Could not load Pokémon list'}</div>`;
    return;
  }
  dexList.innerHTML = matches.slice(0, 100)
    .map(n => `<div class="dex-item">${n}</div>`)
    .join('');
  dexList.querySelectorAll('.dex-item').forEach(el => {
    el.addEventListener('click', () => {
      targetInput.value = el.textContent;
      dexPanel.classList.add('hidden');
    });
  });
}

dexBtn.addEventListener('click', async () => {
  const isOpen = !dexPanel.classList.contains('hidden');
  if (isOpen) { dexPanel.classList.add('hidden'); return; }

  dexPanel.classList.remove('hidden');
  dexSearch.value = '';
  dexList.innerHTML = '<div class="dex-empty">Loading…</div>';
  dexSearch.focus();

  if (!allPokemonNames.length) {
    allPokemonNames = await loadPokemonNames();
  }
  renderDexList('');
});

dexSearch.addEventListener('input', () => renderDexList(dexSearch.value));

const toggleBtn = document.getElementById('toggle');
const targetInput = document.getElementById('target');
const notShinyCheckbox = document.getElementById('not-shiny');
const speedSlider = document.getElementById('speed');
const speedVal = document.getElementById('speed-val');
const statusEl = document.getElementById('status');

speedSlider.addEventListener('input', () => { speedVal.textContent = speedSlider.value; });
speedVal.textContent = speedSlider.value;

let pollInterval = null;

function setStatus(state, attempts, notShiny, rerolls) {
  const running = state === 'searching';
  const cls = state === 'found' ? 'found' : running ? 'searching' : 'idle';
  const prefix = state === 'found' ? (notShiny ? '✓ ' : '✨ ') : '';
  statusEl.textContent = `${prefix}${attempts ?? 0} attempts`;
  statusEl.className = 'status ' + cls;

  toggleBtn.textContent = running ? 'Stop' : 'Start';
  toggleBtn.className = running ? 'running' : '';
  targetInput.disabled = running;
  notShinyCheckbox.disabled = running;
  speedSlider.disabled = running;
}

function pollStatus() {
  chrome.storage.local.get(['shinyState'], ({ shinyState }) => {
    if (!shinyState) return;
    setStatus(shinyState.status, shinyState.attempts, shinyState.notShiny, shinyState.rerolls);
    if (shinyState.status !== 'searching') stopPoll();
  });
}

function startPoll() {
  if (pollInterval) return;
  pollStatus();
  pollInterval = setInterval(pollStatus, 500);
}

function stopPoll() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

async function sendToTab(msg) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  chrome.tabs.sendMessage(tab.id, msg);
}

toggleBtn.addEventListener('click', async () => {
  const isRunning = toggleBtn.classList.contains('running');
  if (isRunning) {
    await sendToTab({ type: 'STOP' });
    setStatus('stopped', 0, false, 0);

    stopPoll();
  } else {
    const target = targetInput.value.trim();
    if (!target) { targetInput.focus(); return; }
    const notShiny = notShinyCheckbox.checked;
    const speed = parseInt(speedSlider.value);
    await sendToTab({ type: 'START', target, notShiny, speed });

    setStatus('searching', 0, notShiny, 0);
    startPoll();
  }
});

// Restore state when popup reopens
chrome.storage.local.get(['shinyState'], ({ shinyState }) => {
  if (!shinyState) return;
  setStatus(shinyState.status, shinyState.attempts, shinyState.notShiny, shinyState.rerolls);
  if (shinyState.target) targetInput.value = shinyState.target;
  if (shinyState.notShiny !== undefined) notShinyCheckbox.checked = shinyState.notShiny;
  if (shinyState.status === 'searching') startPoll();
});
