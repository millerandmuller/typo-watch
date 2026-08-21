# typo.watch

> Type your brand, see who already owns your typos, take the dangerous ones back in one click.

Six strangers own a version of your name. Two of them can receive your
customers' email. typo.watch tells you which, using the registry's own
answers — not a guess.

## What it does

1. Generates ~150 look-alikes of your domain (typos, homoglyphs, keyword
   combosquats, TLD swaps — the same classes as dnstwist).
2. Checks which are taken via the name.com Core API v1 `checkAvailability`.
3. Confirms ownership facts (registrar, nameservers, created, abuse contact)
   via RDAP through the IANA bootstrap.
4. Probes where each one points (DNS + HTTP redirect chain) — already yours,
   parked, live, mail-only, or dark.
5. Checks which taken ones are live in Google search, via SerpApi.
6. Ranks danger by rules (not a model) and writes a one-line reason per card.
7. Lets you register the worst five in one click (sandbox) and drafts a
   takedown notice from the facts on file.

Every badge has a click-through to the raw response that produced it. See
`/methodology` for the rule weights, documented as judgment.

## Setup (5 steps)

1. `python3.12 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt -e .`
3. `npm install && npm run build:css` (compiles Tailwind to `static/app.css`)
4. Copy `.env.example` to `.env` and fill in your keys — or skip this and run
   in replay mode (see below), which needs no keys at all.
5. `uvicorn squatwatch.app:app --reload` and open http://localhost:8000

Or just `make install && make dev`.

### Replay mode (no keys required)

```
REPLAY_MODE=1 uvicorn squatwatch.app:app
```

Every seed brand (`name.com`, `devnetwork.com`, `apiworld.co`, `google.com`)
serves its cached snapshot from `seed/` — no external calls, works from a
fresh clone with zero configuration.

## CLI twin

The same functions, from a terminal:

```
squatwatch gen name.com          # permutation engine only, no I/O
squatwatch scan name.com         # full pipeline
squatwatch scan name.com --replay
squatwatch defend name.com --domains a.com,b.com
squatwatch seed name.com         # run a live scan, save it as a seed snapshot
```

## Tests

```
make test
```

29 tests: permutation engine (T-01), RDAP parsing (T-02), probe classification
(T-03 forwards-home, T-06 mail-only), ranking rules, the sandbox defend flow,
and a full pipeline integration test — all against recorded fixtures, no live
calls required.

## Architecture

```
browser ── HTMX ──> FastAPI
                     ├── /scan (POST)      → orchestrator.scan(brand) → progress fragment
                     ├── /scan/result      → orchestrator.scan(brand) → three-bands fragment
                     ├── /r/<brand>        → cached scan (permalink)
                     ├── /defend (POST)    → namecom.register + namecom.forward (sandbox)
                     ├── /notice/<domain>  → notice.draft
                     └── /methodology
orchestrator.scan
  engine.generate(brand)            pure, tested
  namecom.check_availability(batch) httpx, token bucket, cache
  rdap.lookup(domain)               bootstrap map, cache
  probe.classify(domain)            DoH + redirect chain, cache
  serp.live(domain)                 cache
  rank.score(card)                  rules only — the model never sees this
  reason.write(cards)               one model call, deterministic fallback
  store.save(scan)                  sqlite
cli: squatwatch gen|scan|defend|seed   → same functions, prints tables
```

Single process, SQLite for scans/snapshots/cache, one Jinja template family
with HTMX partials, no SPA, no component library.

## The one production registration

`squatwatch/prod_register.py` checks `squat.watch`, then `typo.watch`, then
`lookalike.watch` against the production name.com API and registers the
first one priced at or below $50 — the only real-money action in this repo.
It requires `--confirm`, real `REGISTRANT_*` contact details in `.env`, and
an interactive "yes" before it spends anything. Read the file before running
it. As of the last price check (2026-08-20): `squat.watch` is taken,
`typo.watch` is available at $4.99/yr.

## What this doesn't do

No accounts, no billing, no scheduler, no email alerts, no sent notices, no
WHOIS port-43 queries, no certificate-transparency search, no PNG/PDF export.
See the "Not covered" line on the result page for what the tool itself
doesn't check for.

## License

MIT — see `LICENSE`.
