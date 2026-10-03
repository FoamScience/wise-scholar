"""Frequency tiers and the reading gate: what a learner's text may contain, and whether a draft fits."""
import re
from collections import Counter
from functools import lru_cache

import simplemma
from wordfreq import top_n_list

TIER = 200
LIST_SIZE = 12000
FUNCTION_WORDS = 150
COVERAGE = 0.95
REPEATS = 3
MAX_GLOSSARY = 10
EXPOSURES_TO_KNOW = 5
TIER_DONE_SHARE = 0.8
# Starting tier by CEFR level until a placement check measures it; a tier is TIER lemmas wide.
STARTING_TIER = {"A1": 1, "A2": 3, "B1": 10, "B2": 20, "C1": 30, "C2": 40}
WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)


def _lemma(word: str, lang: str) -> str:
    """Frequency lists are lowercase, which misleads the lemmatizer on German nouns ('haus' -> 'hausen');
    when the lowercase guess lengthens the word, trust the capitalized reading instead."""
    low = simplemma.lemmatize(word, lang=lang)
    return low if len(low) <= len(word) else simplemma.lemmatize(word.capitalize(), lang=lang)


@lru_cache(maxsize=8)
def _tiers(lang: str) -> tuple[list[str], dict[str, int]]:
    """Frequency-ordered lemmas without duplicates, and a case-folded alias -> rank map for matching."""
    lemmas: list[str] = []
    rank: dict[str, int] = {}
    for word in top_n_list(lang, LIST_SIZE):
        if len(word) < 2 or not word.isalpha():
            continue
        lemma = _lemma(word, lang)
        if not (lemma.isalpha() and len(lemma) > 1):
            continue
        index = rank.get(lemma.lower())
        if index is None:
            lemmas.append(lemma)
            index = len(lemmas) - 1
        for alias in (lemma.lower(), word, simplemma.lemmatize(word, lang=lang).lower()):
            rank.setdefault(alias, index)
    return lemmas, rank


def lemma_list(lang: str) -> list[str]:
    """The most frequent lemmas of a language, most frequent first."""
    return _tiers(lang)[0]


def rank(lemma: str, lang: str) -> int | None:
    """Position of a lemma in the frequency list, or None when it is beyond it."""
    return _tiers(lang)[1].get(lemma.lower())


def tier_words(lang: str, tier: int) -> list[str]:
    return lemma_list(lang)[(tier - 1) * TIER : tier * TIER]


def lemmatize(text: str, lang: str) -> list[str]:
    return [simplemma.lemmatize(w, lang=lang) for w in WORD.findall(text)]


def starting_tier(level: str | None) -> int:
    return STARTING_TIER.get((level or "").strip()[:2].upper(), 1)


def check_reading(text: str, lang: str, tier: int, known: set[str], targets: list[str], names: list[str] = ()) -> dict:
    """Does a draft fit the learner? Allowed: tiers up to the current one, known lemmas, the targets, named people and places."""
    lemmas = lemmatize(text, lang)
    counts = Counter(l.lower() for l in lemmas)
    limit = max(FUNCTION_WORDS, tier * TIER)
    extra = {w.lower() for w in known} | {simplemma.lemmatize(t, lang=lang).lower() for t in targets}
    for name in names:
        extra |= {name.lower(), *(l.lower() for l in lemmatize(name, lang))}

    def allowed(lemma: str) -> bool:
        key = lemma.lower()
        r = rank(key, lang)
        return key in extra or (r is not None and r < limit)

    unknown = sorted({l for l in lemmas if not allowed(l)}, key=lambda l: -counts[l.lower()])
    coverage = 1 - sum(counts[l.lower()] for l in unknown) / len(lemmas) if lemmas else 0.0
    missing = [t for t in targets if counts[simplemma.lemmatize(t, lang=lang).lower()] < REPEATS]
    return {
        "ok": bool(lemmas) and coverage >= COVERAGE and not missing,
        "coverage": round(coverage, 3),
        "unknown": unknown,
        "missing_targets": missing,
        "lemmas": lemmas,
    }


def next_targets(lang: str, tier: int, known: set[str], n: int) -> list[str]:
    low = {w.lower() for w in known}
    return [w for w in tier_words(lang, tier) if w.lower() not in low][:n]


def tier_progress(lang: str, tier: int, known: set[str]) -> dict:
    words = tier_words(lang, tier)
    low = {w.lower() for w in known}
    done = sum(1 for w in words if w.lower() in low)
    return {"tier": tier, "size": len(words), "known": done, "complete": bool(words) and done / len(words) >= TIER_DONE_SHARE}
