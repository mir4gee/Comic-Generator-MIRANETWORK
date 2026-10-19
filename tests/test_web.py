import io

import pytest

from miracomix import create_app

from .conftest import png_bytes, wait_for


@pytest.fixture
def client(fakes, pipeline, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    app = create_app(pipeline=pipeline)
    return app.test_client()


def post(client, **form):
    data = {"name": ["Asha", "Ravi"], "conversation": "Asha: my pizza?", **form}
    return client.post("/api/comics", data=data, content_type="multipart/form-data")


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Make my comic" in resp.data
    assert b'value="pollinations"' in resp.data


def test_create_then_poll_until_done(client, pipeline):
    resp = post(client, photo=[(io.BytesIO(png_bytes()), "a.png")])
    assert resp.status_code == 202
    comic_id = resp.json["id"]
    wait_for(pipeline.store, comic_id)

    state = client.get(f"/api/comics/{comic_id}").json
    assert state["status"] == "done"
    assert all(p["url"] for p in state["panels"])
    assert client.get(state["panels"][0]["url"]).mimetype == "image/png"
    assert client.get(state["comic_url"]).status_code == 200
    assert "error" in state and state["error"] is None


def test_events_stream_ends_with_done(client, pipeline):
    comic_id = post(client).json["id"]
    wait_for(pipeline.store, comic_id)
    body = client.get(f"/api/comics/{comic_id}/events").get_data(as_text=True)
    assert body.startswith("data: ") and '"status": "done"' in body


def test_share_page_escapes_title(client, pipeline):
    comic_id = post(client).json["id"]
    wait_for(pipeline.store, comic_id)
    html = client.get(f"/c/{comic_id}").get_data(as_text=True)
    assert "<b>Heist</b>" not in html
    assert "Pizza &lt;b&gt;Heist" in html
    assert "og:image" in html


@pytest.mark.parametrize("form, message", [
    ({"name": [""]}, "at least one character"),
    ({"conversation": ""}, "conversation or a chat screenshot"),
    ({"provider": "dalle"}, "Unknown image provider"),
    ({"photo": [(io.BytesIO(b"not an image"), "x.png")]}, "isn't a readable image"),
])
def test_rejects_bad_input(client, form, message):
    resp = post(client, **form)
    assert resp.status_code == 400
    assert message in resp.json["error"]


@pytest.mark.parametrize("path", ["/c/nope", "/c/abcdefgh", "/api/comics/../../etc", "/c/abcdefgh/comic.png"])
def test_unknown_comics_404(client, path):
    assert client.get(path).status_code == 404


def test_webhook_rejects_without_secret(client):
    assert client.post("/telegram/webhook", json={}).status_code == 403
