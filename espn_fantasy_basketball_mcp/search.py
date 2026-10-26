"""Name matching for player search."""

from __future__ import annotations

import difflib
import unicodedata

# Fuzzy (difflib) matches below this are noise: live, "Jokic" scored 0.5 against
# "Jamorko Pickett" and "Josh Okogie".
SEARCH_MIN_SCORE = 0.6


def normalize_name(name: str) -> str:
    """Lower-case, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in ascii_only)
    return " ".join(cleaned.casefold().split())


def name_match_score(query: str, full_name: str) -> float:
    """Score how well a query matches a player name (0-1).

    Exact name 1.0; query equal to a name token (usually the surname) 0.95; every query
    token a prefix of some name token in order ("steph curry" -> "Stephen Curry") 0.9;
    query a substring 0.85; otherwise difflib similarity capped at 0.8, so typos still
    rank but never above a structural match.
    """
    q = normalize_name(query)
    n = normalize_name(full_name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    name_tokens = n.split()
    query_tokens = q.split()
    if len(query_tokens) == 1 and q in name_tokens:
        return 0.95
    if len(query_tokens) <= len(name_tokens):
        remaining = list(name_tokens)
        ok = True
        for qt in query_tokens:
            idx = next((i for i, nt in enumerate(remaining) if nt.startswith(qt)), None)
            if idx is None:
                ok = False
                break
            remaining = remaining[idx + 1 :]
        if ok:
            return 0.9
    if q in n:
        return 0.85
    return min(0.8, difflib.SequenceMatcher(None, q, n).ratio())
