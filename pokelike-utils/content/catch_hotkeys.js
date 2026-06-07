// Extra catch-screen hotkeys:
//  - Q rerolls all three catch slots at once (clicks each .reroll-btn)
//  - Numpad1 / Numpad2 / Numpad3 act as aliases for the game's own Digit1 /
//    Digit2 / Digit3 shortcuts (select slot N, or with Shift held, reroll
//    slot N) — done by re-dispatching a synthetic DigitN keydown so the
//    game's own handler (game.js "Keyboard shortcuts" — see CLAUDE.md DOM
//    notes) drives the actual behaviour, on whichever screen those keys apply.
//  - S acts as an alias for Space (skip), re-dispatched the same way so the
//    game's own `skipMap` logic (battle/catch/item/swap/trade screens) runs.
(() => {
  const SYNTHETIC_FLAG = '__pokelikeUtilsSynthetic';

  let running = false;

  function isCatchScreen() {
    return !!document.querySelector('.screen.active#catch-screen');
  }

  function rerollAll() {
    // .poke-choice-wrap is the per-slot wrapper; .reroll-btn only exists for
    // slots that haven't been rerolled yet (and only in Endless Mode) — the
    // optional chain makes clicking a missing button a harmless no-op.
    document.querySelectorAll('.screen.active .poke-choice-wrap')
      .forEach((wrap) => wrap.querySelector('.reroll-btn')?.click());
  }

  function redispatch(source, code, key) {
    const synthetic = new KeyboardEvent('keydown', {
      code,
      key,
      shiftKey: source.shiftKey,
      ctrlKey: source.ctrlKey,
      altKey: source.altKey,
      metaKey: source.metaKey,
      bubbles: true,
      cancelable: true,
    });
    synthetic[SYNTHETIC_FLAG] = true;
    document.dispatchEvent(synthetic);
  }

  const NUMPAD_DIGIT = { Numpad1: 1, Numpad2: 2, Numpad3: 3 };

  function onKeyDown(e) {
    if (!running || e[SYNTHETIC_FLAG]) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;

    const digit = NUMPAD_DIGIT[e.code];
    if (digit) {
      e.preventDefault();
      redispatch(e, `Digit${digit}`, String(digit));
      return;
    }

    if (e.code === 'KeyS' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      redispatch(e, 'Space', ' ');
      return;
    }

    if (e.code === 'KeyQ' && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey && isCatchScreen()) {
      e.preventDefault();
      rerollAll();
    }
  }

  // Registered at document_start, ahead of game.js's own listener — our
  // Numpad re-dispatch happens before the game ever sees the native event,
  // and our Q/reroll handling runs independently of it.
  document.addEventListener('keydown', onKeyDown);

  function postStatus() {
    window.postMessage({
      source: 'pokelike-hotkeys-main',
      payload: { status: running ? 'running' : 'stopped' },
    }, '*');
  }

  function start() {
    if (running) return;
    running = true;
    postStatus();
  }

  function stop() {
    if (!running) return;
    running = false;
    postStatus();
  }

  window.addEventListener('message', (e) => {
    if (e.source !== window || e.data?.source !== 'pokelike-utils-bridge') return;
    const msg = e.data.payload;
    if (msg.util !== 'hotkeys') return;
    if (msg.type === 'START') start();
    else if (msg.type === 'STOP') stop();
  });

  postStatus();
})();
