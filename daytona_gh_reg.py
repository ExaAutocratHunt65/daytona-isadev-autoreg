# Daytona autoreg via GitHub OAuth — uses gh pool (login/password/totp).
# Usage: env -u PYTHONPATH python311 daytona_gh_reg.py N
# Flow: app.daytona.io/dashboard/onboarding -> AuthKit sign-up -> Continue with GitHub
#       -> github.com login -> TOTP -> redirect back -> save state + dashboard probe.
import asyncio, json, os, random, re, sys, time, traceback

import pyotp

HERE = os.path.dirname(os.path.abspath(__file__))
GH_POOL = os.path.join(HERE, "gh_accounts.json")
USED_FILE = os.path.join(HERE, "gh_used.json")
ACC_FILE = os.path.join(HERE, "gh_accounts.jsonl")
LOG = os.path.join(HERE, "gh_progress.log")
ENTRY = "https://app.daytona.io/dashboard/onboarding"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1


def log(msg):
    line = time.strftime("%H:%M:%S") + " " + msg
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_pool():
    pool = json.load(open(GH_POOL, encoding="utf-8"))
    used = set()
    if os.path.exists(USED_FILE):
        used = set(json.load(open(USED_FILE, encoding="utf-8")))
    avail = [a for a in pool if a.get("login") not in used]
    return pool, used, avail


def mark_used(login):
    used = set()
    if os.path.exists(USED_FILE):
        used = set(json.load(open(USED_FILE, encoding="utf-8")))
    used.add(login)
    json.dump(sorted(used), open(USED_FILE, "w", encoding="utf-8"))


async def dump(page, tag):
    try:
        info = await page.evaluate("""() => ({url:location.href, title:document.title,
            body:document.body.innerText.slice(0,300)})""")
        log(f"[{tag}] {info['url'][:110]} | {info['title'][:50]} | {info['body'][:160]!r}")
        return info
    except Exception as e:
        log(f"[{tag}] dump err {str(e)[:80]}")
        return None


async def gh_login(page, acc):
    """Handle github.com login + TOTP. Returns True on success."""
    await page.wait_for_load_state("domcontentloaded", timeout=45000)
    url = page.url
    if "github.com" not in url:
        log("[gh] not on github: " + url[:100])
        return False
    # remember OAuth return_to so we can resume if GH dumps us at /dashboard
    m = re.search(r"return_to=([^&]+)", url)
    if m:
        import urllib.parse
        acc["_return_to"] = "https://github.com" + urllib.parse.unquote(m.group(1))
        log("[gh] saved return_to: " + acc["_return_to"][:120])
    # login form
    try:
        await page.wait_for_selector('input[name="login"]', timeout=20000)
        await page.fill('input[name="login"]', acc["login"])
        await page.fill('input[name="password"]', acc["password"])
        await page.click('input[type=submit]')
        log(f"[gh] creds submitted for {acc['login']}")
    except Exception as e:
        # maybe already session or different page
        log("[gh] login form err: " + str(e)[:100])
    await asyncio.sleep(4)
    # 2FA
    for attempt in range(12):
        url = page.url
        log(f"[gh] loop{attempt} url=" + url[:100])
        if "github.com" not in url:
            log("[gh] left github (authorized): " + url[:100])
            return True
        if "sessions/two-factor" in url:
            code = pyotp.TOTP(acc["totp"]).now()
            log("[gh] filling TOTP " + code)
            try:
                await page.fill('input[name="app_otp"]', code, timeout=8000)
                log("[gh] TOTP filled")
            except Exception as e:
                log("[gh] totp fill err: " + str(e)[:120])
            await asyncio.sleep(2)
            try:
                btn = page.locator('button[type=submit]').first
                await btn.click(timeout=6000, no_wait_after=True)
                log("[gh] TOTP submit clicked")
            except Exception as e:
                log("[gh] totp click err (maybe auto-submitted): " + str(e)[:120])
            await asyncio.sleep(4)
            continue
        if "/dashboard" in url:
            if acc.get("_return_to"):
                log("[gh] on dashboard, resuming OAuth")
                try:
                    await page.goto(acc["_return_to"], wait_until="commit", timeout=30000)
                    log("[gh] resume nav committed, url=" + page.url[:110])
                except Exception as e:
                    log("[gh] resume err: " + str(e)[:100])
                await asyncio.sleep(4)
                continue
        if "authorize" in url.lower() or "/oauth/authorize" in url:
            # authorize app screen
            try:
                b = page.locator('button[name="authorize"], button[type=submit], input[type=submit]').first
                await b.click(timeout=8000, no_wait_after=True)
                log("[gh] authorize clicked")
            except Exception as e:
                log("[gh] authorize err: " + str(e)[:120])
            await asyncio.sleep(4)
            continue
        body = ""
        try:
            body = await asyncio.wait_for(page.evaluate("document.body.innerText"), timeout=8)
        except Exception:
            pass
        low = body.lower()
        if "flagged" in low and "cannot authorize" in low:
            log(f"[gh] FLAGGED account {acc['login']} — cannot authorize OAuth apps")
            acc["_flagged"] = True
            return False
        if "incorrect" in low or "invalid" in low:
            log(f"[gh] BAD CREDS for {acc['login']}: {body[:150]!r}")
            return False
        await asyncio.sleep(2)
    # loop ended still on github — if we landed on /dashboard, resume OAuth manually
    if "github.com" in page.url and acc.get("_return_to"):
        log("[gh] resuming OAuth via return_to")
        try:
            await page.goto(acc["_return_to"], wait_until="commit", timeout=30000)
            await asyncio.sleep(3)
            # authorize screen?
            if "authorize" in page.url.lower() or await page.locator('button[type=submit]').count():
                try:
                    await page.locator('button[name="authorize"], button[type=submit]').first.click(timeout=8000)
                    log("[gh] authorize clicked (resume)")
                except Exception as e:
                    log("[gh] authorize err (resume): " + str(e)[:100])
                await asyncio.sleep(5)
        except Exception as e:
            log("[gh] resume nav err: " + str(e)[:100])
    return "github.com" not in page.url


async def run_one(acc, idx):
    from patchright.async_api import async_playwright
    login = acc["login"]
    log(f"=== [{idx}] GH {login} <{acc['email']}>")
    rec = {"gh_login": login, "gh_email": acc["email"], "ts": int(time.time()), "stage": "start"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        ctx = await browser.new_context(viewport={"width": 1366, "height": 900}, user_agent=UA, locale="en-US")
        page = await ctx.new_page()
        page.on("framenavigated", lambda f: log("nav: " + f.url[:120]) if f == page.main_frame else None)
        try:
            await page.goto(ENTRY, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_selector("input[type=email]", timeout=45000)
            await dump(page, "s0")

            # switch to sign-up if sign-in page
            log("[0a] reading body")
            body0 = await page.evaluate("document.body.innerText")
            log("[0b] body len " + str(len(body0)))
            if "Don't have an account" in body0:
                log("[0c] clicking sign-up link")
                link = page.get_by_role("link", name=re.compile("sign up", re.I)).first
                await link.click(timeout=8000)
                log("[0d] sign-up link clicked")
                await asyncio.sleep(3)
            log("[0e] locating GitHub OAuth link")
            try:
                await page.wait_for_selector('a[href*="GitHubOAuth"]', timeout=25000)
            except Exception as e:
                log("[0e] no GitHubOAuth anchor: " + str(e)[:100])
            href = await page.evaluate("""() => {
                const a = document.querySelector('div[data-method="github"] a') ||
                          document.querySelector('a[href*="provider=GitHubOAuth"]');
                return a ? a.href : null;
            }""")
            log("[0f] oauth href: " + (href or "NONE")[:130])
            if href:
                await page.goto(href, wait_until="domcontentloaded", timeout=60000)
                log("[0g] navigated via href, url=" + page.url[:110])
            else:
                btn = page.locator('a:has-text("GitHub"), button:has-text("GitHub")').first
                await btn.click(timeout=15000, no_wait_after=True)
                log("[0g] fallback click")
            ctx.on("page", lambda p: log("[popup] new page: " + p.url[:110]))
            try:
                await btn.click(timeout=15000, no_wait_after=True)
                log("[0h] click issued ok")
            except Exception as e2:
                log("[0g] click failed: " + str(e2)[:150])
                try:
                    await btn.evaluate("el => el.click()")
                    log("[0h] js-click issued")
                except Exception as e3:
                    log("[0h] js-click failed: " + str(e3)[:120])
            # follow same-tab nav OR popup
            t_end = time.time() + 40
            while time.time() < t_end:
                pages = ctx.pages
                if len(pages) > 1 and pages[-1] != page:
                    page = pages[-1]
                    log("[0i] switched to popup: " + page.url[:110])
                    break
                if "github.com" in page.url:
                    log("[0i] same-tab github: " + page.url[:110])
                    break
                await asyncio.sleep(1)
            log("[1] after click, url=" + page.url[:110])
            await asyncio.sleep(3)
            rec["stage"] = "github"

            ok = await gh_login(page, acc)
            if not ok:
                rec["stage"] = "gh_flagged" if acc.get("_flagged") else "gh_failed"
                info = await dump(page, "gh-fail")
                b = (info or {}).get("body", "").lower()
                if "flagged" in b and "cannot authorize" in b:
                    rec["stage"] = "gh_flagged"
                if rec["stage"] in ("gh_flagged", "gh_failed"):
                    mark_used(login)
                return rec
            rec["stage"] = "authorized"

            # wait redirect back to app.daytona.io
            t_end = time.time() + 60
            while time.time() < t_end:
                for pg in ctx.pages:
                    if pg.url.startswith("https://app.daytona.io"):
                        page = pg
                        break
                if page.url.startswith("https://app.daytona.io"):
                    break
                await asyncio.sleep(2)
            await asyncio.sleep(6)
            rec["final_url"] = page.url
            info = await dump(page, "final")
            body = (info or {}).get("body", "")
            if "could not validate" in body.lower():
                rec["stage"] = "email_block"
            elif page.url.startswith("https://app.daytona.io"):
                rec["stage"] = "REGISTERED"
            else:
                rec["stage"] = "stuck"

            # probe dashboard for credits text
            if rec["stage"] == "REGISTERED":
                try:
                    await page.goto("https://app.daytona.io/dashboard", wait_until="domcontentloaded", timeout=45000)
                    await asyncio.sleep(5)
                    await dump(page, "dash")
                except Exception:
                    pass
            # save state for relogin
            state = await ctx.storage_state()
            sf = os.path.join(HERE, f"gh_state_{login}_{int(time.time())}.json")
            with open(sf, "w", encoding="utf-8") as f:
                json.dump(state, f)
            rec["storage_state"] = sf
            rec["cookies"] = sorted({c["name"] for c in state.get("cookies", []) if c.get("name")})
            if rec["stage"] in ("REGISTERED", "email_block"):
                mark_used(login)
        except Exception:
            rec["stage"] = "error"
            rec["error"] = traceback.format_exc()[-400:]
            log("ERROR: " + rec["error"])
        finally:
            with open(ACC_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            try:
                await browser.close()
            except Exception:
                pass
    return rec


async def main():
    pool, used, avail = load_pool()
    log(f"pool={len(pool)} used={len(used)} avail={len(avail)} N={N}")
    done = 0
    for i, acc in enumerate(avail[:N]):
        rec = await run_one(acc, i + 1)
        log(f"=== [{i+1}] RESULT {rec.get('gh_login')}: {rec.get('stage')}")
        if rec.get("stage") == "REGISTERED":
            done += 1
        if i + 1 < N:
            await asyncio.sleep(random.uniform(8, 20))
    log(f"DONE registered={done}/{N}")


def _crashlog(msg):
    with open(os.path.join(HERE, "gh_crash.log"), "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S") + " " + msg + chr(10))

import atexit, signal
atexit.register(lambda: _crashlog("exit pid=" + str(os.getpid())))
def _sig(signum, frame):
    _crashlog(f"signal {signum}")
    os._exit(1)
for _s in set([signal.SIGTERM, signal.SIGINT] + ([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else [])):
    try:
        signal.signal(_s, _sig)
    except Exception:
        pass

if __name__ == "__main__":
    _crashlog("start pid=" + str(os.getpid()))
    log(f"START pid={os.getpid()}")
    try:
        asyncio.run(main())
    except BaseException:
        _crashlog("tb: " + traceback.format_exc()[-600:])
        raise
