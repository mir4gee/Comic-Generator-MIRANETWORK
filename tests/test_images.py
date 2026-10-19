import base64

import pytest

from miracomix import images

from .conftest import png_bytes


class Resp:
    def __init__(self, status=200, json=None, content=b"", ctype="application/json"):
        self.status_code, self._json, self.content = status, json, content
        self.headers = {"content-type": ctype}
        self.ok = status < 400
        self.text = str(json or content[:50])

    def json(self):
        return self._json


@pytest.fixture
def http(monkeypatch):
    queue, calls = [], []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return queue.pop(0)

    monkeypatch.setattr(images.requests, "request", request)
    monkeypatch.setattr(images.time, "sleep", lambda s: None)
    return queue, calls


def test_cloudflare_decodes_base64(http, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    queue, calls = http
    queue.append(Resp(json={"success": True, "result": {"image": base64.b64encode(b"JPEGDATA").decode()}}))

    assert images.cloudflare("a cat", 7) == b"JPEGDATA"
    method, url, kwargs = calls[0]
    assert url.endswith("/accounts/acct/ai/run/@cf/black-forest-labs/flux-1-schnell")
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["json"]["steps"] == 4 and kwargs["json"]["prompt"].endswith("a cat")


def test_retries_rate_limit_then_succeeds(http, monkeypatch):
    monkeypatch.delenv("POLLINATIONS_KEY", raising=False)
    queue, calls = http
    queue += [Resp(status=429), Resp(content=png_bytes(), ctype="image/jpeg")]
    assert images.pollinations("a dog", 1) == png_bytes()
    assert len(calls) == 2
    assert "image.pollinations.ai" in calls[0][1]


def test_pollinations_uses_key_and_flux(http, monkeypatch):
    monkeypatch.setenv("POLLINATIONS_KEY", "sk_test")
    queue, calls = http
    queue.append(Resp(content=png_bytes(), ctype="image/png"))
    images.pollinations("a dog", 1)
    method, url, kwargs = calls[0]
    assert url.startswith("https://gen.pollinations.ai/image/")
    assert kwargs["params"]["model"] == "black-forest-labs/flux.1-schnell"
    assert kwargs["headers"]["Authorization"] == "Bearer sk_test"


def test_non_image_response_is_an_error(http, monkeypatch):
    monkeypatch.delenv("POLLINATIONS_KEY", raising=False)
    http[0].append(Resp(json={"error": "busy"}))
    with pytest.raises(images.RenderError):
        images.pollinations("a dog", 1)


def test_gives_up_after_three_server_errors(http):
    queue, _ = http
    queue += [Resp(status=503)] * 3
    with pytest.raises(images.RenderError, match="503"):
        images.pollinations("x", 1)
