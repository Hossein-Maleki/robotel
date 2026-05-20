
from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Optional

from rubpy import Client as RubikaPyClient

from config import config

logger = logging.getLogger(__name__)


class RubikaService:
    """
    Long-lived Rubika client. Use `await service.start()` once at boot and
    `await service.stop()` on shutdown.

    All upload/download operations are serialized through a single asyncio
    lock — `rubpy` doesn't make hard guarantees about concurrent use of the
    same session, and serializing is fine for a moderate-traffic bot.
    """

    def __init__(self) -> None:
        self._client: Optional[RubikaPyClient] = None
        self._lock = asyncio.Lock()
        self._started = False
        self._target_peer = config.rubika.target_peer  # 'me' or channel guid

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Authenticate (interactively on first run) and keep client alive."""
        if self._started:
            return
        logger.info("Starting Rubika client (session=%s)", config.rubika.session_name)
        self._client = RubikaPyClient(name=config.rubika.session_name)
        # rubpy supports an explicit connect/start; using `start()` here so the
        # client stays open across many requests instead of using `async with`.
        await self._client.start()
        self._started = True
        logger.info("Rubika client started.")

    async def stop(self) -> None:
        """Cleanly disconnect the Rubika session."""
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception as exc:  # best effort
                logger.warning("Error while disconnecting Rubika: %s", exc)
            self._client = None
        self._started = False

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload_bytes(
        self,
        *,
        data: bytes,
        file_name: str,
        caption: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Upload an in-memory file to the configured Rubika peer.

        Returns a dict containing at least:
            { 'message_id': str, 'peer': str }

        Raises RuntimeError if the underlying rubpy call fails.
        """
        if not self._started or self._client is None:
            raise RuntimeError("RubikaService is not started.")

        async with self._lock:
            # rubpy accepts a path or a file-like object. We use BytesIO so
            # nothing ever touches disk on this server.
            buf = io.BytesIO(data)
            buf.name = file_name  # rubpy/most uploaders inspect .name

            logger.info("Uploading %s (%d bytes) to Rubika peer=%s",
                        file_name, len(data), self._target_peer)
            try:
                result = await self._client.send_file(
                    self._target_peer,
                    buf,
                    caption=caption or "",
                    file_name=file_name,
                )
            except TypeError:
                # Older rubpy versions don't accept `file_name=`; retry without.
                buf.seek(0)
                result = await self._client.send_file(
                    self._target_peer,
                    buf,
                    caption=caption or "",
                )

            message_id = _extract_message_id(result)
            if message_id is None:
                raise RuntimeError(
                    f"Rubika upload returned no message_id. Raw: {result!r}"
                )
            return {"message_id": str(message_id), "peer": self._target_peer}

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def download_bytes(self, *, peer: str, message_id: str) -> bytes:
        """
        Fetch a previously-uploaded file from Rubika and return its raw bytes.

        We deliberately avoid writing to disk: rubpy can download to a
        file-like object or return bytes directly depending on the version.
        """
        if not self._started or self._client is None:
            raise RuntimeError("RubikaService is not started.")

        async with self._lock:
            logger.info("Downloading message_id=%s from peer=%s", message_id, peer)

            # Try the most common rubpy APIs in order of preference.
            # 1) get_messages(...) + download(...)
            message = None
            try:
                message = await self._client.get_messages(peer, [int(message_id)])
            except Exception:
                try:
                    message = await self._client.get_messages_by_id(peer, [int(message_id)])
                except Exception:
                    message = None

            if message is not None:
                # Some versions return a list-like; pick the first message.
                msg_obj = message[0] if isinstance(message, (list, tuple)) else message
                try:
                    data = await msg_obj.download()
                    if isinstance(data, (bytes, bytearray)):
                        return bytes(data)
                except Exception:
                    pass

            # 2) Fallback: client.download(peer, message_id) -> bytes
            try:
                data = await self._client.download(peer, int(message_id))
                if isinstance(data, (bytes, bytearray)):
                    return bytes(data)
            except Exception as exc:
                logger.exception("Rubika download failed: %s", exc)

            raise RuntimeError(
                "Failed to download file from Rubika "
                f"(peer={peer}, message_id={message_id})."
            )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _extract_message_id(result: Any) -> Optional[Any]:
    """
    rubpy's `send_file` return shape varies between versions. Try several
    common locations to extract a numeric message id.
    """
    if result is None:
        return None

    # Plain dict
    if isinstance(result, dict):
        for key in ("message_id", "message_id_str", "id"):
            if key in result and result[key]:
                return result[key]
        # Nested under 'message_update' / 'data'
        for key in ("message_update", "data", "update"):
            if key in result and isinstance(result[key], dict):
                inner = result[key]
                for k in ("message_id", "id"):
                    if k in inner and inner[k]:
                        return inner[k]

    # Object-like
    for attr in ("message_id", "id"):
        val = getattr(result, attr, None)
        if val:
            return val

    return None


# Single shared instance — imported by bot.py
rubika_service = RubikaService()