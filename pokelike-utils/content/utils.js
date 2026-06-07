// Speeds up the page's CSS animations/transitions and Web Animations API animations.
(() => {
  const STYLE_ID = 'pokelike-utils-speed-style';
  const PLAYBACK_INTERVAL_MS = 500;
  const BASE_DURATION_S = 0.3;
  const INSTANT_DURATION_S = 0.001;
  const INSTANT_PLAYBACK_RATE = 1000;

  let playbackTimer = null;
  let running = false;
  let speed = 4;
  let instant = false;

  // Battle/attack sequencing in the game is driven by setTimeout/setInterval
  // delays rather than CSS, so scale those too while the speed-up is active.
  const nativeSetTimeout = window.setTimeout.bind(window);
  const nativeSetInterval = window.setInterval.bind(window);

  function scaledDelay(delay) {
    const ms = Number(delay) || 0;
    if (!running) return ms;
    if (instant) return 0;
    return ms / speed;
  }

  window.setTimeout = function (handler, delay, ...args) {
    return nativeSetTimeout(handler, scaledDelay(delay), ...args);
  };
  window.setInterval = function (handler, delay, ...args) {
    return nativeSetInterval(handler, scaledDelay(delay), ...args);
  };

  // The battle flow `await`s several rAF-driven animation helpers — canvas
  // projectile/impact effects (`playAttackAnimation` → `runCanvas` /
  // `runParticleCanvas`, also called directly for trait/dodge effects) and HP
  // bar tweens (`animateHpBar` → `animateHpBarFull`) — that pace themselves off
  // `performance.now()`/`requestAnimationFrame`, not `setTimeout`, and their
  // particle loops keep running in real time even when `battleSpeedMultiplier`
  // is scaled (they continue until particles report not-alive). That makes them
  // the real bottleneck for overall combat pace. They're all top-level
  // `function` declarations (→ reachable as `window.<name>`), so wrap each to
  // race the real promise against a capped timeout — the game moves on once our
  // cap elapses, regardless of the animation's own internal timing.
  function nativeSleep(ms) {
    return new Promise((resolve) => nativeSetTimeout(resolve, ms));
  }

  function capFor(baseMs) {
    if (!running) return null;
    if (instant) return 0;
    return baseMs / speed;
  }

  function wrapAsyncWithCap(fnName, getBaseMs) {
    const original = window[fnName];
    if (typeof original !== 'function' || original.__pokelikeUtilsWrapped) return false;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      const cap = capFor(getBaseMs(args));
      if (cap === null || !(result instanceof Promise)) return result;
      return Promise.race([result, nativeSleep(cap)]);
    };
    wrapped.__pokelikeUtilsWrapped = true;
    window[fnName] = wrapped;
    return true;
  }

  const ANIM_FNS_TO_WRAP = [
    ['runCanvas',          (args) => args[2]],         // (canvas, ctx, duration, drawFn)
    ['runParticleCanvas',  (args) => args[3]],         // (canvas, ctx, particles, duration)
    ['animateHpBarFull',   (args) => args[5] ?? 250],  // (el, fromHp, fromMax, toHp, toMax, duration=250)
    ['playAttackAnimation', () => 900],                // internal durations vary ~300-800ms
  ];
  let allAnimFnsWrapped = false;

  const wrapPoll = nativeSetInterval(() => {
    allAnimFnsWrapped = ANIM_FNS_TO_WRAP
      .map(([fnName, getBaseMs]) => wrapAsyncWithCap(fnName, getBaseMs) || window[fnName]?.__pokelikeUtilsWrapped)
      .every(Boolean);
    if (allAnimFnsWrapped) clearInterval(wrapPoll);
  }, 200);

  function applyStyle() {
    let style = document.getElementById(STYLE_ID);
    if (!style) {
      style = document.createElement('style');
      style.id = STYLE_ID;
      document.head.appendChild(style);
    }
    const duration = instant ? INSTANT_DURATION_S : (BASE_DURATION_S / speed).toFixed(3);
    style.textContent = `
      *, *::before, *::after {
        animation-duration: ${duration}s !important;
        animation-delay: 0s !important;
        transition-duration: ${duration}s !important;
        transition-delay: 0s !important;
      }
    `;
  }

  function removeStyle() {
    document.getElementById(STYLE_ID)?.remove();
  }

  function tickPlaybackRates() {
    const rate = instant ? INSTANT_PLAYBACK_RATE : speed;
    for (const anim of document.getAnimations()) {
      anim.playbackRate = rate;
    }

    // The game itself paces battles (turn delays, HP-bar tweens, etc.) off an
    // internal `battleSpeedMultiplier` (declared with `let` at the top level of
    // ui.js, so it lives in the page's shared global lexical scope and can be
    // reassigned directly). Drive it to our value every tick — the game resets
    // it at battle start/end, so we keep re-applying ours on top.
    try {
      battleSpeedMultiplier = running ? rate : 1;
    } catch (_) {
      // Not declared yet (page scripts haven't run) — ignore until it exists.
    }
  }

  function postStatus() {
    window.postMessage({
      source: 'pokelike-utils-main',
      payload: { status: running ? 'running' : 'stopped', speed, instant },
    }, '*');
  }

  function start(newSpeed, newInstant) {
    speed = newSpeed || speed;
    instant = !!newInstant;
    running = true;
    applyStyle();
    if (!playbackTimer) playbackTimer = setInterval(tickPlaybackRates, PLAYBACK_INTERVAL_MS);
    postStatus();
  }

  function stop() {
    running = false;
    removeStyle();
    if (playbackTimer) { clearInterval(playbackTimer); playbackTimer = null; }
    try { battleSpeedMultiplier = 1; } catch (_) { /* not declared yet */ }
    postStatus();
  }

  window.addEventListener('message', (e) => {
    if (e.source !== window || e.data?.source !== 'pokelike-utils-bridge') return;
    const msg = e.data.payload;
    if (msg.type === 'START') start(msg.speed, msg.instant);
    else if (msg.type === 'STOP') stop();
    else if (msg.type === 'SET_SPEED') {
      speed = msg.speed;
      instant = !!msg.instant;
      if (running) applyStyle();
      postStatus();
    }
  });

  postStatus();
})();
