from __future__ import annotations

import re

from .request_model import NormalizedRequest, RequestBundle


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def assemble_request(bundle: RequestBundle) -> NormalizedRequest:
    parts: list[str] = [f"[USER_PROMPT]\n{bundle.user_prompt}"]
    sources = ["user_prompt"]

    for chunk in bundle.retrieved_context:
        parts.append(f"[RETRIEVED_CONTEXT:{chunk.source}]\n{chunk.text}")
        sources.append(f"retrieved_context:{chunk.source}")

    for chunk in bundle.logs:
        parts.append(f"[LOG:{chunk.source}]\n{chunk.text}")
        sources.append(f"log:{chunk.source}")

    return NormalizedRequest(
        case_id=bundle.case_id,
        target_profile=bundle.target_profile,
        transport=bundle.transport,
        text=normalize_text("\n\n".join(parts)),
        sources=sources,
        metadata=dict(bundle.metadata),
    )
