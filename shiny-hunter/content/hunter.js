(() => {
  let running = false;
  let targetName = '';
  let notShiny = false;
  let speed = 10;
  let attempts = 0;
  let rerolls = 0;

  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // Click the first accessible node on the map (SVG g element)
  function clickFirstNode() {
    const svg = document.querySelector('.screen.active svg');
    if (!svg) return false;
    const groups = Array.from(svg.children).filter(el => el.tagName === 'g');
    const node = groups.find(g => (g.getAttribute('style') || '').includes('pointer'))
               || groups.find(g => g.querySelector('image'))
               || groups[0];
    if (!node) return false;
    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    return true;
  }

  function rerollSlot(idx) {
    const cards = Array.from(document.querySelectorAll('.screen.active .poke-choice-wrap'))
      .filter(w => w.getBoundingClientRect().width > 0);
    const btn = cards[idx]?.querySelector('.reroll-btn');
    if (btn) btn.click();
  }

  function isMapScreen() {
    const el = document.querySelector('.team-slot');
    return !!(el && el.getBoundingClientRect().width > 0);
  }

  function isCatchScreen() {
    const el = document.querySelector('.screen.active .poke-choice-wrap');
    return !!(el && el.getBoundingClientRect().width > 0);
  }

  function foundTarget() {
    const query = targetName.toLowerCase();
    if (query === 'any') {
      return Array.from(document.querySelectorAll('.screen.active .poke-choice-wrap'))
        .filter(w => w.getBoundingClientRect().width > 0)
        .some(card => notShiny ? !card.querySelector('.shiny-badge') : !!card.querySelector('.shiny-badge'));
    }
    return Array.from(document.querySelectorAll('.screen.active .poke-choice-wrap'))
      .filter(w => w.getBoundingClientRect().width > 0)
      .some(card => {
        const name = card.querySelector('.poke-name')?.innerText.trim().toLowerCase();
        const types = Array.from(card.querySelectorAll('.poke-types .type-badge'))
          .map(t => t.innerText.trim().toLowerCase());
        const match = name === query || types.includes(query);
        const isShiny = !!card.querySelector('.shiny-badge');
        return match && (notShiny ? !isShiny : isShiny);
      });
  }

  function waitFor(condition, timeoutMs) {
    return new Promise(resolve => {
      if (condition()) { resolve(true); return; }
      const timer = setTimeout(() => { obs.disconnect(); resolve(false); }, timeoutMs);
      const obs = new MutationObserver(() => {
        if (!running) { clearTimeout(timer); obs.disconnect(); resolve(false); }
        else if (condition()) { clearTimeout(timer); obs.disconnect(); resolve(true); }
      });
      obs.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] });
    });
  }

  function saveState(status) {
    window.postMessage({ source: 'shiny-hunter-main', payload: { status, attempts, rerolls, target: targetName, notShiny } }, '*');
  }

  async function runLoop() {
    while (running) {
      const onMap = await waitFor(isMapScreen, 10000);
      if (!onMap || !running) break;

      clickFirstNode();

      const onCatch = await waitFor(isCatchScreen, 5000);
      if (!onCatch || !running) break;

      if (foundTarget()) { running = false; saveState('found'); return; }

      rerollSlot(0); rerolls++;
      rerollSlot(1); rerolls++;
      rerollSlot(2); rerolls++;
      saveState('searching');

      await sleep(speed);
      if (!running) break;

      if (foundTarget()) { running = false; saveState('found'); return; }

      const resetBtn = document.querySelector('button[title="Restart run"]');
      if (resetBtn) resetBtn.click();

      attempts++;
      saveState('searching');

      await sleep(speed);
    }

    if (running) saveState('stopped');
    running = false;
  }

  window.addEventListener('message', (e) => {
    if (e.source !== window || e.data?.source !== 'shiny-hunter-bridge') return;
    const msg = e.data.payload;
    if (msg.type === 'START') {
      if (running) return;
      targetName = msg.target;
      notShiny = !!msg.notShiny;
      speed = msg.speed ?? 10;
      attempts = 0;
      rerolls = 0;
      running = true;
      saveState('searching');
      runLoop();
    } else if (msg.type === 'STOP') {
      running = false;
      saveState('stopped');
    }
  });
})();
