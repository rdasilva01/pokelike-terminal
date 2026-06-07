const SAVE_SERVER = 'https://save.pokelike.xyz';
const SAVE_SCHEMA_VERSION = 2;

// Per-call-site timeouts (ms). Without these, a stalled or DDoSed server
// hangs fetches indefinitely — freezing the title screen because initGame()
// awaits initCloudSave() before wiring up the New Run / Hard Run handlers.
// Different ceilings per call site:
//   load — startup-blocking, must stay snappy
//   sync — background pull on tab refocus / run end
//   push — background upload; large saves on slow links need more headroom
//   auth — user-facing, but tolerable; matches sync
const SAVE_FETCH_TIMEOUT_MS = { load: 4000, sync: 8000, push: 15000, auth: 8000 };

function _fetchWithTimeout(url, opts = {}, ms = SAVE_FETCH_TIMEOUT_MS.load) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  return fetch(url, { ...opts, signal: ctl.signal })
    .finally(() => clearTimeout(timer));
}

// Reachability state for the cloud-button indicator: 'loading' | 'online'
// | 'offline'. Starts 'loading' because initGame() awaits initCloudSave()
// before doing anything else — we genuinely don't know if the save server
// is reachable until the first request completes. After that first result
// the status only transitions between online and offline (background syncs
// never flip it back to 'loading', which would cause flicker on every tab
// refocus). Every fetch helper below calls _setCloudStatus() with its
// outcome and _updateSyncUI() re-renders automatically.
let _cloudStatus = 'loading';

function _setCloudStatus(status) {
  if (_cloudStatus === status) return;
  _cloudStatus = status;
  _updateSyncUI();
}

const SYNC_KEYS = [
  'poke_trainer', 'poke_tutorial_seen', 'poke_settings',
  'poke_achievements', 'poke_dex', 'poke_shiny_dex',
  'poke_elite_wins', 'poke_hall_of_fame', 'poke_hof_index', 'poke_last_run_won',
  'poke_stat_buffs', 'poke_used_starters', 'poke_last_used',
];

// Primitive keys use "newest wins" by per-key updatedAt timestamp.
// Collection keys do union-merge with per-item conflict resolution.
const PRIMITIVE_KEYS = new Set([
  'poke_trainer', 'poke_tutorial_seen', 'poke_settings',
  'poke_last_run_won', 'poke_elite_wins',
]);

function _getSaveUuid() { return localStorage.getItem('poke_save_uuid'); }
function _getUsername()  { return localStorage.getItem('poke_username'); }

function _getMeta() {
  try { return JSON.parse(localStorage.getItem('poke_meta') || '{}'); }
  catch { return {}; }
}
function _setMeta(meta) {
  try { localStorage.setItem('poke_meta', JSON.stringify(meta)); } catch {}
}
function _touchKey(key) {
  const m = _getMeta();
  m[key] = Date.now();
  _setMeta(m);
}

// Set while _applyCloudSave is mutating localStorage during a merge. Without
// this guard the patched setItem below would bump per-key timestamps for the
// writes that *apply* cloud values — pretending those merged values were
// freshly authored on this device. On the next push the inflated meta would
// make every other device's genuine local changes look stale and lose.
let _merging = false;
// One-flight guard for syncToCloud so a visibilitychange + a post-win sync
// firing back-to-back don't race two pull-merge-push pipelines at once.
let _syncing = false;

// Wrap localStorage.setItem to track updates for SYNC_KEYS. This lets the
// cloud merger pick the newer side for primitive keys without needing every
// caller to remember to bump a timestamp.
(function patchSetItem() {
  if (typeof localStorage === 'undefined') return;
  if (localStorage.__pokePatched) return;
  const origSet = localStorage.setItem.bind(localStorage);
  localStorage.setItem = function(key, val) {
    origSet(key, val);
    if (!_merging && SYNC_KEYS.includes(key)) _touchKey(key);
  };
  localStorage.__pokePatched = true;
})();

function _getLocalSave() {
  // Trigger the lazy migrations in getHofIndex / getPokedex / getShinyDex
  // before serializing the payload. Without this, players whose saves were
  // already in the bloated legacy format would keep posting the fat blob and
  // hitting 413 — the readers only run when feature code asks for them.
  if (typeof getHofIndex  === 'function') { try { getHofIndex();  } catch {} }
  if (typeof getPokedex   === 'function') { try { getPokedex();   } catch {} }
  if (typeof getShinyDex  === 'function') { try { getShinyDex();  } catch {} }
  const save = { lastSaved: Date.now(), v: SAVE_SCHEMA_VERSION, meta: _getMeta() };
  for (const key of SYNC_KEYS) {
    const val = localStorage.getItem(key);
    if (val !== null) save[key] = val;
  }
  return save;
}

function _applyCloudSave(save) {
  _merging = true;
  try {
  const cloudMeta = save.meta || {};
  const localMeta = _getMeta();
  const mergeReport = { primitiveSwaps: [], collectionMerges: [], dropped: 0 };

  // For a primitive key, prefer whichever side has the newer updatedAt. If
  // local has no record at all (older client), take cloud.
  function takeNewerPrimitive(key) {
    const localVal = localStorage.getItem(key);
    const cloudVal = save[key];
    if (cloudVal === undefined) return;
    if (localVal === null) { localStorage.setItem(key, cloudVal); mergeReport.primitiveSwaps.push(key); return; }
    const lt = localMeta[key] ?? 0;
    const ct = cloudMeta[key] ?? 0;
    if (ct > lt && cloudVal !== localVal) {
      localStorage.setItem(key, cloudVal);
      mergeReport.primitiveSwaps.push(key);
    }
  }

  for (const key of SYNC_KEYS) {
    if (save[key] === undefined) continue;

    if (key === 'poke_hall_of_fame') {
      const parse = s => { try { return JSON.parse(s || '[]'); } catch { return []; } };
      const local = parse(localStorage.getItem(key));
      const cloud = parse(save[key]);
      // Index by stable hash (savedAt OR runNumber+date+endless fallback).
      const hash = e => e.savedAt ? `t:${e.savedAt}` : `r:${e.runNumber}|${e.date}|${!!e.endless}`;
      const seen = new Set();
      const merged = [];
      for (const e of [...local, ...cloud]) {
        const h = hash(e);
        if (seen.has(h)) continue;
        seen.add(h);
        merged.push(e);
      }
      merged.sort((a, b) => (a.savedAt ?? 0) - (b.savedAt ?? 0));
      // Harvest unlocks from EVERY merged entry into the index BEFORE pruning
      // — otherwise unlocks living only in entries we're about to drop would
      // vanish. The hof_index merger (next SYNC_KEY) then unions with cloud's
      // own index, so the final state has unlocks from all sources.
      if (typeof harvestHofUnlocks === 'function') harvestHofUnlocks(merged);
      // Re-apply the entry cap after merging so a fat cloud HoF can't blow
      // past the limit on pull. HOF_MAX_ENTRIES lives in data.js (loaded
      // before this file).
      const cap = typeof HOF_MAX_ENTRIES === 'number' ? HOF_MAX_ENTRIES : 500;
      if (merged.length > cap) merged.splice(0, merged.length - cap);
      // Slim every entry on merge so legacy cloud copies (with name/types/
      // spriteUrl per team Pokemon) don't re-inflate the local save. The
      // slim helper lives in data.js (loaded before this file).
      const slim = typeof _slimHofEntry === 'function' ? merged.map(_slimHofEntry) : merged;
      localStorage.setItem(key, JSON.stringify(slim));
      mergeReport.collectionMerges.push(key);
      continue;
    }

    if (key === 'poke_hof_index') {
      const parse = s => { try { return JSON.parse(s || 'null'); } catch { return null; } };
      const local = parse(localStorage.getItem(key)) || { evoLineRoots: [], starterRuns: [], maxEndlessStage: 0 };
      const cloud = parse(save[key]) || { evoLineRoots: [], starterRuns: [], maxEndlessStage: 0 };
      const merged = {
        evoLineRoots: [...new Set([...(local.evoLineRoots || []), ...(cloud.evoLineRoots || [])])],
        starterRuns:  [...new Set([...(local.starterRuns  || []), ...(cloud.starterRuns  || [])])],
        maxEndlessStage: Math.max(local.maxEndlessStage || 0, cloud.maxEndlessStage || 0),
      };
      localStorage.setItem(key, JSON.stringify(merged));
      mergeReport.collectionMerges.push(key);
      continue;
    }

    if (key === 'poke_achievements') {
      const parse = s => { try { return JSON.parse(s || '[]'); } catch { return []; } };
      const merged = [...new Set([...parse(localStorage.getItem(key)), ...parse(save[key])])];
      localStorage.setItem(key, JSON.stringify(merged));
      mergeReport.collectionMerges.push(key);
      continue;
    }

    if (key === 'poke_used_starters') {
      const parse = s => { try { return JSON.parse(s || '[]'); } catch { return []; } };
      const merged = [...new Set([...parse(localStorage.getItem(key)), ...parse(save[key])])];
      localStorage.setItem(key, JSON.stringify(merged));
      mergeReport.collectionMerges.push(key);
      continue;
    }

    if (key === 'poke_elite_wins') {
      // Numeric: max() never loses progress.
      const localVal = parseInt(localStorage.getItem(key) || '0', 10);
      const cloudVal = parseInt(save[key] || '0', 10);
      localStorage.setItem(key, String(Math.max(localVal, cloudVal)));
      continue;
    }

    if (key === 'poke_dex') {
      const parse = s => { try { return JSON.parse(s || '{}'); } catch { return {}; } };
      const local = parse(localStorage.getItem(key));
      const cloud = parse(save[key]);
      // Normalize both shapes (legacy {caught, name, ...} and new 0|1) and
      // collapse to the slim form. "Caught beats seen" — if either side
      // shows caught for this species, the merge result is caught.
      const caughtOf = v => typeof v === 'number' ? v === 1 : !!(v && v.caught);
      const seenOf   = v => v !== undefined && v !== null;
      const merged = {};
      const ids = new Set([...Object.keys(local), ...Object.keys(cloud)]);
      for (const id of ids) {
        const lv = local[id], cv = cloud[id];
        if (caughtOf(lv) || caughtOf(cv)) merged[id] = 1;
        else if (seenOf(lv) || seenOf(cv)) merged[id] = 0;
      }
      localStorage.setItem(key, JSON.stringify(merged));
      mergeReport.collectionMerges.push(key);
      continue;
    }

    if (key === 'poke_shiny_dex') {
      const parse = s => { try { return JSON.parse(s || '{}'); } catch { return {}; } };
      const local = parse(localStorage.getItem(key));
      const cloud = parse(save[key]);
      // Union of IDs; collapse legacy {id,name,types,...} objects to the slim 1.
      const merged = {};
      for (const id of new Set([...Object.keys(local), ...Object.keys(cloud)])) {
        merged[id] = 1;
      }
      localStorage.setItem(key, JSON.stringify(merged));
      mergeReport.collectionMerges.push(key);
      continue;
    }

    if (key === 'poke_stat_buffs') {
      const parse = s => { try { return JSON.parse(s || '{}'); } catch { return {}; } };
      const local = parse(localStorage.getItem(key));
      const cloud = parse(save[key]);
      const merged = { ...local };
      // Bring in cloud species the local store doesn't have, and max-merge
      // the ones it does. Loss-free: a stat earned anywhere wins.
      for (const [specId, cBufs] of Object.entries(cloud)) {
        if (!merged[specId]) { merged[specId] = cBufs; continue; }
        for (const stat of ['hp', 'atk', 'def', 'special', 'spdef', 'speed']) {
          merged[specId][stat] = Math.max(merged[specId][stat] ?? 0, cBufs[stat] ?? 0);
        }
      }
      localStorage.setItem(key, JSON.stringify(merged));
      mergeReport.collectionMerges.push(key);
      continue;
    }

    if (key === 'poke_last_used') {
      // Per-evo-line timestamp. Newest wins per line.
      const parse = s => { try { return JSON.parse(s || '{}'); } catch { return {}; } };
      const local = parse(localStorage.getItem(key));
      const cloud = parse(save[key]);
      const merged = { ...local };
      for (const [id, t] of Object.entries(cloud)) {
        merged[id] = Math.max(merged[id] ?? 0, Number(t) || 0);
      }
      localStorage.setItem(key, JSON.stringify(merged));
      mergeReport.collectionMerges.push(key);
      continue;
    }

    if (PRIMITIVE_KEYS.has(key)) {
      takeNewerPrimitive(key);
      continue;
    }

    localStorage.setItem(key, save[key]);
  }

  // Persist merged meta as max(local, cloud) per key so subsequent compares
  // use the latest known timestamp.
  const newMeta = { ...localMeta };
  for (const [k, t] of Object.entries(cloudMeta)) {
    newMeta[k] = Math.max(newMeta[k] ?? 0, Number(t) || 0);
  }
  _setMeta(newMeta);

  localStorage.setItem('poke_last_cloud_sync', String(save.lastSaved));
  if (typeof applyDarkMode === 'function') applyDarkMode();
  if (typeof window !== 'undefined') window._lastCloudMergeReport = mergeReport;
  } finally {
    _merging = false;
  }
}

// Push the current local save to the server. Used by the public syncToCloud
// (after a pull+merge) and by _loadFromServer (when the server has nothing or
// the user declined to load).
async function _pushLocal() {
  const uuid = _getSaveUuid();
  if (!uuid) return;
  try {
    const save = _getLocalSave();
    const res = await _fetchWithTimeout(`${SAVE_SERVER}/save/${uuid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(save),
    }, SAVE_FETCH_TIMEOUT_MS.push);
    if (res.ok) {
      localStorage.setItem('poke_last_cloud_sync', String(save.lastSaved));
      _setCloudStatus('online');
    } else {
      _setCloudStatus('offline');
    }
  } catch (e) {
    console.warn('Cloud push failed:', e);
    _setCloudStatus('offline');
  }
}

// Public sync: pull cloud → merge into local → push merged back. The old
// implementation only pushed, so a device with a stale local snapshot could
// clobber progress another device had already uploaded.
async function syncToCloud() {
  const uuid = _getSaveUuid();
  if (!uuid || _syncing) return;
  _syncing = true;
  try {
    // Only push when the pull actually merged. If the pull failed (timeout,
    // network blip, 5xx), a push here would clobber whatever a second device
    // uploaded since our last successful sync — exactly the race the
    // pull-merge-push pipeline exists to prevent. Next sync trigger
    // (visibilitychange, run end) retries the whole pipeline from scratch.
    let pulled = false;
    try {
      const res = await _fetchWithTimeout(`${SAVE_SERVER}/save/${uuid}`, {}, SAVE_FETCH_TIMEOUT_MS.sync);
      if (res.ok) {
        const cloud = await res.json();
        _applyCloudSave(cloud);
        pulled = true;
        _setCloudStatus('online');
      } else {
        _setCloudStatus('offline');
      }
    } catch (e) {
      console.warn('Cloud pull during sync failed:', e);
      _setCloudStatus('offline');
    }
    if (pulled) await _pushLocal();
  } finally {
    _syncing = false;
  }
}

async function _loadFromServer() {
  const uuid = _getSaveUuid();
  if (!uuid) return;
  try {
    const res = await _fetchWithTimeout(`${SAVE_SERVER}/save/${uuid}`, {}, SAVE_FETCH_TIMEOUT_MS.load);
    if (!res.ok) { _setCloudStatus('online'); await _pushLocal(); return; }
    const cloudSave = await res.json();
    _setCloudStatus('online');
    const hasLocal = SYNC_KEYS.some(k => localStorage.getItem(k) !== null);
    const firstTime = !localStorage.getItem('poke_last_cloud_sync');
    if (hasLocal && firstTime) {
      if (confirm('A cloud save was found. Load it? (Local progress will be overwritten)')) {
        _applyCloudSave(cloudSave);
      }
      // Either branch: push so the cloud reflects this device. Declining the
      // prompt keeps local untouched, in which case the push wins for the
      // user's chosen device.
      await _pushLocal();
    } else {
      _applyCloudSave(cloudSave);
      await _pushLocal();
    }
  } catch (e) {
    console.warn('Load from server failed:', e);
    _setCloudStatus('offline');
  }
}

function _updateSyncUI() {
  const btn  = document.getElementById('btn-cloud-sync');
  const info = document.getElementById('cloud-sync-info');
  if (!btn) return;
  // Class is added/removed in every branch so transitioning out of loading
  // strips the cyan/pulse/spinner CSS automatically — no stale animation
  // when we land on online or offline.
  btn.classList.remove('cloud-loading');
  if (info) info.classList.remove('cloud-loading');
  const username = _getUsername();
  if (username) {
    btn.onclick = _showAccountModal;
    if (_cloudStatus === 'loading') {
      // Brief window (≤ load timeout) before the first request completes.
      // Visual: bright cyan + opacity pulse + spinning ⟳ via .cloud-loading
      // — see css/style.css. Don't claim "active" prematurely.
      btn.textContent = `☁ ${username} Loading`;
      btn.style.color = '';
      btn.classList.add('cloud-loading');
      if (info) {
        info.textContent = 'connecting to save server';
        info.style.display = 'block';
        info.style.color = '';
        info.classList.add('cloud-loading');
      }
    } else if (_cloudStatus === 'online') {
      btn.textContent = `☁ ${username}`;
      btn.style.color = '';
      if (info) {
        info.textContent = 'cloud save active';
        info.style.display = 'block';
        info.style.color = '';
      }
    } else {
      // Logged in but the save server is currently unreachable. Make this
      // obvious so the player knows their progress is local-only until
      // connectivity returns — otherwise they assume cross-device sync is
      // working and are surprised when another device doesn't catch up.
      btn.textContent = `☁ ${username} ⚠ offline`;
      btn.style.color = '#e0a050';
      if (info) {
        info.textContent = '⚠ save server unreachable — progress saved locally only';
        info.style.display = 'block';
        info.style.color = '#e0a050';
      }
    }
  } else {
    btn.textContent = '☁ Log In / Register';
    btn.style.color = '';
    btn.onclick = _showAuthModal;
    if (info) info.style.display = 'none';
  }
}

function _showAuthModal() {
  document.getElementById('save-auth-modal')?.remove();
  const modal = document.createElement('div');
  modal.id = 'save-auth-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;z-index:9999;';
  modal.innerHTML = `
    <div style="background:var(--bg2);border:2px solid var(--border);padding:24px;max-width:360px;width:90%;font-family:monospace;display:flex;flex-direction:column;gap:10px;">
      <div style="font-family:'Press Start 2P',monospace;font-size:10px;color:var(--accent);">☁ CLOUD SAVE</div>
      <input id="auth-username" placeholder="Username" autocomplete="username"
        style="background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:8px;font-size:12px;font-family:monospace;">
      <input id="auth-password" type="password" placeholder="Password" autocomplete="current-password"
        style="background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:8px;font-size:12px;font-family:monospace;">
      <div id="auth-error" style="color:#e05050;font-size:9px;display:none;"></div>
      <div style="display:flex;gap:8px;">
        <button id="auth-login-btn" class="btn-secondary" style="flex:1;">Log In</button>
        <button id="auth-register-btn" class="btn-secondary" style="flex:1;">Register</button>
      </div>
      <button id="auth-close-btn" class="btn-secondary" style="width:100%;margin-top:2px;">Cancel</button>
    </div>`;
  document.body.appendChild(modal);

  const errEl = document.getElementById('auth-error');
  const showErr = msg => { errEl.textContent = msg; errEl.style.display = 'block'; };

  async function doAuth(endpoint) {
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value;
    if (!username || !password) { showErr('Enter username and password.'); return; }
    errEl.style.display = 'none';
    const btn = document.getElementById(endpoint === '/login' ? 'auth-login-btn' : 'auth-register-btn');
    btn.disabled = true; btn.textContent = '...';
    try {
      const res = await _fetchWithTimeout(`${SAVE_SERVER}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      }, SAVE_FETCH_TIMEOUT_MS.auth);
      _setCloudStatus('online');
      const data = await res.json();
      if (!res.ok) { showErr(data.error || 'Something went wrong.'); btn.disabled = false; btn.textContent = endpoint === '/login' ? 'Log In' : 'Register'; return; }
      localStorage.setItem('poke_save_uuid', data.uuid);
      localStorage.setItem('poke_username', data.username);
      modal.remove();
      _updateSyncUI();
      await _loadFromServer();
      if (typeof initGame === 'function') initGame();
    } catch (e) {
      _setCloudStatus('offline');
      showErr('Could not reach save server.'); btn.disabled = false; btn.textContent = endpoint === '/login' ? 'Log In' : 'Register';
    }
  }

  document.getElementById('auth-login-btn').onclick    = () => doAuth('/login');
  document.getElementById('auth-register-btn').onclick = () => doAuth('/register');
  document.getElementById('auth-close-btn').onclick    = () => modal.remove();
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

  // Submit on Enter
  modal.addEventListener('keydown', e => { if (e.key === 'Enter') doAuth('/login'); });
}

function _showAccountModal() {
  document.getElementById('save-auth-modal')?.remove();
  const username = _getUsername();
  const modal = document.createElement('div');
  modal.id = 'save-auth-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;z-index:9999;';
  const statusLine = _cloudStatus === 'online'
    ? `<div style="font-size:9px;color:var(--text-dim);">Saves sync automatically.</div>`
    : _cloudStatus === 'offline'
    ? `<div style="font-size:10px;color:#e0a050;line-height:1.4;">⚠ <b>Save server unreachable.</b><br>Your progress is being saved locally and will sync automatically when the connection is restored.</div>`
    : `<div style="font-size:10px;color:var(--text-dim);line-height:1.4;">… Checking save server</div>`;
  modal.innerHTML = `
    <div style="background:var(--bg2);border:2px solid var(--border);padding:24px;max-width:360px;width:90%;font-family:monospace;display:flex;flex-direction:column;gap:10px;">
      <div style="font-family:'Press Start 2P',monospace;font-size:10px;color:var(--accent);">☁ CLOUD SAVE</div>
      <div style="font-size:11px;color:var(--text);">Signed in as <b>${username}</b></div>
      ${statusLine}
      <button id="account-signout-btn" class="btn-secondary" style="width:100%;margin-top:4px;">Sign Out</button>
      <button id="account-close-btn" class="btn-secondary" style="width:100%;">Close</button>
    </div>`;
  document.body.appendChild(modal);

  document.getElementById('account-signout-btn').onclick = () => {
    if (!confirm('Sign out? Your local save will remain but won\'t sync until you log back in.')) return;
    localStorage.removeItem('poke_save_uuid');
    localStorage.removeItem('poke_username');
    localStorage.removeItem('poke_last_cloud_sync');
    modal.remove();
    _updateSyncUI();
  };
  document.getElementById('account-close-btn').onclick = () => modal.remove();
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
}

async function initCloudSave() {
  _updateSyncUI();
  if (_getSaveUuid()) await _loadFromServer();

  // Re-pull when the tab regains focus so a second device's progress shows
  // up without forcing the player to reload. This is safe to do mid-run:
  //   - The active run lives in `poke_current_run` and isn't a SYNC_KEY, so
  //     the merge never touches it.
  //   - In-RAM `state` isn't read back from localStorage during gameplay;
  //     only persistent collections (dex, achievements, hall of fame, stat
  //     buffs …) are, and their mergers are union/max — no progress lost.
  //   - Concurrent syncs are no-oped by the _syncing guard.
  if (typeof document !== 'undefined' && !document.__pokeVisibilityHooked) {
    document.__pokeVisibilityHooked = true;
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && _getSaveUuid()) syncToCloud();
    });
  }
}
