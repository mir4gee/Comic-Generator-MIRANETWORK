import pytest

from miracomix import create_app
from miracomix.telegram import Bot

from .conftest import png_bytes, wait_for


class FakeBot(Bot):
    """Bot with the Telegram HTTP calls replaced by an in-memory log."""

    def __init__(self, *args, has_photo=True, **kwargs):
        super().__init__("TOKEN", *args, **kwargs)
        self.sent = []
        self.has_photo = has_photo

    def api(self, method, files=None, **params):
        if method == "getUserProfilePhotos":
            return {"photos": [[{"file_id": "small"}, {"file_id": "big"}]] if self.has_photo else []}
        if method == "getFile":
            return {"file_path": "p.png"}
        self.sent.append((method, params.get("caption") or params.get("text")))
        return {}

    def download(self, file_id):
        return png_bytes("blue")


def text_update(text, chat_id=7):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "from": {"id": 42, "first_name": "Asha"}, "text": text}}


@pytest.fixture
def bot(fakes, pipeline):
    return FakeBot(pipeline, pipeline.store, public_url="https://comics.example")


def test_text_message_makes_comic_with_profile_photo(bot, pipeline, monkeypatch):
    seen = []
    from miracomix import llm
    real = llm.describe_character
    monkeypatch.setattr(llm, "describe_character",
                        lambda c, name, photo=None, notes="": seen.append((name, photo is not None)) or real(c, name, photo, notes))

    bot.handle_update(text_update("Asha: who ate my pizza?"))
    row = pipeline.store._db.execute("SELECT id FROM comics").fetchone()
    comic = wait_for(pipeline.store, row["id"])

    assert comic["status"] == "done" and comic["chat_id"] == 7
    assert seen == [("Asha", True)]
    captions = [c for m, c in bot.sent if m == "sendPhoto"]
    assert sorted(captions[:4]) == ["Panel 1/4", "Panel 2/4", "Panel 3/4", "Panel 4/4"]
    assert captions[-1].endswith(f"https://comics.example/c/{row['id']}")


def test_one_comic_at_a_time(bot, pipeline):
    pipeline.store.create("busybusy", "telegram", chat_id=7)
    bot.handle_update(text_update("hi there"))
    assert bot.sent[-1] == ("sendMessage", "Still drawing your last comic. One at a time!")


def test_captioned_photo_adds_character(bot):
    update = {"update_id": 2, "message": {"chat": {"id": 7}, "from": {"id": 42}, "caption": "Ravi",
                                          "photo": [{"file_id": "s"}, {"file_id": "b"}]}}
    bot.handle_update(update)
    assert bot.sent[-1] == ("sendMessage", "Added Ravi. Now send the conversation.")
    assert [c.name for c in bot._characters[7]] == ["Ravi"]


def test_help_and_reset(bot):
    bot.handle_update(text_update("/start"))
    assert "4-panel comic" in bot.sent[-1][1]
    bot.handle_update(text_update("/reset"))
    assert bot.sent[-1][1] == "Added characters cleared."


def test_webhook_checks_secret_and_dispatches(fakes, pipeline, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3cret")
    bot = FakeBot(pipeline, pipeline.store)
    client = create_app(pipeline=pipeline, bot=bot).test_client()

    assert client.post("/telegram/webhook", json=text_update("/start"),
                       headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 403
    assert client.post("/telegram/webhook", json=text_update("/start"),
                       headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"}).status_code == 200
