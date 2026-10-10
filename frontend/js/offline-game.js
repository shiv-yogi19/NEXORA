// NEXORA offline game: "Nova Run". Created By Shiv Yogi.
// An original endless runner drawn on a canvas. Runs entirely in the browser with no backend and no assets.
// Nova (a small visor-faced robot) dodges crystal spires and ducks under patrol drones.
// The game has no external dependencies so it keeps working while the phone server is unreachable.

const W = 720, H = 220, GROUND = 176;
const GRAVITY = 2600, JUMP_V = -830;
const PLAYER = { x: 74, w: 30, h: 38, duckH: 22 };
const BEST_KEY = "nexora.dino.best";

function rng(seed) { // small deterministic PRNG so tests can replay a run
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** Axis-aligned overlap test (exported for tests). */
export function overlaps(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}

export function createGame(mount, opts = {}) {
  const reduced = !!opts.reducedMotion;
  const rand = rng(opts.seed ?? (Date.now() & 0xffffffff));
  const wrap = document.createElement("div");
  wrap.className = "game-canvas-wrap";
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Nova Run game. Press Space or tap to jump over crystals. Press Down to duck under drones.");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const overlay = document.createElement("div");
  overlay.className = "game-overlay";
  const title = document.createElement("h3");
  const sub = document.createElement("p");
  sub.className = "muted";
  const startBtn = document.createElement("button");
  startBtn.type = "button";
  startBtn.className = "btn btn-primary";
  overlay.append(title, sub, startBtn);
  const duckBtn = document.createElement("button");
  duckBtn.type = "button";
  duckBtn.className = "btn game-duck";
  duckBtn.textContent = "Duck";
  duckBtn.setAttribute("aria-label", "Duck (hold)");
  const live = document.createElement("div");
  live.className = "sr-only";
  live.setAttribute("role", "status");
  live.setAttribute("aria-live", "polite");
  wrap.append(canvas, overlay, duckBtn, live);
  mount.append(wrap);

  let best = 0;
  try { best = Number(localStorage.getItem(BEST_KEY)) || 0; } catch (_) { /* storage may be blocked */ }

  const s = {
    state: "ready", score: 0, dist: 0, speed: 360, t: 0, nextGap: 0,
    p: { y: GROUND - PLAYER.h, vy: 0, ducking: false, ground: true, run: 0 },
    obstacles: [], stars: [], dust: [], flash: 0, shake: 0, lastOverAt: 0, paused: false,
  };
  for (let i = 0; i < 38; i++) s.stars.push({ x: rand() * W, y: rand() * (GROUND - 30), z: 0.2 + rand() * 0.8 });

  let sound = false, audio = null;
  function tone(freq, dur, type = "sine", gain = 0.05, slide = 0) {
    if (!sound) return;
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      const o = audio.createOscillator(), g = audio.createGain();
      o.type = type; o.frequency.value = freq;
      if (slide) o.frequency.linearRampToValueAtTime(freq + slide, audio.currentTime + dur);
      g.gain.value = gain; g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + dur);
      o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + dur);
    } catch (_) { /* sound is optional */ }
  }

  const css = getComputedStyle(document.documentElement);
  const col = { blue: "#3d7bff", violet: "#8b5cf6", cyan: "#34d3ee", mag: "#d86bf0", ink: "#eaf0ff", muted: "#92a0c0", line: "rgba(160,185,255,.35)" };
  void css;

  function showOverlay(kind) {
    overlay.hidden = false;
    if (kind === "ready") { title.textContent = "Nova Run"; sub.textContent = best ? "Best score " + best : "Jump the crystals, duck the drones."; startBtn.textContent = "Start"; }
    else if (kind === "paused") { title.textContent = "Paused"; sub.textContent = "Your run is waiting."; startBtn.textContent = "Resume"; }
    else { title.textContent = "Game over"; sub.textContent = "Score " + s.score + (s.score >= best && s.score > 0 ? " (new best)" : "  Best " + best); startBtn.textContent = "Restart"; }
  }
  function hideOverlay() { overlay.hidden = true; }

  function reset() {
    s.score = 0; s.dist = 0; s.speed = 360; s.t = 0; s.nextGap = 0.9; s.obstacles = []; s.dust = []; s.flash = 0; s.shake = 0;
    Object.assign(s.p, { y: GROUND - PLAYER.h, vy: 0, ducking: false, ground: true, run: 0 });
  }
  function start() {
    if (s.state === "running") return;
    if (s.state === "over" || s.state === "ready") reset();
    s.state = "running"; s.paused = false;
    hideOverlay();
    startBtn.blur();
    last = 0;
  }
  function restart() { s.state = "ready"; start(); }
  function pause() {
    if (s.state !== "running") return;
    s.state = "paused"; showOverlay("paused");
  }
  function jump() {
    if (s.state === "ready" || s.state === "paused") { start(); }
    if (s.state === "over") { if (performance.now() - s.lastOverAt > 350) restart(); return; }
    if (s.state === "running" && s.p.ground && !s.p.ducking) { s.p.vy = JUMP_V; s.p.ground = false; tone(420, 0.14, "triangle", 0.05, 260); }
  }
  function duck(on) {
    if (s.state !== "running") { s.p.ducking = false; return; }
    s.p.ducking = on;
    if (on && !s.p.ground) s.p.vy = Math.max(s.p.vy, 900); // fast-fall
  }

  function playerBox() {
    const h = s.p.ducking && s.p.ground ? PLAYER.duckH : PLAYER.h;
    return { x: PLAYER.x + 4, y: s.p.y + (PLAYER.h - h) + 3, w: PLAYER.w - 8, h: h - 6 };
  }

  function spawn(type, x) {
    if (type === "drone") {
      s.obstacles.push({ type: "drone", x: x ?? W + 20, y: GROUND - 54, w: 38, h: 24, bob: rand() * 6 });
    } else {
      const n = 1 + Math.floor(rand() * (s.score > 200 ? 3 : 2));
      const hgt = 30 + Math.floor(rand() * 24);
      s.obstacles.push({ type: "crystal", x: x ?? W + 20, y: GROUND - hgt, w: 17 * n, h: hgt, n });
    }
  }

  function end() {
    s.state = "over"; s.lastOverAt = performance.now();
    s.flash = reduced ? 0 : 1; s.shake = reduced ? 0 : 1;
    tone(160, 0.35, "sawtooth", 0.06, -90);
    if (s.score > best) { best = s.score; try { localStorage.setItem(BEST_KEY, String(best)); } catch (_) { /* ignore */ } }
    showOverlay("over");
    live.textContent = "Game over. Score " + s.score + ". Best " + best + ".";
    if (opts.onGameOver) opts.onGameOver(s.score);
  }

  /** Advance the simulation by `ms` milliseconds (the animation loop and tests both call this). */
  function step(ms) {
    let left = Math.min(ms, 100);
    while (left > 0) {
      const dt = Math.min(left, 16.7) / 1000;
      left -= 16.7;
      if (s.state !== "running") break;
      s.t += dt;
      s.speed = Math.min(900, 360 + s.t * 9);
      s.dist += s.speed * dt;
      const newScore = Math.floor(s.dist / 12);
      if (newScore !== s.score) {
        if (Math.floor(newScore / 100) > Math.floor(s.score / 100)) tone(880, 0.1, "square", 0.025);
        s.score = newScore;
      }
      const p = s.p;
      if (!p.ground) {
        p.vy += GRAVITY * dt; p.y += p.vy * dt;
        if (p.y >= GROUND - PLAYER.h) { p.y = GROUND - PLAYER.h; p.vy = 0; p.ground = true; if (!reduced) s.dust.push({ x: PLAYER.x + 12, y: GROUND, life: 0.3 }); }
      } else p.run += dt * s.speed * 0.045;
      for (const o of s.obstacles) o.x -= s.speed * dt;
      s.obstacles = s.obstacles.filter((o) => o.x + o.w > -10);
      s.nextGap -= dt;
      const last = s.obstacles[s.obstacles.length - 1];
      if (s.nextGap <= 0 && (!last || last.x < W - 180)) {
        spawn(s.score > 250 && rand() < 0.3 ? "drone" : "crystal");
        s.nextGap = Math.max(0.55, 0.95 + rand() * 0.9 - s.t * 0.012);
      }
      const pb = playerBox();
      for (const o of s.obstacles) {
        const ob = o.type === "drone" ? { x: o.x + 3, y: o.y + 3, w: o.w - 6, h: o.h - 6 } : { x: o.x + 3, y: o.y + 4, w: o.w - 6, h: o.h - 4 };
        if (overlaps(pb, ob)) { end(); return; }
      }
      for (const d of s.dust) d.life -= dt;
      s.dust = s.dust.filter((d) => d.life > 0);
      if (s.flash > 0) s.flash = Math.max(0, s.flash - dt * 3);
    }
  }

  function draw() {
    ctx.save();
    ctx.clearRect(0, 0, W, H);
    if (s.shake > 0 && !reduced) { ctx.translate((Math.random() - 0.5) * 6 * s.shake, 0); s.shake = Math.max(0, s.shake - 0.06); }
    const sky = ctx.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0, "#070d22"); sky.addColorStop(1, "#14183f");
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = "rgba(190,210,255,.8)";
    for (const st of s.stars) {
      const x = reduced || s.state !== "running" ? st.x : ((st.x - s.dist * 0.04 * st.z) % W + W) % W;
      ctx.globalAlpha = 0.25 + st.z * 0.55;
      ctx.fillRect(x, st.y, st.z > 0.7 ? 2 : 1, st.z > 0.7 ? 2 : 1);
    }
    ctx.globalAlpha = 1;
    // ground
    ctx.strokeStyle = col.line; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(0, GROUND + 1); ctx.lineTo(W, GROUND + 1); ctx.stroke();
    ctx.fillStyle = "rgba(160,185,255,.28)";
    const off = reduced ? 0 : s.dist % 60;
    for (let x = -off; x < W; x += 60) ctx.fillRect(x + 10, GROUND + 10, 16, 2);
    for (let x = -off * 1.6; x < W; x += 90) ctx.fillRect(x + 40, GROUND + 22, 8, 2);
    // obstacles
    for (const o of s.obstacles) {
      if (o.type === "crystal") {
        for (let i = 0; i < o.n; i++) {
          const bx = o.x + i * 17, hh = o.h * (i === 1 ? 1 : 0.82);
          const g = ctx.createLinearGradient(0, GROUND - hh, 0, GROUND);
          g.addColorStop(0, col.cyan); g.addColorStop(1, col.violet);
          ctx.fillStyle = g;
          ctx.beginPath(); ctx.moveTo(bx, GROUND); ctx.lineTo(bx + 8.5, GROUND - hh); ctx.lineTo(bx + 17, GROUND); ctx.closePath(); ctx.fill();
          ctx.fillStyle = "rgba(255,255,255,.35)";
          ctx.beginPath(); ctx.moveTo(bx + 8.5, GROUND - hh); ctx.lineTo(bx + 11, GROUND - hh * 0.35); ctx.lineTo(bx + 8.5, GROUND); ctx.closePath(); ctx.fill();
        }
      } else {
        const bob = reduced ? 0 : Math.sin(s.t * 8 + o.bob) * 2;
        const y = o.y + bob;
        ctx.fillStyle = col.mag; ctx.beginPath(); ctx.ellipse(o.x + 19, y + 14, 18, 9, 0, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = "#2a1450"; ctx.fillRect(o.x + 8, y + 11, 22, 5);
        ctx.fillStyle = col.cyan; ctx.fillRect(o.x + 16, y + 12, 6, 3);
        ctx.strokeStyle = col.ink; ctx.lineWidth = 2; ctx.beginPath();
        const rot = reduced ? 8 : 8 + Math.sin(s.t * 40) * 8;
        ctx.moveTo(o.x + 19 - rot, y + 3); ctx.lineTo(o.x + 19 + rot, y + 3); ctx.moveTo(o.x + 19, y + 3); ctx.lineTo(o.x + 19, y + 7); ctx.stroke();
      }
    }
    // Nova
    const p = s.p, ducking = p.ducking && p.ground;
    const bh = ducking ? PLAYER.duckH : PLAYER.h, by = p.y + (PLAYER.h - bh), bx = PLAYER.x;
    const bg = ctx.createLinearGradient(bx, by, bx + PLAYER.w, by + bh);
    bg.addColorStop(0, col.blue); bg.addColorStop(1, col.violet);
    ctx.fillStyle = bg;
    ctx.beginPath(); ctx.roundRect ? ctx.roundRect(bx, by, PLAYER.w, bh - 6, 9) : ctx.rect(bx, by, PLAYER.w, bh - 6); ctx.fill();
    ctx.fillStyle = "#06122e"; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(bx + 13, by + 5, 15, ducking ? 7 : 10, 4) : ctx.rect(bx + 13, by + 5, 15, 10); ctx.fill();
    ctx.fillStyle = col.cyan; ctx.fillRect(bx + 21, by + 8, 5, ducking ? 2 : 4);
    if (!ducking) { ctx.strokeStyle = col.cyan; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(bx + 8, by); ctx.lineTo(bx + 8, by - 6); ctx.stroke(); ctx.fillStyle = col.mag; ctx.beginPath(); ctx.arc(bx + 8, by - 7, 2.5, 0, 7); ctx.fill(); }
    ctx.fillStyle = "#c9d8ff";
    const swing = p.ground && s.state === "running" && !reduced ? Math.sin(p.run) * 5 : 0;
    ctx.fillRect(bx + 6 + swing, by + bh - 7, 7, 7);
    ctx.fillRect(bx + 17 - swing, by + bh - 7, 7, 7);
    ctx.fillStyle = "rgba(160,185,255,.5)";
    for (const d of s.dust) ctx.fillRect(d.x - (0.3 - d.life) * 40, d.y - 3 - (0.3 - d.life) * 10, 4, 3);
    // HUD
    ctx.fillStyle = col.ink; ctx.font = "600 15px ui-sans-serif, system-ui, sans-serif"; ctx.textAlign = "right";
    ctx.fillText(String(s.score).padStart(5, "0"), W - 14, 24);
    ctx.fillStyle = col.muted; ctx.font = "13px ui-sans-serif, system-ui, sans-serif";
    ctx.fillText("Best " + String(best).padStart(5, "0"), W - 14, 44);
    if (s.flash > 0) { ctx.fillStyle = "rgba(255,255,255," + (s.flash * 0.25) + ")"; ctx.fillRect(0, 0, W, H); }
    ctx.restore();
  }

  let raf = 0, last = 0, destroyed = false;
  function frame(ts) {
    if (destroyed) return;
    if (!last) last = ts;
    step(ts - last); last = ts;
    draw();
    raf = requestAnimationFrame(frame);
  }

  const onKey = (e) => {
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    if (e.code === "Space" || e.code === "ArrowUp" || e.code === "KeyW") {
      if (e.target && e.target.tagName === "BUTTON" && e.code === "Space" && e.target !== startBtn) return;
      e.preventDefault(); if (!e.repeat) jump();
    } else if (e.code === "ArrowDown" || e.code === "KeyS") { e.preventDefault(); duck(true); }
  };
  const onKeyUp = (e) => { if (e.code === "ArrowDown" || e.code === "KeyS") duck(false); };
  const onPointer = (e) => { if (e.target === duckBtn || e.target === startBtn) return; e.preventDefault(); jump(); };
  const onDuckDown = (e) => { e.preventDefault(); duck(true); };
  const onDuckUp = () => duck(false);
  const onVis = () => { if (document.hidden) pause(); };
  startBtn.addEventListener("click", () => { if (s.state === "over") restart(); else start(); });
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", onKeyUp);
  canvas.addEventListener("pointerdown", onPointer);
  duckBtn.addEventListener("pointerdown", onDuckDown);
  duckBtn.addEventListener("pointerup", onDuckUp);
  duckBtn.addEventListener("pointerleave", onDuckUp);
  duckBtn.addEventListener("pointercancel", onDuckUp);
  document.addEventListener("visibilitychange", onVis);
  window.addEventListener("blur", pause);

  showOverlay("ready");
  draw();
  raf = requestAnimationFrame(frame);

  return {
    start, restart, jump, duck, pause, step, spawn, draw,
    setSound(on) { sound = !!on; },
    getState() { return { state: s.state, score: s.score, best, speed: s.speed, player: { y: s.p.y, vy: s.p.vy, ducking: s.p.ducking, onGround: s.p.ground }, obstacles: s.obstacles.map((o) => ({ type: o.type, x: o.x, y: o.y, w: o.w, h: o.h })) }; },
    focusStart() { startBtn.focus(); },
    destroy() {
      destroyed = true; cancelAnimationFrame(raf);
      window.removeEventListener("keydown", onKey); window.removeEventListener("keyup", onKeyUp); window.removeEventListener("blur", pause);
      document.removeEventListener("visibilitychange", onVis);
      wrap.remove();
      try { audio && audio.close(); } catch (_) { /* ignore */ }
    },
  };
}
