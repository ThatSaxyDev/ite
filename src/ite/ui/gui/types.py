from dataclasses import dataclass


@dataclass
class GUIFlags:
    auto_scroll_enabled: bool = True
    scroll_request_id: int = 0
