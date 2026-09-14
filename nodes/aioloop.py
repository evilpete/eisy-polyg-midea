"""
Bridge between Polyglot's synchronous/threaded callbacks and msmart's asyncio API.

A single event loop runs on a dedicated daemon thread for the life of the node
server.  Every coroutine the nodes need is submitted to that loop and waited on
with a timeout, so a wedged device can never block a poll thread forever.
"""

import asyncio
import concurrent.futures
import threading

import udi_interface

LOGGER = udi_interface.LOGGER

# Nothing on a LAN device should take longer than this.
DEFAULT_TIMEOUT = 45


class AsyncRunner:
    """Owns the background asyncio event loop."""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self._run, name='midea-aio', daemon=True)
        self._thread.start()

        if not self._started.wait(timeout=10):
            raise RuntimeError('Timed out starting the asyncio event loop')

        LOGGER.debug('Asyncio event loop thread started')

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._started.set)
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            finally:
                self._loop.close()

    @property
    def loop(self):
        return self._loop

    def run(self, coro, timeout: int = DEFAULT_TIMEOUT):
        """Run a coroutine on the loop and return its result.

        Raises whatever the coroutine raised, or TimeoutError if it overran.
        """
        if self._loop is None or self._loop.is_closed():
            raise RuntimeError('Asyncio event loop is not running')

        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(
                f'Operation did not complete within {timeout} seconds') from None

    def new_lock(self) -> asyncio.Lock:
        """Create an asyncio.Lock bound to this runner's loop."""
        return self.run(_make_lock(), timeout=10)

    def stop(self) -> None:
        if self._loop is None or self._loop.is_closed():
            return

        LOGGER.debug('Stopping asyncio event loop')
        self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None


async def _make_lock() -> asyncio.Lock:
    return asyncio.Lock()


# One runner shared by the controller and every device node.
RUNNER = AsyncRunner()
