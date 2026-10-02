from datetime import datetime, timedelta, timezone

from fsrs import Rating

from wise_scholar import review


def test_rating_follows_correctness_then_confidence():
    assert review.rating(False, 0.95) is Rating.Again
    assert review.rating(False, 0.2) is Rating.Again
    assert review.rating(True, 0.3) is Rating.Hard
    assert review.rating(True, 0.7) is Rating.Good
    assert review.rating(True, 0.95) is Rating.Easy
    assert review.is_confident_miss(False, 0.8) and not review.is_confident_miss(False, 0.5)
    assert not review.is_confident_miss(True, 0.99)


def test_schedule_round_trips_state_and_spaces_a_sure_correct_answer_further_than_a_miss():
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    state, due_miss = review.schedule(None, False, 0.9, now)
    _, due_sure = review.schedule(None, True, 0.95, now)
    assert datetime.fromisoformat(due_miss) - now < timedelta(hours=1)
    assert datetime.fromisoformat(due_sure) - now > timedelta(days=1)
    _, due_next = review.schedule(state, True, 0.7, now + timedelta(minutes=5))
    assert datetime.fromisoformat(due_next) > now


def test_calibration_buckets_and_brier():
    result = review.calibration([(0.9, True), (0.9, False), (0.6, True), (0.2, False)])
    assert result["n"] == 4
    assert abs(result["brier"] - (0.01 + 0.81 + 0.16 + 0.04) / 4) < 1e-9
    by_label = {b["label"]: b for b in result["buckets"]}
    assert by_label["90–100%"] == {"label": "90–100%", "n": 2, "stated": 0.9, "actual": 0.5}
    assert by_label["70–89%"]["n"] == 0 and by_label["70–89%"]["actual"] is None
    assert review.calibration([])["brier"] is None
