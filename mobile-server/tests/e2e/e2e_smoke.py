import sys, json
from playwright.sync_api import sync_playwright
S=sys.argv[1]  # scratch dir for screenshots and temp files; import os; PW=os.environ["NEXORA_TEST_PASSWORD"]
URL="http://localhost:8080/?api=http://localhost:8787"
errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    ctx=b.new_context(viewport={"width":1440,"height":900}, accept_downloads=True)
    pg=ctx.new_page()
    pg.on("console", lambda m: errs.append(("console."+m.type, m.text)) if m.type in("error","warning") else None)
    pg.on("pageerror", lambda e: errs.append(("pageerror", str(e))))
    pg.on("requestfailed", lambda r: errs.append(("reqfail", r.url, r.failure)))
    pg.goto(URL)
    pg.wait_for_selector("#intro:not([hidden])")
    pg.screenshot(path=S+"/s_intro.png")
    pg.wait_for_timeout(3000)
    print("credit visible during intro:", "Shiv Yogi" in pg.inner_text("#intro"))
    pg.click("#intro-skip")
    pg.wait_for_selector("#login-screen:not([hidden])")
    pg.screenshot(path=S+"/s_login.png")
    pg.fill("#login-password","wrong-password-xx"); pg.click("#login-submit")
    pg.wait_for_selector("#login-msg:not(:empty)")
    print("wrong pw msg:", pg.inner_text("#login-msg"))
    print("app hidden after wrong:", pg.is_hidden("#app"))
    pg.fill("#login-password",PW); pg.click("#login-submit")
    pg.wait_for_selector("#app:not([hidden])", timeout=8000)
    pg.wait_for_selector(".stats")
    print("stats:", pg.inner_text(".stats").replace("\n"," "))
    pg.screenshot(path=S+"/s_home.png")
    for r in ["movies","music","photos","documents","downloads","favorites","watchlist","recent","uploads","shares","storage","server","activity","settings","about"]:
        pg.goto(f"http://localhost:8080/?api=http://localhost:8787#/{r}")
        pg.wait_for_timeout(900)
        t=pg.inner_text("#main")[:90].replace("\n"," | ")
        print(r, "->", t)
        pg.screenshot(path=f"{S}/s_{r}.png")
    print("ERRORS:", json.dumps(errs,indent=1)[:3000])
    b.close()
