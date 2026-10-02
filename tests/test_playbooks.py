from wise_scholar.playbooks import PLAYBOOKS, check_ranking, describe


def test_every_playbook_has_the_fields_the_ui_and_the_agent_read():
    assert {"hands-on", "crossover", "leveled-course"} <= set(PLAYBOOKS)
    for book in PLAYBOOKS.values():
        assert book["title"] and book["summary"] and book["fits"] and book["body"]
        assert book["evidence"]
        for source in book["evidence"]:
            assert source["source"] and source["finding"] and source["url"].startswith("https://")


def test_check_ranking_rejects_unusable_rankings():
    ok = [{"mechanism": "hands-on", "rationale": "a"}, {"mechanism": "crossover", "rationale": "b"}]
    assert check_ranking(ok) is None
    assert "unknown" in check_ranking([*ok, {"mechanism": "osmosis", "rationale": "c"}])
    assert "more than once" in check_ranking([*ok, ok[0]])
    assert "at least two" in check_ranking(ok[:1])
    assert describe(ok)[0]["title"] == PLAYBOOKS["hands-on"]["title"]
