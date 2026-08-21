"""CLI twin: `squatwatch gen|scan|defend|seed` — same functions as the
web app, printing tables instead of HTML (Section 4: "CLI twin ...
calls the same functions and prints tables").
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx

from squatwatch import engine, orchestrator
from squatwatch.cache import Cache
from squatwatch.config import get_settings
from squatwatch.defend import defend as run_defend
from squatwatch.store import Store


def _print_table(rows: list[tuple], headers: tuple[str, ...]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*(str(c) for c in row)))


def cmd_gen(args: argparse.Namespace) -> None:
    candidates, total = engine.generate(args.brand, args.max)
    _print_table(
        [(c.domain, c.cls, f"{c.prior:.2f}") for c in candidates],
        ("domain", "class", "prior"),
    )
    print(f"\n{len(candidates)} of {total} candidates checked (top by risk prior)")


async def _scan(brand: str, replay: bool) -> None:
    settings = get_settings()
    cache = Cache(settings.app.db_path, default_ttl_seconds=settings.app.cache_ttl_seconds)
    store = Store(settings.app.db_path, settings.app.seed_dir)
    async with httpx.AsyncClient() as client:
        result = await orchestrator.scan(brand, settings, cache, store, client, replay=replay)

    counts = result.band_counts()
    print(f"typo.watch — {result.brand} ({result.scanned_at})")
    if result.replay:
        print(result.replay_label)
    print(f"\nStrangers hold {counts['strangers']}")
    _print_table(
        [
            (c.domain, c.cls, c.score.total, c.land_line or "")
            for c in result.cards
            if c.band and c.band.value == "strangers"
        ],
        ("domain", "class", "score", "where it lands"),
    )
    print(f"\nForward to you {counts['yours']}")
    _print_table(
        [(c.domain, c.cls) for c in result.cards if c.band and c.band.value == "yours"],
        ("domain", "class"),
    )
    print(f"\nFree and dangerous {counts['free']}")
    _print_table(
        [
            (c.domain, c.cls, c.availability.price or "")
            for c in result.cards
            if c.band and c.band.value == "free"
        ][:20],
        ("domain", "class", "price"),
    )
    print(
        f"\n{result.footer.generated} generated · {result.footer.answered} answered by "
        f"the registry · {result.footer.not_authoritative} not authoritative"
    )


def cmd_scan(args: argparse.Namespace) -> None:
    asyncio.run(_scan(args.brand, args.replay))


async def _defend(brand: str, domains: list[str]) -> None:
    settings = get_settings()
    cache = Cache(settings.app.db_path, default_ttl_seconds=settings.app.cache_ttl_seconds)
    store = Store(settings.app.db_path, settings.app.seed_dir)
    parsed = engine.parse_brand(brand)
    latest = store.get_latest_scan(parsed.registrable)
    if latest is None:
        print(f"No cached scan for {parsed.registrable}. Run 'scan' first.", file=sys.stderr)
        sys.exit(1)
    cards = [c for c in latest.cards if c.domain in domains]
    async with httpx.AsyncClient() as client:
        results = await run_defend(
            cards, parsed.registrable, settings.namecom, cache, client,
            settings.dns.doh_resolver_url,
        )
    _print_table(
        [(r.domain, r.status, r.pointed_home_via or "", r.error or "") for r in results],
        ("domain", "status", "pointed home via", "error"),
    )


def cmd_defend(args: argparse.Namespace) -> None:
    asyncio.run(_defend(args.brand, args.domains.split(",")))


async def _seed(brand: str) -> None:
    settings = get_settings()
    cache = Cache(settings.app.db_path, default_ttl_seconds=settings.app.cache_ttl_seconds)
    store = Store(settings.app.db_path, settings.app.seed_dir)
    async with httpx.AsyncClient() as client:
        result = await orchestrator.scan(brand, settings, cache, store, client, replay=False)
    path = store.write_seed_snapshot(result)
    print(f"wrote {path}")


def cmd_seed(args: argparse.Namespace) -> None:
    asyncio.run(_seed(args.brand))


def main() -> None:
    parser = argparse.ArgumentParser(prog="squatwatch")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("gen", help="generate permutation candidates (pure, no I/O)")
    p_gen.add_argument("brand")
    p_gen.add_argument("--max", type=int, default=150)
    p_gen.set_defaults(func=cmd_gen)

    p_scan = sub.add_parser("scan", help="run the full scan pipeline")
    p_scan.add_argument("brand")
    p_scan.add_argument("--replay", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_defend = sub.add_parser("defend", help="sandbox-register and forward chosen domains")
    p_defend.add_argument("brand")
    p_defend.add_argument("--domains", required=True, help="comma-separated domain list")
    p_defend.set_defaults(func=cmd_defend)

    p_seed = sub.add_parser("seed", help="run a live scan and write it as a seed snapshot")
    p_seed.add_argument("brand")
    p_seed.set_defaults(func=cmd_seed)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
