import os
import re
import tempfile
import zlib

import numpy as np
import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))


class Words:
    """Stands in for the search model: a text's vector is the sum of one fixed random vector per word, so texts
    sharing words are close and texts sharing none are not."""

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.array([
            sum((np.random.default_rng(zlib.crc32(w.encode())).standard_normal(64) for w in re.findall(r"\w+", t.lower())), np.zeros(64))
            for t in texts
        ])


@pytest.fixture(autouse=True)
def search_model(monkeypatch):
    from wise_scholar import search

    monkeypatch.setattr(search, "_model", Words())
