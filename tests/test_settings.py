from recomp_profiler import settings as S


def test_roundtrip_with_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOMP_SETTINGS", str(tmp_path / "config.toml"))
    s = S.Settings()
    s.agent.port = 50000
    s.rom_sources.append(S.RomSource(name="nas", kind="smb", host="192.0.2.10", share="games", username="u", password="pw"))
    s.games.append(S.Game(id="ssx3", title="SSX 3", source="nas", source_path="Xbox/SSX 3", backends=["cpu", "vulkan"]))
    assert s.validate() == []
    S.save(s)
    assert "pw" not in (tmp_path / "config.toml").read_text()
    assert "pw" in (tmp_path / "secrets.toml").read_text()
    back = S.load()
    assert back == s


def test_validation_catches_problems():
    s = S.Settings()
    s.agent.allowed_clients = ["not-an-ip"]
    s.rom_sources = [S.RomSource(name="a", kind="nfs"), S.RomSource(name="a", kind="local")]
    s.games = [S.Game(id="g", source="missing", format="image", backends=["cpu"], default_backend="vulkan")]
    errors = "\n".join(s.validate())
    for needle in ("not-an-ip", "duplicate ROM source 'a'", "server is required", "base path is required",
                   "unknown ROM source", "default backend", "extractor command"):
        assert needle in errors


def test_set_value():
    s = S.Settings()
    S.set_value(s, "agent.port", "1234")
    S.set_value(s, "agent.autostart", "false")
    S.set_value(s, "agent.allowed_clients", "198.51.100.0/24, 10.0.0.5")
    S.set_value(s, "install.source", "/src")
    assert (s.agent.port, s.agent.autostart, s.agent.allowed_clients, s.install.source) == (
        1234, False, ["198.51.100.0/24", "10.0.0.5"], "/src")
