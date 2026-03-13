from __future__ import annotations
import asyncio
from pathlib import Path
import flet as ft
from datetime import datetime
from ite.agent.session_manager import SessionManager
from ..tokens import *


class WorkspaceControllerMixin:
    def _session_list_signature(self, sessions: list[dict]) -> list[tuple[str, str, str, int]]:
        return [
            (
                str(s.get("session_id", "")),
                str(s.get("name", "")),
                str(s.get("updated_at", "")),
                int(s.get("turn_count", 0) or 0),
            )
            for s in sessions
        ]

    async def _reload_sidebar_threads_async(self, workspace_path: str | None = None):
        target_workspace = str(Path(workspace_path or self.config.cwd).resolve())
        try:
            sessions = await asyncio.to_thread(
                SessionManager().list_sessions,
                workspace_path=target_workspace,
                include_legacy_unscoped=False,
            )
            sessions = [s for s in sessions if s.get("turn_count", 0) > 0][:20]
            if str(self.config.cwd.resolve()) != target_workspace:
                return
            previous_signature = self._session_list_signature(self.sidebar_sessions_cache or [])
            new_signature = self._session_list_signature(sessions)
            self.sidebar_sessions_cache = sessions
            self.sidebar_sessions_by_id = {
                s.get("session_id", ""): s for s in sessions if s.get("session_id")
            }
            if hasattr(self, "_refresh_empty_state_copy"):
                self._refresh_empty_state_copy()
            if new_signature != previous_signature:
                self._render_sidebar_threads(sessions)
        finally:
            current_task = asyncio.current_task()
            if self._sidebar_refresh_task is current_task:
                self._sidebar_refresh_task = None

    def _schedule_sidebar_threads_refresh(self):
        if not self.page:
            return
        existing = getattr(self, "_sidebar_refresh_task", None)
        if existing and hasattr(existing, "done") and not existing.done():
            return
        self._sidebar_refresh_task = self.page.run_task(
            self._reload_sidebar_threads_async,
            str(self.config.cwd.resolve()),
        )

    def _known_workspace_paths(self) -> list[str]:
        manager = SessionManager()
        current_workspace = str(self.config.cwd.resolve())
        known = [p for p in manager.list_workspaces() if p]
        if current_workspace not in known:
            known.insert(0, current_workspace)
        return known

    def _refresh_sidebar_threads(self):
        if not self.sidebar_threads_column:
            return
        self._render_sidebar_threads(self.sidebar_sessions_cache or [])
        self._schedule_sidebar_threads_refresh()

    def _render_sidebar_threads(self, sessions: list[dict] | None = None):
        if not self.sidebar_threads_column:
            return

        if sessions is None:
            sessions = self.sidebar_sessions_cache or []

        controls: list[ft.Control] = []
        if self.sidebar_collapsed:
            self.sidebar_threads_column.controls = controls
            self._safe_control_update(self.sidebar_threads_column)
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
                                            size=TYPE_MD,
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
                                        content=ft.Row(
                                            [
                                                ft.ProgressRing(
                                                    width=9,
                                                    height=9,
                                                    stroke_width=1.5,
                                                    color=ACCENT,
                                                ),
                                                ft.Text("Loading...", size=TYPE_XS, color=ACCENT),
                                            ],
                                            spacing=5,
                                            tight=True,
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
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
        self._safe_control_update(self.sidebar_threads_column)

    def _refresh_workspace_options(self):
        if not self.workspace_selector:
            return
        current_workspace = str(self.config.cwd.resolve())
        known = self._known_workspace_paths()
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
        self._safe_control_update(self.workspace_selector)

    def _open_empty_state_workspace_dialog(self, e=None):
        if not self.page:
            return
        current_workspace = str(self.config.cwd.resolve())
        known = self._known_workspace_paths()

        items: list[ft.Control] = []
        for workspace in known:
            name = Path(workspace).name or workspace
            is_current = workspace == current_workspace
            items.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=8, vertical=8),
                    border_radius=RADIUS_SM,
                    bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE)
                    if is_current
                    else ft.Colors.TRANSPARENT,
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.FOLDER_OPEN, size=13, color=TEXT_MUTED),
                            ft.Column(
                                [
                                    ft.Text(
                                        name,
                                        size=TYPE_BODY,
                                        color=TEXT_PRIMARY,
                                        expand=True,
                                        no_wrap=True,
                                    ),
                                    ft.Text(
                                        workspace,
                                        size=TYPE_XS,
                                        color=TEXT_MUTED,
                                        no_wrap=True,
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                                tight=True,
                            ),
                            ft.Container(
                                visible=is_current,
                                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                border_radius=999,
                                bgcolor=ft.Colors.with_opacity(0.12, ACCENT),
                                content=ft.Text(
                                    "current",
                                    size=TYPE_XS,
                                    color=ACCENT,
                                    weight=WEIGHT_SEMIBOLD,
                                ),
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    on_click=lambda _, w=workspace: self._on_empty_state_workspace_pick(w),
                )
            )

        self.empty_workspace_picker_dialog = ft.AlertDialog(
            modal=True,
            bgcolor=SURFACE_1,
            title=ft.Text(
                "Select workspace",
                color=TEXT_PRIMARY,
                size=TYPE_H1,
                weight=WEIGHT_SEMIBOLD,
            ),
            content=ft.Container(
                width=460,
                height=360,
                content=ft.Column(
                    [ft.Column(items, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True)],
                    spacing=0,
                    expand=True,
                ),
            ),
            actions=[
                ft.TextButton(
                    "Close",
                    on_click=lambda _: self.page.pop_dialog() if self.page else None,
                    style=ft.ButtonStyle(color=ft.Colors.WHITE),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            actions_padding=ft.Padding.only(right=16, bottom=12),
            content_padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        )
        self.page.show_dialog(self.empty_workspace_picker_dialog)

    def _on_empty_state_workspace_pick(self, workspace: str):
        if not self.page:
            return
        self.page.pop_dialog()
        self.page.run_task(self._switch_workspace, workspace)

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
            await self._cancel_active_turn_and_wait()
            self.config.cwd = target
            self.gui_state.set_workspace(target)
            if self.header_workspace_text:
                self.header_workspace_text.value = f"Workspace: {self.config.cwd}"
            if hasattr(self, "_refresh_empty_state_copy"):
                self._refresh_empty_state_copy()
            if self.agent is not None:
                await self._shutdown_agent()
            if self.messages_column:
                self._clear_chat_controls()
            self.gui_state.session_loaded(
                session_id=None,
                title=None,
                workspace=self.config.cwd,
                visible_transcript_messages=[],
                transcript_truncated=False,
                pending_transcript_load=False,
            )
            self._set_current_session_title(None)
            self._tool_call_row_indices.clear()
            if hasattr(self, "_tool_args_by_call_id"):
                self._tool_args_by_call_id.clear()
            if hasattr(self, "_refresh_workboard_from_session"):
                self._refresh_workboard_from_session()
            self._refresh_workspace_options()
            self._refresh_sidebar_threads()
            if self.page:
                self.page.run_task(self._refresh_branch_options_async)
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
        if self._has_active_turn():
            self._show_transient_notice(
                "A process is running. Stop it first before switching threads."
            )
            return
        if self.loading_session_id is not None:
            self._show_transient_notice("A thread is already loading. Please wait.")
            return
        if self.loading_session_id == session_id:
            return
        self.gui_state.select_session(session_id)
        self._render_sidebar_threads()
        self.page.run_task(self._open_session_from_sidebar, session_id)
