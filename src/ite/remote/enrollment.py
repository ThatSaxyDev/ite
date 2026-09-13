from __future__ import annotations

import httpx

from .host_identity import HostIdentity, platform_label, save_host_identity
from .security import runtime_label


def enroll_host(
    *,
    api_url: str,
    access_token: str,
    name: str = "",
    host_id: str | None = None,
) -> HostIdentity:
    """Register this machine as a host and persist the returned host token.

    Uses the operator's one-off sign-in only to *enrol*. After this the machine
    authenticates as itself, and `ite remote serve` never needs a user session.
    """
    base = str(api_url or "").strip().rstrip("/")
    token = str(access_token or "").strip()
    if not base:
        raise RuntimeError("A cloud API URL is required to enrol this host.")
    if not token:
        raise RuntimeError(
            "Enrolling a host needs a one-time terminal sign-in. "
            "Run `ite cloud login` first."
        )

    payload: dict[str, str] = {
        "name": str(name or "").strip() or runtime_label(),
        "platform": platform_label(),
    }
    if host_id:
        payload["hostId"] = host_id

    try:
        response = httpx.post(
            f"{base}/remote/hosts",
            headers={"authorization": f"Bearer {token}"},
            json=payload,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach iTE Cloud at {base}: {exc}") from exc

    if response.status_code != 200:
        detail = ""
        try:
            body = response.json()
            detail = str((body.get("error") or {}).get("message") or "").strip()
        except ValueError:
            detail = response.text.strip()
        raise RuntimeError(
            detail
            or f"Host enrolment failed ({response.status_code}). "
            "iTE Remote requires an active Pro subscription."
        )

    body = response.json()
    resolved_host_id = str(body.get("hostId") or "").strip()
    host_token = str(body.get("hostToken") or "").strip()
    if not resolved_host_id or not host_token:
        raise RuntimeError("Host enrolment succeeded but the response was incomplete.")

    identity = HostIdentity(
        host_id=resolved_host_id,
        host_token=host_token,
        api_url=base,
        name=payload["name"],
        platform=payload["platform"],
    )
    save_host_identity(identity)
    return identity
