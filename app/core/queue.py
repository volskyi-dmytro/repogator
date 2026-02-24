import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Optional

import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import get_logger
from app.core.metrics import queue_depth

logger = get_logger(__name__)


class RedisQueue:
    """Async Redis-backed queue using a list for FIFO event processing.

    Events are pushed to the left (LPUSH) and popped from the right (BRPOP)
    so that the oldest event is always processed first.
    """

    def __init__(self, redis_url: str = settings.redis_url) -> None:
        """Initialise the queue with a Redis connection URL.

        Args:
            redis_url: Redis connection string, e.g. redis://localhost:6379.
        """
        self._redis_url = redis_url
        self._client: Optional[aioredis.Redis] = None

    async def connect(self) -> None:
        """Create the Redis connection pool."""
        self._client = aioredis.from_url(
            self._redis_url, encoding="utf-8", decode_responses=True
        )

    async def disconnect(self) -> None:
        """Close the Redis connection pool."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure_connected(self) -> aioredis.Redis:
        """Return the Redis client, raising if not yet connected."""
        if self._client is None:
            raise RuntimeError(
                "RedisQueue is not connected. Call connect() first."
            )
        return self._client

    async def push_event(self, event_data: dict) -> None:
        """Push an event dict onto the left of the queue.

        Args:
            event_data: Arbitrary dict that will be JSON-serialised.
        """
        client = self._ensure_connected()
        await client.lpush(settings.webhook_queue_name, json.dumps(event_data))
        depth = await client.llen(settings.webhook_queue_name)
        queue_depth.set(depth)
        logger.debug("Pushed event to queue", extra={"queue": settings.webhook_queue_name})

    async def pop_event(self) -> Optional[dict]:
        """Pop and return the oldest event from the right of the queue.

        Blocks for up to 1 second waiting for an item. Returns None on timeout.

        Returns:
            Decoded event dict or None if the queue was empty within the timeout.
        """
        client = self._ensure_connected()
        result = await client.brpop(settings.webhook_queue_name, timeout=1)
        if result is None:
            return None
        _, raw = result
        depth = await client.llen(settings.webhook_queue_name)
        queue_depth.set(depth)
        return json.loads(raw)

    async def ping(self) -> bool:
        """Return True if Redis responds to PING, False otherwise."""
        try:
            client = self._ensure_connected()
            return await client.ping()
        except Exception:
            return False


DispatchCallback = Callable[[dict], Coroutine[Any, Any, None]]


class QueueWorker:
    """Consumes events from a RedisQueue and dispatches them to a callback.

    Runs in an asyncio loop. Supports graceful shutdown via stop().
    """

    def __init__(self, queue: RedisQueue, dispatch: DispatchCallback) -> None:
        """Initialise the worker.

        Args:
            queue: A connected RedisQueue instance.
            dispatch: Async callable that receives each event dict.
        """
        self._queue = queue
        self._dispatch = dispatch
        self._running = False

    async def start(self) -> None:
        """Start the worker loop, consuming and dispatching events until stop() is called."""
        self._running = True
        logger.info("QueueWorker started")

        while self._running:
            try:
                event = await self._queue.pop_event()
                if event is None:
                    # BRPOP timed out — loop again to check _running flag
                    continue
                try:
                    await self._dispatch(event)
                except Exception as exc:
                    logger.error(
                        "Error dispatching event",
                        extra={"error": str(exc)},
                        exc_info=True,
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "Unexpected error in QueueWorker loop",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
                await asyncio.sleep(1)

        logger.info("QueueWorker stopped")

    def stop(self) -> None:
        """Signal the worker loop to stop after the current iteration."""
        self._running = False
