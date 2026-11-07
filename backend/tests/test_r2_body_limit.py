"""Review #2 (MAJOR): body size limit enforced while receiving, also without Content-Length."""


def _chunks(total: int, size: int = 64 * 1024):
    sent = 0
    while sent < total:
        n = min(size, total - sent)
        sent += n
        yield b" " * n


def test_streamed_json_without_content_length_is_rejected(client):
    r = client.post("/api/configurations", content=_chunks(5 * 1024 * 1024),
                    headers={"content-type": "application/json"})
    assert "content-length" not in {k.lower() for k in r.request.headers}
    assert r.status_code == 413 and r.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_streamed_multipart_without_content_length_is_rejected(client):
    boundary = "xyz"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\ncheck\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\nbig\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"big.py\"\r\n"
            "Content-Type: text/x-python\r\n\r\n").encode()

    def body():
        yield head
        yield from (b"#" * 65536 for _ in range(64))  # 4 MiB
        yield f"\r\n--{boundary}--\r\n".encode()
    r = client.post("/api/scripts/upload", content=body(),
                    headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    assert r.status_code == 413 and r.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_small_streamed_body_still_works(client):
    import json
    payload = json.dumps({"kind": "check", "name": "s", "code": "x = 1\n"}).encode()
    r = client.post("/api/scripts", content=iter([payload[:10], payload[10:]]),
                    headers={"content-type": "application/json"})
    assert r.status_code == 201, r.json()
