"""Connection URI helpers for secure iTE Remote pairing."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, quote, urlencode, urlparse


def create_connection_uri(
    host: str,
    port: int,
    pair_code: str,
    *,
    name: str,
    fingerprint: str,
    expires_at: datetime | None = None,
    version: int = 1,
) -> str:
    """Create the secure connect URI shown to the user."""
    query = {
        "name": name,
        "host": host,
        "port": str(port),
        "code": pair_code,
        "fp": fingerprint,
        "v": str(version),
    }
    if expires_at is not None:
        query["exp"] = expires_at.isoformat()
    return f"ite://connect?{urlencode(query, quote_via=quote)}"


def parse_connection_uri(uri: str) -> dict | None:
    """Parse a connection URI into connection info."""
    if not uri:
        return None

    parsed = urlparse(uri)

    if parsed.scheme == "ite" and (
        parsed.netloc == "connect" or parsed.path in {"connect", "/connect"}
    ):
        params = parse_qs(parsed.query)
        try:
            return {
                "name": params.get("name", [""])[0],
                "host": params.get("host", [None])[0],
                "port": int(params.get("port", [0])[0]),
                "pair_code": params.get("code", [None])[0]
                or params.get("pair_code", [None])[0],
                "fingerprint": params.get("fp", [""])[0],
                "expires_at": params.get("exp", [""])[0],
                "version": int(params.get("v", ["1"])[0]),
            }
        except (ValueError, IndexError):
            return None

    if parsed.scheme == "ite" and parsed.path.startswith("/c/"):
        parts = parsed.path[3:].split("/")
        if len(parts) >= 3:
            try:
                return {
                    "host": parts[0],
                    "port": int(parts[1]),
                    "pair_code": parts[2],
                    "fingerprint": "",
                    "name": "",
                    "expires_at": "",
                    "version": 0,
                }
            except ValueError:
                return None

    if parsed.scheme == "ite-remote":
        try:
            host_port = parsed.netloc
            if ":" in host_port:
                host, port_str = host_port.rsplit(":", 1)
                return {
                    "host": host,
                    "port": int(port_str),
                    "pair_code": parsed.path.lstrip("/"),
                    "fingerprint": "",
                    "name": "",
                    "expires_at": "",
                    "version": 0,
                }
        except (ValueError, IndexError):
            return None

    return None


def format_for_clipboard(host: str, port: int, pair_code: str) -> str:
    """Legacy plain clipboard format."""
    return f"{host}:{port}:{pair_code}"


def parse_clipboard(text: str) -> dict | None:
    """Parse clipboard text in format host:port:code or secure URI."""
    if not text:
        return None

    parts = text.strip().split(":")
    if len(parts) >= 3:
        try:
            return {
                "host": parts[0],
                "port": int(parts[1]),
                "pair_code": parts[2],
                "fingerprint": "",
                "name": "",
                "expires_at": "",
                "version": 0,
            }
        except ValueError:
            pass

    return parse_connection_uri(text)
