"""FLUX renderers. IMAGE_PROVIDER picks the default; the web form can override per comic."""
import base64
import os
import time
from urllib.parse import quote

import requests

STYLE = "comic book panel, bold ink outlines, flat vibrant colors, dynamic composition, no text, no speech bubbles. "
SIZE = 1024
TIMEOUT = 90
RETRYABLE = {429, 500, 502, 503, 504}


class RenderError(Exception):
    pass


def _request(method, url, **kwargs):
    """HTTP with a short backoff on rate limits and server errors."""
    for attempt in range(3):
        try:
            resp = requests.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            if attempt == 2:
                raise RenderError(f"network error: {exc}") from exc
        else:
            if resp.status_code not in RETRYABLE or attempt == 2:
                if not resp.ok:
                    raise RenderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return resp
        time.sleep(2 ** attempt)


def cloudflare(prompt, seed):
    # Workers AI's FLUX schema rejects unknown fields, seed included, so the seed is unused here.
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    resp = _request(
        "POST",
        f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/black-forest-labs/flux-1-schnell",
        headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"},
        json={"prompt": (STYLE + prompt)[:2048], "steps": 4},
    )
    body = resp.json()
    image = body.get("result", body).get("image")
    if not image:
        raise RenderError(f"no image in response: {str(body)[:200]}")
    return base64.b64decode(image)


def pollinations(prompt, seed):
    params = {"width": SIZE, "height": SIZE, "seed": seed}
    key = os.environ.get("POLLINATIONS_KEY")
    if key:
        # Keyed API: FLUX.1 schnell explicitly.
        url = f"https://gen.pollinations.ai/image/{quote(STYLE + prompt)}"
        params["model"] = "black-forest-labs/flux.1-schnell"
        resp = _request("GET", url, params=params, headers={"Authorization": f"Bearer {key}"})
    else:
        # Keyless legacy endpoint: free but the server may substitute another model.
        url = f"https://image.pollinations.ai/prompt/{quote(STYLE + prompt)}"
        params.update(model="flux", nologo="true")
        resp = _request("GET", url, params=params)
    if not resp.headers.get("content-type", "").startswith("image/"):
        raise RenderError(f"not an image: {resp.text[:200]}")
    return resp.content


PROVIDERS = {"cloudflare": cloudflare, "pollinations": pollinations}
DEFAULT_PROVIDER = os.environ.get("IMAGE_PROVIDER", "cloudflare")
