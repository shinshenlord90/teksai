"""Humanizer for TeksAI.

Uses the rules from blader/humanizer (MIT, bundled in ../humanizer/SKILL.md)
as the system prompt for Claude. The rules edit style only: they remove
AI writing habits while keeping every fact, name and number.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from . import config

SKILL_PATH = Path(__file__).resolve().parent.parent / "humanizer" / "SKILL.md"

MODELS = {
    "Claude Opus 5.5 (terbaik)": "claude-opus-5-5",
    "Claude Sonnet 5.5 (lebih murah)": "claude-sonnet-5-5",
    "Claude Haiku 5.5 (paling murah)": "claude-haiku-5-5",
}


def load_rules() -> str:
    text = SKILL_PATH.read_text(encoding="utf-8")
    # Drop the YAML front matter; it is metadata for agent tools.
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)


def system_prompt(sample: str = "") -> str:
    prompt = (
        "You are the editing engine of a desktop app. Apply the rules below to the "
        "user's text, which is wrapped in <text> tags. Use embedded mode: return only "
        "the final rewritten text, with no preface, notes, lists of tells or tags. "
        "Write in the same language as the input (for example, Malay stays Malay).\n\n"
        "<rules>\n" + load_rules() + "\n</rules>"
    )
    if sample.strip():
        prompt += ("\n\nThe user supplied this sample of their own writing. Match its voice "
                   "as the rules describe:\n<writing_sample>\n" + sample.strip() + "\n</writing_sample>")
    return prompt


class HumanizeError(Exception):
    pass


def humanize(
    text: str,
    model: str = "claude-opus-5-5",
    effort: str = "medium",
    sample: str = "",
    on_text: Callable[[str], None] | None = None,
) -> str:
    """Rewrite ``text``. Streams chunks to ``on_text`` and returns the full result."""
    try:
        import anthropic
    except ImportError:
        raise HumanizeError("Pakej 'anthropic' belum dipasang. Jalankan: sudo dpkg-reconfigure teksai")

    key = config.api_key()
    if not key:
        raise HumanizeError("Tiada kunci API Anthropic. Masukkan kunci di tab Tetapan.")

    client = anthropic.Anthropic(api_key=key)
    kwargs = dict(
        model=model,
        max_tokens=64000,
        system=system_prompt(sample),
        output_config={"effort": effort},
        messages=[{"role": "user", "content": f"<text>\n{text}\n</text>"}],
    )
    # Server-side fallback: if the model declines, the API reruns the request on
    # a fallback model inside the same call. Haiku 5.5 does not offer it.
    if model != "claude-haiku-5-5":
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
        stream_cm = client.beta.messages.stream(**kwargs)
    else:
        stream_cm = client.messages.stream(**kwargs)

    try:
        with stream_cm as stream:
            for chunk in stream.text_stream:
                if on_text:
                    on_text(chunk)
            final = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise HumanizeError("Kunci API tidak sah. Semak semula di tab Tetapan.")
    except anthropic.PermissionDeniedError:
        raise HumanizeError("Kunci API ini tiada kebenaran untuk model yang dipilih.")
    except anthropic.RateLimitError:
        raise HumanizeError("Had kadar API dicapai. Cuba lagi sebentar lagi.")
    except anthropic.APIStatusError as e:
        raise HumanizeError(f"Ralat API ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise HumanizeError("Tidak dapat menyambung ke API. Semak sambungan internet.")

    if final.stop_reason == "refusal":
        raise HumanizeError("Model menolak permintaan ini.")
    out = "".join(b.text for b in final.content if b.type == "text").strip()
    if final.stop_reason == "max_tokens":
        out += "\n\n[Output terpotong: teks terlalu panjang. Bahagikan kepada bahagian lebih kecil.]"
    return out
