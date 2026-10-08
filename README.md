# daytona-isadev-autoreg

Daytona.io mass autoreg pipeline: free $200 compute per account.

## Chain

1. **GitHub accounts (pool with password+TOTP)** — resource for everything below
2. **is-a.dev domain farm** (`isadev_farm_api.py`) — one live GH token → repo+Pages → fork `is-a-dev/register` → commit `domains/<name>.json` → PR. Domain `<login>.is-a.dev` goes live after maintainer merge (they merge actively, ~18 merges per 30 recent closed PRs).
3. **Mail** — no registration needed. Domain JSON carries MX → forwardemail.net + TXT `forward-email=YOUR@gmail.com`. Every `anything@<name>.is-a.dev` lands in your Gmail. Unlimited aliases per domain.
4. **Daytona reg** (`daytona_reg2.py`, `DTN_PROVIDER=reforrm` + `DTN_DOMAIN=<name>.is-a.dev`) — WorkOS AuthKit email flow, code read from Gmail IMAP (all-boxes search incl. Spam/Invoices categories), final onboarding.

## Why not direct GitHub OAuth

Tested with non-Gmail GH accounts (outlook/hotmail/t-online): GH login+TOTP+authorize pass, WorkOS returns `idp_access_denied` — "Your authentication provider denied this sign-in". Daytona blocks GitHub IdP at connector level. GH accounts are used as API resource instead.

## Domain walls (tested)

- gmail.com email+password → "use Continue with Google"
- temp domains (voidash.bond/cyou, pomoi.eu.cc) → Access blocked
- .loc.cc / .nl8.eu free subdomains → code passes, final onboarding: "Daytona accounts need a validated work email"
- t-online.de → same work-email wall
- **is-a.dev → not in disposable blocklists** (developer TLD), the viable path

## Files

- `isadev_farm_api.py` — API-only mass farm (repo→fork→commit→PR), ~90% yield on live tokens, 429 backoff, dup-PR recovery via search API
- `isadev_fixold.py` — migrate old PRs from ImprovMX to forwardemail.net records
- `daytona_reg2.py` — email autoreg: providers `reforrm` (Gmail-forwarded domain), `voidash`, `gmail`, `tonline`; env `DTN_PROVIDER`, `DTN_DOMAIN`, `GMAIL_APP_PW`
- `daytona_gh_reg.py` — GitHub OAuth attempt (kept as reference, blocked by idp_access_denied)

## Run

```bash
export GMAIL_APP_PW="<16-char app password for your forward gmail>"
# 1. farm domains (tokens: JSON list [{login, token}])
python3 isadev_farm_api.py 100
# 2. wait merges, then per merged domain:
DTN_PROVIDER=reforrm DTN_DOMAIN=<name>.is-a.dev python3 daytona_reg2.py 1
```

## Pricing (daytona.io/pricing)

$200 free compute, no card, per-second billing. 4vCPU+8GiB ≈ $0.33/h → ~600h. RTX 4090 preemptible $0.57/h → ~350h. H100 $2.27/h. Startup program up to $50k credits.

For authorized security research / abuse-vectors documentation only.
