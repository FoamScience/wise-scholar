"""Frequency tiers and the reading gate: what a learner's text may contain, and whether a draft fits."""
import random
import re
from collections import Counter
from functools import lru_cache

import geonamescache
import simplemma
from wordfreq import top_n_list, zipf_frequency

TIER = 200
LIST_SIZE = 12000
SAMPLE = 12
FUNCTION_WORDS = 150
COVERAGE = 0.95
REPEATS = 3
MAX_GLOSSARY = 10
EXPOSURES_TO_KNOW = 5
TIER_DONE_SHARE = 0.8
# Starting tier by CEFR level until a placement check measures it; a tier is TIER lemmas wide.
STARTING_TIER = {"A1": 1, "A2": 3, "B1": 10, "B2": 20, "C1": 30, "C2": 40}
WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)
# Names, brands and loanwords are frequent in several languages at once; German nouns are not.
OTHER_LANGS = ("en", "fr", "es", "it", "nl", "pt")
INTERNATIONAL_VOTES = 3
ENGLISH_MARGIN = 0.7
CITY_POPULATION = 150_000


def _lemma(word: str, lang: str) -> str:
    """Frequency lists are lowercase, which misleads the lemmatizer on German nouns ('haus' -> 'hausen');
    when the lowercase guess is far rarer than the word itself, trust the capitalized reading instead."""
    low = simplemma.lemmatize(word, lang=lang)
    if zipf_frequency(low, lang) >= zipf_frequency(word, lang) - 1.5:
        return low
    return simplemma.lemmatize(word.capitalize(), lang=lang)


@lru_cache(maxsize=1)
def _places() -> set[str]:
    cache = geonamescache.GeonamesCache()
    names = {c["name"] for c in cache.get_countries().values()} | {c["name"] for c in cache.get_continents().values()}
    for city in cache.get_cities().values():
        if city["population"] >= CITY_POPULATION:
            names.add(city["name"])
            names.update(city["alternatenames"])
    return names


def _teachable(lemma: str, lang: str) -> bool:
    """Worth sampling or targeting: a dictionary word that is not an acronym, a place, a name or a loan the
    learner knows from elsewhere. ponytail: place names that are also nouns (Essen, Rest, Halle) are lost too,
    and English proper nouns slip through because that list keeps them lowercase."""
    if lemma.isupper() or not simplemma.is_known(lemma, lang=lang):
        return False
    own = zipf_frequency(lemma, lang)
    if lemma[0].isupper():
        if lemma in _places():
            return False
        votes = sum(zipf_frequency(lemma, o) >= max(3.0, own - 1.0) for o in OTHER_LANGS if o != lang)
        return votes < INTERNATIONAL_VOTES
    return lang == "en" or zipf_frequency(lemma, "en") < own + ENGLISH_MARGIN


@lru_cache(maxsize=8)
def _tiers(lang: str) -> tuple[list[str], dict[str, int]]:
    """Frequency-ordered teachable lemmas without duplicates, and a case-folded alias -> rank map for matching.
    Words that are not teachable keep rank 0: always allowed in a text, never counted."""
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
            if _teachable(lemma, lang):
                lemmas.append(lemma)
                index = len(lemmas) - 1
            else:
                index = 0
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


def max_tier(lang: str) -> int:
    """The last full tier of a language's teachable list; higher tiers would be empty."""
    return max(1, len(lemma_list(lang)) // TIER)


def lemmatize(text: str, lang: str) -> list[str]:
    return [simplemma.lemmatize(w, lang=lang) for w in WORD.findall(text)]


def starting_tier(level: str | None, lang: str) -> int:
    return min(STARTING_TIER.get((level or "").strip()[:2].upper(), 1), max_tier(lang))


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


def sample_tier(lang: str, tier: int, k: int = SAMPLE) -> list[str]:
    """A random handful of a tier's words for a yes/no knowledge check."""
    words = tier_words(lang, tier)
    return random.sample(words, min(k, len(words)))


def next_probe(results: dict[int, bool], top: int) -> int | None:
    """The next tier to sample given which tiers passed so far: double up until one fails, then bisect.
    None once the learner's tier is bracketed; top is the last tier that has words."""
    lo = max((t for t, ok in results.items() if ok), default=0)
    hi = min((t for t, ok in results.items() if not ok), default=top + 1)
    if hi - lo <= 1:
        return None
    return max(1, min(lo * 2, hi - 1)) if hi > top else (lo + hi) // 2


def estimated_tier(results: dict[int, bool], top: int) -> int:
    """The tier the learner works on: one above the highest tier held."""
    return min(max((t for t, ok in results.items() if ok), default=0) + 1, top)
