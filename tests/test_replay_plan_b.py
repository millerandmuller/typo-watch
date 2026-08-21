"""Demo-Rehearsal finding, Round 3: `?replay=1` on the homepage must
actually reach the scan form as a hidden field, not just the backend
`/scan/result?replay=1` endpoint — a presenter's only mid-take recovery
path (project_brief.md Section 1.6 Plan B for the Cold Open/Pain and
Reveal+Wow beats) was previously inert: `GET /` ignored all query
params. Covers both the route (squatwatch.app.index) and the template's
rendering of the hidden field.
"""

from jinja2 import Environment, FileSystemLoader
from starlette.testclient import TestClient

from squatwatch.app import app

_env = Environment(loader=FileSystemLoader("templates"))


def test_index_template_omits_the_hidden_field_by_default():
    html = _env.get_template("index.html").render(initial=False, replay=False)
    assert 'name="replay"' not in html


def test_index_template_includes_the_hidden_replay_field_when_replay_is_true():
    html = _env.get_template("index.html").render(initial=False, replay=True)
    assert '<input type="hidden" name="replay" value="1">' in html


def test_get_index_with_replay_query_param_renders_the_hidden_field():
    client = TestClient(app)
    resp = client.get("/?replay=1")
    assert resp.status_code == 200
    assert '<input type="hidden" name="replay" value="1">' in resp.text


def test_get_index_without_replay_query_param_omits_the_hidden_field():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'name="replay"' not in resp.text
