from wise_scholar import serve


def test_the_server_listens_on_loopback_and_each_extra_address_or_on_every_address_alone(monkeypatch):
    monkeypatch.delenv("WISE_SCHOLAR_LISTEN", raising=False)
    assert serve.hosts() == ["127.0.0.1"]
    monkeypatch.setenv("WISE_SCHOLAR_LISTEN", " 100.91.207.77, 127.0.0.1,,10.0.0.2")
    assert serve.hosts() == ["127.0.0.1", "10.0.0.2", "100.91.207.77"]
    monkeypatch.setenv("WISE_SCHOLAR_LISTEN", "100.91.207.77,0.0.0.0")
    assert serve.hosts() == ["0.0.0.0"]
