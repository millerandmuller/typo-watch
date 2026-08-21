"""F8 — one-click defend (sandbox only). Registers the chosen candidates
against api.dev.name.com with the "-test" user, then points each one
home: URL forwarding first, falling back to an A record if forwarding
is unavailable in the sandbox (onboarding Q4).

No production purchase path exists here (F8 acceptance) — that is the
single, separately-gated R script (squatwatch/prod_register.py), never
this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx

from squatwatch.cache import Cache
from squatwatch.config import NamecomConfig
from squatwatch.models import Card
from squatwatch.namecom import CHECK_AVAILABILITY_PATH, NamecomClient, NamecomError
from squatwatch.probe import resolve_a


@dataclass
class DefendItemResult:
    domain: str
    production_price: Optional[float] = None
    order_response: dict = field(default_factory=dict)
    forwarding_response: dict = field(default_factory=dict)
    status: str = "pending"  # "ok" | "failed"
    error: Optional[str] = None
    pointed_home_via: Optional[str] = None  # "forwarding" | "a-record"


async def defend(
    cards: list[Card],
    brand_registrable: str,
    namecom_cfg: NamecomConfig,
    cache: Cache,
    http_client: httpx.AsyncClient,
    doh_resolver_url: str,
) -> list[DefendItemResult]:
    results: list[DefendItemResult] = []
    async with NamecomClient(
        username=namecom_cfg.sandbox_username,
        token=namecom_cfg.sandbox_token,
        base_url=namecom_cfg.sandbox_base_url,
        cache=cache,
        http_client=http_client,
    ) as client:
        for card in cards:
            item = DefendItemResult(domain=card.domain, production_price=card.availability.price)
            try:
                # register requires the price it quotes for THIS request to
                # match exactly (live-discovered: passing card.availability
                # .price straight through fails with "Purchase price does
                # not match" -- that price was quoted by the PRODUCTION
                # client during the scan, but sandbox pricing is its own,
                # separate quote. A cached checkAvailability() call would
                # also risk returning a stale or wrong-environment price
                # under the shared "namecom:avail:<domain>" cache key, so
                # this is a fresh, uncached, sandbox-only lookup done right
                # before the purchase it prices.
                price_check = await client._request(
                    "POST", CHECK_AVAILABILITY_PATH, {"domainNames": [card.domain]}
                )
                sandbox_price = (price_check.get("results") or [{}])[0].get("purchasePrice")
                item.order_response = await client.register(
                    card.domain, purchase_price=sandbox_price
                )
            except NamecomError as exc:
                item.status = "failed"
                item.error = f"{exc.message}: {exc.details}".strip(": ")
                results.append(item)
                continue

            target_url = f"https://{brand_registrable}"
            try:
                item.forwarding_response = await client.create_url_forwarding(
                    card.domain, forwards_to=target_url
                )
                item.pointed_home_via = "forwarding"
                item.status = "ok"
            except NamecomError as fwd_exc:
                brand_ips = await resolve_a(http_client, doh_resolver_url, brand_registrable)
                if not brand_ips:
                    item.status = "failed"
                    item.error = (
                        f"forwarding unavailable ({fwd_exc.message}) and no A record "
                        f"to fall back to for {brand_registrable}"
                    )
                    results.append(item)
                    continue
                try:
                    item.forwarding_response = await client.create_record(
                        card.domain, "A", "@", brand_ips[0]
                    )
                    item.pointed_home_via = "a-record"
                    item.status = "ok"
                except NamecomError as rec_exc:
                    item.status = "failed"
                    item.error = f"{rec_exc.message}: {rec_exc.details}".strip(": ")
            results.append(item)
    return results
