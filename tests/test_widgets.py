import asyncio
import json
import os
import tempfile

import pytest

os.environ.setdefault("WISE_SCHOLAR_DB", os.path.join(tempfile.mkdtemp(), "test.db"))

from wise_scholar import app, bundle, db, figures, obsidian, tutor, widgets  # noqa: E402

GEARS = {
    "controls": [
        {"name": "driver", "label": "Driver teeth", "min": 12, "max": 24, "step": 12, "value": 12, "unit": "teeth"},
        {"name": "idlers", "label": "Idler gears", "min": 0, "max": 2, "step": 1, "value": 0},
    ],
    "readouts": [{"label": "Output turns per input turn", "expr": "driver/24 * (-1)**(idlers + 1)", "unit": "turns", "digits": 2}],
    "plot": {
        "x": {"label": "input turns"},
        "y": {"label": "output turns"},
        "marks": [{"type": "line", "fn": "x * driver/24 * (-1)**(idlers + 1)", "domain": [0, 4], "label": "output"}, {"type": "rule", "y": "0"}],
    },
}


def test_every_setting_is_evaluated_in_slider_order_with_one_y_range():
    w = widgets.resolve(GEARS)
    assert [c["values"] for c in w["controls"]] == [[12.0, 24.0], [0.0, 1.0, 2.0]] and [c["start"] for c in w["controls"]] == [0, 0]
    assert [s["readouts"] for s in w["states"]] == [[-0.5], [0.5], [-0.5], [-1.0], [1.0], [-1.0]]
    assert w["states"][4]["marks"][0][-1] == 4.0 and w["states"][4]["marks"][1] == 0.0
    assert w["plot"]["y"] == {"label": "output turns", "domain": [-4.0, 4.0]} and widgets.start_index(w) == 0
    assert widgets.resolve({**GEARS, "readouts": [{"label": "r", "expr": "1/3"}]})["states"][0]["readouts"] == [0.333333]
    assert widgets.start_index(widgets.resolve({**GEARS, "controls": [{**c, "value": c["max"]} for c in GEARS["controls"]]})) == 5
    assert len(w["plot"]["marks"][0]["xs"]) == widgets.SAMPLES and "fn" not in w["plot"]["marks"][0]


def test_a_reading_that_is_not_a_number_is_none():
    w = widgets.resolve({"controls": [{"name": "d", "label": "d", "min": 0, "max": 1, "step": 1, "value": 1}], "readouts": [{"label": "r", "expr": "1/d"}]})
    assert [s["readouts"] for s in w["states"]] == [[None], [1.0]] and "plot" not in w


@pytest.mark.parametrize("change, reason", [
    ({"controls": []}, "controls must be a list of 1 to 3 sliders"),
    ({"controls": [{**GEARS["controls"][0], "name": "x"}]}, "name must be a short lowercase identifier"),
    ({"controls": [{**GEARS["controls"][0], "name": "sin"}]}, "name must be a short lowercase identifier"),
    ({"controls": [GEARS["controls"][0], GEARS["controls"][0]]}, "is used twice"),
    ({"controls": [{**GEARS["controls"][0], "value": 18}]}, "value 18 is not one of the slider's positions"),
    ({"controls": [{**GEARS["controls"][0], "max": 12}]}, "needs min < max and step > 0"),
    ({"controls": [{**GEARS["controls"][0], "step": 0.01, "max": 14}]}, "at most 101 positions"),
    ({"controls": [{**GEARS["controls"][0], "name": n, "min": 0, "max": 9, "step": 1, "value": 0} for n in "abc"]}, "more than 400 settings"),
    ({"readouts": [{"label": "r", "expr": "__import__('os')"}]}, "uses something outside"),
    ({"readouts": [{"label": "r", "expr": "x"}]}, "uses something outside driver, idlers"),
    ({"plot": {"marks": [{"type": "line", "fn": "x"}]}}, "needs domain"),
    ({"controls": [{**GEARS["controls"][0], "name": n, "min": 0, "max": 14, "step": 1, "value": 0} for n in "ab"],
      "readouts": [{"label": "r", "expr": "a"}], "plot": {"marks": [{"type": "line", "fn": f"x*{k}", "domain": [0, 1]} for k in range(2)]}},
     "pass 40000 points"),
    ({"plot": {"marks": [{"type": "dot", "fn": "x"}]}}, "type must be line, area, or rule"),
    ({"plot": {"marks": [{"type": "rule", "x": "1", "y": "1"}]}}, "type must be line, area, or rule"),
])
def test_a_widget_is_refused_with_a_reason(change, reason):
    with pytest.raises(ValueError, match=reason):
        widgets.resolve(GEARS | change)


def test_the_tool_shows_the_widget_and_an_imported_one_is_evaluated_again():
    who = db.conn.execute("INSERT INTO profiles (name) VALUES ('Widget')").lastrowid
    course = db.create_course("Gears", who)["id"]
    db.conn.execute("UPDATE courses SET started = 1 WHERE id = ?", (course,))
    try:
        lesson = db.create_lesson(course, "Idlers", "lesson", None)
        teaches = figures.Teaches(claim="An idler keeps the ratio.", notice="Move the idler slider; the size stays at 0.5.", limits="Ideal gears.")
        assert asyncio.run(tutor.add_widget(lesson, "Idlers", GEARS, "", teaches)) == "error: alt text is required"
        assert asyncio.run(tutor.add_widget(lesson, "Idlers", {"controls": []}, "a", teaches)) == "error: controls must be a list of 1 to 3 sliders"
        reply = asyncio.run(tutor.add_widget(lesson, "Idlers", GEARS, "output turns against input turns", teaches))
        [block] = [b for b in db.blocks(lesson) if b["kind"] == "widget"]
        assert reply == f"shown as widget {block['id']}" and block["data"]["spec"] == GEARS and block["data"]["widget"] == widgets.resolve(GEARS)
        assert app._record_line(block).startswith(f"[block {block['id']}, widget] Idlers | claim: An idler keeps the ratio.")

        note = obsidian.Vault(course).lesson_text(db.lesson(lesson) | {"blocks": db.blocks(lesson), "messages": []}, chat=False, kinds=("widget",))
        assert "".join(note) == (
            "**Idlers**\n\n- Driver teeth: 12 – 24 teeth (starts at 12 teeth)\n- Idler gears: 0 – 2 (starts at 0)\n"
            "- Output turns per input turn: -0.50 turns\n*Where this stops matching the real thing: Ideal gears.*\n"
        )

        with pytest.raises(app.HTTPException, match="not a setting"):
            asyncio.run(app.try_widget(block["id"], app.WidgetSetting(at=[2, 0])))
        assert asyncio.run(app.try_widget(block["id"], app.WidgetSetting(at=[1, 0]))) == {"tried": 1}
        assert asyncio.run(app.try_widget(block["id"], app.WidgetSetting(at=[1, 0]))) == {"tried": 1}
        assert asyncio.run(app.try_widget(block["id"], app.WidgetSetting(at=[1, 1]))) == {"tried": 2}
        assert app._widget_tries(lesson) == [
            f"[widget {block['id']}] The learner tried, in order: "
            "Driver teeth = 24 teeth, Idler gears = 0 -> Output turns per input turn -1.00 turns; "
            "Driver teeth = 24 teeth, Idler gears = 1 -> Output turns per input turn 1.00 turns"
        ]
        assert app._widget_tries(lesson) == []
        asyncio.run(app.try_widget(block["id"], app.WidgetSetting(at=[0, 0])))
        assert app._widget_tries(lesson)[0].endswith("tried, in order: Driver teeth = 12 teeth, Idler gears = 0 -> Output turns per input turn -0.50 turns")
        block = db.block(block["id"])
        assert "| tried: Driver teeth = 24 teeth" in app._record_line(block)
        assert "tried" not in bundle._block_data({**block, "data": json.dumps(block["data"])}, {})
        forged = {**block["data"], "widget": {"states": "anything"}}
        clean = bundle._clean_block(bundle.Block(kind="widget", markdown="Idlers", data=forged, key="a" * 32), {})
        assert clean["widget"] == widgets.resolve(GEARS) and clean["teaches"]["limits"] == "Ideal gears." and clean["imported"] is True
        with pytest.raises(ValueError, match="spec must be an object"):
            bundle._clean_block(bundle.Block(kind="widget", markdown="", data={"widget": {}}, key="a" * 32), {})
    finally:
        db.delete_course(course)
        db.conn.execute("DELETE FROM profiles WHERE id = ?", (who,))
