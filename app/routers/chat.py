from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import chat_state
from app.database import get_db
from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/chat")


def _room_peer(room, current_user: User, db: Session | None = None) -> User | None:
    if room.is_group or db is None:
        return None
    other_ids = [uid for uid in room.participant_ids if uid != current_user.id]
    if not other_ids:
        return None
    return db.query(User).filter(User.id == other_ids[0], User.is_archived == False).first()


def _room_title(room, current_user: User, db: Session | None = None) -> str:
    if room.is_group:
        return room.title
    other = _room_peer(room, current_user, db)
    if other:
        return other.display_name
    other_ids = [uid for uid in room.participant_ids if uid != current_user.id]
    if not other_ids:
        return "Notes to self"
    return room.title


def _room_payload(room, current_user: User, db: Session | None = None) -> dict:
    other = _room_peer(room, current_user, db)
    participants = []
    if db is not None:
        users = (
            db.query(User)
            .filter(User.id.in_(room.participant_ids), User.is_active == True, User.is_archived == False)
            .order_by(User.display_name)
            .all()
        )
        participants = [
            {
                "id": user.id,
                "display_name": user.display_name,
                "duty_role": user.duty_role or "",
                "duty_role_color": user.duty_role_color or "",
            }
            for user in users
        ]
    return {
        "id": room.id,
        "title": other.display_name if other else _room_title(room, current_user, db),
        "title_duty_role": other.duty_role if other else "",
        "title_duty_role_color": other.duty_role_color if other else "",
        "is_group": room.is_group,
        "participants": sorted(room.participant_ids),
        "participant_details": participants,
        "last_message_id": chat_state.last_message_id(room),
        "typing_users": _typing_payload(room, current_user, db),
        "unread_hint": False,
    }


def _typing_payload(room, current_user: User, db: Session | None = None) -> list[dict]:
    user_ids = chat_state.typing_user_ids(room.id, current_user.id)
    if not user_ids:
        return []
    if db is None:
        return [{"id": uid, "display_name": "Someone"} for uid in user_ids]
    users = (
        db.query(User)
        .filter(User.id.in_(user_ids), User.is_active == True, User.is_archived == False)
        .order_by(User.display_name)
        .all()
    )
    return [{"id": user.id, "display_name": user.display_name} for user in users]


def _message_payload(msg, room=None) -> dict:
    payload = {
        "id": msg.id,
        "room_id": msg.room_id,
        "sender_id": msg.sender_id,
        "sender_name": msg.sender_name,
        "body": msg.body,
        "sent_at": msg.sent_at.strftime("%H:%M:%S"),
    }
    if room is not None:
        payload["receipt"] = chat_state.message_receipt(msg, room.participant_ids)
    return payload


def _receipt_payloads(room) -> list[dict]:
    if room is None:
        return []
    return [
        {"id": msg.id, "receipt": chat_state.message_receipt(msg, room.participant_ids)}
        for msg in room.messages
    ]


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "duty_role": user.duty_role or "",
        "duty_role_color": user.duty_role_color or "",
    }


@router.get("/state")
async def chat_state_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chat_state.touch_user(
        current_user.id,
        current_user.display_name,
        str(current_user.role.value if hasattr(current_user.role, "value") else current_user.role),
        current_user.duty_role or "",
        current_user.duty_role_color or "",
    )
    available_users = (
        db.query(User)
        .filter(User.is_active == True, User.is_archived == False)
        .order_by(User.display_name)
        .all()
    )
    return JSONResponse({
        "me": {"id": current_user.id, "display_name": current_user.display_name},
        "online_users": chat_state.online_users(),
        "available_users": [_user_payload(user) for user in available_users],
        "rooms": [_room_payload(room, current_user, db) for room in chat_state.user_rooms(current_user.id)],
    })


@router.post("/offline")
async def chat_offline(
    current_user: User = Depends(get_current_user),
):
    chat_state.forget_user(current_user.id)
    return JSONResponse({"ok": True})


@router.post("/rooms/private")
async def chat_private_room(
    user_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    other = db.query(User).filter(User.id == user_id, User.is_active == True, User.is_archived == False).first()
    if not other:
        return JSONResponse({"error": "User not found"}, status_code=404)
    room = chat_state.ensure_private_room(
        current_user.id,
        other.id,
        other.display_name if other.id != current_user.id else "Notes to self",
    )
    return JSONResponse({"room": _room_payload(room, current_user, db)})


@router.post("/rooms/group")
async def chat_group_room(
    participant_ids: str = Form(""),
    title: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ids = []
    for raw in participant_ids.split(","):
        raw = raw.strip()
        if raw.isdigit():
            ids.append(int(raw))
    active_ids = [
        uid for (uid,) in db.query(User.id)
        .filter(User.id.in_(ids), User.is_active == True, User.is_archived == False)
        .all()
    ] if ids else []
    room = chat_state.create_group_room(current_user.id, active_ids, title)
    return JSONResponse({"room": _room_payload(room, current_user, db)})


@router.post("/rooms/{room_id}/members")
async def chat_add_group_members(
    room_id: str,
    participant_ids: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ids = []
    for raw in participant_ids.split(","):
        raw = raw.strip()
        if raw.isdigit():
            ids.append(int(raw))
    active_ids = [
        uid for (uid,) in db.query(User.id)
        .filter(User.id.in_(ids), User.is_active == True, User.is_archived == False)
        .all()
    ] if ids else []
    room = chat_state.add_group_members(room_id, current_user.id, active_ids)
    if not room:
        return JSONResponse({"error": "Group chat not found"}, status_code=404)
    return JSONResponse({"room": _room_payload(room, current_user, db)})


@router.get("/rooms/{room_id}/messages")
async def chat_messages(
    room_id: str,
    after: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = chat_state.get_room_for_user(room_id, current_user.id)
    messages = chat_state.messages_after(room_id, current_user.id, after)
    return JSONResponse({
        "room": _room_payload(room, current_user, db) if room else None,
        "messages": [_message_payload(msg, room) for msg in messages],
        "receipts": _receipt_payloads(room),
    })


@router.post("/rooms/{room_id}/messages")
async def chat_send_message(
    room_id: str,
    body: str = Form(...),
    current_user: User = Depends(get_current_user),
):
    msg = chat_state.add_message(room_id, current_user.id, current_user.display_name, body)
    if not msg:
        return JSONResponse({"error": "Message not sent"}, status_code=400)
    room = chat_state.get_room_for_user(room_id, current_user.id)
    return JSONResponse({"message": _message_payload(msg, room)})


@router.post("/rooms/{room_id}/read")
async def chat_mark_read(
    room_id: str,
    up_to: int = Form(0),
    current_user: User = Depends(get_current_user),
):
    ok = chat_state.mark_read(room_id, current_user.id, up_to if up_to > 0 else None)
    if not ok:
        return JSONResponse({"error": "Chat room not found"}, status_code=404)
    return JSONResponse({"ok": True})


@router.post("/rooms/{room_id}/typing")
async def chat_typing(
    room_id: str,
    is_typing: int = Form(1),
    current_user: User = Depends(get_current_user),
):
    ok = chat_state.set_typing(room_id, current_user.id, bool(is_typing))
    if not ok:
        return JSONResponse({"error": "Chat room not found"}, status_code=404)
    return JSONResponse({"ok": True})
