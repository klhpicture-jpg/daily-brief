"""Twitter collector. Deliberately a stub: disabled unless asked for."""
from __future__ import annotations

import logging
from datetime import datetime

from ..schema import Item

log = logging.getLogger("collectors.twitter")


def collect(config: dict, since: datetime) -> list[Item]:
    log.info("twitter collector is disabled")
    return []
