import logging
from nio import (
    AsyncClient,
    MatrixRoom,
    RoomMessageText,
    InviteMemberEvent,
)

logger = logging.getLogger("matrix-pdf-bot")


async def dm_callback(
    room: MatrixRoom,
    event: RoomMessageText,
    matrix_client: AsyncClient,
    configured_room_id: str,
):
    """Handle direct messages to the bot with predefined responses (no LLM calls)."""
    # Only process DMs (messages not from the configured room)
    if room.room_id == configured_room_id:
        return

    # Ignore messages from the bot itself
    if event.sender == matrix_client.user_id:
        return

    logger.info(f"📬 Received DM from {event.sender} in room {room.room_id}")

    # Predefined response - no LLM processing to avoid costs
    response = "Não sou um bot conversacional, apenas realizo automações. Para análise de PDFs, envie o arquivo na sala/grupo configurada."

    await matrix_client.room_send(
        room_id=room.room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": response,
        },
    )
    logger.info(f"✅ Sent DM response to {event.sender}")


async def mention_callback(
    room: MatrixRoom,
    event: RoomMessageText,
    matrix_client: AsyncClient,
    configured_room_id: str,
):
    """Handle mentions of the bot in the configured room."""
    # Only process messages from the configured room
    if room.room_id != configured_room_id:
        return

    # Ignore messages from the bot itself
    if event.sender == matrix_client.user_id:
        return

    # Check if the bot is mentioned in the message
    bot_user_id = matrix_client.user_id
    message_body = event.body.lower()

    # Look for mentions: @username or full user ID
    bot_username = bot_user_id.split(":")[0][
        1:
    ]  # Extract username from @username:domain
    is_mentioned = (
        f"@{bot_username}" in message_body or bot_user_id.lower() in message_body
    )

    if not is_mentioned:
        return

    logger.info(f"👋 Bot mentioned by {event.sender} in configured room")

    response = "Não precisa me marcar, basta enviar os PDF para a sala/grupo"

    await matrix_client.room_send(
        room_id=configured_room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": response,
            "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
        },
    )
    logger.info(f"✅ Sent mention response to {event.sender}")


async def invite_callback(
    room: MatrixRoom,
    event: InviteMemberEvent,
    matrix_client: AsyncClient,
    configured_room_id: str,
):
    """Handle invitations to new rooms."""
    # Only process invitations to the bot
    if event.state_key != matrix_client.user_id:
        return

    logger.info(f"📨 Received invitation to room {room.room_id} from {event.sender}")

    try:
        # Accept the invitation
        await matrix_client.join(room.room_id)
        logger.info(f"✅ Joined room {room.room_id}")

        # Send explanatory message
        response = "Só posso funcionar na sala/chat pública já configurada. Se precisa de acesso direto, contacte o administrador"

        await matrix_client.room_send(
            room_id=room.room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": response,
            },
        )
        logger.info(f"✅ Sent explanation to room {room.room_id}")

        # Optionally leave the room after explaining
        # Uncomment the lines below if you want the bot to leave after explaining
        # await matrix_client.room_leave(room.room_id)
        # logger.info(f"👋 Left room {room.room_id}")

    except Exception as e:
        logger.error(f"❌ Failed to handle invitation to room {room.room_id}: {e}")
