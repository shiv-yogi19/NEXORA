import sys, os, signal, subprocess, time
from playwright.sync_api import sync_playwright
S=sys.argv[1]  # scratch dir for screenshots and temp files; import os; PW=os.environ["NEXORA_TEST_PASSWORD"]; B="http://localhost:8080/?api=http://localhost:8787"
def ok(n,c,x=""): print(("PASS " if c else "FAIL ")+n,x)
def server_pid(): return int(open(S+"/server.pid").read())
def start():
    env=dict(os.environ, NEXORA_PRIVATE_DIR=S+"/priv", NEXORA_LIBRARY_ROOT=S+"/lib")
    pr=subprocess.Popen(["python3","/home/claude/NEXORA/mobile-server/nexora_server.py","run"],stdout=open(S+"/server.log","a"),stderr=subprocess.STDOUT,env=env,start_new_session=True)
    open(S+"/server.pid","w").write(str(pr.pid)); return pr
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":1280,"height":800}); pg=ctx.new_page()
    pg.goto(B); pg.click("#intro-skip"); pg.wait_for_selector("#login-screen:not([hidden])")
    pg.fill("#login-password",PW); pg.click("#login-submit"); pg.wait_for_selector("#app:not([hidden])"); pg.wait_for_selector(".stats")
    pg.evaluate("()=>{window.__marker='same-page'}")
    os.kill(server_pid(), signal.SIGTERM); time.sleep(1.5)
    pg.click("#side-nav a[data-nav=photos]")
    pg.wait_for_selector("#offline-screen:not([hidden])", timeout=15000)
    txt=pg.inner_text("#offline-screen"); print(txt[:700].replace("\n"," | "))
    ok("offline screen text", "NEXORA is Offline" in txt and "Retry Connection" in txt)
    pg.screenshot(path=S+"/s_offline.png")
    pg.click("#offline-retry"); pg.wait_for_timeout(2500)
    ok("retry while down stays offline", pg.is_visible("#offline-screen"))
    pg.click("#offline-play"); pg.wait_for_selector("#game-panel:not([hidden])")
    pg.keyboard.press("Space"); pg.wait_for_timeout(1800)
    pg.screenshot(path=S+"/s_game.png")
    ok("game canvas present", pg.query_selector("#game-mount canvas") is not None)
    pg.click("#game-back"); pg.wait_for_timeout(300)
    # restart server; recovery without reload
    start(); time.sleep(3)
    pg.click("#offline-retry")
    try:
        pg.wait_for_selector("#offline-screen", state="hidden", timeout=20000); rec=True
    except Exception: rec=False
    ok("recovers without reload", rec)
    ok("same page instance (no reload)", pg.evaluate("()=>window.__marker")=="same-page")
    pg.wait_for_timeout(1500); print(pg.inner_text("#main")[:120].replace("\n"," | "))
    b.close()
