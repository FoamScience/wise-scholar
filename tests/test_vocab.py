from wise_scholar import vocab


def test_lemma_list_is_frequency_ordered_and_unique():
    words = vocab.lemma_list("de")
    assert words[0] in ("der", "die", "und") and len(words) == len(set(words))
    assert all(w.isalpha() and len(w) > 1 for w in words[:2000])
    assert vocab.tier_words("de", 2) == words[200:400]
    assert "Haus" in words[:2000] and "hausen" not in words[:2000]
    assert vocab.rank("Hause", "de") == vocab.rank("haus", "de") == words.index("Haus")


def test_reading_gate_rejects_out_of_scope_words_and_missing_repeats():
    known = {"Arzt", "Termin"}
    text = (
        "Am Montag hat Lena einen Termin beim Arzt. Der Arzt sagt: Der Termin ist um neun Uhr. "
        "Lena geht zum Arzt und wartet. Der Termin dauert nicht lange. Dann geht Lena nach Hause."
    )
    ok = vocab.check_reading(text, "de", tier=7, known=known, targets=["Termin", "Arzt"], names=["Lena"])
    assert ok["ok"], ok
    assert ok["coverage"] >= 0.95 and ok["missing_targets"] == []

    rare = text + " Die Bürgschaftserklärung der Hypothekenbank war unleserlich und die Thrombozytenzahl niedrig."
    bad = vocab.check_reading(rare, "de", tier=7, known=known, targets=["Termin", "Arzt"], names=["Lena"])
    assert not bad["ok"] and "Hypothekenbank" in bad["unknown"] and bad["coverage"] < ok["coverage"]

    thin = vocab.check_reading("Lena geht zum Arzt.", "de", tier=3, known=known, targets=["Arzt"], names=["Lena"])
    assert not thin["ok"] and thin["missing_targets"] == ["Arzt"]


def test_targets_and_tier_progress_follow_what_is_known():
    tier2 = vocab.tier_words("de", 2)
    known = set(tier2[:160])
    assert vocab.next_targets("de", 2, known, 3) == tier2[160:163]
    progress = vocab.tier_progress("de", 2, known)
    assert progress == {"tier": 2, "size": 200, "known": 160, "complete": True}
    assert not vocab.tier_progress("de", 2, set(tier2[:100]))["complete"]
    assert vocab.starting_tier("A2") == 3 and vocab.starting_tier("b1 (solid)") == 10 and vocab.starting_tier(None) == 1
