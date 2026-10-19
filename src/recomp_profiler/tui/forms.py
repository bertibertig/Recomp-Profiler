"""Forms generated from the settings dataclasses' field metadata."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, SelectionList, Static, Switch


class FieldsForm(Vertical):
    """One labelled widget per dataclass field. ``context`` resolves ``@name`` choices."""

    DEFAULT_CSS = """
    FieldsForm { height: auto; }
    FieldsForm .field-label { margin-top: 1; text-style: bold; }
    FieldsForm .field-help { color: $text-muted; }
    FieldsForm SelectionList { height: auto; max-height: 8; }
    """

    def __init__(self, obj: Any, context: dict[str, list[str]] | None = None, **kw: Any):
        super().__init__(**kw)
        self.obj = obj
        self.context = context or {}

    def _choices(self, meta: dict) -> tuple[list[str], bool] | None:
        choices = meta.get("choices")
        if choices is None:
            return None
        if isinstance(choices, str) and choices.startswith("@"):
            return list(self.context.get(choices[1:], [])), True  # dynamic: blank allowed
        return list(choices), False

    def compose(self) -> ComposeResult:
        for f in fields(self.obj):
            meta, value, wid = f.metadata, getattr(self.obj, f.name), f"f-{f.name}"
            yield Label(meta.get("label", f.name), classes="field-label")
            choices = self._choices(meta)
            if isinstance(value, bool):
                yield Switch(value=value, id=wid)
            elif isinstance(value, list) and choices:
                yield SelectionList[str](*[(c, c, c in value) for c in choices[0]], id=wid)
            elif isinstance(value, list):
                yield Input(", ".join(value), id=wid)
            elif choices:
                opts, allow_blank = choices
                yield Select(
                    [(c, c) for c in opts],
                    value=value if value in opts else Select.NULL,
                    allow_blank=allow_blank or value not in opts,
                    prompt="(none)",
                    id=wid,
                )
            elif isinstance(value, int):
                yield Input(str(value), type="integer", id=wid)
            else:
                yield Input(str(value), password=bool(meta.get("secret")), id=wid)
            if meta.get("help"):
                yield Static(meta["help"], classes="field-help")

    def read(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self.obj):
            w = self.query_one(f"#f-{f.name}")
            current = getattr(self.obj, f.name)
            if isinstance(w, Switch):
                out[f.name] = w.value
            elif isinstance(w, SelectionList):
                out[f.name] = list(w.selected)
            elif isinstance(w, Select):
                out[f.name] = "" if w.is_blank() else w.value
            elif isinstance(current, list):
                out[f.name] = [x.strip() for x in w.value.split(",") if x.strip()]
            elif isinstance(current, int) and not isinstance(current, bool):
                out[f.name] = int(w.value or 0)
            else:
                out[f.name] = w.value.strip()
        return out

    def build(self) -> Any:
        return type(self.obj)(**self.read())


class EditModal(ModalScreen):
    """Edit one dataclass instance; ``check`` returns validation errors that block saving."""

    DEFAULT_CSS = """
    EditModal { align: center middle; }
    EditModal > Vertical { width: 90; max-width: 100%; height: 90%; border: thick $accent; background: $surface; padding: 1 2; }
    EditModal #errors { color: $error; height: auto; }
    EditModal .buttons { height: auto; margin-top: 1; }
    """
    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title: str, obj: Any, context: dict | None = None,
                 check: Callable[[Any], list[str]] | None = None):
        super().__init__()
        self.title_text, self.obj, self.context, self.check = title, obj, context, check

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="field-label")
            with VerticalScroll():
                yield FieldsForm(self.obj, self.context, id="form")
            yield Static("", id="errors")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        try:
            obj = self.query_one("#form", FieldsForm).build()
        except ValueError as e:
            self.query_one("#errors", Static).update(str(e))
            return
        errors = self.check(obj) if self.check else []
        if errors:
            self.query_one("#errors", Static).update("\n".join(errors))
            return
        self.dismiss(obj)


class ConfirmModal(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal > Vertical { width: 60; height: auto; border: thick $warning; background: $surface; padding: 1 2; }
    """

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.question)
            with Horizontal():
                yield Button("Yes", variant="warning", id="yes")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class TextModal(ModalScreen):
    DEFAULT_CSS = """
    TextModal { align: center middle; }
    TextModal > Vertical { width: 90; max-width: 100%; height: auto; max-height: 90%; border: thick $accent; background: $surface; padding: 1 2; }
    """
    BINDINGS = [("escape", "dismiss(None)", "Close")]

    def __init__(self, title: str, text: str):
        super().__init__()
        self.title_text, self.text = title, text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.title_text, classes="field-label")
            with VerticalScroll():
                yield Static(self.text, markup=False)
            yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class PromptModal(ModalScreen):
    DEFAULT_CSS = """
    PromptModal { align: center middle; }
    PromptModal > Vertical { width: 80; max-width: 100%; height: auto; border: thick $accent; background: $surface; padding: 1 2; }
    """

    def __init__(self, question: str, value: str = ""):
        super().__init__()
        self.question, self.value = question, value

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.question)
            yield Input(self.value, id="answer")
            with Horizontal():
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.query_one("#answer", Input).value if event.button.id == "ok" else None)
