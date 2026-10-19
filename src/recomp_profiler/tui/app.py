"""Textual app: one tab per configuration area."""

from __future__ import annotations

import copy
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Header, Static, TabbedContent, TabPane

from .. import settings as S
from ..client import HostConfig, load_hosts
from ..config import agent_dir, hosts_dir, settings_file
from . import system
from .forms import ConfirmModal, EditModal, FieldsForm, PromptModal, TextModal


class RecompTUI(App):
    TITLE = "Recomp Profiler"
    SUB_TITLE = "configuration"
    CSS = """
    TabPane { padding: 1 2; }
    .buttons { height: auto; margin: 1 0; }
    .buttons Button { margin-right: 1; }
    DataTable { height: auto; max-height: 20; }
    .step { height: auto; margin-bottom: 1; }
    .step Button { width: 32; }
    .step Static { padding: 1 0 0 2; color: $text-muted; }
    #overview-text { height: auto; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    def __init__(self, initial_tab: str | None = None):
        super().__init__()
        self.settings = S.load()
        self.initial_tab = initial_tab

    # ------------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial=self.initial_tab or "overview"):
            with TabPane("Overview", id="overview"):
                with VerticalScroll():
                    yield Static(id="overview-text")
            with TabPane("Agent", id="agent"):
                with VerticalScroll():
                    yield FieldsForm(self.settings.agent, id="agent-form")
                    with Horizontal(classes="buttons"):
                        yield Button("Save", variant="primary", id="agent-save")
                        yield Button("Rotate token + certificate", variant="warning", id="agent-rotate")
                        yield Button("Show connection.json", id="agent-show")
            with TabPane("System setup", id="system"):
                with VerticalScroll():
                    yield Static("Each action runs the install script in this terminal (it may ask for your sudo/admin password), then returns here.")
                    for step in system.STEPS:
                        with Horizontal(classes="step"):
                            yield Button(step.label, id=f"step-{step.id}",
                                         variant="error" if step.id == "uninstall" else "default")
                            yield Static(step.help + ("  [admin]" if step.needs_admin else ""))
            with TabPane("ROM sources", id="sources"):
                yield DataTable(id="sources-table", cursor_type="row")
                with Horizontal(classes="buttons"):
                    yield Button("Add", variant="primary", id="src-add")
                    yield Button("Edit", id="src-edit")
                    yield Button("Test connection", id="src-test")
                    yield Button("Delete", variant="error", id="src-del")
            with TabPane("Games", id="games"):
                yield DataTable(id="games-table", cursor_type="row")
                with Horizontal(classes="buttons"):
                    yield Button("Add", variant="primary", id="game-add")
                    yield Button("Edit", id="game-edit")
                    yield Button("Delete", variant="error", id="game-del")
            with TabPane("Hosts", id="hosts"):
                yield Static("Target machines this dev machine can control (from their connection.json).")
                yield DataTable(id="hosts-table", cursor_type="row")
                with Horizontal(classes="buttons"):
                    yield Button("Add from connection.json", variant="primary", id="host-add")
                    yield Button("Toggle trust own/external", id="host-trust")
                    yield Button("Ping", id="host-ping")
                    yield Button("Remove", variant="error", id="host-del")
            with TabPane("Storage & profiling", id="storage"):
                with VerticalScroll():
                    yield FieldsForm(self.settings.storage, id="storage-form")
                    yield FieldsForm(self.settings.profiling, id="profiling-form")
                    yield FieldsForm(self.settings.install, id="install-form")
                    with Horizontal(classes="buttons"):
                        yield Button("Save", variant="primary", id="storage-save")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#sources-table", DataTable).add_columns("Name", "Type", "Server", "Share", "Path", "Mount point")
        self.query_one("#games-table", DataTable).add_columns("ID", "Title", "Platform", "Source", "Path", "Stored as", "Backends", "Status")
        self.query_one("#hosts-table", DataTable).add_columns("Name", "URL", "Platform", "Trust")
        self.action_refresh()

    def action_refresh(self) -> None:
        self._refresh_overview()
        self._refresh_sources()
        self._refresh_games()
        self._refresh_hosts()

    # ------------------------------------------------------------------ helpers
    def _save(self, candidate: S.Settings) -> bool:
        errors = candidate.validate()
        if errors:
            self.notify("\n".join(errors), title="Not saved", severity="error", timeout=10)
            return False
        S.save(candidate)
        self.settings = candidate
        self.notify(f"Saved {settings_file()}")
        self.action_refresh()
        return True

    def _selected(self, table_id: str) -> int | None:
        t = self.query_one(table_id, DataTable)
        return t.cursor_row if t.row_count else None

    def _check_with(self, attr: str, index: int | None):
        """Validator for a modal: validate settings as if the edited item were saved."""
        def check(obj) -> list[str]:
            cand = copy.deepcopy(self.settings)
            items = getattr(cand, attr)
            items.append(obj) if index is None else items.__setitem__(index, obj)
            return cand.validate()
        return check

    # ------------------------------------------------------------------ overview
    def _refresh_overview(self) -> None:
        conn = system.connection_info()
        lines = [f"[b]Config[/b]      {settings_file()}"]
        if conn:
            lines += [
                f"[b]Agent[/b]       {conn['name']}  →  wss://{conn['address']}:{conn['port']}",
                f"[b]Service[/b]     {system.service_status()}",
                f"[b]Fingerprint[/b] {conn['tls_fingerprint_sha256'][:23]}…",
            ]
        else:
            lines.append("[b]Agent[/b]       not initialised on this machine (System setup → Write connection info)")
        lines.append("")
        lines.append("[b]IP addresses[/b]")
        lines += [f"  {iface:16} {ip}" for iface, ip in system.ip_addresses()] or ["  none"]
        lines.append("")
        games = self.settings.games
        lines.append(f"[b]ROM sources[/b] {len(self.settings.rom_sources)}    [b]Games[/b] {len(games)}    [b]Hosts[/b] {len(load_hosts())}")
        for g in games:
            lines.append(f"  {g.title or g.id:24} {system.game_status(g, self.settings)}")
        if system.scripts_dir() is None:
            lines.append("\n[yellow]Install scripts not found; System setup actions are unavailable.[/yellow]")
        self.query_one("#overview-text", Static).update("\n".join(lines))

    # ------------------------------------------------------------------ agent
    def _agent_button(self, bid: str) -> None:
        if bid == "agent-save":
            try:
                agent = self.query_one("#agent-form", FieldsForm).build()
            except ValueError as e:
                self.notify(str(e), severity="error")
                return
            cand = replace(self.settings, agent=agent)
            if self._save(cand):
                self.notify("Restart the agent (System setup → autostart) to apply bind/port/allowlist changes.")
        elif bid == "agent-rotate":
            def done(yes: bool | None) -> None:
                if yes:
                    from ..agent.__main__ import init_agent

                    init_agent(force=True)
                    self.notify("New token and certificate written. Re-add this host on the dev machine and restart the agent.")
                    self._refresh_overview()
            self.push_screen(ConfirmModal("Rotate token and certificate? Every dev machine must re-add this host."), done)
        elif bid == "agent-show":
            p = agent_dir() / "connection.json"
            text = p.read_text() if p.exists() else "Not initialised yet."
            self.push_screen(TextModal(f"{p}  (contains the access token, share privately)", text))

    # ------------------------------------------------------------------ system setup
    def _run_step(self, step_id: str) -> None:
        argv = system.step_command(step_id, self.settings)
        if argv is None:
            self.notify("Not available on this platform / install scripts not found.", severity="warning")
            return

        def go(yes: bool | None) -> None:
            if not yes:
                return
            with self.suspend():
                print(f"$ {' '.join(argv)}\n", flush=True)
                rc = subprocess.call(argv)
                input(f"\n[exit code {rc}] press Enter to return to the TUI…")
            self.action_refresh()

        if step_id == "uninstall":
            self.push_screen(ConfirmModal("Uninstall the agent and delete its credentials?"), go)
        else:
            go(True)

    # ------------------------------------------------------------------ ROM sources
    def _refresh_sources(self) -> None:
        t = self.query_one("#sources-table", DataTable)
        t.clear()
        for s in self.settings.rom_sources:
            t.add_row(s.name, s.kind, s.host or "-", s.share or "-", s.path or "-", s.mount_point or "-")

    def _source_button(self, bid: str) -> None:
        idx = self._selected("#sources-table")
        if bid == "src-add":
            self._edit_item("rom_sources", None, S.RomSource(), "Add ROM source")
        elif bid == "src-edit" and idx is not None:
            self._edit_item("rom_sources", idx, self.settings.rom_sources[idx], "Edit ROM source")
        elif bid == "src-del" and idx is not None:
            src = self.settings.rom_sources[idx]
            users = [g.id for g in self.settings.games if g.source == src.name]
            if users:
                self.notify(f"Used by games: {', '.join(users)}", severity="error")
                return
            cand = copy.deepcopy(self.settings)
            del cand.rom_sources[idx]
            self._save(cand)
        elif bid == "src-test" and idx is not None:
            self._test_source(self.settings.rom_sources[idx])

    @work(exclusive=True)
    async def _test_source(self, src: S.RomSource) -> None:
        self.notify(f"Testing {src.name}…")
        ok, msg = await system.test_source(src)
        self.notify(msg[:600], title=f"{src.name}: {'OK' if ok else 'FAILED'}",
                    severity="information" if ok else "error", timeout=12)

    # ------------------------------------------------------------------ games
    def _refresh_games(self) -> None:
        t = self.query_one("#games-table", DataTable)
        t.clear()
        for g in self.settings.games:
            t.add_row(g.id, g.title, g.platform, g.source or "(project folder)", g.source_path or "-",
                      g.format, ",".join(g.backends), system.game_status(g, self.settings))

    def _game_button(self, bid: str) -> None:
        idx = self._selected("#games-table")
        if bid == "game-add":
            self._edit_item("games", None, S.Game(), "Add game")
        elif bid == "game-edit" and idx is not None:
            self._edit_item("games", idx, self.settings.games[idx], "Edit game")
        elif bid == "game-del" and idx is not None:
            cand = copy.deepcopy(self.settings)
            del cand.games[idx]
            self._save(cand)

    def _edit_item(self, attr: str, index: int | None, obj, title: str) -> None:
        context = {"rom_sources": [s.name for s in self.settings.rom_sources]}

        def done(result) -> None:
            if result is None:
                return
            cand = copy.deepcopy(self.settings)
            items = getattr(cand, attr)
            items.append(result) if index is None else items.__setitem__(index, result)
            self._save(cand)

        self.push_screen(EditModal(title, obj, context, self._check_with(attr, index)), done)

    # ------------------------------------------------------------------ hosts
    def _host_files(self) -> list[Path]:
        d = hosts_dir()
        return sorted(d.glob("*.json")) if d.is_dir() else []

    def _refresh_hosts(self) -> None:
        t = self.query_one("#hosts-table", DataTable)
        t.clear()
        for p in self._host_files():
            h = HostConfig.load(p)
            t.add_row(h.name, h.url, h.platform or "?", h.trust)

    def _host_button(self, bid: str) -> None:
        files = self._host_files()
        idx = self._selected("#hosts-table")
        if bid == "host-add":
            def add(path: str | None) -> None:
                if not path:
                    return
                from ..cli import main as cli_main

                try:
                    cli_main(["add-host", str(Path(path).expanduser())])
                except (OSError, ValueError, KeyError) as e:
                    self.notify(repr(e), severity="error")
                self._refresh_hosts()
            self.push_screen(PromptModal("Path to the target's connection.json:"), add)
        elif idx is None or idx >= len(files):
            return
        elif bid == "host-trust":
            data = json.loads(files[idx].read_text())
            data["trust"] = "external" if data.get("trust", "own") == "own" else "own"
            files[idx].write_text(json.dumps(data, indent=2) + "\n")
            self._refresh_hosts()
        elif bid == "host-ping":
            self._ping(HostConfig.load(files[idx]))
        elif bid == "host-del":
            def rm(yes: bool | None) -> None:
                if yes:
                    files[idx].unlink()
                    self._refresh_hosts()
            self.push_screen(ConfirmModal(f"Remove host {files[idx].stem}?"), rm)

    @work(exclusive=True)
    async def _ping(self, host: HostConfig) -> None:
        from ..client import AgentClient

        try:
            async with AgentClient(host) as c:
                r = await c.call("system.ping", timeout=5)
            self.notify(f"agent {r['agent']}, protocol {r['protocol']}", title=f"{host.name}: OK")
        except Exception as e:
            self.notify(repr(e), title=f"{host.name}: unreachable", severity="error")

    # ------------------------------------------------------------------ storage
    def _storage_save(self) -> None:
        try:
            cand = replace(
                self.settings,
                storage=self.query_one("#storage-form", FieldsForm).build(),
                profiling=self.query_one("#profiling-form", FieldsForm).build(),
                install=self.query_one("#install-form", FieldsForm).build(),
            )
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self._save(cand)

    # ------------------------------------------------------------------ dispatch
    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("agent-"):
            self._agent_button(bid)
        elif bid.startswith("step-"):
            self._run_step(bid.removeprefix("step-"))
        elif bid.startswith("src-"):
            self._source_button(bid)
        elif bid.startswith("game-"):
            self._game_button(bid)
        elif bid.startswith("host-"):
            self._host_button(bid)
        elif bid == "storage-save":
            self._storage_save()


def run(initial_tab: str | None = None) -> None:
    RecompTUI(initial_tab).run()
