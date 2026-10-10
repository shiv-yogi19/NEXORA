import sys
from playwright.sync_api import sync_playwright
S=sys.argv[1]  # scratch dir for screenshots and temp files; import os; PW=os.environ["NEXORA_TEST_PASSWORD"]; B="http://localhost:8080/?api=http://localhost:8787"
routes=["home","movies","music","photos","documents","uploads","shares","storage","server","activity","settings","about"]
with sync_playwright() as p:
    b=p.chromium.launch()
    for w,hh in [(360,740),(390,844),(430,932),(768,1024),(1024,768),(1440,900)]:
        ctx=b.new_context(viewport={"width":w,"height":hh}, reduced_motion="reduce")
        pg=ctx.new_page(); pg.goto(B); pg.wait_for_selector("#intro:not([hidden])")
        pg.wait_for_selector("#login-screen:not([hidden])", timeout=6000)  # reduced motion => short intro
        if w in (360,768): pg.screenshot(path=f"{S}/r_login_{w}.png")
        pg.fill("#login-password",PW); pg.click("#login-submit"); pg.wait_for_selector("#app:not([hidden])"); pg.wait_for_selector(".stats")
        bad=[]
        for r in routes:
            pg.goto(f"{B}#/{r}"); pg.wait_for_timeout(700)
            ov=pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
            if ov>1: bad.append((r,ov))
            if r in("home","music","server") and w in (360,768,1024): pg.screenshot(path=f"{S}/r_{r}_{w}.png")
        print(w, "overflow routes:", bad or "none")
        ctx.close()
    b.close()
