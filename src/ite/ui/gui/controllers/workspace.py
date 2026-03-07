from __future__ import annotations
from pathlib import Path
import flet as ft
from datetime import datetime
from ite.agent.session_manager import SessionManager
from ..tokens import *


class WorkspaceControllerMixin:
    def _refresh_sidebar_threads(self):
        if not self.sidebar_threads_column:
            return

        sessions = [
            s
            for s in SessionManager().list_sessions(
                workspace_path=self.config.cwd,
                include_legacy_unscoped=False,
            )
            if s.get("turn_count", 0) > 0
        ][:20]
        self.sidebar_sessions_cache = sessions
        self.sidebar_sessions_by_id = {
            s.get("session_id", ""): s for s in sessions if s.get("session_id")
        }
        self._render_sidebar_threads(sessions)

    def _render_sidebar_threads(self, sessions: list[dict] | None = None):
        if not self.sidebar_threads_column:
            return

        if sessions is None:
            sessions = self.sidebar_sessions_cache or []

        controls: list[ft.Control] = []
        if self.sidebar_collapsed:
            self.sidebar_threads_column.controls = controls
            if self.page:
                self.page.update()
            return
        if not sessions:
            if not self.sidebar_collapsed:
                controls.append(ft.Text("No saved threads", size=TYPE_SM, color=TEXT_MUTED))
        else:
            for session in sessions:
                updated = datetime.fromisoformat(session["updated_at"]).strftime("%b %d")
                is_active = session["session_id"] == self.active_session_id
                is_loading = session["session_id"] == self.loading_session_id
                session_name = (session.get("name") or session["session_id"]).strip()

                controls.append(
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Container(
                                    width=3,
                                    height=26,
                                    border_radius=RADIUS_SM,
                                    bgcolor=ACCENT if is_active else ft.Colors.TRANSPARENT,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(
                                            session_name[:32],
                                            size=TYPE_SM,
                                            color=TEXT_PRIMARY,
                                            weight=WEIGHT_SEMIBOLD if is_active else WEIGHT_MEDIUM,
                                            no_wrap=True,
                                        ),
                                    ],
                                    spacing=1,
                                    expand=True,
                                ),
                                (
                                    ft.Container(
                                        content=ft.Text("loading", size=TYPE_XS, color=ACCENT),
                                        padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                                        border=ft.Border.all(1, ACCENT_SOFT),
                                        border_radius=RADIUS_LG,
                                        bgcolor=ft.Colors.with_opacity(0.10, ACCENT),
                                    )
                                    if is_loading
                                    else ft.Text(updated, size=TYPE_XS, color=TEXT_MUTED)
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding.symmetric(horizontal=9, vertical=7),
                        border=ft.Border.all(1, ACCENT_SOFT if is_active else ft.Colors.TRANSPARENT),
                        border_radius=RADIUS_SM,
                        bgcolor=ft.Colors.with_opacity(0.12, ACCENT) if is_active else ft.Colors.TRANSPARENT,
                        on_click=lambda e, sid=session["session_id"]: self._on_sidebar_session_click(sid),
                    )
                )

        self.sidebar_threads_column.controls = controls
        if self.page:
            self.page.update()

    def _refresh_workspace_options(self):
        if not self.workspace_selector:
            return
        manager = SessionManager()
        current_workspace = str(self.config.cwd.resolve())
        known = [p for p in manager.list_workspaces() if p]
        if current_workspace not in known:
            known.insert(0, current_workspace)
        self.workspace_selector.options = [
            ft.dropdown.Option(
                key=p,
                text=(Path(p).name or p),
                content=ft.Column(
                    [
                        ft.Text(Path(p).name or p, size=TYPE_MD, color=TEXT_PRIMARY),
                        ft.Text(p, size=TYPE_XS, color=TEXT_MUTED, no_wrap=True),
                    ],
                    tight=True,
                    spacing=1,
                ),
            )
            for p in known
        ]
        self.workspace_selector.value = current_workspace
        if self.page:
            self.page.update()

    def _on_workspace_select(self, e: ft.Event[ft.Dropdown]):
        if not self.workspace_selector or not self.page:
            return
        selected = self.workspace_selector.value
        if not selected:
            return
        self.page.run_task(self._switch_workspace, selected)

    async def _switch_workspace(self, workspace: str):
        target = Path(workspace).expanduser().resolve()
        if not target.exists() or not target.is_dir():
            self._add_message("system", f"Workspace not found: {target}", is_error=True)
            self._refresh_workspace_options()
            return
        if target == self.config.cwd.resolve():
            return
        self._set_loading(True)
        try:
            self.config.cwd = target
            if self.header_workspace_text:
                self.header_workspace_text.value = f"Workspace: {self.config.cwd}"
            if self.agent is not None:
                await self._shutdown_agent()
            if self.messages_column:
                self.messages_column.controls.clear()
            self._set_current_session_title(None)
            self.active_session_id = None
            self._tool_call_row_indices.clear()
            self._refresh_workspace_options()
            self._refresh_sidebar_threads()
            self._add_assistant_card(
                "Workspace",
                ft.Text(f"Switched to {self.config.cwd}", color=TEXT_SECONDARY),
            )
        finally:
            self._set_loading(False)

    def _on_new_thread(self):
        if self.page:
            self.page.run_task(self._start_new_thread)

    def _on_sidebar_session_click(self, session_id: str):
        if not self.page:
            return
        if self.loading_session_id == session_id:
            return
        self.loading_session_id = session_id
        self.active_session_id = session_id
        session = self.sidebar_sessions_by_id.get(session_id)
        if session:
            self._set_current_session_title(session.get("name") or "New thread")
        self._render_sidebar_threads()
        self.page.run_task(self._open_session_from_sidebar, session_id)
