from __future__ import annotations

import re

from .request_model import NormalizedRequest, RequestBundle


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def assemble_request(bundle: RequestBundle) -> NormalizedRequest:
    current_text = normalize_text(f"[USER_PROMPT]\n{bundle.user_prompt}")
    parts: list[str] = [current_text]
    sources = ["user_prompt"]

    for index, chunk in enumerate(bundle.conversation_turns, start=1):
        parts.append(f"[CONVERSATION_TURN:{index}:{chunk.source}]\n{chunk.text}")
        sources.append(f"conversation_turn:{index}:{chunk.source}")

    for chunk in bundle.retrieved_context:
        parts.append(f"[RETRIEVED_CONTEXT:{chunk.source}]\n{chunk.text}")
        sources.append(f"retrieved_context:{chunk.source}")

    for chunk in bundle.logs:
        parts.append(f"[LOG:{chunk.source}]\n{chunk.text}")
        sources.append(f"log:{chunk.source}")

    metadata = dict(bundle.metadata)
    metadata["conversation_turn_texts"] = [chunk.text for chunk in bundle.conversation_turns]
    metadata["conversation_turn_sources"] = [chunk.source for chunk in bundle.conversation_turns]

    return NormalizedRequest(
        case_id=bundle.case_id,
        target_profile=bundle.target_profile,
        transport=bundle.transport,
        text=normalize_text("\n\n".join(parts)),
        current_text=current_text,
        sources=sources,
        conversation_turns=list(bundle.conversation_turns),
        metadata=metadata,
    )
