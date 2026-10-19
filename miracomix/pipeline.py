"""Orchestrates one comic: character sheets -> script -> 4 panels in parallel -> page.

Job threads only coordinate; Gemini and FLUX calls run on a separate worker pool so a job
waiting on its panels can never starve the pool it is waiting on.
"""
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import images, llm, render

log = logging.getLogger(__name__)


@dataclass
class CharacterInput:
    name: str
    photo: bytes | None = None   # normalised JPEG
    notes: str = ""


@dataclass
class ComicRequest:
    characters: list[CharacterInput]
    conversation: str = ""
    screenshots: list[bytes] = field(default_factory=list)
    provider: str = images.DEFAULT_PROVIDER


class Notifier:
    """Hooks for push-style clients (Telegram). The web UI reads the store instead."""

    def panel(self, comic_id, index, path):
        pass

    def done(self, comic_id, page_path, title):
        pass

    def failed(self, comic_id, message):
        pass


class Pipeline:
    def __init__(self, store, data_dir, llm_client, jobs=2, workers=8):
        self.store = store
        self.data_dir = Path(data_dir)
        self.llm = llm_client
        self._jobs = ThreadPoolExecutor(jobs, thread_name_prefix="comic-job")
        self._work = ThreadPoolExecutor(workers, thread_name_prefix="comic-work")

    def comic_dir(self, comic_id):
        return self.data_dir / comic_id

    def submit(self, comic_id, request, notifier=None):
        self._jobs.submit(self._run, comic_id, request, notifier or Notifier())

    def _run(self, comic_id, req, notifier):
        try:
            self._make(comic_id, req, notifier)
        except Exception as exc:
            log.exception("comic %s failed", comic_id)
            message = "Couldn't make this comic. Please try again."
            self.store.update(comic_id, status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
            notifier.failed(comic_id, message)

    def _make(self, comic_id, req, notifier):
        out = self.comic_dir(comic_id)
        out.mkdir(parents=True, exist_ok=True)

        self.store.update(comic_id, status="writing")
        sheets = list(self._work.map(
            lambda c: llm.describe_character(self.llm, c.name, c.photo, c.notes), req.characters))
        script = llm.write_script(self.llm, sheets, req.conversation, req.screenshots)
        panels = [{"status": "drawing", "dialogue": [l.model_dump() for l in p.dialogue]} for p in script.panels]
        self.store.update(comic_id, status="drawing", title=script.title, panels=panels)

        draw = images.PROVIDERS[req.provider]
        seed = random.randrange(1, 2**31)  # one seed per comic keeps the look consistent
        futures = {self._work.submit(draw, p.scene, seed): i for i, p in enumerate(script.panels)}
        finished = [None] * 4
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                panel = render.panel_with_dialogue(fut.result(), panels[i]["dialogue"])
            except Exception:
                log.exception("comic %s panel %d failed", comic_id, i)
                self.store.set_panel(comic_id, i, status="failed")
                continue
            path = out / f"panel-{i}.png"
            panel.save(path)
            finished[i] = panel
            self.store.set_panel(comic_id, i, status="done")
            notifier.panel(comic_id, i, path)

        if any(p is None for p in finished):
            raise RuntimeError(f"{finished.count(None)} of 4 panels failed to render")
        page_path = out / "comic.png"
        render.compose_page(finished, script.title).save(page_path)
        self.store.update(comic_id, status="done")
        notifier.done(comic_id, page_path, script.title)
