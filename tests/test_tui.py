"""Drive the real TUI headlessly with Textual's pilot."""

from __future__ import annotations

import pytest
from textual.widgets import Input, Select, SelectionList

from recomp_profiler import settings as S
from recomp_profiler.tui.app import RecompTUI
from recomp_profiler.tui.forms import EditModal


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("RECOMP_SETTINGS", str(tmp_path / "config.toml"))
    monkeypatch.setenv("RECOMP_AGENT_DIR", str(tmp_path / "agent"))
    monkeypatch.setenv("RECOMP_HOSTS_DIR", str(tmp_path / "hosts"))
    return tmp_path


async def _fill(modal: EditModal, values: dict) -> None:
    for name, value in values.items():
        w = modal.query_one(f"#f-{name}")
        if isinstance(w, Input):
            w.value = value
        elif isinstance(w, Select):
            w.value = value
        elif isinstance(w, SelectionList):
            w.deselect_all()
            for v in value:
                w.select(v)


async def test_add_rom_source_and_game(isolated):
    app = RecompTUI(initial_tab="sources")
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.click("#src-add")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, EditModal)
        await _fill(modal, {"name": "nas-games", "kind": "smb", "host": "192.0.2.10",
                            "share": "games", "username": "tester", "password": "secret"})
        await pilot.click("#save")
        await pilot.pause()

        app.query_one("TabbedContent").active = "games"
        await pilot.pause()
        app.query_one("#game-add").press()
        await pilot.pause()
        modal = app.screen
        # disc image without extractor must be rejected inside the modal
        await _fill(modal, {"id": "ssx3", "title": "SSX 3", "source": "nas-games",
                            "source_path": "Xbox/SSX 3.iso", "format": "image",
                            "backends": ["cpu", "vulkan"], "default_backend": "vulkan"})
        await pilot.click("#save")
        await pilot.pause()
        assert app.screen is modal
        assert "extractor" in str(modal.query_one("#errors").render())
        await _fill(modal, {"extractor_cmd": "extract-xiso -x {image} -d {out}"})
        modal.query_one("#save").press()
        await pilot.pause()
        assert not isinstance(app.screen, EditModal), str(modal.query_one("#errors").render())

    s = S.load()
    assert s.rom_sources[0].host == "192.0.2.10" and s.rom_sources[0].password == "secret"
    assert "secret" not in (isolated / "config.toml").read_text()
    g = s.games[0]
    assert (g.source, g.format, g.backends, g.default_backend) == ("nas-games", "image", ["cpu", "vulkan"], "vulkan")


async def test_agent_tab_saves_and_validates(isolated):
    app = RecompTUI(initial_tab="agent")
    async with app.run_test(size=(140, 50)) as pilot:
        app.query_one("#agent-form #f-port", Input).value = "48000"
        app.query_one("#agent-form #f-allowed_clients", Input).value = "198.51.100.0/24"
        await pilot.click("#agent-save")
        await pilot.pause()
        assert S.load().agent.port == 48000
        app.query_one("#agent-form #f-allowed_clients", Input).value = "nonsense"
        await pilot.click("#agent-save")
        await pilot.pause()
    assert S.load().agent.allowed_clients == ["198.51.100.0/24"]


async def test_all_tabs_render(isolated):
    app = RecompTUI()
    async with app.run_test(size=(140, 50)) as pilot:
        for tab in ("overview", "agent", "system", "sources", "games", "hosts", "storage"):
            app.query_one("TabbedContent").active = tab
            await pilot.pause()
