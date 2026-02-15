"""
WebSocket client for real-time messaging.
Connects to backend /ws/messages, subscribes to conversations, and invokes
a callback when new messages arrive.
"""
import asyncio
import json
import logging
from typing import Callable, Awaitable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger("tuitter.ws")

# Fallback when BACKEND_WS_URL is not set: derive from REST base URL (https -> wss)
def _default_ws_url(base_url: str) -> str:
    if not base_url:
        return ""
    u = base_url.strip().rstrip("/")
    if u.startswith("https://"):
        return u.replace("https://", "wss://", 1)
    if u.startswith("http://"):
        return u.replace("http://", "ws://", 1)
    return "wss://" + u


async def run_messaging_ws(
    ws_url: str,
    token: str,
    subscribe_queue: asyncio.Queue,
    on_message: Callable[[int, dict], Awaitable[None]],
) -> None:
    """
    Connect to the messaging WebSocket and run the receive loop.
    - ws_url: base URL or full path (e.g. wss://host or wss://host/ws/messages); /ws/messages appended if path has no /ws/
    - token: bearer token for query param
    - subscribe_queue: when an int (conversation_id) is put, send subscribe
    - on_message: async callback(conversation_id, message_payload) for each new message
    """
    if not ws_url or not token:
        logger.debug("WebSocket skipped: missing ws_url or token")
        return
    url = f"{ws_url.rstrip('/')}/ws/messages" if "/ws/" not in ws_url else ws_url
    url = f"{url}?token={token}"
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                logger.debug("WebSocket connected to %s", url.split("?")[0])
                recv_task: Optional[asyncio.Task] = None
                while True:
                    # Wait for either a message from the server or a subscribe request
                    queue_get = asyncio.create_task(subscribe_queue.get())
                    recv_task = recv_task or asyncio.create_task(ws.recv())
                    done, pending = await asyncio.wait(
                        [queue_get, recv_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                    try:
                        await asyncio.gather(*pending)
                    except asyncio.CancelledError:
                        pass

                    if queue_get in done:
                        try:
                            conv_id = queue_get.result()
                            await ws.send(json.dumps({"type": "subscribe", "conversation_id": conv_id}))
                            logger.debug("Subscribed to conversation %s", conv_id)
                        except Exception as e:
                            logger.debug("Subscribe send failed: %s", e)
                        recv_task = None
                        continue

                    if recv_task in done:
                        try:
                            raw = recv_task.result()
                            data = json.loads(raw)
                            if data.get("type") == "message" and "payload" in data:
                                payload = data["payload"]
                                conv_id = payload.get("conversation_id")
                                if conv_id is not None:
                                    await on_message(int(conv_id), payload)
                            recv_task = None
                        except (json.JSONDecodeError, KeyError, TypeError) as e:
                            logger.debug("Invalid WS message: %s", e)
                            recv_task = None
        except ConnectionClosed as e:
            logger.debug("WebSocket closed: %s", e)
        except Exception as e:
            logger.debug("WebSocket error: %s", e)
        await asyncio.sleep(2)
