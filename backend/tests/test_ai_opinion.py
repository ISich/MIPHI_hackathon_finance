"""FR-024 / AC-21: AI opinion over a real published report; the model is replaced by a fake HTTP transport."""
import json
import time

import pytest

from conftest import make_client, wait_run
from helpers import config, demo_dataset, start_run

from dd_backend import ai_opinion as ai


@pytest.fixture
def ai_env(env, monkeypatch):
    monkeypatch.setenv("DD_AI_MODEL", "test/model")
    monkeypatch.setenv("DD_AI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("DD_AI_TIMEOUT_SECONDS", "20")
    return env


def _report(client) -> tuple[str, dict]:
    ds = demo_dataset(client)
    builtin = [{"script_id": s["script_id"]} for s in client.get("/api/scripts?kind=check").json() if s["source"] == "builtin"]
    run = wait_run(client, start_run(client, config(client, ds["dataset_id"], checks=builtin)["config_id"]).json()["run_id"])
    assert run["status"] == "COMPLETED", run
    rid = run["initial_report_id"]
    return rid, client.get(f"/api/reports/{rid}/checks").json()


def _completion(content) -> dict:
    return {"model": "test/model-2026", "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


def _wait(client, rid, timeout=15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/reports/{rid}/ai-opinion").json()
        if body["status"] in ("READY", "FAILED"):
            return body
        time.sleep(0.05)
    raise AssertionError(body)


def test_disabled_without_key_and_report_untouched(env):
    with make_client() as c:
        rid, doc = _report(c)
        view = c.get(f"/api/reports/{rid}/ai-opinion").json()
        assert view["status"] == "DISABLED" and view["disabled_reason"]
        r = c.post(f"/api/reports/{rid}/ai-opinion", json={})
        assert r.status_code == 409 and r.json()["code"] == "AI_DISABLED"
        html = c.get(f"/api/reports/{rid}/checks.html").text
        assert "Альтернативное мнение ИИ" in html and "не включено" in html
        assert c.get(f"/api/reports/{rid}/checks").json() == doc


def test_package_is_depersonalised(ai_env):
    with make_client() as c:
        rid, doc = _report(c)
        pkg = c.get(f"/api/reports/{rid}/ai-opinion/package").json()
        text = json.dumps(pkg, ensure_ascii=False)
        app_ids = {a for row in doc["checks"] for a in row.get("APP_IDS", [])} | {"I32554354"}
        assert not any(a in text for a in app_ids), "application ids must not reach the model"
        kinds = {f["kind"] for f in pkg["facts"]}
        assert {"summary", "check_execution"} <= kinds
        assert any(f["id"] == "S:total_apps" for f in pkg["facts"])
        assert all("value_before" not in f and "value_after" not in f for f in pkg["facts"])


def test_ready_opinion_with_refs_html_and_cache(ai_env):
    calls = []
    with make_client() as c:
        rid, doc = _report(c)

        def fake_post(url, headers, body, timeout):
            calls.append((url, headers, body))
            pkg = json.loads(body["messages"][1]["content"].split("<package>\n", 1)[1].rsplit("\n</package>", 1)[0])
            first = pkg["facts"][0]["id"]
            return _completion(json.dumps({
                "summary": "Решение изменилось у <b>всех</b> заявок.",
                "findings": [
                    {"title": "Смена решения", "text": "Смена решения у 1 заявки.", "severity": "concern", "refs": [first]},
                    {"title": "Выдумка", "text": "Ссылка в никуда", "severity": "info", "refs": ["X99"]},
                    {"title": "Без ссылок", "text": "…", "severity": "info", "refs": []},
                    {"title": "Число", "text": "Одобрение выросло на 4242 п.п.", "severity": "attention", "refs": [first]},
                ],
                "limitations": ["Одна заявка"],
            }, ensure_ascii=False))

        c.app.state.ai.post = fake_post
        r = c.post(f"/api/reports/{rid}/ai-opinion", json={})
        assert r.status_code == 202 and r.json()["status"] in ("PENDING", "READY")
        view = _wait(c, rid)
        assert view["status"] == "READY", view
        op = view["opinion"]
        assert [f["title"] for f in op["findings"]] == ["Смена решения", "Число"]
        assert op["findings"][1]["unverified_numbers"] == [4242]
        assert view["validation"]["findings_received"] == 4 and len(view["validation"]["dropped"]) == 2
        assert all(ref in view["facts"] for f in op["findings"] for ref in f["refs"])
        assert view["model"] == "test/model-2026" and view["usage"]["total_tokens"] == 150

        url, headers, body = calls[0]
        assert url.endswith("/chat/completions") and headers["Authorization"] == "Bearer sk-test-secret"
        assert body["model"] == "test/model" and body["response_format"]["type"] == "json_schema"
        assert body["provider"] == {"require_parameters": True, "data_collection": "deny"}

        # deterministic results are untouched; HTML carries the escaped opinion
        assert c.get(f"/api/reports/{rid}/checks").json() == doc
        html = c.get(f"/api/reports/{rid}/checks.html").text
        assert "Смена решения" in html and "&lt;b&gt;всех&lt;/b&gt;" in html and "<b>всех</b>" not in html
        assert "sk-test-secret" not in html and "sk-test-secret" not in json.dumps(view)

        # same facts + model -> cached, no second call; force -> new call
        c.post(f"/api/reports/{rid}/ai-opinion", json={})
        assert len(calls) == 1
        c.post(f"/api/reports/{rid}/ai-opinion", json={"force": True})
        assert _wait(c, rid)["status"] == "READY" and len(calls) == 2


@pytest.mark.parametrize("behaviour,code", [
    ("timeout", "AI_TIMEOUT"),
    ("invalid_json", "AI_RESPONSE_INVALID"),
    ("auth", "AI_AUTH_FAILED"),
    ("empty", "AI_RESPONSE_INVALID"),
])
def test_failures_are_explicit_and_do_not_change_report(ai_env, behaviour, code):
    with make_client() as c:
        rid, doc = _report(c)

        def fake_post(url, headers, body, timeout):
            if behaviour == "timeout":
                raise ai.AiCallError("AI_TIMEOUT", "Модель не ответила")
            if behaviour == "auth":
                raise ai.AiCallError("AI_AUTH_FAILED", "Провайдер ответил HTTP 401")
            if behaviour == "empty":
                return _completion("")
            return _completion("это не json")

        c.app.state.ai.post = fake_post
        c.post(f"/api/reports/{rid}/ai-opinion", json={})
        view = _wait(c, rid)
        assert view["status"] == "FAILED" and view["error"]["code"] == code, view
        assert view["opinion"] is None
        assert c.get(f"/api/reports/{rid}/checks").json() == doc
        html = c.get(f"/api/reports/{rid}/checks.html").text
        assert "Ошибка получения ИИ-мнения" in html and code in html


def test_foreign_owner_cannot_see_or_request(ai_env):
    from conftest import peer
    with make_client() as c:
        rid, _ = _report(c)
        other = peer(c.app)
        assert other.get(f"/api/reports/{rid}/ai-opinion").status_code == 404
        assert other.post(f"/api/reports/{rid}/ai-opinion", json={}).status_code == 404


def test_retry_on_transient_error_then_success():
    cfg = ai.AiConfig(base_url="https://openrouter.ai/api/v1", model="m", timeout_seconds=30, max_output_tokens=100,
                      response_format="json_object", openrouter_privacy=False)
    attempts = []

    def post(url, headers, body, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise ai.AiCallError("AI_RATE_LIMITED", "429")
        return _completion('{"summary":"ok","findings":[],"limitations":[]}')

    import os
    os.environ["DD_AI_API_KEY"] = "k"
    try:
        content, usage, model = ai.call_model(cfg, {"facts": []}, post=post)
    finally:
        del os.environ["DD_AI_API_KEY"]
    assert len(attempts) == 2 and json.loads(content)["summary"] == "ok"


def test_validate_extracts_fenced_json():
    pkg = {"facts": [{"id": "S:total_apps", "kind": "summary", "value": 7}]}
    op, val = ai.validate_response('```json\n{"summary":"Всего 7","findings":[{"title":"t","text":"7 заявок",'
                                   '"severity":"weird","refs":["S:total_apps"]}],"limitations":[]}\n```', pkg)
    assert op["findings"][0]["severity"] == "info" and op["findings"][0]["unverified_numbers"] == []
    assert val["summary_unverified_numbers"] == []
    with pytest.raises(ai.AiResponseInvalid):
        ai.validate_response('{"findings": []}', pkg)
