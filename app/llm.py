import base64
import io
import json
import logging
import os
import re
import sys
import time

import openai
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image, ImageOps
from pydantic import ValidationError

from app.schemas import Approach

load_dotenv()
log = logging.getLogger("approach-mapper")

SYSTEM_PROMPT = """You are a patient STEM tutor. A learner is stuck at "I don't know where to start" on a problem (coding, math, physics, statistics, or any other STEM subject). It may be given as text, as photos, or both.
Your job is to teach the WAY OF THINKING, not to solve the problem. Never state the final answer or give full code/working, except in hint level 4.

Rules:
- Use only what is visible or stated. If part of an image is unclear, list it in unreadable_parts instead of guessing.
- domain: a short free-text label you choose (e.g. "coding", "calculus", "physics", "probability").
- pattern: the pattern or method that fits (an algorithm pattern, theorem, formula family, etc.).
- steps: 4 to 8, each written as a question the learner asks themselves ("think"), then what to do in words ("do"). n starts at 1.
- mindmap: 6 to 12 nodes, exactly one node of kind "start", branching "question" nodes with labelled edges (e.g. yes / no), at least one "end". kind is one of start, question, action, pattern, end. Node ids are unique strings; every edge's from/to must be an existing node id. Labels are short plain text, at most 6 words, with no brackets, quotes or parentheses.
- hint_ladder: exactly 4 escalating strings: level 1 a nudge only, level 2 names the pattern, level 3 outlines the method, level 4 may include pseudocode or a worked first step.
- cost_note: for code, time and space complexity; otherwise the cost or key quantity of the method; null if not applicable.
- similar_problems: 3 well-known problems using the same pattern (names only).
- Output ONE JSON object only, no markdown fences, with exactly these keys:
{"domain": str, "problem_restated": str, "given_and_goal": {"given": [str], "find": str},
 "clues": [{"clue": str, "suggests": str}], "pattern": {"name": str, "why_it_fits": str},
 "steps": [{"n": int, "title": str, "think": str, "do": str}],
 "mindmap": {"nodes": [{"id": str, "label": str, "kind": str}], "edges": [{"from": str, "to": str, "label": str or null}]},
 "hint_ladder": [str, str, str, str], "cost_note": str or null,
 "pitfalls": [str], "similar_problems": [str], "unreadable_parts": [str]}"""


class LLMError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def prep_image(raw: bytes) -> str:
    max_px = int(os.getenv("MAX_IMAGE_PX", "1600"))
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    except Exception:
        raise LLMError(400, "Could not read that image. Use a valid jpg, png or webp file.")
    img.thumbnail((max_px, max_px))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def parse(raw: str) -> Approach:
    raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw.strip())
    return Approach.model_validate(json.loads(raw))


def _client() -> OpenAI:
    base, key = os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY")
    if not (base and os.getenv("LLM_MODEL")):
        raise LLMError(500, "Server is not configured: set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL.")
    # local servers (Ollama etc.) accept any non-empty key
    return OpenAI(base_url=base, api_key=key or "none",
                  timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")), max_retries=0)


def _complete(client: OpenAI, messages: list, has_images: bool) -> str:
    kwargs = dict(model=os.environ["LLM_MODEL"], messages=messages)
    try:
        try:
            r = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except openai.BadRequestError as e:
            msg = str(e).lower()
            if has_images and re.search(r"image|vision|multimodal|modalit", msg) and "response_format" not in msg:
                raise
            r = client.chat.completions.create(**kwargs)  # provider rejected json mode
        return r.choices[0].message.content or ""
    except openai.APITimeoutError:
        raise LLMError(504, "The model took too long to answer. Try again, or use a smaller image or faster model.")
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        raise LLMError(502, "The API key was rejected (401/403). Check LLM_API_KEY.")
    except openai.RateLimitError:
        raise LLMError(429, "Rate limit hit on the model provider. Wait a bit and try again.")
    except openai.APIConnectionError:
        raise LLMError(502, "Could not reach the model endpoint. Check LLM_BASE_URL.")
    except openai.APIStatusError as e:
        if e.status_code == 413:
            raise LLMError(413, "Image too large for the model. Try a smaller image.")
        if e.status_code == 404:
            raise LLMError(502, "Model or endpoint not found. Check LLM_MODEL and LLM_BASE_URL.")
        if e.status_code == 400 and has_images:
            raise LLMError(400, "This model doesn't appear to support images. Paste the problem as text, or switch to a vision model.")
        raise LLMError(502, f"The model provider returned an error ({e.status_code}).")


def map_approach(text: str, images: list[bytes]) -> tuple[Approach, dict]:
    client = _client()
    content = [{"type": "image_url", "image_url": {"url": prep_image(b)}} for b in images]
    content.append({"type": "text", "text": text.strip() or "The problem is in the image(s)."})
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]
    if not images:  # plain string content works on text-only models
        messages[1]["content"] = content[0]["text"]

    t0 = time.monotonic()
    raw = _complete(client, messages, bool(images))
    try:
        approach = parse(raw)
    except (ValueError, ValidationError) as e:  # JSONDecodeError is a ValueError
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"That output was invalid: {e}\nReturn the corrected JSON object only."}]
        try:
            approach = parse(_complete(client, messages, bool(images)))
        except (ValueError, ValidationError):
            raise LLMError(502, "The model returned an answer I couldn't parse, even after a retry. Try again or use a stronger model.")
    latency = round(time.monotonic() - t0, 1)
    model = os.environ["LLM_MODEL"]
    log.info("answered model=%s latency=%.1fs", model, latency)
    return approach, {"model": model, "latency_seconds": latency}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    problem = sys.argv[1] if len(sys.argv) > 1 else ""
    imgs = [open(p, "rb").read() for p in sys.argv[2:]]
    try:
        a, meta = map_approach(problem, imgs)
        print(a.model_dump_json(indent=2, by_alias=True), meta)
    except LLMError as e:
        sys.exit(f"Error {e.status}: {e.message}")
