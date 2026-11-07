"""Review #9 (MINOR): OpenAPI error responses describe what the server really sends."""
import json

REF = "#/components/schemas/ErrorBody"


def test_openapi_errors_are_the_json_envelope_everywhere(client):
    spec = client.app.openapi()
    text = json.dumps(spec)
    assert "HTTPValidationError" not in text and "#/components/schemas/ValidationError" not in text
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, op in ops.items():
            responses = op["responses"]
            for status, resp in responses.items():
                if status.startswith("2"):
                    continue
                content = resp.get("content", {})
                assert list(content) == ["application/json"], (method, path, status, list(content))
                assert content["application/json"]["schema"] == {"$ref": REF}, (method, path, status)
            if op.get("parameters") or op.get("requestBody"):
                assert "422" in responses, (method, path)
    html = spec["paths"]["/api/reports/{report_id}/checks.html"]["get"]["responses"]
    assert list(html["200"]["content"]) == ["text/html"]


def test_html_route_error_is_json_on_the_wire(client):
    r = client.get("/api/reports/rep_missing/checks.html")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert set(r.json()) == {"code", "message", "details", "request_id"}
    r = client.get("/api/runs?limit=0")
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
