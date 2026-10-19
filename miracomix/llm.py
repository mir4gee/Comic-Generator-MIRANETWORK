"""Gemini steps: one character sheet per person (from their photo), then the 4-panel script.

Same two-stage shape as the original Mira flow (per-character flows, then a merge step).
"""
import base64
import os

from google import genai
from pydantic import BaseModel

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")


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


def _image_part(jpeg_bytes):
    return {"type": "image", "data": base64.b64encode(jpeg_bytes).decode(), "mime_type": "image/jpeg"}


def _ask(client, parts, schema):
    interaction = client.interactions.create(
        model=MODEL,
        input=parts,
        response_format={"type": "text", "mime_type": "application/json", "schema": schema.model_json_schema()},
        store=False,
    )
    return schema.model_validate_json(interaction.output_text)


def make_client():
    return genai.Client()  # reads GEMINI_API_KEY


def describe_character(client, name, photo=None, notes=""):
    parts = [{"type": "text", "text": CHARACTER_PROMPT.format(name=name, notes=notes or "none")}]
    if photo:
        parts.append(_image_part(photo))
    character = _ask(client, parts, Character)
    character.name = name  # keep the user's spelling
    return character


def write_script(client, characters, conversation, screenshots=()):
    roster = "\n".join(f"- {c.name}: {c.appearance} Personality: {c.personality}" for c in characters)
    parts = [{"type": "text", "text": SCRIPT_PROMPT.format(characters=roster, conversation=conversation or "(see screenshots)")}]
    parts += [_image_part(s) for s in screenshots]
    script = _ask(client, parts, Script)
    if len(script.panels) != 4:
        raise ValueError(f"expected 4 panels, model returned {len(script.panels)}")
    return script
