"""Gemini steps: one character sheet per person (from their photo), then the 4-panel script.

Same two-stage shape as the original Mira flow (per-character flows, then a merge step).
"""
import logging
import os

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

log = logging.getLogger(__name__)

# Tried in order: free-tier Flash models are often briefly overloaded (503) or rate limited (429).
MODELS = os.environ.get("GEMINI_MODELS", "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.8-flash").split(",")
TIMEOUT_MS = 30_000


class Character(BaseModel):
    name: str
    appearance: str   # visual description reused verbatim in every panel prompt
    personality: str


class Line(BaseModel):
    speaker: str
    text: str


class Panel(BaseModel):
    scene: str        # self-contained image prompt, no text or speech bubbles
    dialogue: list[Line]


class Script(BaseModel):
    title: str
    panels: list[Panel]


CHARACTER_PROMPT = (
    "You design characters for a comic. Describe {name} so an image model can draw them "
    "consistently in every panel: age range, build, face, hair, skin tone, clothing, one "
    "distinctive detail. Keep 'appearance' under 60 words. Do not guess sensitive traits "
    "(ethnicity, religion, health). Extra notes from the user: {notes}"
)

SCRIPT_PROMPT = (
    "Write a funny 4-panel comic based on the conversation below.\n"
    "Characters:\n{characters}\n\n"
    "Conversation (it may also be in the attached chat screenshots):\n{conversation}\n\n"
    "Rules: exactly 4 panels. Each 'scene' is a standalone prompt for an image model: "
    "repeat each visible character's full appearance in it, describe setting, pose and "
    "expression, and never ask for text, letters or speech bubbles (dialogue is added "
    "separately). Each panel has 0-3 short lines of dialogue (under 15 words each), taken "
    "from or faithful to the conversation."
)


def _retryable(exc):
    if isinstance(exc, errors.ServerError) or isinstance(exc, httpx.TimeoutException):
        return True
    return isinstance(exc, errors.ClientError) and exc.code == 429


def _ask(client, parts, schema):
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema)
    for i, model in enumerate(MODELS):
        try:
            resp = client.models.generate_content(model=model, contents=parts, config=config)
        except Exception as exc:
            if not _retryable(exc) or i == len(MODELS) - 1:
                raise
            log.warning("Gemini %s unavailable (%s), trying %s", model, type(exc).__name__, MODELS[i + 1])
            continue
        if resp.parsed is None:
            raise ValueError(f"{model} returned no parseable JSON")
        return resp.parsed


def make_client():
    return genai.Client(http_options=types.HttpOptions(timeout=TIMEOUT_MS))  # reads GEMINI_API_KEY


def describe_character(client, name, photo=None, notes=""):
    parts = [CHARACTER_PROMPT.format(name=name, notes=notes or "none")]
    if photo:
        parts.append(types.Part.from_bytes(data=photo, mime_type="image/jpeg"))
    character = _ask(client, parts, Character)
    character.name = name  # keep the user's spelling
    return character


def write_script(client, characters, conversation, screenshots=()):
    roster = "\n".join(f"- {c.name}: {c.appearance} Personality: {c.personality}" for c in characters)
    parts = [SCRIPT_PROMPT.format(characters=roster, conversation=conversation or "(see screenshots)")]
    parts += [types.Part.from_bytes(data=s, mime_type="image/jpeg") for s in screenshots]
    script = _ask(client, parts, Script)
    if len(script.panels) != 4:
        raise ValueError(f"expected 4 panels, model returned {len(script.panels)}")
    return script
