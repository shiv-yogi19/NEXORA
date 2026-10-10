from playwright.sync_api import sync_playwright
JS = """
async () => {
  const { createGame } = await import('/js/offline-game.js');
  const mount = document.createElement('div'); document.body.append(mount);
  let overs = 0;
  const g = createGame(mount, { reducedMotion: true, seed: 12345, onGameOver: () => { overs++; } });
  const out = {};
  g.start();
  out.running = g.getState().state;
  for (let i = 0; i < 30; i++) g.step(16);
  out.scoreAdvances = g.getState().score > 0;
  g.jump(); g.step(16); const up = g.getState().player;
  out.jumpLeavesGround = !up.onGround && up.y < 200 ? true : !up.onGround;
  for (let i = 0; i < 80; i++) g.step(16);
  out.landsAgain = g.getState().player.onGround;
  let frames = 0;
  while (g.getState().state === 'running' && frames < 20000) { g.step(16); frames++; }
  out.collisionEndsGame = g.getState().state === 'over' && overs === 1;
  out.framesUntilDeath = frames;
  g.restart(); out.restartResets = g.getState().state === 'running' && g.getState().score < 5;
  g.pause(); out.paused = g.getState().state === 'paused';
  g.destroy();
  return out;
}
"""
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(); pg.goto("http://localhost:8080/?api=http://localhost:8787")
    print(pg.evaluate(JS)); b.close()
