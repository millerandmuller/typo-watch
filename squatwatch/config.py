"""One place for provider config: model id, endpoints, timeouts, caps.

Swapping the AI provider or model is a change to this file, never a
rewrite of squatwatch.reason. See project_brief.md Section 6, "AI Runtime
Profile" and "Grundsatz: provider choice is configuration, not architecture."
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


@dataclass(frozen=True)
class NamecomConfig:
    username: str = field(default_factory=lambda: os.getenv("NAMECOM_USERNAME", ""))
    token: str = field(default_factory=lambda: os.getenv("NAMECOM_TOKEN", ""))
    base_url: str = field(
        default_factory=lambda: os.getenv("NAMECOM_BASE_URL", "https://api.name.com")
    )
    sandbox_username: str = field(
        default_factory=lambda: os.getenv("NAMECOM_SANDBOX_USERNAME", "")
    )
    sandbox_token: str = field(
        default_factory=lambda: os.getenv("NAMECOM_SANDBOX_TOKEN", "")
    )
    sandbox_base_url: str = field(
        default_factory=lambda: os.getenv(
            "NAMECOM_SANDBOX_BASE_URL", "https://api.dev.name.com"
        )
    )
    prod_purchase_cap_usd: float = field(
        default_factory=lambda: _float("NAMECOM_PROD_PURCHASE_CAP_USD", 50.0)
    )
    prod_domain_candidates: list[str] = field(
        default_factory=lambda: [
            d.strip()
            for d in os.getenv(
                "NAMECOM_PROD_DOMAIN_CANDIDATES",
                "squat.watch,typo.watch,lookalike.watch",
            ).split(",")
            if d.strip()
        ]
    )
    rate_limit_per_second: float = 15.0
    rate_limit_per_hour: int = 3000
    batch_size: int = 50


@dataclass(frozen=True)
class SerpapiConfig:
    api_key: str = field(default_factory=lambda: os.getenv("SERPAPI_API_KEY", ""))
    max_queries_per_scan: int = field(
        default_factory=lambda: _int("SERPAPI_MAX_QUERIES_PER_SCAN", 10)
    )
    base_url: str = "https://serpapi.com/search"


@dataclass(frozen=True)
class AnthropicConfig:
    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    # claude-sonnet-5, not claude-opus-5: measured live during Round 1
    # revision (examiner_report.md P1 finding) that a 7-card reasoning
    # batch on opus-5 didn't complete even at a 10s budget, while
    # sonnet-5 succeeded 3/3 at 5.8-7.3s. project_brief.md Section 6
    # names this exact swap as the pre-approved fix "if the 4s timeout
    # bites" — it did, so this is a config change, not a new decision.
    model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    )
    effort: str = "low"
    # 10s, not 8s: live-observed one flake on a cold scan (RDAP/probe/serp
    # still winding down concurrently push the model call's actual
    # latency past a tight budget occasionally, even though isolated
    # calls consistently land at 5.8-7.5s) — the extra headroom costs
    # nothing on the happy path and meaningfully cuts the fallback rate.
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class DnsConfig:
    rdap_bootstrap_url: str = field(
        default_factory=lambda: os.getenv(
            "RDAP_BOOTSTRAP_URL", "https://data.iana.org/rdap/dns.json"
        )
    )
    doh_resolver_url: str = field(
        default_factory=lambda: os.getenv(
            "DOH_RESOLVER_URL", "https://cloudflare-dns.com/dns-query"
        )
    )


@dataclass(frozen=True)
class AppConfig:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    base_url: str = field(
        default_factory=lambda: os.getenv("APP_BASE_URL", "http://localhost:8000")
    )
    replay_default: bool = field(default_factory=lambda: _bool("REPLAY_MODE", False))
    cache_ttl_seconds: int = field(default_factory=lambda: _int("CACHE_TTL_SECONDS", 86400))
    max_candidates: int = 150
    db_path: str = field(
        default_factory=lambda: os.getenv("SQLITE_PATH", "squatwatch.db")
    )
    seed_dir: str = field(default_factory=lambda: os.getenv("SQUATWATCH_SEED_DIR", "seed"))
    snapshot_frozen_brands: frozenset[str] = field(
        default_factory=lambda: frozenset(
            b.strip() for b in os.getenv("SNAPSHOT_FROZEN_BRANDS", "").split(",") if b.strip()
        )
    )
    # Round 6 (refinements/typo-watch-access-code-2026-08-26.md): shared
    # cost-gate code for a live (non-replay) POST /scan. Empty = gate off,
    # so local dev, the test suite, and a fresh clone behave exactly as
    # before by default -- the gate exists in production only because the
    # Fly secret is set.
    scan_access_code: str = field(default_factory=lambda: os.getenv("SCAN_ACCESS_CODE", ""))


@dataclass(frozen=True)
class Settings:
    namecom: NamecomConfig = field(default_factory=NamecomConfig)
    serpapi: SerpapiConfig = field(default_factory=SerpapiConfig)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    dns: DnsConfig = field(default_factory=DnsConfig)
    app: AppConfig = field(default_factory=AppConfig)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
