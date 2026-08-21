"""R — the ONE production domain registration (project_brief.md Section 3,
M0, onboarding Q1).

Calls checkAvailability against production for squat.watch, then
typo.watch, then lookalike.watch (in that order), shows the returned
price for each, and registers the FIRST one priced at or below
NAMECOM_PROD_PURCHASE_CAP_USD (default $50). If all three exceed the
cap, it stops and prints exactly that — it never registers anything
above the cap and never falls through to a fourth candidate.

THIS SPENDS REAL MONEY ON A REAL PRODUCTION DOMAIN PURCHASE.

Safety, on top of what the brief specifies:
  - Requires --confirm to do anything beyond the price check.
  - Never invents registrant contact details. REGISTRANT_* env vars
    must be set to the real registrant's real information (name.com
    requires accurate WHOIS contact data by ICANN policy); the script
    refuses to run --confirm without them.
  - Prints the full request/response it is about to send and asks for
    the exact word "yes" on stdin before the purchase call, even with
    --confirm.

Run the price check only (safe, read-only, no purchase):
    python3 -m squatwatch.prod_register

Run for real (after setting REGISTRANT_* in .env and reading this file):
    python3 -m squatwatch.prod_register --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

from squatwatch.cache import Cache
from squatwatch.config import get_settings
from squatwatch.namecom import NamecomClient, NamecomError

REQUIRED_REGISTRANT_ENV = (
    "REGISTRANT_FIRST_NAME",
    "REGISTRANT_LAST_NAME",
    "REGISTRANT_ADDRESS1",
    "REGISTRANT_CITY",
    "REGISTRANT_STATE",
    "REGISTRANT_ZIP",
    "REGISTRANT_COUNTRY",
    "REGISTRANT_EMAIL",
    "REGISTRANT_PHONE",
)


def _registrant_contact() -> dict:
    missing = [k for k in REQUIRED_REGISTRANT_ENV if not os.environ.get(k)]
    if missing:
        print(
            "Missing registrant contact env vars: " + ", ".join(missing) +
            "\nSet these to the REAL registrant's real details in .env before "
            "running --confirm. name.com requires accurate WHOIS contact data.",
            file=sys.stderr,
        )
        sys.exit(1)
    contact = {
        "firstName": os.environ["REGISTRANT_FIRST_NAME"],
        "lastName": os.environ["REGISTRANT_LAST_NAME"],
        "address1": os.environ["REGISTRANT_ADDRESS1"],
        "city": os.environ["REGISTRANT_CITY"],
        "state": os.environ["REGISTRANT_STATE"],
        "zip": os.environ["REGISTRANT_ZIP"],
        "country": os.environ["REGISTRANT_COUNTRY"],
        "email": os.environ["REGISTRANT_EMAIL"],
        "phone": os.environ["REGISTRANT_PHONE"],
    }
    return {"registrant": contact, "admin": contact, "tech": contact, "billing": contact}


async def _run(confirm: bool) -> None:
    settings = get_settings()
    cache = Cache(settings.app.db_path, default_ttl_seconds=settings.app.cache_ttl_seconds)

    async with httpx.AsyncClient() as http_client, NamecomClient(
        username=settings.namecom.username,
        token=settings.namecom.token,
        base_url=settings.namecom.base_url,
        cache=cache,
        http_client=http_client,
    ) as client:
        chosen: tuple[str, float] | None = None
        for domain in settings.namecom.prod_domain_candidates:
            avail_map = await client.check_availability([domain])
            avail = avail_map.get(domain)
            if avail is None or not avail.purchasable:
                print(f"{domain}: not purchasable")
                continue
            price = avail.price
            print(f"{domain}: purchasable, ${price:.2f}/yr" if price else f"{domain}: purchasable, price unknown")
            if price is not None and price <= settings.namecom.prod_purchase_cap_usd:
                chosen = (domain, price)
                break
            print(f"  -> exceeds cap (${settings.namecom.prod_purchase_cap_usd:.2f}), trying next")

        if chosen is None:
            print(
                f"\nAll {len(settings.namecom.prod_domain_candidates)} candidates exceed "
                f"the ${settings.namecom.prod_purchase_cap_usd:.2f} cap, or none were "
                "purchasable. Stopping — this is the point where the user gets asked "
                "(onboarding Q1), not a fallback to a fourth candidate."
            )
            return

        domain, price = chosen
        print(f"\nChosen: {domain} at ${price:.2f}/yr")

        if not confirm:
            print("\n(price check only — pass --confirm to actually register)")
            return

        contacts = _registrant_contact()
        print(f"\nAbout to register {domain} for ${price:.2f} against PRODUCTION name.com.")
        print("This is a REAL purchase with REAL money. Type 'yes' to proceed: ", end="")
        answer = input().strip()
        if answer != "yes":
            print("Aborted.")
            return

        try:
            order = await client.register(domain, contacts=contacts, purchase_price=price)
        except NamecomError as exc:
            print(f"Registration failed: {exc.message}: {exc.details}", file=sys.stderr)
            sys.exit(1)

        print("\nOrder response:")
        print(order)
        print(
            f"\n{domain} registered. Next: point its DNS at the deployed app "
            "(F11) and confirm it resolves before using it in the video."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm", action="store_true",
        help="actually register the chosen domain (real money); omit for a price-check-only dry run",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.confirm))


if __name__ == "__main__":
    main()
