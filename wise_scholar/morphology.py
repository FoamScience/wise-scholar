"""Grammatical analysis of a course's language with a spaCy pipeline: each word's lemma, part of speech and Universal
Dependencies features (Case, Tense, Mood, VerbForm, ...), which name the same things in every language spaCy covers.
spaCy is an opt-in extra (`make morphology`); the pipeline for a language is a resource the learner allows."""
import json
import re
import shutil
import tarfile
import threading
from collections import Counter
from pathlib import Path

import httpx

COMPATIBILITY = "https://raw.githubusercontent.com/explosion/spacy-models/master/compatibility.json"
RELEASE = "https://github.com/explosion/spacy-models/releases/download/{name}-{version}/{name}-{version}.tar.gz"
ARCHIVE = "model.tar.gz"
MODEL = "model"
# A pipeline is installed only under a licence that allows any use, and only when none of the data it was trained on
# is marked non-commercial; a pipeline that names no licence is not installed.
OPEN_LICENCE = re.compile(r"MIT|Apache[- ]2\.0|BSD.*|CC0.*|CC BY(-SA)? \d\.\d", re.IGNORECASE)
NON_COMMERCIAL = re.compile(r"\bNC\b|non-?commercial", re.IGNORECASE)
TEXT = 2000
TOKENS = 200


def available() -> bool:
    try:
        import spacy  # noqa: F401
    except ImportError:
        return False
    return True


def _spacy_version() -> str:
    import spacy

    return ".".join(spacy.__version__.split(".")[:2])


async def pipeline(lang: str) -> tuple[str, str] | None:
    """The name and version of the small pipeline for a language that fits the installed spaCy, or None."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        response = await client.get(COMPATIBILITY)
        response.raise_for_status()
    models = response.json()["spacy"].get(_spacy_version(), {})
    name = next((n for n in (f"{lang}_core_news_sm", f"{lang}_core_web_sm") if models.get(n)), None)
    return (name, models[name][0]) if name else None


def _licence_problem(meta_path: Path) -> str | None:
    if not meta_path.exists():
        return "the pipeline names no licence"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except ValueError:
        return "the pipeline's description cannot be read"
    licence = meta.get("license") or ""
    if not OPEN_LICENCE.fullmatch(licence.strip()):
        return f"the pipeline's licence does not allow any use: {licence or 'none given'}"
    closed = [s.get("name", "?") for s in meta.get("sources", []) if isinstance(s, dict) and NON_COMMERCIAL.search(str(s.get("license", "")))]
    if closed:
        return f"the pipeline was trained on data that forbids commercial use: {', '.join(closed)}"
    return None


def prepare(folder: Path) -> None:
    """Unpacks the downloaded pipeline into the folder's model directory, refuses one whose licence or training data
    does not allow any use, and loads it once, so a pipeline that needs packages this server lacks fails here and
    not in a lesson."""
    import spacy

    archive, unpacked, model = folder / ARCHIVE, folder / "unpacked", folder / MODEL
    shutil.rmtree(unpacked, ignore_errors=True)
    shutil.rmtree(model, ignore_errors=True)
    with tarfile.open(archive) as tar:
        tar.extractall(unpacked, filter="data")
    # a release holds its pipeline in one directory; a config nested deeper belongs to that pipeline
    configs = sorted(unpacked.rglob("config.cfg"), key=lambda p: len(p.parts))
    if not configs:
        raise ValueError("the download holds no spaCy pipeline")
    if problem := _licence_problem(configs[0].parent / "meta.json"):
        raise ValueError(problem)
    configs[0].parent.rename(model)
    shutil.rmtree(unpacked)
    archive.unlink()
    spacy.load(model)


_models: dict[Path, tuple[float, object, threading.Lock]] = {}
_models_lock = threading.Lock()


def _model(path: Path) -> tuple[object, threading.Lock]:
    """The loaded pipeline at a path with its lock; a pipeline installed again at the same path is loaded again. spaCy
    pipelines are not safe to call from two threads at once, so callers hold the lock."""
    import spacy

    stamp = (path / "config.cfg").stat().st_mtime
    with _models_lock:
        loaded = _models.get(path)
        if not loaded or loaded[0] != stamp:
            loaded = _models[path] = (stamp, spacy.load(path), threading.Lock())
    return loaded[1], loaded[2]


def analyze(folder: Path, text: str) -> tuple[list[list[dict]], bool]:
    """The text's sentences, each as its words with lemma, part of speech, features and dependency relation; and
    whether the text was cut to TEXT characters."""
    nlp, lock = _model(folder / MODEL)
    with lock:
        doc = nlp(text[:TEXT])
    sentences = [[{"text": t.text, "lemma": t.lemma_, "pos": t.pos_, "features": str(t.morph), "dep": t.dep_}
                  for t in sentence if not t.is_space] for sentence in doc.sents]
    return sentences, len(text) > TEXT


def describe(sentences: list[list[dict]], cut: bool = False) -> str:
    """The analysis as the tutor reads it, one word per line, at most TOKENS words."""
    lines, shown = [], 0
    for n, sentence in enumerate(sentences, 1):
        lines.append(f"sentence {n}:")
        for token in sentence:
            if shown == TOKENS:
                return "\n".join([*lines, f"(the rest of the text is not shown; analyze at most {TOKENS} words at a time)"])
            lines.append(f"  {token['text']}\t{token['lemma']}\t{token['pos']}\t{token['features'] or '-'}\t{token['dep']}")
            shown += 1
    if cut:
        lines.append(f"(only the first {TEXT} characters were analysed)")
    return "\n".join(lines)


def features(folder: Path, texts: list[str]) -> Counter:
    """How often each part of speech and each feature value occurs across the texts."""
    counts = Counter()
    nlp, lock = _model(folder / MODEL)
    with lock:
        docs = list(nlp.pipe(t[:TEXT] for t in texts))
    for doc in docs:
        for token in doc:
            if token.is_punct or token.is_space:
                continue
            counts[f"pos={token.pos_}"] += 1
            for feature in token.morph:
                counts[feature] += 1
    return counts
