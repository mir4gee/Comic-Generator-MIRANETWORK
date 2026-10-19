"""MiraComix: turn a chat and profile photos into a 4-panel comic (Flask + Telegram + Gemini + FLUX)."""
import hmac
import json
import os
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click
from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory, url_for

from . import images, llm, render
from .pipeline import CharacterInput, ComicRequest, Pipeline
from .store import Store
from .telegram import Bot

COMIC_ID = re.compile(r"^[A-Za-z0-9_-]{8,16}$")
MAX_CHARACTERS = 4


def create_app(pipeline=None, bot=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    if pipeline is None:
        pipeline = Pipeline(Store(str(data_dir / "comics.db")), data_dir, llm.make_client())
    store = pipeline.store
    if bot is None and os.environ.get("TELEGRAM_BOT_TOKEN"):
        bot = Bot(os.environ["TELEGRAM_BOT_TOKEN"], pipeline, store, os.environ.get("PUBLIC_URL", ""))
    updates = ThreadPoolExecutor(4, thread_name_prefix="tg-update")

    def get_comic_or_404(comic_id):
        comic = store.get(comic_id) if COMIC_ID.match(comic_id) else None
        if comic is None:
            abort(404)
        return comic

    def public_state(comic):
        return {
            "id": comic["id"],
            "status": comic["status"],
            "title": comic["title"],
            "error": "Couldn't make this comic. Please try again." if comic["status"] == "failed" else None,
            "panels": [
                {"status": p["status"],
                 "url": url_for("panel_image", comic_id=comic["id"], index=i) if p["status"] == "done" else None}
                for i, p in enumerate(comic["panels"])
            ],
            "comic_url": url_for("comic_image", comic_id=comic["id"]) if comic["status"] == "done" else None,
        }

    # --- Web UI ----------------------------------------------------------------------
    @app.get("/")
    def index():
        return render_template("index.html", providers=list(images.PROVIDERS), default=images.DEFAULT_PROVIDER)

    @app.get("/c/<comic_id>")
    def comic_page(comic_id):
        comic = get_comic_or_404(comic_id)
        return render_template("comic.html", comic=public_state(comic))

    @app.get("/c/<comic_id>/panel-<int:index>.png")
    def panel_image(comic_id, index):
        get_comic_or_404(comic_id)
        return send_from_directory(pipeline.comic_dir(comic_id), f"panel-{index}.png")

    @app.get("/c/<comic_id>/comic.png")
    def comic_image(comic_id):
        get_comic_or_404(comic_id)
        return send_from_directory(pipeline.comic_dir(comic_id), "comic.png")

    # --- JSON API --------------------------------------------------------------------
    @app.post("/api/comics")
    def create_comic():
        names = request.form.getlist("name")
        photos = request.files.getlist("photo")
        characters = []
        for i, name in enumerate(names[:MAX_CHARACTERS]):
            name = name.strip()[:40]
            if not name:
                continue
            upload = photos[i] if i < len(photos) else None
            try:
                photo = render.to_jpeg(upload.read()) if upload and upload.filename else None
            except Exception:
                return jsonify(error=f"Photo for {name} isn't a readable image."), 400
            characters.append(CharacterInput(name, photo))

        conversation = request.form.get("conversation", "").strip()[:4000]
        screenshots = []
        for upload in request.files.getlist("screenshot")[:3]:
            if upload.filename:
                try:
                    screenshots.append(render.to_jpeg(upload.read(), max_side=1600))
                except Exception:
                    return jsonify(error="A screenshot isn't a readable image."), 400
        provider = request.form.get("provider", images.DEFAULT_PROVIDER)

        if not characters:
            return jsonify(error="Add at least one character."), 400
        if not conversation and not screenshots:
            return jsonify(error="Add a conversation or a chat screenshot."), 400
        if provider not in images.PROVIDERS:
            return jsonify(error="Unknown image provider."), 400

        comic_id = secrets.token_urlsafe(8)
        store.create(comic_id, "web")
        pipeline.submit(comic_id, ComicRequest(characters, conversation, screenshots, provider))
        return jsonify(id=comic_id, url=url_for("comic_page", comic_id=comic_id),
                       status_url=url_for("comic_status", comic_id=comic_id)), 202

    @app.get("/api/comics/<comic_id>")
    def comic_status(comic_id):
        return jsonify(public_state(get_comic_or_404(comic_id)))

    @app.get("/api/comics/<comic_id>/events")
    def comic_events(comic_id):
        """Server-sent events: one message per state change, closed when the comic finishes."""
        get_comic_or_404(comic_id)

        def stream():
            last = None
            deadline = time.monotonic() + 300
            with app.app_context(), app.test_request_context():
                while time.monotonic() < deadline:
                    state = public_state(store.get(comic_id))
                    if state != last:
                        yield f"data: {json.dumps(state)}\n\n"
                        last = state
                    if state["status"] in ("done", "failed"):
                        return
                    time.sleep(0.5)

        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})

    # --- Telegram ----------------------------------------------------------------------
    @app.post("/telegram/webhook")
    def telegram_webhook():
        expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        given = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if bot is None or not expected or not hmac.compare_digest(given, expected):
            abort(403)
        updates.submit(bot.handle_update, request.get_json(force=True))
        return "ok"  # answer fast; Telegram retries slow or failed webhooks

    @app.cli.group()
    def telegram():
        """Telegram bot commands."""

    @telegram.command("poll")
    def telegram_poll():
        """Long-poll for updates (local development, no public URL needed)."""
        if bot is None:
            raise click.ClickException("Set TELEGRAM_BOT_TOKEN first.")
        bot.api("deleteWebhook")
        offset = None
        click.echo("Polling Telegram. Ctrl+C to stop.")
        while True:
            for update in bot.api("getUpdates", timeout=30, offset=offset):
                offset = update["update_id"] + 1
                updates.submit(bot.handle_update, update)

    @telegram.command("set-webhook")
    @click.argument("public_url")
    def telegram_set_webhook(public_url):
        """Point Telegram at PUBLIC_URL/telegram/webhook (needs TELEGRAM_WEBHOOK_SECRET)."""
        if bot is None or not os.environ.get("TELEGRAM_WEBHOOK_SECRET"):
            raise click.ClickException("Set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET first.")
        bot.api("setWebhook", url=f"{public_url.rstrip('/')}/telegram/webhook",
                secret_token=os.environ["TELEGRAM_WEBHOOK_SECRET"], allowed_updates='["message"]')
        click.echo("Webhook set.")

    return app
