"""Telegram bot: a conversation + profile photos -> comic, panels pushed as they finish.

Bots can't read private chats between two people, so a conversation reaches the bot one of
three ways:
- Group: add the bot to a group with the other person; it keeps the recent messages and
  /comic draws them, every speaker a character from their profile photo.
  (Needs privacy mode off in @BotFather -> /setprivacy -> Disable, or the bot only sees commands.)
- Forwards: forward messages from any chat to the bot in private, then /comic.
- Paste: send a chat as text ("Name: message" lines), or a screenshot, in private.
In private, a photo with a caption adds a character named by the caption (kept until /reset).
"""
import logging
import secrets
import threading
from collections import deque

import requests

from . import render
from .pipeline import CharacterInput, ComicRequest, Notifier

log = logging.getLogger(__name__)

HELP = (
    "I turn conversations into 4-panel comics.\n\n"
    "In a group: chat as usual, then send /comic to draw the recent messages.\n"
    "In private: forward messages from any chat, then /comic. Or paste a chat "
    "('Name: message' lines) or send a screenshot.\n"
    "Photo with a caption: adds that person as a character (caption = their name).\n"
    "/reset clears collected messages and added characters."
)
MAX_EXTRA_CHARACTERS = 3
MAX_SPEAKERS = 4
HISTORY = 30          # messages kept per chat
MIN_MESSAGES = 2


class Bot:
    def __init__(self, token, pipeline, store, public_url=""):
        self._base = f"https://api.telegram.org/bot{token}"
        self._file_base = f"https://api.telegram.org/file/bot{token}"
        self.pipeline = pipeline
        self.store = store
        self.public_url = public_url.rstrip("/")
        # Both in memory, lost on restart.
        self._characters = {}   # chat_id -> [CharacterInput] added by captioned photos
        self._history = {}      # chat_id -> deque of (speaker_name, user_id | None, text)
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
        """Largest current profile photo as JPEG, or None (no photo, or hidden by privacy settings)."""
        try:
            photos = self.api("getUserProfilePhotos", user_id=user_id, limit=1)["photos"]
            if not photos:
                return None
            return render.to_jpeg(self.download(photos[0][-1]["file_id"]))
        except Exception:
            log.warning("no profile photo for user %s", user_id, exc_info=True)
            return None

    # --- Updates -------------------------------------------------------------------
    def handle_update(self, update):
        msg = update.get("message")
        if not msg or "from" not in msg:
            return
        chat_id = msg["chat"]["id"]
        try:
            if msg["chat"].get("type") in ("group", "supergroup"):
                self._handle_group(chat_id, msg)
            else:
                self._handle_private(chat_id, msg)
        except Exception:
            log.exception("update %s failed", update.get("update_id"))
            self.send_message(chat_id, "Something went wrong. Please try again.")

    def _handle_group(self, chat_id, msg):
        text = (msg.get("text") or "").strip()
        command = _command(text)
        if command in ("/start", "/help"):
            return self.send_message(chat_id, HELP)
        if command == "/reset":
            return self._reset(chat_id)
        if command == "/comic":
            return self._comic_from_history(chat_id, msg["from"])
        if text and not command and not msg["from"].get("is_bot"):
            user = msg["from"]
            self._remember(chat_id, user.get("first_name") or "Someone", user["id"], text)

    def _handle_private(self, chat_id, msg):
        text = (msg.get("text") or "").strip()
        command = _command(text)
        if command in ("/start", "/help"):
            return self.send_message(chat_id, HELP)
        if command == "/reset":
            return self._reset(chat_id)
        if command == "/comic":
            return self._comic_from_history(chat_id, msg["from"])

        origin = msg.get("forward_origin")
        if origin and text:
            name, user_id = _origin_speaker(origin)
            first = self._remember(chat_id, name, user_id, text)
            if first:
                self.send_message(chat_id, "Collecting forwarded messages. Send /comic when you're done.")
            return

        if "photo" in msg:
            image = render.to_jpeg(self.download(msg["photo"][-1]["file_id"]))
            name = (msg.get("caption") or "").strip()[:40]
            if name:
                return self._add_character(chat_id, name, image)
            me = CharacterInput(msg["from"].get("first_name") or "Me", self.profile_photo(msg["from"]["id"]),
                                notes="This is the person who sent the chat.")
            return self._start_comic(chat_id, [me], screenshots=[image])
        if text and not command:
            me = CharacterInput(msg["from"].get("first_name") or "Me", self.profile_photo(msg["from"]["id"]),
                                notes="This is the person who sent the chat.")
            return self._start_comic(chat_id, [me], conversation=text[:4000])
        self.send_message(chat_id, HELP)

    # --- Helpers ---------------------------------------------------------------------
    def _remember(self, chat_id, name, user_id, text):
        """Store one message; returns True if it is the first in the buffer."""
        with self._lock:
            history = self._history.setdefault(chat_id, deque(maxlen=HISTORY))
            history.append((name[:40], user_id, text[:300]))
            return len(history) == 1

    def _reset(self, chat_id):
        with self._lock:
            self._characters.pop(chat_id, None)
            self._history.pop(chat_id, None)
        self.send_message(chat_id, "Cleared collected messages and added characters.")

    def _add_character(self, chat_id, name, image):
        with self._lock:
            extra = self._characters.setdefault(chat_id, [])
            extra[:] = [c for c in extra if c.name != name][-(MAX_EXTRA_CHARACTERS - 1):]
            extra.append(CharacterInput(name, image))
        self.send_message(chat_id, f"Added {name}. Now send the conversation.")

    def _comic_from_history(self, chat_id, requester):
        with self._lock:
            history = list(self._history.get(chat_id, []))
        if len(history) < MIN_MESSAGES:
            return self.send_message(
                chat_id, "I need a few messages first. In a group, chat a bit (and make sure privacy "
                         "mode is off in @BotFather). In private, forward me some messages.")
        speakers = {}   # (name, user_id) -> CharacterInput, in order of first appearance
        for name, user_id, _ in history:
            if (name, user_id) not in speakers and len(speakers) < MAX_SPEAKERS:
                photo = self.profile_photo(user_id) if user_id else None
                speakers[(name, user_id)] = CharacterInput(name, photo)
        conversation = "\n".join(f"{name}: {text}" for name, _, text in history)
        if self._start_comic(chat_id, list(speakers.values()), conversation=conversation):
            with self._lock:
                self._history.pop(chat_id, None)

    def _start_comic(self, chat_id, characters, conversation="", screenshots=()):
        if self.store.active_for_chat(chat_id):
            self.send_message(chat_id, "Still drawing the last comic. One at a time!")
            return False
        with self._lock:
            names = {c.name for c in characters}
            extra = [c for c in self._characters.get(chat_id, []) if c.name not in names]
        comic_id = secrets.token_urlsafe(8)
        self.store.create(comic_id, "telegram", chat_id)
        self.pipeline.submit(comic_id, ComicRequest([*characters, *extra], conversation, list(screenshots)),
                             _ChatNotifier(self, chat_id))
        self.send_message(chat_id, "Drawing your comic. Panels will arrive as they finish...")
        return True


def _command(text):
    """'/comic@MiraComixBot now' -> '/comic'; None for ordinary text."""
    if not text.startswith("/"):
        return None
    return text.split()[0].split("@")[0].lower()


def _origin_speaker(origin):
    """Who wrote a forwarded message: (name, user_id or None if hidden by their privacy settings)."""
    kind = origin.get("type")
    if kind == "user":
        user = origin["sender_user"]
        return user.get("first_name") or "Someone", user["id"]
    if kind == "hidden_user":
        return origin.get("sender_user_name") or "Someone", None
    chat = origin.get("sender_chat") or origin.get("chat") or {}
    return chat.get("title") or "Someone", None


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
