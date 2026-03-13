from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class AppShellState:
    active_session_id: str | None = None
    loading_session_id: str | None = None
    sidebar_collapsed: bool = False
    workboard_visible: bool = True


@dataclass(frozen=True)
class InteractionState:
    is_turn_running: bool = False
    is_switching_session: bool = False
    is_hydrating_chat: bool = False
    can_send: bool = True


@dataclass(frozen=True)
class SessionViewState:
    current_session_title: str = "New thread"
    current_workspace: str = ""
    visible_transcript_messages: list[dict[str, Any]] = field(default_factory=list)
    transcript_truncated: bool = False
    pending_transcript_load: bool = False


@dataclass(frozen=True)
class WorkboardState:
    has_content: bool = False
    plan_text: str = ""
    todos_state: dict[str, Any] | None = None
    show_planning_todos: bool = False


@dataclass(frozen=True)
class GUIState:
    shell: AppShellState
    interaction: InteractionState
    session_view: SessionViewState
    workboard: WorkboardState


StoreSubscriber = Callable[[GUIState], None]


class GUIStateStore:
    def __init__(self, *, initial_workspace: str) -> None:
        self._state = GUIState(
            shell=AppShellState(),
            interaction=InteractionState(),
            session_view=SessionViewState(current_workspace=initial_workspace),
            workboard=WorkboardState(),
        )
        self._subscribers: dict[str, list[StoreSubscriber]] = {
            "shell": [],
            "interaction": [],
            "session_view": [],
            "workboard": [],
            "all": [],
        }

    @property
    def state(self) -> GUIState:
        return self._state

    def subscribe(self, topic: str, callback: StoreSubscriber) -> None:
        self._subscribers.setdefault(topic, []).append(callback)

    def _publish(self, *topics: str) -> None:
        notified: set[int] = set()
        for topic in (*topics, "all"):
            for callback in self._subscribers.get(topic, []):
                callback_id = id(callback)
                if callback_id in notified:
                    continue
                callback(self._state)
                notified.add(callback_id)

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        if self._state.shell.sidebar_collapsed == collapsed:
            return
        self._state = replace(
            self._state,
            shell=replace(self._state.shell, sidebar_collapsed=collapsed),
        )
        self._publish("shell")

    def toggle_sidebar(self) -> None:
        self.set_sidebar_collapsed(not self._state.shell.sidebar_collapsed)

    def toggle_workboard(self) -> None:
        if not self._state.workboard.has_content:
            return
        self._state = replace(
            self._state,
            shell=replace(
                self._state.shell,
                workboard_visible=not self._state.shell.workboard_visible,
            ),
        )
        self._publish("shell")

    def open_workboard(self) -> None:
        if not self._state.workboard.has_content or self._state.shell.workboard_visible:
            return
        self._state = replace(
            self._state,
            shell=replace(self._state.shell, workboard_visible=True),
        )
        self._publish("shell")

    def select_session(self, session_id: str) -> None:
        self._state = replace(
            self._state,
            shell=replace(self._state.shell, loading_session_id=session_id),
            interaction=replace(
                self._state.interaction,
                is_switching_session=True,
                can_send=False,
            ),
        )
        self._publish("shell", "interaction")

    def clear_session_loading(self) -> None:
        if (
            self._state.shell.loading_session_id is None
            and not self._state.interaction.is_switching_session
        ):
            return
        self._state = replace(
            self._state,
            shell=replace(self._state.shell, loading_session_id=None),
            interaction=replace(
                self._state.interaction,
                is_switching_session=False,
                can_send=not self._state.interaction.is_turn_running,
            ),
        )
        self._publish("shell", "interaction")

    def session_loaded(
        self,
        *,
        session_id: str | None,
        title: str | None,
        workspace: str | Path,
        visible_transcript_messages: list[dict[str, Any]],
        transcript_truncated: bool,
        pending_transcript_load: bool,
    ) -> None:
        normalized_title = (title or "").strip() or "New thread"
        workspace_str = str(Path(workspace).resolve())
        self._state = replace(
            self._state,
            shell=replace(
                self._state.shell,
                active_session_id=session_id,
                loading_session_id=None,
            ),
            interaction=replace(
                self._state.interaction,
                is_switching_session=False,
                is_hydrating_chat=False,
                can_send=not self._state.interaction.is_turn_running,
            ),
            session_view=replace(
                self._state.session_view,
                current_session_title=normalized_title,
                current_workspace=workspace_str,
                visible_transcript_messages=list(visible_transcript_messages),
                transcript_truncated=transcript_truncated,
                pending_transcript_load=pending_transcript_load,
            ),
        )
        self._publish("shell", "interaction", "session_view")

    def session_load_failed(self) -> None:
        self._state = replace(
            self._state,
            shell=replace(self._state.shell, loading_session_id=None),
            interaction=replace(
                self._state.interaction,
                is_switching_session=False,
                is_hydrating_chat=False,
                can_send=not self._state.interaction.is_turn_running,
            ),
        )
        self._publish("shell", "interaction")

    def set_turn_running(self, running: bool) -> None:
        can_send = not (running or self._state.interaction.is_switching_session)
        self._state = replace(
            self._state,
            interaction=replace(
                self._state.interaction,
                is_turn_running=running,
                can_send=can_send,
            ),
        )
        self._publish("interaction")

    def set_hydrating_chat(self, hydrating: bool) -> None:
        self._state = replace(
            self._state,
            interaction=replace(self._state.interaction, is_hydrating_chat=hydrating),
        )
        self._publish("interaction")

    def set_current_session_title(self, title: str | None) -> None:
        normalized_title = (title or "").strip() or "New thread"
        if self._state.session_view.current_session_title == normalized_title:
            return
        self._state = replace(
            self._state,
            session_view=replace(
                self._state.session_view,
                current_session_title=normalized_title,
            ),
        )
        self._publish("session_view")

    def set_workspace(self, workspace: str | Path) -> None:
        workspace_str = str(Path(workspace).resolve())
        if self._state.session_view.current_workspace == workspace_str:
            return
        self._state = replace(
            self._state,
            session_view=replace(
                self._state.session_view,
                current_workspace=workspace_str,
            ),
        )
        self._publish("session_view")

    def set_workboard_content(
        self,
        *,
        plan_text: str,
        todos_state: dict[str, Any] | None,
        show_planning_todos: bool,
        has_content: bool,
    ) -> None:
        workboard_visible = self._state.shell.workboard_visible if has_content else False
        self._state = replace(
            self._state,
            shell=replace(self._state.shell, workboard_visible=workboard_visible),
            workboard=replace(
                self._state.workboard,
                has_content=has_content,
                plan_text=plan_text,
                todos_state=todos_state,
                show_planning_todos=show_planning_todos,
            ),
        )
        self._publish("shell", "workboard")

    def set_transcript_view(
        self,
        *,
        visible_transcript_messages: list[dict[str, Any]],
        transcript_truncated: bool,
        pending_transcript_load: bool,
    ) -> None:
        self._state = replace(
            self._state,
            session_view=replace(
                self._state.session_view,
                visible_transcript_messages=list(visible_transcript_messages),
                transcript_truncated=transcript_truncated,
                pending_transcript_load=pending_transcript_load,
            ),
        )
        self._publish("session_view")
