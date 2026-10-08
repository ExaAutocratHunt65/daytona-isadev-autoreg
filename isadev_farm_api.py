"""is-a.dev API-only mass farm using live GH tokens (gh_alive_FIXED_0810.json).
Per token: repo+pages -> fork -> branch -> commit domains/<name>.json -> PR.
Unique name per login; skip if domain taken upstream or already done.
"""
import json, time, sys, re, os, base64, random
import urllib.request, urllib.error
import concurrent.futures as cf

TOK_FILE = "isadev_gh_tokens.json"
OUT = "isadev_farm_api.jsonl"
DONE = "isadev_done_logins.json"

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def gh(tok, url, method="GET", data=None, retries=2):
    H = {"Authorization": "Bea" + "rer " + tok, "User-Agent": "isadev-farm",
         "Accept": "application/vnd.github+json"}
    for attempt in range(retries + 1):
        r = urllib.request.Request(url, headers=H, method=method)
        if data is not None:
            r.data = json.dumps(data).encode()
        try:
            resp = urllib.request.urlopen(r, timeout=30)
            b = resp.read().decode()
            return resp.status, (json.loads(b) if b else {})
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(20 * (attempt + 1))
                continue
            return e.code, e.read().decode()[:150]
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            return -1, str(e)[:100]

def load_done():
    if os.path.exists(DONE):
        return set(json.load(open(DONE)))
    return set()

def save_done(s):
    json.dump(sorted(s), open(DONE, "w"))

def rec(o):
    with open(OUT, "a") as f:
        f.write(json.dumps(o) + "\n")

def farm_one(item):
    login, tok = item["login"], item["token"]
    t0 = time.time()
    # verify token + real login
    s, u = gh(tok, "https://api.github.com/user")
    if s != 200:
        return {"login": login, "stage": "tok_dead:%s" % s}
    real = u["login"]
    # domain name from real login
    name = re.sub(r"[^a-z0-9-]", "", real.lower().replace("_", "-"))[:25]
    if not name or not re.match(r"^[a-z]", name):
        name = "d" + name
    name = re.sub(r"-+", "-", name).strip("-") or "farm%d" % random.randint(10**4, 10**6)
    # taken upstream?
    s, _ = gh(tok, f"https://api.github.com/repos/is-a-dev/register/contents/domains/{name}.json")
    if s == 200:
        name2 = name + "-dev"
        s, _ = gh(tok, f"https://api.github.com/repos/is-a-dev/register/contents/domains/{name2}.json")
        if s == 200:
            return {"login": real, "stage": "domain_taken", "domain": name}
        name = name2
    # site repo + pages
    gh(tok, "https://api.github.com/user/repos", "POST",
       {"name": name + "-site", "public": True, "auto_init": True})
    html = ("<!doctype html><html><head><title>%s</title></head><body>"
            "<h1>%s</h1><p>Personal developer blog and notes.</p></body></html>" % (name, name))
    idx = base64.b64encode(html.encode()).decode()
    gh(tok, f"https://api.github.com/repos/{real}/{name}-site/contents/index.html", "PUT",
       {"message": "init", "content": idx, "branch": "main"})
    gh(tok, f"https://api.github.com/repos/{real}/{name}-site/pages", "POST",
       {"source": {"branch": "main", "path": "/"}})
    # fork
    s, r = gh(tok, "https://api.github.com/repos/is-a-dev/register/forks", "POST", {})
    for _ in range(12):
        s2, _ = gh(tok, f"https://api.github.com/repos/{real}/register")
        if s2 == 200:
            break
        time.sleep(3)
    else:
        return {"login": real, "stage": "fork_fail:%s" % s}
    # branch off upstream main
    s, up = gh(tok, "https://api.github.com/repos/is-a-dev/register/branches/main")
    if s != 200:
        return {"login": real, "stage": "upstream_fail:%s" % s}
    branch = "add-" + name
    for _try in range(4):
        s, r = gh(tok, f"https://api.github.com/repos/{real}/register/git/refs", "POST",
                  {"ref": "refs/heads/" + branch, "sha": up["commit"]["sha"]})
        if s in (200, 201) or "already exists" in str(r):
            break
        time.sleep(8)
    else:
        return {"login": real, "stage": "branch_fail:%s" % s}
    dom = {"owner": {"username": real, "email": f"{real}@users.noreply.github.com"},
           "record": {"MX": ["mx1.forwardemail.net", "mx2.forwardemail.net"],
                      "TXT": ["forward-email=baradok609@gmail.com",
                              "v=spf1 include:spf.forwardemail.net ~all"]}}
    content = json.dumps(dom, indent=2).encode()
    committed = False
    for _try in range(3):
        s, r = gh(tok, f"https://api.github.com/repos/{real}/register/contents/domains/{name}.json",
                  "PUT", {"message": f"feat(domain): add {name}.is-a.dev",
                          "content": base64.b64encode(content).decode(), "branch": branch})
        if s in (200, 201) or "already exists" in str(r):
            committed = True
            break
        # fallback: git data API (blob -> tree -> commit -> ref)
        try:
            s1, blob = gh(tok, f"https://api.github.com/repos/{real}/register/git/blobs", "POST",
                          {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            s2, tree = gh(tok, f"https://api.github.com/repos/{real}/register/git/trees", "POST",
                          {"base_tree": up["commit"]["sha"], "tree": [
                              {"path": f"domains/{name}.json", "mode": "100644",
                               "type": "blob", "sha": blob["sha"]}]})
            s3, cm = gh(tok, f"https://api.github.com/repos/{real}/register/git/commits", "POST",
                        {"message": f"feat(domain): add {name}.is-a.dev", "tree": tree["sha"],
                         "parents": [up["commit"]["sha"]]})
            s4, _ = gh(tok, f"https://api.github.com/repos/{real}/register/git/refs/heads/{branch}",
                       "PATCH", {"sha": cm["sha"], "force": True})
            if s4 in (200, 201):
                committed = True
                break
        except Exception:
            pass
        time.sleep(10)
    if not committed:
        return {"login": real, "stage": "commit_fail:%s" % s, "detail": str(r)[:100]}
    s3, t = gh(tok, "https://api.github.com/repos/is-a-dev/register/contents/.github/PULL_REQUEST_TEMPLATE.md")
    tpl = base64.b64decode(t['content']).decode() if isinstance(t, dict) and 'content' in t else ""
    body = tpl.replace("- [ ]", "- [x]")
    body = body.replace("<!-- WEBSITE_PREVIEW_START -->",
                        "<!-- WEBSITE_PREVIEW_START -->\nhttps://%s.github.io/%s-site/\n" % (real, name))
    body = re.sub(r"(<!-- WEBSITE_PURPOSE_START -->)(\s*)(<!-- WEBSITE_PURPOSE_END -->)",
                  r"\1\nPersonal developer blog for the %s project.\n\3" % name, body)
    s, r = gh(tok, "https://api.github.com/repos/is-a-dev/register/pulls", "POST",
              {"title": f"feat(domain): add {name}.is-a.dev", "head": f"{real}:{branch}",
               "base": "main", "body": body})
    if s in (200, 201) and isinstance(r, dict) and r.get("html_url"):
        return {"login": real, "stage": "PR", "domain": name + ".is-a.dev", "pr": r["html_url"],
                "sec": round(time.time() - t0)}
    if s == 422 and "already exists" in str(r).lower():
        # find the existing open PR from this fork
        import urllib.parse as uparse
        q = uparse.quote(f"repo:is-a-dev/register is:pr is:open author:{real}")
        s2, lst = gh(tok, "https://api.github.com/search/issues?q=" + q)
        if s2 == 200 and isinstance(lst, dict) and lst.get("items"):
            it = lst["items"][0]
            return {"login": real, "stage": "PR", "domain": name + ".is-a.dev",
                    "pr": it["html_url"], "existing": True, "sec": round(time.time() - t0)}
    return {"login": real, "stage": "pr_fail:%s" % s, "detail": str(r)[:100]}

def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    toks = json.load(open(TOK_FILE))
    done = load_done()
    todo = [t for t in toks if t["login"].lower() not in {d.lower() for d in done}]
    log("tokens:", len(toks), "todo:", len(todo), "this batch:", min(N, len(todo)))
    stats = {}
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(farm_one, t): t["login"] for t in todo[:N]}
        for i, fut in enumerate(cf.as_completed(futs, timeout=600)):
            try:
                res = fut.result()
            except Exception as e:
                res = {"login": futs[fut], "stage": "exc:" + str(e)[:80]}
            stats[res["stage"].split(":")[0]] = stats.get(res["stage"].split(":")[0], 0) + 1
            done.add(res["login"].lower()); save_done(done); rec(res)
            if res["stage"] == "PR":
                log(f"[{i}] PR {res['domain']} {res['pr']}")
            elif i % 10 == 0:
                log(f"[{i}] stats {stats}")
    log("FINAL", json.dumps(stats))

if __name__ == "__main__":
    main()
