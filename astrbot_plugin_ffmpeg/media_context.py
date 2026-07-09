from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MediaItem:
    media_id: str
    session_id: str
    component: Any
    component_type: str
    source: str
    message_id: str
    sender_id: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_id": self.media_id,
            "session_id": self.session_id,
            "type": self.component_type,
            "source": self.source,
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "created_at": self.created_at,
        }


class MediaContextManager:
    def __init__(self, max_items_per_session: int = 20) -> None:
        self.max_items_per_session = max(1, int(max_items_per_session or 20))
        self._items: dict[str, deque[MediaItem]] = defaultdict(deque)

    def capture_event_media(self, event: Any) -> list[MediaItem]:
        session_id = _session_id(event)
        captured: list[MediaItem] = []
        for component in _event_messages(event):
            source = _component_source(component)
            if not source:
                continue
            item = MediaItem(
                media_id=uuid.uuid4().hex[:12],
                session_id=session_id,
                component=component,
                component_type=component.__class__.__name__,
                source=source,
                message_id=str(getattr(event, "message_id", "")),
                sender_id=str(getattr(event, "user_id", "")),
                created_at=time.time(),
            )
            self._items[session_id].append(item)
            captured.append(item)

        self._trim(session_id)
        return captured

    def list_media(self, event: Any) -> list[dict[str, Any]]:
        session_id = _session_id(event)
        return [item.to_dict() for item in self._items.get(session_id, [])]

    def get_media(self, event: Any, index: int = -1, media_id: str | None = None) -> MediaItem | None:
        session_id = _session_id(event)
        items = list(self._items.get(session_id, []))
        if not items:
            return None

        if media_id:
            media_id = media_id.strip()
            for item in items:
                if item.media_id == media_id:
                    return item
            return None

        if index == -1:
            return items[-1]
        if index <= 0:
            return None
        zero_based = index - 1
        if zero_based >= len(items):
            return None
        return items[zero_based]

    def clear(self) -> None:
        self._items.clear()

    def _trim(self, session_id: str) -> None:
        items = self._items[session_id]
        while len(items) > self.max_items_per_session:
            items.popleft()


def _session_id(event: Any) -> str:
    return str(getattr(event, "unified_msg_origin", "") or getattr(event, "session_id", "") or "global")


def _event_messages(event: Any) -> list[Any]:
    getter = getattr(event, "get_messages", None)
    if callable(getter):
        return _flatten_components(list(getter() or []))
    return _flatten_components(list(getattr(event, "message", []) or []))


def _flatten_components(components: list[Any]) -> list[Any]:
    flattened: list[Any] = []
    for component in components:
        flattened.append(component)
        chain = getattr(component, "chain", None)
        if chain:
            flattened.extend(_flatten_components(list(chain)))
    return flattened


def _component_source(component: Any) -> str:
    for attr in ("path", "file", "url", "file_"):
        value = getattr(component, attr, "")
        if value:
            return str(value)
    return ""
