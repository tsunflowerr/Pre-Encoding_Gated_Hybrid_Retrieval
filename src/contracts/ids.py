"""One string-ID policy for corpus, qrels, rankings and method adapters."""

from __future__ import annotations

import re

_DOMAIN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_RAW_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def validate_domain(domain: str) -> None:
    if not isinstance(domain, str) or _DOMAIN.fullmatch(domain) is None:
        raise ValueError("domain must be a lowercase label without colon/whitespace")


def canonical_id(identifier: str, domain: str) -> str:
    """Accept raw or already canonical IDs; never cast integers or trim strings."""
    validate_domain(domain)
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("IDs must be nonempty strings; numeric IDs must stay strings")
    raw = identifier
    if ":" in identifier:
        prefix, raw = identifier.split(":", 1)
        if prefix != domain:
            raise ValueError("ID domain differs from the requested corpus domain")
    if _RAW_ID.fullmatch(raw) is None:
        raise ValueError("ID contains whitespace, an extra colon or unsupported characters")
    return f"{domain}:{raw}"


def validate_id(identifier: str, domain: str) -> None:
    if canonical_id(identifier, domain) != identifier:
        raise ValueError("ID must already be namespaced as domain:source_id")
