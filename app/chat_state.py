"""In-memory instant chat state.

Chat is intentionally ephemeral: messages and rooms live only in this Python
process and are lost on restart/logout/browser refresh state changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock


ONLINE_WINDOW = timedelta(seconds=45)


@dataclass
class ChatMessage:
    id: int
    room_id: str
    sender_id: int
    sender_name: str
    body: str
    sent_at: datetime


@dataclass
class ChatRoom:
    id: str
    title: str
    participant_ids: set[int]
    is_group: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    messages: list[ChatMessage] = field(default_factory=list)


_lock = Lock()
_presence: dict[int, dict] = {}
_rooms: dict[str, ChatRoom] = {}
_message_seq = 0


def touch_user(
    user_id: int,
    display_name: str,
    role: str | None = None,
    duty_role: str | None = None,
    duty_role_color: str | None = None,
) -> None:
    with _lock:
        existing = _presence.get(user_id, {})
        _presence[user_id] = {
            "id": user_id,
            "display_name": display_name,
            "role": role if role is not None else existing.get("role", ""),
            "duty_role": duty_role if duty_role is not None else existing.get("duty_role", ""),
            "duty_role_color": duty_role_color if duty_role_color is not None else existing.get("duty_role_color", ""),
            "last_seen": datetime.utcnow(),
        }


def forget_user(user_id: int) -> None:
    with _lock:
        _presence.pop(user_id, None)


def online_users() -> list[dict]:
    cutoff = datetime.utcnow() - ONLINE_WINDOW
    with _lock:
        stale = [uid for uid, item in _presence.items() if item["last_seen"] < cutoff]
        for uid in stale:
            _presence.pop(uid, None)
        return [
            {
                "id": item["id"],
                "display_name": item["display_name"],
                "role": item["role"],
                "duty_role": item.get("duty_role", ""),
                "duty_role_color": item.get("duty_role_color", ""),
                "last_seen": item["last_seen"].isoformat(),
            }
            for item in sorted(_presence.values(), key=lambda x: x["display_name"].lower())
        ]


def _private_room_id(user_a: int, user_b: int) -> str:
    lo, hi = sorted((user_a, user_b))
    return f"private-{lo}-{hi}"


def ensure_private_room(user_a: int, user_b: int, title: str) -> ChatRoom:
    rid = _private_room_id(user_a, user_b)
    with _lock:
        room = _rooms.get(rid)
        if room is None:
            room = ChatRoom(id=rid, title=title, participant_ids={user_a, user_b}, is_group=False)
            _rooms[rid] = room
        return room


def create_group_room(creator_id: int, participant_ids: list[int], title: str) -> ChatRoom:
    ids = set(participant_ids)
    ids.add(creator_id)
    rid = f"group-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
    with _lock:
        room = ChatRoom(id=rid, title=title.strip() or "Group Chat", participant_ids=ids, is_group=True)
        _rooms[rid] = room
        return room


def user_rooms(user_id: int) -> list[ChatRoom]:
    with _lock:
        return [room for room in _rooms.values() if user_id in room.participant_ids]


def last_message_id(room: ChatRoom) -> int:
    return room.messages[-1].id if room.messages else 0


def get_room_for_user(room_id: str, user_id: int) -> ChatRoom | None:
    with _lock:
        room = _rooms.get(room_id)
        if room and user_id in room.participant_ids:
            return room
        return None


def add_message(room_id: str, sender_id: int, sender_name: str, body: str) -> ChatMessage | None:
    global _message_seq
    text = body.strip()
    if not text:
        return None
    with _lock:
        room = _rooms.get(room_id)
        if room is None or sender_id not in room.participant_ids:
            return None
        _message_seq += 1
        msg = ChatMessage(
            id=_message_seq,
            room_id=room_id,
            sender_id=sender_id,
            sender_name=sender_name,
            body=text[:2000],
            sent_at=datetime.utcnow(),
        )
        room.messages.append(msg)
        room.messages = room.messages[-100:]
        return msg


def messages_after(room_id: str, user_id: int, after_id: int = 0) -> list[ChatMessage]:
    with _lock:
        room = _rooms.get(room_id)
        if room is None or user_id not in room.participant_ids:
            return []
        return [msg for msg in room.messages if msg.id > after_id]
