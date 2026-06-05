// Relay extension messages → MAIN world via postMessage
chrome.runtime.onMessage.addListener((msg) => {
  window.postMessage({ source: 'shiny-hunter-bridge', payload: msg }, '*');
});

// Relay status updates from MAIN world → storage
window.addEventListener('message', (e) => {
  if (e.source !== window || e.data?.source !== 'shiny-hunter-main') return;
  chrome.storage.local.set({ shinyState: e.data.payload });
});
