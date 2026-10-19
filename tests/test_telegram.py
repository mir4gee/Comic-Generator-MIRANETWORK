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
    assert bot.sent[-1] == ("sendMessage", "Still drawing the last comic. One at a time!")


def test_captioned_photo_adds_character(bot):
    update = {"update_id": 2, "message": {"chat": {"id": 7}, "from": {"id": 42}, "caption": "Ravi",
                                          "photo": [{"file_id": "s"}, {"file_id": "b"}]}}
    bot.handle_update(update)
    assert bot.sent[-1] == ("sendMessage", "Added Ravi. Now send the conversation.")
    assert [c.name for c in bot._characters[7]] == ["Ravi"]


def test_help_and_reset(bot):
    bot.handle_update(text_update("/start"))
    assert "4-panel comics" in bot.sent[-1][1]
    bot.handle_update(text_update("/reset"))
    assert bot.sent[-1][1] == "Cleared collected messages and added characters."


def test_webhook_checks_secret_and_dispatches(fakes, pipeline, monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "s3cret")
    bot = FakeBot(pipeline, pipeline.store)
    client = create_app(pipeline=pipeline, bot=bot).test_client()

    assert client.post("/telegram/webhook", json=text_update("/start"),
                       headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 403
    assert client.post("/telegram/webhook", json=text_update("/start"),
                       headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"}).status_code == 200


def group_msg(text, user_id, name, chat_id=-100):
    return {"update_id": 3, "message": {"chat": {"id": chat_id, "type": "supergroup"},
                                        "from": {"id": user_id, "first_name": name}, "text": text}}


def speakers_seen(monkeypatch):
    from miracomix import llm
    seen = []
    real = llm.describe_character
    monkeypatch.setattr(llm, "describe_character",
                        lambda c, name, photo=None, notes="": seen.append((name, photo is not None)) or real(c, name, photo, notes))
    return seen


def test_group_chat_only_draws_on_comic_command(bot, pipeline, monkeypatch):
    seen = speakers_seen(monkeypatch)
    bot.handle_update(group_msg("did you eat my pizza?", 1, "Asha"))
    bot.handle_update(group_msg("define 'your'", 2, "Ravi"))
    bot.handle_update(group_msg("it had my name on it", 1, "Asha"))
    assert bot.sent == []  # ordinary group messages never trigger a comic
    assert pipeline.store._db.execute("SELECT COUNT(*) FROM comics").fetchone()[0] == 0

    bot.handle_update(group_msg("/comic@MiraComixBot", 1, "Asha"))
    row = pipeline.store._db.execute("SELECT id FROM comics").fetchone()
    assert wait_for(pipeline.store, row["id"])["status"] == "done"
    assert seen == [("Asha", True), ("Ravi", True)]
    assert bot._history.get(-100) is None  # buffer cleared once the comic starts


def test_group_comic_needs_messages(bot):
    bot.handle_update(group_msg("/comic", 1, "Asha"))
    assert "I need a few messages first" in bot.sent[-1][1]


def test_forwarded_messages_become_a_conversation(bot, pipeline, monkeypatch):
    seen = speakers_seen(monkeypatch)
    from miracomix import llm
    convo = []
    real_script = llm.write_script
    monkeypatch.setattr(llm, "write_script", lambda c, chars, conversation, screenshots=(): convo.append(conversation) or real_script(c, chars, conversation))

    def fwd(text, origin):
        return {"update_id": 4, "message": {"chat": {"id": 7, "type": "private"}, "from": {"id": 42, "first_name": "Kush"},
                                            "text": text, "forward_origin": origin}}

    bot.handle_update(fwd("you up?", {"type": "user", "sender_user": {"id": 9, "first_name": "Priya"}}))
    assert "Collecting forwarded messages" in bot.sent[-1][1]
    bot.handle_update(fwd("no", {"type": "hidden_user", "sender_user_name": "Arjun"}))
    assert len(bot.sent) == 1  # only the first forward is acknowledged
    bot.handle_update(text_update("/comic"))

    row = pipeline.store._db.execute("SELECT id FROM comics").fetchone()
    assert wait_for(pipeline.store, row["id"])["status"] == "done"
    assert seen == [("Priya", True), ("Arjun", False)]  # hidden users have no photo to fetch
    assert convo == ["Priya: you up?\nArjun: no"]
