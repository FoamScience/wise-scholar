import tomllib
from pathlib import Path

DIR = Path(__file__).parent / "playbooks"


def _load() -> dict[str, dict]:
    books = {}
    for path in sorted(DIR.glob("*.md")):
        _, meta, body = path.read_text().split("+++", 2)
        books[path.stem] = {"id": path.stem, **tomllib.loads(meta), "body": body.strip()}
    return books


PLAYBOOKS = _load()


def check_ranking(ranking: list[dict]) -> str | None:
    """Return what is wrong with a ranking, or None when it is usable."""
    ids = [r["mechanism"] for r in ranking]
    unknown = [i for i in ids if i not in PLAYBOOKS]
    if unknown:
        return f"unknown mechanism ids {unknown}; valid ids are {sorted(PLAYBOOKS)}"
    if len(set(ids)) != len(ids):
        return "a mechanism appears more than once"
    if len(ids) < 2:
        return "rank at least two mechanisms so the learner has a choice"
    return None


def describe(ranking: list[dict]) -> list[dict]:
    """Attach the learner-facing playbook fields to each ranked entry."""
    keys = ("title", "summary", "evidence")
    return [{**r, **{k: PLAYBOOKS[r["mechanism"]][k] for k in keys}} for r in ranking]
