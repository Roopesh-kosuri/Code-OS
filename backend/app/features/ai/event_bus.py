import asyncio
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[[Any], Any]]] = {}

    def subscribe(self, event_type: str, callback: Callable[[Any], Any]) -> None:
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)
        logger.info("event_bus.subscribe event_type=%s count=%d", event_type, len(self._listeners[event_type]))

    async def publish(self, event_type: str, data: Any) -> None:
        logger.debug("event_bus.publish event_type=%s", event_type)
        if event_type in self._listeners:
            for cb in self._listeners[event_type]:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(data)
                    else:
                        cb(data)
                except Exception as exc:
                    logger.error("event_bus.publish error event_type=%s callback=%s: %s", event_type, cb.__name__, exc)

event_bus = EventBus()
