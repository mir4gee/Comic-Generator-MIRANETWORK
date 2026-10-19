import io
import time

import pytest
from PIL import Image

from miracomix import images, llm
from miracomix.pipeline import Pipeline
from miracomix.store import Store


def png_bytes(color="red", size=(64, 64)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def fake_script(*_args, **_kwargs):
    return llm.Script(title="Pizza <b>Heist</b>", panels=[
        llm.Panel(scene=f"scene {i}", dialogue=[llm.Line(speaker="Asha", text=f"line {i}")]) for i in range(4)
    ])


def fake_character(_client, name, photo=None, notes=""):
    return llm.Character(name=name, appearance=f"{name} look", personality="cheeky")


@pytest.fixture
def fakes(monkeypatch):
    """Replace Gemini and FLUX with local fakes; returns the list of render calls."""
    calls = []

    def draw(prompt, seed):
        calls.append(prompt)
        return png_bytes()

    monkeypatch.setattr(llm, "describe_character", fake_character)
    monkeypatch.setattr(llm, "write_script", fake_script)
    monkeypatch.setitem(images.PROVIDERS, "cloudflare", draw)
    monkeypatch.setitem(images.PROVIDERS, "pollinations", draw)
    return calls


@pytest.fixture
def pipeline(tmp_path):
    return Pipeline(Store(str(tmp_path / "comics.db")), tmp_path, llm_client=None)


def wait_for(store, comic_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        comic = store.get(comic_id)
        if comic["status"] in ("done", "failed"):
            return comic
        time.sleep(0.02)
    raise AssertionError(f"comic stuck in {store.get(comic_id)['status']}")
