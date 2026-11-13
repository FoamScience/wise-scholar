import pytest
from fastapi.testclient import TestClient

from wise_scholar import app as application
from wise_scholar import settings


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# mine\nexport WISE_SCHOLAR_TURNS ?= 3\nexport OTHER ?= x\nexport WISE_SCHOLAR_LISTEN ?= 100.1.2.3\n")
    monkeypatch.setattr(settings, "ENV_FILE", path)
    monkeypatch.setattr(settings, "STARTED", {s.name: None for s in settings.CATALOG} | {
        "WISE_SCHOLAR_TURNS": "3", "WISE_SCHOLAR_LISTEN": "100.1.2.3", "WISE_SCHOLAR_TOOL_CALLS": "50"})
    monkeypatch.setattr(settings, "FILE_AT_START", settings.read_file(path))
    return path


def client(address: str, host: str = "127.0.0.1") -> TestClient:
    return TestClient(application.app, base_url=f"http://{host}:8321", client=(address, 50000), raise_server_exceptions=False)


def by_name(rows: list[dict]) -> dict:
    return {row["name"]: row for row in rows}


def test_a_value_comes_from_the_file_the_shell_or_the_default(env_file):
    rows = by_name(settings.view())
    assert rows["WISE_SCHOLAR_TURNS"]["source"] == "file"
    assert rows["WISE_SCHOLAR_TOOL_CALLS"]["source"] == "shell" and not rows["WISE_SCHOLAR_TOOL_CALLS"]["editable"]
    assert rows["WISE_SCHOLAR_PODCASTS"]["source"] == "default" and rows["WISE_SCHOLAR_PODCASTS"]["editable"]
    assert not rows["WISE_SCHOLAR_LISTEN"]["editable"] and not rows["WISE_SCHOLAR_SANDBOX"]["editable"]
    assert not any(row["pending"] for row in rows.values())


def test_the_secret_is_never_shown(env_file, monkeypatch):
    monkeypatch.setitem(settings.STARTED, "WISE_SCHOLAR_MCP_SECRET", "hunter2")
    assert by_name(settings.view())["WISE_SCHOLAR_MCP_SECRET"]["value"] == "set"


def test_writing_keeps_other_lines_and_marks_the_change_pending(env_file):
    settings.write({"WISE_SCHOLAR_TURNS": "4", "WISE_SCHOLAR_PODCASTS": "1", "WISE_SCHOLAR_KEEP_DAYS": None})
    assert env_file.read_text() == (
        "# mine\nexport WISE_SCHOLAR_TURNS ?= 4\nexport OTHER ?= x\nexport WISE_SCHOLAR_LISTEN ?= 100.1.2.3\n"
        "export WISE_SCHOLAR_PODCASTS ?= 1\n"
    )
    rows = by_name(settings.view())
    assert rows["WISE_SCHOLAR_TURNS"]["pending"] and rows["WISE_SCHOLAR_TURNS"]["saved"] == "4"
    assert rows["WISE_SCHOLAR_PODCASTS"]["pending"]
    settings.write({"WISE_SCHOLAR_TURNS": None})
    assert "WISE_SCHOLAR_TURNS" not in env_file.read_text()


def test_values_make_could_misread_or_out_of_range_are_refused(env_file):
    assert settings.check("WISE_SCHOLAR_TURNS", "0") and settings.check("WISE_SCHOLAR_TURNS", "two")
    assert settings.check("WISE_SCHOLAR_SEARCH_MODEL", "a$(rm -rf ~)") and settings.check("WISE_SCHOLAR_SEARCH_MODEL", "a\nexport X=1")
    assert settings.check("WISE_SCHOLAR_PODCASTS", "yes") and settings.check("WISE_SCHOLAR_AGENT", "codex")
    assert settings.check("WISE_SCHOLAR_SANDBOX", "0") and settings.check("WISE_SCHOLAR_TOOL_CALLS", "40")
    assert settings.check("WISE_SCHOLAR_NOPE", "1")
    assert settings.check("WISE_SCHOLAR_AGENT", "agy/gemini-3.8-flash-high") is None
    assert settings.check("WISE_SCHOLAR_MODELS", "chat=haiku") and settings.check("WISE_SCHOLAR_MODELS", "cards=")
    assert settings.check("WISE_SCHOLAR_MODELS", "cards=haiku, graph=openrouter/qwen/qwen3.8-27b") is None
    assert settings.check("WISE_SCHOLAR_KEEP_DAYS", None) is None and settings.check("WISE_SCHOLAR_TURNS", "5") is None


def test_a_restart_takes_the_files_values_and_keeps_the_shells(env_file, monkeypatch):
    monkeypatch.setenv("WISE_SCHOLAR_TURNS", "3")
    monkeypatch.setenv("WISE_SCHOLAR_TOOL_CALLS", "50")
    settings.write({"WISE_SCHOLAR_TURNS": None, "WISE_SCHOLAR_PODCASTS": "1"})
    env = settings.environment_for_restart()
    assert "WISE_SCHOLAR_TURNS" not in env and env["WISE_SCHOLAR_PODCASTS"] == "1" and env["WISE_SCHOLAR_TOOL_CALLS"] == "50"


def test_only_this_machine_at_its_loopback_name_may_change_settings(env_file):
    change = {"values": {"WISE_SCHOLAR_TURNS": "5"}}
    assert client("100.64.0.9").post("/api/settings", json=change).status_code == 403
    assert client("127.0.0.1").post("/api/settings", json=change, headers={"x-forwarded-for": "1.2.3.4"}).status_code == 403
    assert client("100.64.0.9").get("/api/settings").json()["editable"] is False
    local = client("127.0.0.1")
    assert local.post("/api/settings", json={"values": {"WISE_SCHOLAR_SANDBOX": "0"}}).status_code == 422
    saved = local.post("/api/settings", json=change)
    assert saved.status_code == 200 and by_name(saved.json()["settings"])["WISE_SCHOLAR_TURNS"]["saved"] == "5"
    assert local.post("/api/settings/restart").status_code == 409


def test_every_setting_has_a_label_and_help_in_each_language():
    import json
    from pathlib import Path

    for code in ("en", "fr", "ar"):
        items = json.loads((Path(__file__).parents[1] / "web/src/locales" / f"{code}.json").read_text())["translation"]["settings"]["items"]
        assert set(items) == set(settings.BY_NAME) and all(i["label"] and i["help"] for i in items.values())
