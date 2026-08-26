"""Round 6 (refinements/typo-watch-access-code-2026-08-26.md): a live
(non-replay) POST /scan is gated behind a shared SCAN_ACCESS_CODE when
one is configured. Replay is never gated (hard rule 1); an unset code
disables the gate entirely (hard rule 3), which the existing 157-test
suite already proves by staying green with no code configured.

`_settings_with` swaps squatwatch.app's module-level `_settings` for a
copy with only the named `app.*` fields overridden -- every other field
(including anything read from the real .env) passes through untouched,
so these tests don't depend on what's in the workspace's own .env.

`client` is function-scoped (a fresh TestClient per test): httpx
persists cookies across requests made on the same client instance, and
several tests here specifically assert "no cookie was sent/granted" --
a shared module-level client would leak a cookie set by one test into
every test that runs after it.
"""

import pytest
from starlette.testclient import TestClient

from squatwatch import app as app_module
from squatwatch.config import AppConfig, Settings

CODE = "tw-judges-4242"


def _settings_with(**app_overrides):
    original = app_module._settings
    app_fields = {
        "env": original.app.env,
        "base_url": original.app.base_url,
        "replay_default": original.app.replay_default,
        "cache_ttl_seconds": original.app.cache_ttl_seconds,
        "max_candidates": original.app.max_candidates,
        "db_path": original.app.db_path,
        "seed_dir": original.app.seed_dir,
        "snapshot_frozen_brands": original.app.snapshot_frozen_brands,
        "scan_access_code": original.app.scan_access_code,
    }
    app_fields.update(app_overrides)
    return Settings(
        namecom=original.namecom,
        serpapi=original.serpapi,
        anthropic=original.anthropic,
        dns=original.dns,
        app=AppConfig(**app_fields),
    )


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def gated(monkeypatch):
    """Gate configured with CODE, replay_default left at whatever the
    real settings resolve to (false in every test environment here)."""
    monkeypatch.setattr(app_module, "_settings", _settings_with(scan_access_code=CODE))


@pytest.fixture
def gated_and_replay_default(monkeypatch):
    """REPLAY_MODE=1 equivalent: gate configured but every scan resolves
    to replay, so the gate must never trigger (hard rule 1)."""
    monkeypatch.setattr(
        app_module, "_settings", _settings_with(scan_access_code=CODE, replay_default=True)
    )


@pytest.fixture(autouse=True)
def _no_orchestrator_by_default(monkeypatch):
    """Belt-and-suspenders for every test in this file: the orchestrator
    (registry/search/model calls) must never be invoked from POST /scan
    itself -- only /scan/result does that, and this route only ever
    returns _scan_gate.html or _progress.html, never triggers the
    follow-up call within the same test-client request."""

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("orchestrator must not be invoked from POST /scan")

    monkeypatch.setattr(app_module.orchestrator, "scan_phase1", fail_if_called)
    monkeypatch.setattr(app_module.orchestrator, "scan", fail_if_called)


# ---------------------------------------------------------------------
# Criterion 2: gate on, no code -> gate partial, no pipeline side effects.
def test_live_scan_without_code_returns_the_gate_partial(gated, client):
    resp = client.post("/scan", data={"brand": "acme-test.com"})
    assert resp.status_code == 200
    assert "access code" in resp.text
    assert "Unlock" in resp.text
    assert "in our Devpost submission" in resp.text
    # never auto-continues into the real pipeline
    assert "hx-get=\"/scan/result" not in resp.text
    assert "typowatch-access" not in resp.cookies


def test_live_scan_without_code_does_not_show_the_wrong_code_line(gated, client):
    resp = client.post("/scan", data={"brand": "acme-test.com"})
    assert "recognized" not in resp.text


# ---------------------------------------------------------------------
# Criterion 3: replay is never gated, via the form field or REPLAY_MODE.
def test_live_scan_with_replay_form_field_bypasses_the_gate_with_no_code(gated, client):
    resp = client.post("/scan", data={"brand": "acme-test.com", "replay": "1"})
    assert resp.status_code == 200
    assert "access code" not in resp.text
    assert "Enter a domain" not in resp.text  # sanity: not the error page either
    assert "id=\"results\"" in resp.text
    assert "hx-get=\"/scan/result" in resp.text


def test_replay_default_bypasses_the_gate_with_no_code(gated_and_replay_default, client):
    resp = client.post("/scan", data={"brand": "acme-test.com"})
    assert resp.status_code == 200
    assert "access code" not in resp.text
    assert "hx-get=\"/scan/result" in resp.text


# ---------------------------------------------------------------------
# Criterion 1 (spot check): gate off entirely when unconfigured.
def test_gate_off_when_scan_access_code_is_unset(monkeypatch, client):
    monkeypatch.setattr(app_module, "_settings", _settings_with(scan_access_code=""))
    resp = client.post("/scan", data={"brand": "acme-test.com"})
    assert resp.status_code == 200
    assert "access code" not in resp.text
    assert "hx-get=\"/scan/result" in resp.text


# ---------------------------------------------------------------------
# Criterion 4: GET /?code= redemption.
def test_get_index_with_correct_code_redirects_and_sets_cookie(gated, client):
    resp = client.get(f"/?code={CODE}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert app_module.ACCESS_COOKIE_NAME in resp.cookies
    assert resp.cookies[app_module.ACCESS_COOKIE_NAME] == CODE


def test_get_index_with_wrong_code_redirects_without_cookie(gated, client):
    resp = client.get("/?code=not-the-code", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert app_module.ACCESS_COOKIE_NAME not in resp.cookies


def test_get_index_with_correct_code_and_replay_preserves_replay_in_redirect(gated, client):
    resp = client.get(f"/?code={CODE}&replay=1", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/?replay=1"
    assert app_module.ACCESS_COOKIE_NAME in resp.cookies


def test_code_query_param_is_a_noop_when_gate_is_unconfigured(monkeypatch, client):
    monkeypatch.setattr(app_module, "_settings", _settings_with(scan_access_code=""))
    resp = client.get(f"/?code={CODE}", follow_redirects=False)
    assert resp.status_code == 200  # normal index render, no redirect at all


# ---------------------------------------------------------------------
# Criterion 5: correct/wrong code via the gate's own form field.
def test_correct_code_via_form_field_runs_the_scan_and_sets_the_cookie(gated, client):
    resp = client.post("/scan", data={"brand": "acme-test.com", "code": CODE})
    assert resp.status_code == 200
    assert "access code" not in resp.text
    assert "hx-get=\"/scan/result" in resp.text
    assert app_module.ACCESS_COOKIE_NAME in resp.cookies
    assert resp.cookies[app_module.ACCESS_COOKIE_NAME] == CODE


def test_wrong_code_via_form_field_re_renders_the_gate_with_the_extra_line(gated, client):
    resp = client.post("/scan", data={"brand": "acme-test.com", "code": "nope"})
    assert resp.status_code == 200
    assert "access code" in resp.text
    assert "recognized" in resp.text
    assert app_module.ACCESS_COOKIE_NAME not in resp.cookies


# ---------------------------------------------------------------------
# Criterion 6: with a valid cookie, response is byte-identical to gate-off.
def test_valid_cookie_makes_a_live_scan_byte_identical_to_gate_off(gated, monkeypatch, client):
    client.cookies.set(app_module.ACCESS_COOKIE_NAME, CODE)
    gated_resp = client.post("/scan", data={"brand": "acme-test.com"})

    monkeypatch.setattr(app_module, "_settings", _settings_with(scan_access_code=""))
    off_client = TestClient(app_module.app)  # fresh jar -- no cookie needed when gate is off
    off_resp = off_client.post("/scan", data={"brand": "acme-test.com"})

    assert gated_resp.status_code == off_resp.status_code == 200
    assert gated_resp.text == off_resp.text
    assert "access code" not in gated_resp.text
    # No new Set-Cookie on the cookie path -- nothing to refresh.
    assert app_module.ACCESS_COOKIE_NAME not in gated_resp.cookies


# ---------------------------------------------------------------------
# Adversarial finding (examiner_report.md Round 6, P2): hmac.compare_digest
# raises TypeError on two str operands when either has a non-ASCII
# character -- a judge pasting the code from a PDF can easily introduce
# stray Unicode (curly quotes, NBSP). Must fail closed (gate re-renders),
# never 500.
def test_non_ascii_code_via_form_field_fails_closed_not_500(gated, client):
    resp = client.post("/scan", data={"brand": "acme-test.com", "code": "tw-judges-’"})
    assert resp.status_code == 200
    assert "access code" in resp.text
    assert "recognized" in resp.text


def test_non_ascii_code_via_query_param_fails_closed_not_500(gated, client):
    resp = client.get("/?code=" + "tw-judges-’", follow_redirects=False)
    assert resp.status_code == 303
    assert app_module.ACCESS_COOKIE_NAME not in resp.cookies


# ---------------------------------------------------------------------
# Criterion 7: every other surface stays open with the gate configured.
@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/", {}),
        ("get", "/methodology", {}),
        ("get", "/r/devnetwork.com", {}),
    ],
)
def test_read_surfaces_stay_open_with_the_gate_configured(gated, client, method, path, kwargs):
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 200


def test_methodology_states_the_access_code_sentence(gated, client):
    resp = client.get("/methodology")
    assert "access code" in resp.text
    assert "shared with the event's judges" in resp.text
