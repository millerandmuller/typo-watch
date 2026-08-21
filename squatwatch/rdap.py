"""F3 — RDAP enrichment via the IANA bootstrap.

Bootstrap format and RDAP response shape verified against the live
services on 2026-08-20 (data.iana.org/rdap/dns.json is a list of
[[tlds...], [base_urls...]] pairs; rdap.verisign.com's domain response
carries entities[role=registrar].vcardArray, events[eventAction=
registration].eventDate, and nameservers[].ldhName — not guessed).

404 means not registered (D-02, RFC 7480) and overrides a stale
availability answer (Section 4, step 4). A ccTLD absent from the
bootstrap (.de, confirmed absent 2026-08-20) is flagged non-authoritative
rather than guessed at (D-04: the RDAP mandate covers gTLDs only).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx

from squatwatch.cache import Cache, get_semaphore
from squatwatch.models import RdapInfo


@dataclass
class RdapLookupResult:
    registered: Optional[bool]  # None = pending / could not be answered
    authoritative: bool
    info: RdapInfo


class RdapBootstrap:
    def __init__(self, bootstrap_url: str, http_client: httpx.AsyncClient):
        self.bootstrap_url = bootstrap_url
        self._client = http_client
        self._tld_to_bases: dict[str, list[str]] = {}
        self._loaded = False
        self._load_lock = asyncio.Lock()

    async def ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            resp = await self._client.get(self.bootstrap_url, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            mapping: dict[str, list[str]] = {}
            for entry in data.get("services", []):
                if len(entry) < 2:
                    continue
                tlds, bases = entry[0], entry[1]
                for tld in tlds:
                    mapping[tld.lower()] = list(bases)
            self._tld_to_bases = mapping
            self._loaded = True

    def base_urls_for(self, tld: str) -> list[str]:
        return self._tld_to_bases.get(tld.lower(), [])

    def is_authoritative(self, tld: str) -> bool:
        return tld.lower() in self._tld_to_bases


def _vcard_field(vcard_array: list, field_name: str) -> Optional[str]:
    if not vcard_array or len(vcard_array) < 2:
        return None
    for entry in vcard_array[1]:
        if entry and entry[0] == field_name:
            value = entry[-1]
            return value if isinstance(value, str) and value else None
    return None


def _parse_domain_response(body: dict) -> RdapInfo:
    registrar = None
    abuse_email = None
    for entity in body.get("entities", []):
        roles = entity.get("roles", [])
        if "registrar" in roles:
            registrar = _vcard_field(entity.get("vcardArray", []), "fn") or registrar
            for sub in entity.get("entities", []):
                if "abuse" in sub.get("roles", []):
                    abuse_email = _vcard_field(sub.get("vcardArray", []), "email")

    created = None
    for event in body.get("events", []):
        if event.get("eventAction") == "registration":
            created = event.get("eventDate")
            break

    nameservers = [
        ns.get("ldhName", "").lower()
        for ns in body.get("nameservers", [])
        if ns.get("ldhName")
    ]

    return RdapInfo(
        registrar=registrar,
        nameservers=nameservers,
        created=created,
        abuse_email=abuse_email,
        source=None,  # filled in by caller with the queried URL
    )


class RdapClient:
    def __init__(
        self, bootstrap: RdapBootstrap, cache: Cache, http_client: httpx.AsyncClient
    ):
        self.bootstrap = bootstrap
        self.cache = cache
        self._client = http_client

    async def lookup(self, domain: str, tld: str) -> RdapLookupResult:
        cache_key = f"rdap:{domain}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return RdapLookupResult(
                registered=cached["registered"],
                authoritative=cached["authoritative"],
                info=RdapInfo(**cached["info"]),
            )

        await self.bootstrap.ensure_loaded()
        if not self.bootstrap.is_authoritative(tld):
            result = RdapLookupResult(registered=None, authoritative=False, info=RdapInfo())
            self._store(cache_key, result)
            return result

        base_urls = self.bootstrap.base_urls_for(tld)
        result = await self._query(domain, base_urls)
        self._store(cache_key, result)
        return result

    def _store(self, cache_key: str, result: RdapLookupResult) -> None:
        self.cache.set(
            cache_key,
            {
                "registered": result.registered,
                "authoritative": result.authoritative,
                "info": result.info.model_dump(),
            },
        )

    async def _query(self, domain: str, base_urls: list[str]) -> RdapLookupResult:
        sem = get_semaphore("rdap", 10)
        last_error: Optional[str] = None
        for base_url in base_urls:
            url = base_url.rstrip("/") + f"/domain/{domain}"
            for attempt in range(2):  # one retry after 2s, edge case #3
                try:
                    async with sem:
                        resp = await self._client.get(
                            url,
                            headers={"Accept": "application/rdap+json"},
                            timeout=6.0,
                        )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = str(exc)
                    if attempt == 0:
                        await asyncio.sleep(2)
                        continue
                    break

                if resp.status_code == 404:
                    return RdapLookupResult(
                        registered=False, authoritative=True, info=RdapInfo(source=url)
                    )
                if resp.status_code == 200:
                    info = _parse_domain_response(resp.json())
                    info.source = url
                    return RdapLookupResult(registered=True, authoritative=True, info=info)
                if resp.status_code == 429 and attempt == 0:
                    await asyncio.sleep(2)
                    continue
                last_error = f"HTTP {resp.status_code}"
                break
        # Timed out / errored on every base URL: "registry answer pending".
        return RdapLookupResult(
            registered=None, authoritative=True, info=RdapInfo(source=last_error)
        )
