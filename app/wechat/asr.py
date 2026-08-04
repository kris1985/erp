"""Voice ASR adapter — replace recognize() with real provider later."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AsrAdapter:
    def recognize(self, media_id: str, access_token: str | None = None) -> str:
        logger.info("ASR stub media_id=%s", media_id)
        return ""


asr_adapter = AsrAdapter()
