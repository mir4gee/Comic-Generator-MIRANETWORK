from PIL import Image

from miracomix import images
from miracomix.pipeline import CharacterInput, ComicRequest, Notifier

from .conftest import png_bytes, wait_for


class Recorder(Notifier):
    def __init__(self):
        self.events = []

    def panel(self, comic_id, index, path):
        self.events.append(("panel", index))

    def done(self, comic_id, page_path, title):
        self.events.append(("done", title))

    def failed(self, comic_id, message):
        self.events.append(("failed", message))


def test_makes_four_panels_and_a_page(fakes, pipeline):
    rec = Recorder()
    pipeline.store.create("abcdefgh", "web")
    pipeline.submit("abcdefgh", ComicRequest([CharacterInput("Asha")], "Asha: hi"), rec)
    comic = wait_for(pipeline.store, "abcdefgh")

    assert comic["status"] == "done"
    assert [p["status"] for p in comic["panels"]] == ["done"] * 4
    assert sorted(e[1] for e in rec.events if e[0] == "panel") == [0, 1, 2, 3]
    assert rec.events[-1] == ("done", "Pizza <b>Heist</b>")
    page = Image.open(pipeline.comic_dir("abcdefgh") / "comic.png")
    assert page.width > 1500  # 2 panels wide
    assert len(fakes) == 4


def test_a_failed_panel_fails_the_comic(fakes, pipeline, monkeypatch):
    def flaky(prompt, seed):
        if prompt == "scene 2":
            raise images.RenderError("HTTP 500")
        return png_bytes()

    monkeypatch.setitem(images.PROVIDERS, "cloudflare", flaky)
    rec = Recorder()
    pipeline.store.create("abcdefgh", "web")
    pipeline.submit("abcdefgh", ComicRequest([CharacterInput("Asha")], "Asha: hi", provider="cloudflare"), rec)
    comic = wait_for(pipeline.store, "abcdefgh")

    assert comic["status"] == "failed"
    assert comic["panels"][2]["status"] == "failed"
    assert "1 of 4 panels" in comic["error"]
    assert rec.events[-1][0] == "failed"
    assert "HTTP 500" not in rec.events[-1][1]  # internal errors are not shown to users


def test_script_error_marks_failed(fakes, pipeline, monkeypatch):
    from miracomix import llm

    def broken(*_a, **_k):
        raise ValueError("expected 4 panels, model returned 3")

    monkeypatch.setattr(llm, "write_script", broken)
    pipeline.store.create("abcdefgh", "web")
    pipeline.submit("abcdefgh", ComicRequest([CharacterInput("Asha")], "hi"))
    assert wait_for(pipeline.store, "abcdefgh")["status"] == "failed"
