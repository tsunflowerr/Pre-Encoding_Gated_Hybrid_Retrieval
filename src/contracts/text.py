"""Lossless retrieval text policy, compatible with frozen dense v1 artifacts."""

TEXT_POLICY = "join_nonempty_title_text_newline_v1"


def build_document_text(title: str, body: str) -> str:
    if not isinstance(title, str) or not isinstance(body, str):
        raise TypeError("title/body must be strings")
    return "\n".join(part for part in (title, body) if part)
