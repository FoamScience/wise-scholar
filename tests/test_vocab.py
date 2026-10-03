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
    assert vocab.starting_tier("A2", "de") == 3 and vocab.starting_tier("b1 (solid)", "de") == 10
    assert vocab.starting_tier(None, "de") == 1 and vocab.starting_tier("C2", "de") == vocab.max_tier("de")


def test_tier_probe_doubles_then_bisects():
    results: dict[int, bool] = {}
    probes = []
    while (probe := vocab.next_probe(results, 30)) is not None:
        probes.append(probe)
        results[probe] = probe <= 11
    assert probes == [1, 2, 4, 8, 16, 12, 10, 11] and vocab.estimated_tier(results, 30) == 12
    assert vocab.next_probe({1: False}, 30) is None and vocab.estimated_tier({1: False}, 30) == 1
    assert vocab.next_probe({16: True}, 30) == 30 and vocab.estimated_tier({30: True}, 30) == 30
    assert vocab.max_tier("de") >= 25
    sample = vocab.sample_tier("de", 3)
    assert len(sample) == vocab.SAMPLE and set(sample) <= set(vocab.tier_words("de", 3))


def test_names_places_and_loanwords_are_not_teachable_but_stay_allowed():
    words = vocab.lemma_list("de")
    assert not {"Hamburg", "Freiburg", "Peter", "CDU", "Hotel", "Berlin", "Will", "on"} & set(words)
    assert {"Haus", "Kind", "Hand", "Name", "wollen", "Polizei"} <= set(words[:400])
    assert vocab.rank("Hamburg", "de") == 0 and vocab.rank("will", "de") == vocab.rank("wollen", "de")
    text = "Peter wohnt in Hamburg. Peter wohnt in Hamburg. Peter wohnt in Hamburg."
    assert vocab.check_reading(text, "de", tier=1, known=set(), targets=["wohnen"])["ok"]
