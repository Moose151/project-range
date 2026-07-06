from app import chat_state


def test_group_message_receipts_progress_from_sent_to_received_to_read():
    room = chat_state.create_group_room(101, [102, 103], "Ops")
    msg = chat_state.add_message(room.id, 101, "Alice", "Check comms")

    assert chat_state.message_receipt(msg, room.participant_ids)["state"] == "sent"

    chat_state.messages_after(room.id, 102, 0)
    partial = chat_state.message_receipt(msg, room.participant_ids)
    assert partial["state"] == "sent"
    assert partial["delivered"] == 1

    chat_state.messages_after(room.id, 103, 0)
    assert chat_state.message_receipt(msg, room.participant_ids)["state"] == "received"

    chat_state.mark_read(room.id, 102)
    partial_read = chat_state.message_receipt(msg, room.participant_ids)
    assert partial_read["state"] == "received"
    assert partial_read["read"] == 1

    chat_state.mark_read(room.id, 103)
    assert chat_state.message_receipt(msg, room.participant_ids)["state"] == "read"


def test_typing_state_is_hidden_from_typing_user():
    room = chat_state.create_group_room(201, [202], "Ops")

    assert chat_state.set_typing(room.id, 202, True)
    assert chat_state.typing_user_ids(room.id, 201) == [202]
    assert chat_state.typing_user_ids(room.id, 202) == []

    chat_state.set_typing(room.id, 202, False)
    assert chat_state.typing_user_ids(room.id, 201) == []
