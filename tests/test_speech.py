import os
import tempfile

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import speech  # noqa: E402


def test_word_match_marks_what_the_recogniser_heard():
    words = speech.word_match("Der Kühlschrank ist voll, wir müssen nicht einkaufen.", "der kühlschrank ist leer wir müssen einkaufen")
    assert [w["word"] for w in words] == ["Der", "Kühlschrank", "ist", "voll", "wir", "müssen", "nicht", "einkaufen"]
    assert [w["score"] for w in words] == [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    assert all(w["score"] == 0.0 for w in speech.word_match("Guten Morgen", ""))
