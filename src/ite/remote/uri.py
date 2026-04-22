"""Simple connection URI scheme for iTE Remote pairing."""
from __future__ import annotations

from urllib.parse import urlparse, parse_qs


# URL scheme: ite-remote://host:port/paircode
# Or simpler: ite://connect?host=X&port=Y&code=Z

def create_connection_uri(host: str, port: int, pair_code: str) -> str:
    """Create a connection URI that can be tapped/opened directly."""
    return f"ite://connect?host={host}&port={port}&code={pair_code}"


def create_simple_uri(host: str, port: int, pair_code: str) -> str:
    """Create a simpler URI format."""
    return f"ite://c/{host}/{port}/{pair_code}"


def parse_connection_uri(uri: str) -> dict | None:
    """Parse a connection URI into connection info."""
    if not uri:
        return None
    
    parsed = urlparse(uri)
    
    # Must be ite:// scheme
    if parsed.scheme != "ite":
        return None
    
    # Format 1: ite://connect?host=X&port=Y&code=Z
    if parsed.path == "/connect" or parsed.path == "connect":
        params = parse_qs(parsed.query)
        try:
            return {
                "host": params.get("host", [None])[0],
                "port": int(params.get("port", [0])[0]),
                "pair_code": params.get("code", [None])[0] or params.get("pair_code", [None])[0],
            }
        except (ValueError, IndexError):
            return None
    
    # Format 2: ite://c/host/port/code
    if parsed.path.startswith("/c/"):
        parts = parsed.path[3:].split("/")
        if len(parts) >= 3:
            try:
                return {
                    "host": parts[0],
                    "port": int(parts[1]),
                    "pair_code": parts[2],
                }
            except ValueError:
                return None
    
    # Format 3: ite-remote://host:port/code (legacy)
    if parsed.scheme == "ite-remote":
        try:
            host_port = parsed.netloc
            if ":" in host_port:
                host, port_str = host_port.rsplit(":", 1)
                return {
                    "host": host,
                    "port": int(port_str),
                    "pair_code": parsed.path.lstrip("/"),
                }
        except (ValueError, IndexError):
            return None
    
    return None


def format_for_clipboard(host: str, port: int, pair_code: str) -> str:
    """Format connection info for easy clipboard copy."""
    return f"{host}:{port}:{pair_code}"


def parse_clipboard(text: str) -> dict | None:
    """Parse clipboard text in format host:port:code."""
    if not text:
        return None
    
    # Try simple format
    parts = text.strip().split(":")
    if len(parts) >= 3:
        try:
            return {
                "host": parts[0],
                "port": int(parts[1]),
                "pair_code": parts[2],
            }
        except ValueError:
            pass
    
    # Try URL format
    return parse_connection_uri(text)
