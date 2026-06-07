const viewMenu = document.getElementById('view-menu');
const viewSpeed = document.getElementById('view-speed');
const viewPath = document.getElementById('view-path');
const viewHotkeys = document.getElementById('view-hotkeys');
const openSpeedBtn = document.getElementById('open-speed');
const openPathBtn = document.getElementById('open-path');
const openHotkeysBtn = document.getElementById('open-hotkeys');
const backBtn = document.getElementById('back-btn');
const backBtnPath = document.getElementById('back-btn-path');
const backBtnHotkeys = document.getElementById('back-btn-hotkeys');

const toggleSwitch = document.getElementById('toggle');
const instantCheckbox = document.getElementById('instant');
const speedSlider = document.getElementById('speed');
const speedVal = document.getElementById('speed-val');
const statusEl = document.getElementById('status');

const pathToggle = document.getElementById('path-toggle');
const pathStatusEl = document.getElementById('path-status');
const pathCatchToggle = document.getElementById('path-catch-toggle');

const hotkeysToggle = document.getElementById('hotkeys-toggle');
const hotkeysStatusEl = document.getElementById('hotkeys-status');

const INSTANT_SPEED = 100;

function showView(view) {
  viewMenu.classList.toggle('hidden', view !== 'menu');
  viewSpeed.classList.toggle('hidden', view !== 'speed');
  viewPath.classList.toggle('hidden', view !== 'path');
  viewHotkeys.classList.toggle('hidden', view !== 'hotkeys');
}

openSpeedBtn.addEventListener('click', () => showView('speed'));
openPathBtn.addEventListener('click', () => showView('path'));
openHotkeysBtn.addEventListener('click', () => showView('hotkeys'));
backBtn.addEventListener('click', () => showView('menu'));
backBtnPath.addEventListener('click', () => showView('menu'));
backBtnHotkeys.addEventListener('click', () => showView('menu'));

function currentSpeed() {
  return instantCheckbox.checked ? INSTANT_SPEED : parseInt(speedSlider.value);
}

function applyLiveSpeed() {
  if (toggleSwitch.checked) {
    sendToTab({ type: 'SET_SPEED', speed: currentSpeed(), instant: instantCheckbox.checked });
  }
}

speedSlider.addEventListener('input', () => {
  speedVal.textContent = speedSlider.value;
  applyLiveSpeed();
});

instantCheckbox.addEventListener('change', () => {
  speedSlider.disabled = toggleSwitch.checked || instantCheckbox.checked;
  applyLiveSpeed();
});

function setStatus(state, speed, instant) {
  const running = state === 'running';
  statusEl.textContent = running
    ? (instant ? 'running (instant)' : `running ×${speed ?? speedSlider.value}`)
    : 'stopped';
  statusEl.className = 'status ' + (running ? 'running' : 'stopped');

  toggleSwitch.checked = running;
  speedSlider.disabled = running || instantCheckbox.checked;
  instantCheckbox.disabled = running;

  if (instant !== undefined) instantCheckbox.checked = instant;
  if (speed !== undefined && !instant) {
    speedSlider.value = speed;
    speedVal.textContent = speed;
  }
}

async function sendToTab(msg) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  chrome.tabs.sendMessage(tab.id, msg);
}

toggleSwitch.addEventListener('change', async () => {
  if (toggleSwitch.checked) {
    const instant = instantCheckbox.checked;
    const speed = currentSpeed();
    await sendToTab({ type: 'START', speed, instant });
    setStatus('running', speed, instant);
  } else {
    await sendToTab({ type: 'STOP' });
    setStatus('stopped');
  }
});

function setPathStatus(state, catchPriority) {
  const running = state === 'running';
  pathStatusEl.textContent = running ? 'running' : 'stopped';
  pathStatusEl.className = 'status ' + (running ? 'running' : 'stopped');
  pathToggle.checked = running;
  if (catchPriority !== undefined) pathCatchToggle.checked = catchPriority;
}

pathToggle.addEventListener('change', async () => {
  if (pathToggle.checked) {
    await sendToTab({ util: 'path', type: 'START', catchPriority: pathCatchToggle.checked });
    setPathStatus('running');
  } else {
    await sendToTab({ util: 'path', type: 'STOP' });
    setPathStatus('stopped');
  }
});

pathCatchToggle.addEventListener('change', async () => {
  await sendToTab({ util: 'path', type: 'SET_CATCH_PRIORITY', catchPriority: pathCatchToggle.checked });
  chrome.storage.local.get(['pathState'], ({ pathState }) => {
    chrome.storage.local.set({ pathState: { ...(pathState || {}), catchPriority: pathCatchToggle.checked } });
  });
});

function setHotkeysStatus(state) {
  const running = state === 'running';
  hotkeysStatusEl.textContent = running ? 'running' : 'stopped';
  hotkeysStatusEl.className = 'status ' + (running ? 'running' : 'stopped');
  hotkeysToggle.checked = running;
}

hotkeysToggle.addEventListener('change', async () => {
  if (hotkeysToggle.checked) {
    await sendToTab({ util: 'hotkeys', type: 'START' });
    setHotkeysStatus('running');
  } else {
    await sendToTab({ util: 'hotkeys', type: 'STOP' });
    setHotkeysStatus('stopped');
  }
});

// Restore state when popup reopens
chrome.storage.local.get(['utilsState', 'pathState', 'hotkeysState'], ({ utilsState, pathState, hotkeysState }) => {
  if (utilsState) setStatus(utilsState.status, utilsState.speed, utilsState.instant);
  if (pathState) setPathStatus(pathState.status, pathState.catchPriority);
  if (hotkeysState) setHotkeysStatus(hotkeysState.status);
});
