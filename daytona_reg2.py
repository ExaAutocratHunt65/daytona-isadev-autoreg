# Daytona autoreg v2 — hardened: detached, per-step file log, no silent death.
import asyncio, json, os, random, re, string, sys, time, traceback, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ACC_FILE = os.path.join(HERE, "accounts.jsonl")
LOG = os.path.join(HERE, "progress.log")
ENTRY = "https://app.daytona.io/dashboard/onboarding"
VOIDASH = "https://api.voidash.com/api/v1"
DOMAIN = os.environ.get("DTN_VOIDASH_DOMAIN", "voidash.bond")
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


def voidash_inbox(domain=DOMAIN):
    body = json.dumps({"domain": domain}).encode()
    req = urllib.request.Request(VOIDASH + "/inboxes", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read().decode())
    data = resp.get("data", resp)
    sk = data.get("session_key") or data.get("sessionKey")
    addr = data.get("address")
    if not sk or not addr:
        raise RuntimeError("voidash bad resp: " + json.dumps(resp)[:200])
    return addr, sk


def voidash_wait(sk, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(VOIDASH + "/messages",
                                         headers={"Authorization": "Bearer " + sk})
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode())
            msgs = resp.get("messages", resp.get("data", resp)) if isinstance(resp, dict) else resp
            if isinstance(msgs, list) and msgs:
                log("RAW MAIL: " + json.dumps(msgs)[:600])
                for m in msgs:
                    if not isinstance(m, dict):
                        continue
                    otp = m.get("otp_code") or (m.get("metadata") or {}).get("otp_code")
                    if otp:
                        return str(otp), json.dumps(m)[:300]
                for m in msgs:
                    if not isinstance(m, dict):
                        continue
                    body = (m.get("html") or "") + (m.get("text") or "") + (m.get("body") or "")
                    plain = re.sub(r"<[^>]+>", " ", body)
                    mc = re.search(r"(?:code|Code|CODE)[^0-9]{0,40}(\d{6})", plain) or re.search(r"\b(\d{6})\b", plain)
                    if mc:
                        return mc.group(1), plain[:300]
                log("mail seen, no code yet: " + json.dumps(msgs)[:200])
        except Exception as e:
            log("mail poll err: " + str(e)[:80])
        time.sleep(5)
    return None, ""


GMAIL_USER = "baradok609@gmail.com"
GMAIL_APP_PW = os.environ.get("GMAIL_APP_PW", "")


TONLINE_POOL = r"C:/Users/User/Desktop/avtoreg/working_mails.txt"

def reforrm_wait_code(to_email, timeout=240):
    """Read Daytona code from baradok609@gmail.com inbox (reforrm.me catch-all forward)."""
    import imaplib, email as emaillib, time as _t
    GW_USER = "baradok609@gmail.com"
    GW_PW = "udjahoqgagvaojhz"
    t_end = _t.time() + timeout
    local = to_email.split("@")[0]
    while _t.time() < t_end:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            m.login(GW_USER, GW_PW)
            found = None
            boxes = ['"INBOX"', '"[Gmail]/&BCEEPwQwBDw-"']
            try:
                _, blist = m.list()
                for b in blist:
                    s = b.decode("utf-8", "ignore")
                    nm = s.split(' "/" ')[-1] if ' "/" ' in s else s.split(' "\\" ')[-1]
                    nm = '"' + nm.strip('"') + '"'
                    if nm not in boxes:
                        boxes.append(nm)
            except Exception:
                pass
            for box in boxes:
                st, _ = m.select(box, readonly=False)
                if st != "OK":
                    continue
                _, d2 = m.search(None, '(FROM "workos-mail.com")')
                for i in reversed(d2[0].split()[-10:]):
                    _, md = m.fetch(i, "(RFC822)")
                    msg = emaillib.message_from_bytes(md[0][1])
                    to = msg.get("To", "") + msg.get("Delivered-To", "") + msg.get("X-Original-To", "")
                    if local.lower() not in to.lower():
                        continue
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ("text/plain", "text/html"):
                                body += part.get_payload(decode=True).decode("utf-8", "ignore")
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", "ignore")
                    mc = re.search(r"\b(\d{6})\b", body)
                    if mc:
                        found = mc.group(1)
                        break
                if found:
                    break
            if found:
                m.logout()
                return found, None
            m.logout()
        except Exception as e:
            log("reforrm imap err: " + str(e)[:90])
        _t.sleep(6)
    return None, None


def tonline_next():
    """Pick next unused t-online.de email:password from pool."""
    import os
    used_f = os.path.join(HERE, "tonline_used.txt")
    used = set()
    if os.path.exists(used_f):
        used = set(l.strip() for l in open(used_f, encoding="utf-8"))
    for line in open(TONLINE_POOL, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if len(parts) < 2:
            continue
        em, pw = parts[0].strip(), parts[1].strip()
        if em.endswith("@t-online.de") and em not in used:
            with open(used_f, "a", encoding="utf-8") as f:
                f.write(em + chr(10))
            return em, pw
    return None, None

def tonline_wait_code(em, pw, timeout=240):
    import imaplib, email as emaillib, re, time as _t
    t_end = _t.time() + timeout
    while _t.time() < t_end:
        for host in ("secureimap.t-online.de", "imap.t-online.de"):
            try:
                m = imaplib.IMAP4_SSL(host, 993, timeout=25)
                m.login(em, pw)
                m.select("INBOX")
                _, data = m.search(None, "ALL")
                ids = data[0].split()
                for i in reversed(ids[-15:]):
                    _, md = m.fetch(i, "(RFC822)")
                    raw = md[0][1]
                    msg = emaillib.message_from_bytes(raw)
                    if "daytona" not in (msg.get("From","") + msg.get("Subject","")).lower():
                        continue
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body += part.get_payload(decode=True).decode("utf-8","ignore")
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8","ignore")
                    mc = re.search(r'\b(\d{6})\b', body)
                    m2 = re.search(r'(https://\S*verify\S*)', body)
                    if mc or m2:
                        m.logout()
                        return (mc.group(1) if mc else None), (m2.group(1) if m2 else None)
                m.logout()
            except Exception as e:
                log("tonline imap err: " + str(e)[:80])
        _t.sleep(6)
    return None, None

def gmail_alias(tag):
    return GMAIL_USER.replace("@", "+" + tag + "@")


def gmail_wait_code(tag, timeout=300):
    import imaplib, email as emaillib
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            m.login(GMAIL_USER, GMAIL_APP_PW)
            m.select("INBOX")
            typ, data = m.search(None, "UNSEEN")
            for num in data[0].split():
                typ, msgd = m.fetch(num, "(RFC822)")
                raw = msgd[0][1]
                msg = emaillib.message_from_bytes(raw)
                to = msg.get("To", "")
                if tag.lower() not in to.lower():
                    continue
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", "ignore")
                            break
                    if not body:
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                body = re.sub(r"<[^>]+>", " ", part.get_payload(decode=True).decode("utf-8", "ignore"))
                                break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", "ignore")
                mc = re.search(r"(?:code|Code)[^0-9]{0,60}(\d{6})", body) or re.search(r"(\d{6})", body)
                m.logout()
                if mc:
                    return mc.group(1), body[:200]
            m.logout()
        except Exception as e:
            log("imap err: " + str(e)[:100])
        time.sleep(6)
    return None, ""


def gen_password():
    return "".join(random.choices(string.ascii_letters, k=12)) + random.choice("!@#$%") + str(random.randint(10, 99))


async def set_react_input(page, selector, value):
    await page.evaluate("""([sel, val]) => {
        const el = document.querySelector(sel);
        if (!el) throw new Error("no input " + sel);
        const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
        setter.call(el, val);
        el.dispatchEvent(new Event("input", {bubbles: true}));
        el.dispatchEvent(new Event("change", {bubbles: true}));
    }""", [selector, value])


async def dump_state(page, tag):
    try:
        info = await page.evaluate("""() => ({
            url: location.href,
            title: document.title,
            inputs: Array.from(document.querySelectorAll('input')).map(i=>i.type+':'+(i.name||i.id||i.placeholder||'?')),
            buttons: Array.from(document.querySelectorAll('button')).map(b=>b.textContent.trim()).filter(Boolean),
            body: document.body.innerText.slice(0,400)
        })""")
        log(f"[{tag}] url={info['url'][:110]}")
        log(f"[{tag}] title={info['title'][:70]} inputs={info['inputs'][:10]} buttons={info['buttons'][:10]}")
        log(f"[{tag}] body={info['body'][:250]!r}")
        return info
    except Exception as e:
        log(f"[{tag}] dump err: " + str(e)[:120])
        return None


async def click_by_text(page, kws):
    try:
        btns = page.locator("button")
        n = await btns.count()
        for i in range(n):
            b = btns.nth(i)
            try:
                if not await b.is_visible():
                    continue
                txt = (await b.inner_text()).strip().lower()
                if any(k in txt for k in kws):
                    await b.click(timeout=8000)
                    return txt
            except Exception:
                continue
    except Exception as e:
        log("click err: " + str(e)[:100])
    await page.keyboard.press("Enter")
    return "<enter>"


async def run_one(idx):
    from patchright.async_api import async_playwright
    provider = os.environ.get("DTN_PROVIDER", "gmail")
    if provider == "gmail":
        tag = "dtn" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        email = gmail_alias(tag)
        sk = None
    elif provider == "reforrm":
        tag = None
        import string as _st
        local = "dtn" + "".join(random.choices(_st.ascii_lowercase + _st.digits, k=7))
        email = local + "@" + os.environ.get("DTN_DOMAIN","reforrm.me")
        sk = None
    elif provider == "tonline":
        tag = None
        email, topw = tonline_next()
        sk = None
        if not email:
            log("NO t-online emails left")
            return {"stage": "no_email"}
        log("t-online mail: " + email)
    else:
        email, sk = voidash_inbox()
    pw = gen_password()
    log(f"=== account {idx}: {email}")
    rec = {"email": email, "password": pw, "voidash_sk": sk, "ts": int(time.time()), "stage": "start"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        ctx = await browser.new_context(viewport={"width": 1366, "height": 900}, user_agent=UA, locale="en-US")
        page = await ctx.new_page()
        page.on("framenavigated", lambda f: log("nav: " + f.url[:130]) if f == page.main_frame else None)
        try:
            await page.goto(ENTRY, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_selector("input[type=email]", timeout=45000)
            await asyncio.sleep(2)
            await dump_state(page, "s0-form")

            # if this is the Sign-in page, switch to Sign up first
            try:
                body0 = await page.evaluate("document.body.innerText")
            except Exception:
                body0 = ""
            if "Don't have an account" in body0 or "Sign up" in body0 and "Sign in" in body0:
                try:
                    link = page.get_by_role("link", name=re.compile("sign up", re.I)).first
                    await link.click(timeout=8000)
                    log("[0] clicked 'Sign up' link")
                except Exception as e:
                    log("[0] sign-up link click failed: " + str(e)[:100])
                await asyncio.sleep(3)
                await dump_state(page, "s0b-signup-form")
            await page.wait_for_selector("input[type=email]", timeout=20000)
            await set_react_input(page, "input[type=email]", email)
            rec["stage"] = "email"
            t = await click_by_text(page, ("continue", "sign up", "next", "create"))
            log(f"[1] email clicked: {t}")
            await asyncio.sleep(4)
            await dump_state(page, "s1-after-email")

            # password page
            got_pw = False
            for _ in range(12):
                try:
                    await page.wait_for_selector("input[type=password]", timeout=5000, state="visible")
                    got_pw = True
                    break
                except Exception:
                    await asyncio.sleep(1)
            if got_pw:
                await asyncio.sleep(1)
                await set_react_input(page, "input[type=password]", pw)
                rec["stage"] = "password"
                t = await click_by_text(page, ("continue", "sign up", "next", "create", "agree"))
                log(f"[2] password clicked: {t}")
                await asyncio.sleep(5)
                await dump_state(page, "s2-after-password")
            else:
                log("[2] NO password field appeared")

            # registration page? (name/org fields)
            info = await dump_state(page, "s3-check")
            rec["stage"] = "post-password"

            # wait for code input OR redirect to app
            code_done = False
            t_end = time.time() + 120
            while time.time() < t_end:
                url = page.url
                if url.startswith("https://app.daytona.io"):
                    break
                try:
                    has_code = await page.locator('input[autocomplete=one-time-code], input[inputmode=numeric], input[name*=code i]').count()
                    if not has_code and 'email-verification' in page.url:
                        has_code = await page.locator('input:not([type=hidden])').count()
                except Exception:
                    has_code = 0
                if has_code:
                    log("[3] code input visible, polling mail...")
                    if sk:
                        code, _ = await asyncio.to_thread(voidash_wait, sk, 240)
                    elif provider == "reforrm":
                        code, _l = await asyncio.to_thread(reforrm_wait_code, email, 400)
                    elif provider == "tonline":
                        code, link = await asyncio.to_thread(tonline_wait_code, email, topw, 240)
                        if not code and link:
                            log("[3] got verify link, navigating: " + link[:110])
                            try:
                                await page.goto(link, wait_until="domcontentloaded", timeout=60000)
                                await asyncio.sleep(5)
                                code = "LINK_DONE"
                            except Exception as e:
                                log("[3] link nav err: " + str(e)[:100])
                    else:
                        code, _ = await asyncio.to_thread(gmail_wait_code, tag, 240)
                    if code:
                        filled = False
                        try:
                            # focus first visible non-hidden input via JS (type may be property-only)
                            info = await page.evaluate("""() => {
                                const els = Array.from(document.querySelectorAll('input'))
                                    .filter(i => i.type !== 'hidden' && i.offsetParent !== null);
                                return els.map(e => ({type:e.type, ml:e.maxLength, ph:e.placeholder}));
                            }""")
                            log(f"[3] code inputs: {info}")
                            boxes = page.locator('input:not([type=hidden])')
                            nb = await boxes.count()
                            log(f"[3] visible boxes: {nb}, code={code}")
                            if code == "LINK_DONE":
                                filled = True
                            elif nb >= 1:
                                await boxes.first.click()
                                await asyncio.sleep(0.4)
                                # single field holding full code, or split boxes auto-advance
                                for ch in code[:8]:
                                    await page.keyboard.type(ch, delay=180)
                                    await asyncio.sleep(0.15)
                                filled = True
                                log("[3] typed code via keyboard")
                                await asyncio.sleep(4)
                        except Exception as e:
                            log("[3] box-type err: " + str(e)[:120])
                        if not filled:
                            try:
                                await set_react_input(page, 'input[name=code]', code)
                            except Exception:
                                pass
                        t = await click_by_text(page, ("continue", "verify", "submit", "next"))
                        log(f"[3] code {code} done, click={t}")
                        code_done = True
                        await asyncio.sleep(5)
                        await dump_state(page, "s4-after-code")
                    else:
                        log("[3] NO code in mail within 240s")
                    break
                await asyncio.sleep(3)

            # final: wait for app redirect
            t_end = time.time() + 90
            while time.time() < t_end:
                if page.url.startswith("https://app.daytona.io"):
                    break
                await asyncio.sleep(2)
            await asyncio.sleep(4)
            rec["final_url"] = page.url
            ok = page.url.startswith("https://app.daytona.io")
            rec["stage"] = "REGISTERED" if ok else "stuck"
            log(f"[FINAL] {rec['stage']} url={page.url[:120]}")
            await dump_state(page, "final")
            try:
                state = await ctx.storage_state()
                sf = os.path.join(HERE, f"state_{idx}_{int(time.time())}.json")
                with open(sf, "w", encoding="utf-8") as f:
                    json.dump(state, f)
                rec["storage_state"] = sf
                rec["cookies"] = sorted({c["name"] for c in state.get("cookies", [])})
            except Exception as e:
                rec["state_error"] = str(e)[:120]
        except Exception:
            rec["stage"] = "error"
            rec["error"] = traceback.format_exc()[-500:]
            log("ERROR: " + rec["error"])
            try:
                await page.screenshot(path=os.path.join(HERE, f"err_{idx}.png"))
            except Exception:
                pass
        finally:
            with open(ACC_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            try:
                await browser.close()
            except Exception:
                pass
    return rec


async def main():
    for i in range(N):
        await run_one(i + 1)
        if i + 1 < N:
            await asyncio.sleep(random.uniform(5, 15))
    log("DONE")


if __name__ == "__main__":
    log(f"START pid={os.getpid()} N={N}")
    asyncio.run(main())
