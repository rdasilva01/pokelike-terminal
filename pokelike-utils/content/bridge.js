// Relay extension messages → MAIN world via postMessage
chrome.runtime.onMessage.addListener((msg) => {
  window.postMessage({ source: 'pokelike-utils-bridge', payload: msg }, '*');
});

// Relay status updates from MAIN world → storage. Each util posts under its
// own `source` tag and gets its own storage key so they don't clobber each other.
window.addEventListener('message', (e) => {
  if (e.source !== window) return;
  const { source, payload } = e.data || {};
  if (source === 'pokelike-utils-main') {
    chrome.storage.local.set({ utilsState: payload });
  } else if (source === 'pokelike-path-main') {
    chrome.storage.local.get(['pathState'], ({ pathState }) => {
      chrome.storage.local.set({ pathState: { ...(pathState || {}), ...payload } });
    });
  } else if (source === 'pokelike-hotkeys-main') {
    chrome.storage.local.set({ hotkeysState: payload });
  }
});

// Re-apply saved on/off state to the MAIN-world scripts on every (re)load —
// the page can reload mid-session (e.g. via the Python automation's "reload"
// action), which re-injects content scripts and resets MAIN-world state to
// off. Without this, the stored state would get clobbered to "stopped" by the
// fresh scripts' initial status posts, even though the user had it turned on.
chrome.storage.local.get(['utilsState', 'pathState', 'hotkeysState'], ({ utilsState, pathState, hotkeysState }) => {
  if (utilsState?.status === 'running') {
    window.postMessage({
      source: 'pokelike-utils-bridge',
      payload: { type: 'START', speed: utilsState.speed, instant: utilsState.instant },
    }, '*');
  }
  if (pathState?.status === 'running') {
    window.postMessage({
      source: 'pokelike-utils-bridge',
      payload: { util: 'path', type: 'START', catchPriority: pathState.catchPriority },
    }, '*');
  }
  if (hotkeysState?.status === 'running') {
    window.postMessage({
      source: 'pokelike-utils-bridge',
      payload: { util: 'hotkeys', type: 'START' },
    }, '*');
  }
});
