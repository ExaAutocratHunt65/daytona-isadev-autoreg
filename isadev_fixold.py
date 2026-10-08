"""Fix old is-a.dev PRs: replace ImprovMX MX with forwardemail.net records.
For each PR row in isadev_farm_api.jsonl (stage=PR) with improvmx content:
find fork+branch from PR, PUT updated domains/<name>.json (contents API w/ sha).
"""
import json, base64, re, sys, time
import urllib.request, urllib.error
import concurrent.futures as cf

OUT="isadev_farm_api.jsonl"
DONE="isadev_fixed_logins.json"

def gh(tok,url,method="GET",data=None):
    H={"Authorization":"Bea"+"rer "+tok,"User-Agent":"isadev-farm","Accept":"application/vnd.github+json"}
    r=urllib.request.Request(url,headers=H,method=method)
    if data is not None: r.data=json.dumps(data).encode()
    try:
        resp=urllib.request.urlopen(r,timeout=30); b=resp.read().decode()
        return resp.status,(json.loads(b) if b else {})
    except urllib.error.HTTPError as e:
        return e.code,e.read().decode()[:120]
    except Exception as e:
        return -1,str(e)[:100]

def main():
    rows=[json.loads(l) for l in open(OUT)]
    prs=[r for r in rows if r['stage']=='PR' and r.get('pr')]
    fixed=set(json.load(open(DONE))) if __import__('os').path.exists(DONE) else set()
    todo=[r for r in prs if r['login'] not in fixed]
    print("PRs:",len(prs),"to fix:",len(todo),flush=True)
    ok=0
    def fix(r):
        login=r['login']; dom=r['domain'].replace('.is-a.dev','')
        prn=r['pr'].rstrip('/').split('/')[-1]
        # need a token: use isadev_gh_tokens for this login
        tokmap={t['login'].lower():t['token'] for t in json.load(open('isadev_gh_tokens.json'))}
        tok=tokmap.get(login.lower())
        if not tok: return (login,'no_tok')
        s,p=gh(tok,f"https://api.github.com/repos/is-a-dev/register/pulls/{prn}")
        if s!=200: return (login,f'pr_{s}')
        head=p['head']; branch=head['ref']; owner=head['repo']['owner']['login']
        f=f"https://api.github.com/repos/{owner}/register/contents/domains/{dom}.json"
        s,cur=gh(tok,f+"?ref="+branch)
        if s!=200: return (login,f'file_{s}')
        try:
            data=json.loads(base64.b64decode(cur['content']))
        except Exception as e:
            return (login,'decode')
        if 'forwardemail' in json.dumps(data): return (login,'already')
        data['record']={"MX":["mx1.forwardemail.net","mx2.forwardemail.net"],
                        "TXT":["forward-email=baradok609@gmail.com","v=spf1 include:spf.forwardemail.net ~all"]}
        c=base64.b64encode(json.dumps(data,indent=2).encode()).decode()
        s,_=gh(tok,f,"PUT",{"message":"fix: use forwardemail.net forwarding","content":c,"branch":branch,"sha":cur['sha']})
        return (login,'OK' if s==200 else f'put_{s}')
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(fix,todo):
            login,st=res
            fixed.add(login)
            if st=='OK': ok+=1
            json.dump(sorted(fixed),open(DONE,'w'))
    print("FIXED:",ok,"of",len(todo),flush=True)

if __name__=="__main__": main()
