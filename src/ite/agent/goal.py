"""Durable, thread-scoped Goal mode state.

Goal state deliberately lives outside the Textual runtime so the same lifecycle
is available to the terminal UI, slash commands, and future remote surfaces.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

GOAL_EVENT_LIMIT = 100
GOAL_PROOF_LIMIT = 24


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    BUDGET_LIMITED = "budget_limited"
    COMPLETED = "completed"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_datetime(value: Any, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, str):
        try:
            return _as_utc(datetime.fromisoformat(value))
        except ValueError:
            pass
    return fallback or _utc_now()


@dataclass
class GoalMetrics:
    active_elapsed_seconds: float = 0.0
    work_elapsed_seconds: float = 0.0
    model_rounds: int = 0
    continuation_count: int = 0
    tool_calls_started: int = 0
    tool_calls_succeeded: int = 0
    tool_calls_failed: int = 0
    files_changed: int = 0
    verification_attempts: int = 0
    verification_passes: int = 0


@dataclass
class GoalEvent:
    timestamp: datetime
    kind: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": _as_utc(self.timestamp).isoformat(),
            "kind": self.kind,
            "summary": self.summary,
            "evidence": dict(self.evidence),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoalEvent:
        return cls(
            timestamp=_parse_datetime(data.get("timestamp")),
            kind=str(data.get("kind") or "note"),
            summary=str(data.get("summary") or ""),
            evidence=dict(data.get("evidence") or {}),
        )


@dataclass
class GoalMilestone:
    """A user-visible outcome that must be reached before goal completion."""

    milestone_id: str
    title: str
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.milestone_id,
            "title": self.title,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoalMilestone":
        return cls(
            milestone_id=str(data.get("id") or uuid4()),
            title=str(data.get("title") or "").strip(),
            completed=bool(data.get("completed", False)),
        )


@dataclass
class GoalProof:
    """A concise, user-readable reference that supports goal completion."""

    kind: str
    label: str
    reference: str
    status: str = "recorded"

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "label": self.label,
            "reference": self.reference,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoalProof":
        return cls(
            kind=str(data.get("kind") or "other").strip(),
            label=str(data.get("label") or "Evidence recorded").strip(),
            reference=str(data.get("reference") or "").strip(),
            status=str(data.get("status") or "recorded").strip(),
        )


@dataclass
class GoalState:
    goal_id: str
    objective: str
    status: GoalStatus
    created_at: datetime
    updated_at: datetime
    active_started_at: datetime | None = None
    completed_at: datetime | None = None
    metrics: GoalMetrics = field(default_factory=GoalMetrics)
    events: list[GoalEvent] = field(default_factory=list)
    milestones: list[GoalMilestone] = field(default_factory=list)
    proofs: list[GoalProof] = field(default_factory=list)
    latest_evidence: str | None = None
    blocker: str | None = None
    budget_details: dict[str, Any] | None = None

    @classmethod
    def create(cls, objective: str, *, now: datetime | None = None) -> GoalState:
        cleaned_objective = objective.strip()
        if not cleaned_objective:
            raise ValueError("A goal needs an objective.")
        timestamp = _as_utc(now or _utc_now())
        state = cls(
            goal_id=str(uuid4()),
            objective=cleaned_objective,
            status=GoalStatus.ACTIVE,
            created_at=timestamp,
            updated_at=timestamp,
            active_started_at=timestamp,
        )
        state.add_event("created", "Goal created.", now=timestamp)
        return state

    def active_elapsed_seconds(self, *, now: datetime | None = None) -> float:
        elapsed = max(0.0, float(self.metrics.active_elapsed_seconds))
        if self.status is not GoalStatus.ACTIVE or self.active_started_at is None:
            return elapsed
        timestamp = _as_utc(now or _utc_now())
        return elapsed + max(
            0.0, (timestamp - _as_utc(self.active_started_at)).total_seconds()
        )

    def _settle_active_elapsed(self, *, now: datetime) -> None:
        if self.status is GoalStatus.ACTIVE and self.active_started_at is not None:
            self.metrics.active_elapsed_seconds = self.active_elapsed_seconds(now=now)
            self.active_started_at = None

    def add_event(
        self,
        kind: str,
        summary: str,
        *,
        evidence: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        timestamp = _as_utc(now or _utc_now())
        self.events.append(
            GoalEvent(
                timestamp=timestamp,
                kind=kind,
                summary=summary.strip(),
                evidence=dict(evidence or {}),
            )
        )
        if len(self.events) > GOAL_EVENT_LIMIT:
            del self.events[:-GOAL_EVENT_LIMIT]
        self.updated_at = timestamp

    def pause(
        self, *, reason: str = "Paused by user.", now: datetime | None = None
    ) -> None:
        if self.status is not GoalStatus.ACTIVE:
            raise ValueError("Only an active goal can be paused.")
        timestamp = _as_utc(now or _utc_now())
        self._settle_active_elapsed(now=timestamp)
        self.status = GoalStatus.PAUSED
        self.add_event("paused", reason, now=timestamp)

    def resume(self, *, now: datetime | None = None) -> None:
        if self.status not in {
            GoalStatus.PAUSED,
            GoalStatus.BLOCKED,
            GoalStatus.BUDGET_LIMITED,
        }:
            raise ValueError(
                "Only a paused, blocked, or usage-limited goal can resume."
            )
        timestamp = _as_utc(now or _utc_now())
        self.status = GoalStatus.ACTIVE
        self.active_started_at = timestamp
        self.blocker = None
        self.budget_details = None
        self.add_event("resumed", "Goal resumed.", now=timestamp)

    def edit(self, objective: str, *, now: datetime | None = None) -> None:
        cleaned_objective = objective.strip()
        if not cleaned_objective:
            raise ValueError("A goal needs an objective.")
        timestamp = _as_utc(now or _utc_now())
        previous = self.objective
        self.objective = cleaned_objective
        self.completed_at = None
        self.latest_evidence = None
        self.milestones = []
        self.proofs = []
        self.add_event(
            "edited",
            "Goal objective updated.",
            evidence={"previous_objective": previous},
            now=timestamp,
        )

    def block(self, blocker: str, *, now: datetime | None = None) -> None:
        message = blocker.strip()
        if not message:
            raise ValueError("A blocked goal needs a reason.")
        timestamp = _as_utc(now or _utc_now())
        self._settle_active_elapsed(now=timestamp)
        self.status = GoalStatus.BLOCKED
        self.blocker = message
        self.add_event("blocked", message, now=timestamp)

    def limit_budget(
        self, details: dict[str, Any], *, now: datetime | None = None
    ) -> None:
        timestamp = _as_utc(now or _utc_now())
        self._settle_active_elapsed(now=timestamp)
        self.status = GoalStatus.BUDGET_LIMITED
        self.budget_details = dict(details)
        self.add_event("budget_limited", "Provider usage limit reached.", now=timestamp)

    def record_evidence(
        self,
        summary: str,
        *,
        evidence: list[GoalProof] | None = None,
        now: datetime | None = None,
    ) -> None:
        text = summary.strip()
        if not text:
            raise ValueError("Evidence needs a summary.")
        self._add_proofs(evidence or [])
        self.latest_evidence = text
        self.add_event("evidence", text, now=now)

    def set_milestones(
        self, titles: list[str], *, now: datetime | None = None
    ) -> list[GoalMilestone]:
        cleaned = [title.strip() for title in titles if title.strip()]
        if not cleaned:
            raise ValueError("A goal plan needs at least one milestone.")
        if len(cleaned) > 6:
            raise ValueError("A goal plan can have at most six milestones.")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("Goal milestones must be distinct.")
        self.milestones = [
            GoalMilestone(milestone_id=str(uuid4())[:8], title=title)
            for title in cleaned
        ]
        self.add_event(
            "plan",
            f"Plan recorded with {len(self.milestones)} milestone"
            f"{'s' if len(self.milestones) != 1 else ''}.",
            now=now,
        )
        return self.milestones

    def complete_milestone(
        self,
        milestone_id: str,
        *,
        summary: str,
        evidence: list[GoalProof] | None = None,
        now: datetime | None = None,
    ) -> GoalMilestone:
        milestone = next(
            (item for item in self.milestones if item.milestone_id == milestone_id),
            None,
        )
        if milestone is None:
            raise ValueError("That goal milestone no longer exists.")
        if not evidence:
            raise ValueError("Completing a milestone requires observed proof.")
        milestone.completed = True
        self._add_proofs(evidence or [])
        self.add_event(
            "milestone_completed",
            summary.strip() or milestone.title,
            now=now,
        )
        return milestone

    def _add_proofs(self, proofs: list[GoalProof]) -> None:
        seen = {(proof.kind, proof.label, proof.reference) for proof in self.proofs}
        for proof in proofs:
            identity = (proof.kind, proof.label, proof.reference)
            if not proof.reference or identity in seen:
                continue
            self.proofs.append(proof)
            seen.add(identity)
        if len(self.proofs) > GOAL_PROOF_LIMIT:
            del self.proofs[:-GOAL_PROOF_LIMIT]

    def complete(
        self,
        summary: str,
        *,
        evidence: list[GoalProof] | None = None,
        now: datetime | None = None,
    ) -> None:
        text = summary.strip()
        if not text:
            raise ValueError("Completion needs a summary.")
        if not self.milestones:
            raise ValueError("Completion requires a goal plan.")
        if any(not milestone.completed for milestone in self.milestones):
            raise ValueError("Completion requires every goal milestone to be complete.")
        if not evidence:
            raise ValueError("Completion requires observed proof.")
        timestamp = _as_utc(now or _utc_now())
        self._settle_active_elapsed(now=timestamp)
        self.status = GoalStatus.COMPLETED
        self.completed_at = timestamp
        self._add_proofs(evidence or [])
        self.latest_evidence = text
        self.add_event("completed", text, now=timestamp)

    def to_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        metrics = asdict(self.metrics)
        metrics["active_elapsed_seconds"] = self.active_elapsed_seconds(now=now)
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "status": self.status.value,
            "created_at": _as_utc(self.created_at).isoformat(),
            "updated_at": _as_utc(self.updated_at).isoformat(),
            "active_started_at": (
                _as_utc(self.active_started_at).isoformat()
                if self.active_started_at is not None
                else None
            ),
            "completed_at": (
                _as_utc(self.completed_at).isoformat()
                if self.completed_at is not None
                else None
            ),
            "metrics": metrics,
            "events": [event.to_dict() for event in self.events],
            "milestones": [milestone.to_dict() for milestone in self.milestones],
            "proofs": [proof.to_dict() for proof in self.proofs],
            "latest_evidence": self.latest_evidence,
            "blocker": self.blocker,
            "budget_details": self.budget_details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoalState:
        created_at = _parse_datetime(data.get("created_at"))
        metrics_data = dict(data.get("metrics") or {})
        metric_names = GoalMetrics.__dataclass_fields__.keys()
        metrics = GoalMetrics(
            **{
                name: metrics_data[name]
                for name in metric_names
                if name in metrics_data
            }
        )
        raw_status = str(data.get("status") or GoalStatus.PAUSED.value)
        try:
            status = GoalStatus(raw_status)
        except ValueError:
            status = GoalStatus.PAUSED
        events = [
            GoalEvent.from_dict(event)
            for event in data.get("events") or []
            if isinstance(event, dict)
        ][-GOAL_EVENT_LIMIT:]
        milestones = [
            GoalMilestone.from_dict(item)
            for item in data.get("milestones") or []
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        proofs = [
            GoalProof.from_dict(item)
            for item in data.get("proofs") or []
            if isinstance(item, dict) and str(item.get("reference") or "").strip()
        ][-GOAL_PROOF_LIMIT:]
        return cls(
            goal_id=str(data.get("goal_id") or uuid4()),
            objective=str(data.get("objective") or "").strip(),
            status=status,
            created_at=created_at,
            updated_at=_parse_datetime(data.get("updated_at"), fallback=created_at),
            active_started_at=(
                _parse_datetime(data["active_started_at"])
                if data.get("active_started_at")
                else None
            ),
            completed_at=(
                _parse_datetime(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            metrics=metrics,
            events=events,
            milestones=milestones,
            proofs=proofs,
            latest_evidence=(
                str(data["latest_evidence"])
                if data.get("latest_evidence") is not None
                else None
            ),
            blocker=str(data["blocker"]) if data.get("blocker") is not None else None,
            budget_details=(
                dict(data["budget_details"])
                if isinstance(data.get("budget_details"), dict)
                else None
            ),
        )
