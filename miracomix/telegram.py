"""Telegram bot: chat text (or a chat screenshot) + profile photos -> comic, panels pushed as they finish.

- Text message: the conversation. The sender is a character, drawn from their profile photo.
- Photo with a caption: adds a character named by the caption (kept until /reset).
- Photo without a caption: a chat screenshot to turn into a comic.
"""
import logging
import secrets
import threading

import requests

from . import render
from .pipeline import CharacterInput, ComicRequest, Notifier

log = logging.getLogger(__name__)

HELP = (
    "Send me a conversation and I'll turn it into a 4-panel comic.\n\n"
    "- Text: paste the chat, one 'Name: message' per line.\n"
    "- Photo without caption: a chat screenshot.\n"
    "- Photo with a caption: adds that person as a character (caption = their name).\n"
    "/reset forgets added characters."
)
MAX_EXTRA_CHARACTERS = 3


class Bot:
    def __init__(self, token, pipeline, store, public_url=""):
        self._base = f"https://api.telegram.org/bot{token}"
        self._file_base = f"https://api.telegram.org/file/bot{token}"
        self.pipeline = pipeline
        self.store = store
        self.public_url = public_url.rstrip("/")
        self._characters = {}   # chat_id -> [CharacterInput]; in memory, lost on restart
        self._lock = threading.Lock()

    # --- Bot API -----------------------------------------------------------------
    def api(self, method, files=None, **params):
        resp = requests.post(f"{self._base}/{method}", data=params, files=files, timeout=60)
        body = resp.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
        return body["result"]

    def send_message(self, chat_id, text):
        self.api("sendMessage", chat_id=chat_id, text=text)

    def send_photo(self, chat_id, path, caption=""):
        with open(path, "rb") as f:
            self.api("sendPhoto", chat_id=chat_id, caption=caption, files={"photo": f})

    def download(self, file_id):
        path = self.api("getFile", file_id=file_id)["file_path"]
        resp = requests.get(f"{self._file_base}/{path}", timeout=60)
        resp.raise_for_status()
        return resp.content

    def profile_photo(self, user_id):
        photos = self.api("getUserProfilePhotos", user_id=user_id, limit=1)["photos"]
        if not photos:
            return None
        return render.to_jpeg(self.download(photos[0][-1]["file_id"]))  # last size = largest

    # --- Updates -------------------------------------------------------------------
    def handle_update(self, update):
        msg = update.get("message")
        if not msg or "from" not in msg:
            return
        chat_id = msg["chat"]["id"]
        try:
            self._handle_message(chat_id, msg)
        except Exception:
            log.exception("update %s failed", update.get("update_id"))
            self.send_message(chat_id, "Something went wrong. Please try again.")

    def _handle_message(self, chat_id, msg):
        text = (msg.get("text") or "").strip()
        if text in ("/start", "/help"):
            return self.send_message(chat_id, HELP)
        if text == "/reset":
            with self._lock:
                self._characters.pop(chat_id, None)
            return self.send_message(chat_id, "Added characters cleared.")

        if "photo" in msg:
            image = render.to_jpeg(self.download(msg["photo"][-1]["file_id"]))
            name = (msg.get("caption") or "").strip()[:40]
            if name:
                return self._add_character(chat_id, name, image)
            return self._start_comic(chat_id, msg["from"], screenshots=[image])
        if text and not text.startswith("/"):
            return self._start_comic(chat_id, msg["from"], conversation=text[:4000])
        self.send_message(chat_id, HELP)

    def _add_character(self, chat_id, name, image):
        with self._lock:
            extra = self._characters.setdefault(chat_id, [])
            extra[:] = [c for c in extra if c.name != name][-(MAX_EXTRA_CHARACTERS - 1):]
            extra.append(CharacterInput(name, image))
        self.send_message(chat_id, f"Added {name}. Now send the conversation.")

    def _start_comic(self, chat_id, sender, conversation="", screenshots=()):
        if self.store.active_for_chat(chat_id):
            return self.send_message(chat_id, "Still drawing your last comic. One at a time!")
        me = CharacterInput(sender.get("first_name") or "Me", self.profile_photo(sender["id"]),
                            notes="This is the person who sent the chat.")
        with self._lock:
            extra = list(self._characters.get(chat_id, []))
        comic_id = secrets.token_urlsafe(8)
        self.store.create(comic_id, "telegram", chat_id)
        self.pipeline.submit(comic_id, ComicRequest([me, *extra], conversation, list(screenshots)),
                             _ChatNotifier(self, chat_id))
        self.send_message(chat_id, "Drawing your comic. Panels will arrive as they finish...")


class _ChatNotifier(Notifier):
    def __init__(self, bot, chat_id):
        self.bot, self.chat_id = bot, chat_id

    def panel(self, comic_id, index, path):
        self.bot.send_photo(self.chat_id, path, caption=f"Panel {index + 1}/4")

    def done(self, comic_id, page_path, title):
        link = f"\nShare: {self.bot.public_url}/c/{comic_id}" if self.bot.public_url else ""
        self.bot.send_photo(self.chat_id, page_path, caption=f"{title}{link}")

    def failed(self, comic_id, message):
        self.bot.send_message(self.chat_id, message)
