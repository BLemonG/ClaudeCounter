from __future__ import annotations

import logging
import logging.handlers
import signal
import threading
from pathlib import Path
from typing import Optional

from . import protocol
from . import render as renderer
from . import transport
from . import usage_source
from .config import DeviceConfig
from .snapshot import UsageSnapshot

POLL_INTERVAL_SECONDS = 60.0
USAGE_FETCH_INTERVAL_SECONDS = 300.0
INITIAL_BACKOFF_SECONDS = 5.0
MAXIMUM_BACKOFF_SECONDS = 300.0
FORCED_RESEND_SECONDS = 600.0
FAILURE_HEARTBEAT_EVERY = 60

LOG_DIRECTORY = Path.home() / "Library" / "Logs" / "ClaudeCounter"
LOG_PATH = LOG_DIRECTORY / "claudecounter.log"
LOG_MAXIMUM_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


def build_logger(verbose: bool = False) -> logging.Logger:
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("claudecounter")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)
    to_file = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=LOG_MAXIMUM_BYTES, backupCount=LOG_BACKUP_COUNT
    )
    to_file.setFormatter(formatter)
    logger.addHandler(to_file)

    to_console = logging.StreamHandler()
    to_console.setFormatter(formatter)
    logger.addHandler(to_console)

    logger.propagate = False
    return logger


class Daemon:
    def __init__(
        self,
        target: DeviceConfig,
        logger: logging.Logger,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        usage_fetch_interval: float = USAGE_FETCH_INTERVAL_SECONDS,
        read_usage=usage_source.read_usage,
        read_local_usage=usage_source.read_local_usage,
        send_packet=transport.send_packet,
        clock=None,
    ) -> None:
        self.target = target
        self.logger = logger
        self.poll_interval = poll_interval
        self.usage_fetch_interval = usage_fetch_interval
        self.read_usage = read_usage
        self.read_local_usage = read_local_usage
        self.send_packet = send_packet
        self.clock = clock or __import__("time").monotonic
        self.stop_requested = threading.Event()
        self.last_snapshot: Optional[UsageSnapshot] = None
        self.last_payload: Optional[bytes] = None
        self.last_sent_at: Optional[float] = None
        self.consecutive_usage_failures = 0
        self.next_usage_fetch_at: Optional[float] = None

    def request_stop(self, *arguments) -> None:
        self.stop_requested.set()

    def usage_fetch_is_due(self) -> bool:
        return self.next_usage_fetch_at is None or self.clock() >= self.next_usage_fetch_at

    def held_snapshot(self) -> Optional[UsageSnapshot]:
        if self.last_snapshot is None:
            return None
        if self.consecutive_usage_failures:
            return self.last_snapshot.marked_stale()
        return self.last_snapshot

    def pause_usage_requests(self, seconds: float) -> None:
        self.next_usage_fetch_at = self.clock() + seconds

    def local_snapshot(self) -> Optional[UsageSnapshot]:
        try:
            snapshot = self.read_local_usage()
        except Exception:
            return None
        if snapshot is None or snapshot.stale:
            return None
        return snapshot

    def current_snapshot(self) -> Optional[UsageSnapshot]:
        if not self.usage_fetch_is_due():
            local = self.local_snapshot()
            if local is not None:
                self.last_snapshot = local
                return local
            return self.held_snapshot()
        try:
            snapshot = self.read_usage()
        except usage_source.RateLimited as failure:
            self.consecutive_usage_failures += 1
            self.pause_usage_requests(failure.retry_after)
            self.logger.warning(
                "usage endpoint rate limited, pausing requests for %ds",
                int(failure.retry_after),
            )
            return self.held_snapshot()
        except usage_source.UsageError as failure:
            self.consecutive_usage_failures += 1
            first_failure = self.consecutive_usage_failures == 1
            heartbeat_due = self.consecutive_usage_failures % FAILURE_HEARTBEAT_EVERY == 0
            if first_failure:
                level = self.logger.warning
            elif heartbeat_due:
                level = self.logger.info
            else:
                level = self.logger.debug
            level(
                "usage unavailable (%s, attempt %d): %s",
                type(failure).__name__,
                self.consecutive_usage_failures,
                failure,
            )
            self.pause_usage_requests(self.usage_fetch_interval)
            return self.held_snapshot()
        self.pause_usage_requests(self.usage_fetch_interval)
        if self.consecutive_usage_failures:
            self.logger.info(
                "usage available again after %d failed attempt(s)",
                self.consecutive_usage_failures,
            )
            self.consecutive_usage_failures = 0
        self.last_snapshot = snapshot
        return snapshot

    def payload_is_due(self, payload: bytes) -> bool:
        if payload != self.last_payload:
            return True
        if self.last_sent_at is None:
            return True
        return (self.clock() - self.last_sent_at) >= FORCED_RESEND_SECONDS

    def tick(self) -> bool:
        snapshot = self.current_snapshot()
        if snapshot is None:
            image = renderer.render_unavailable()
            description = "no usage data, showing the unavailable frame"
        else:
            image = renderer.render(snapshot)
            description = "session %.1f%% weekly %.1f%%%s" % (
                snapshot.session_pct,
                snapshot.weekly_pct,
                " (stale)" if snapshot.stale else "",
            )

        payload = protocol.image_packet(image)
        if not self.payload_is_due(payload):
            self.logger.debug("frame unchanged, nothing to send")
            return True

        try:
            written = self.send_packet(self.target.mac, self.target.channel, payload)
        except transport.TransportError as failure:
            self.logger.warning("could not reach the display: %s", failure)
            return False

        self.last_payload = payload
        self.last_sent_at = self.clock()
        self.logger.info("%s, %d bytes sent", description, written)
        return True

    def wait(self, seconds: float) -> None:
        self.stop_requested.wait(seconds)

    def run(self) -> int:
        self.logger.info(
            "starting, target %s channel %d, redrawing every %.0fs, "
            "asking the usage endpoint at most every %.0fs",
            self.target.mac,
            self.target.channel,
            self.poll_interval,
            self.usage_fetch_interval,
        )
        backoff = INITIAL_BACKOFF_SECONDS
        while not self.stop_requested.is_set():
            try:
                delivered = self.tick()
            except Exception:
                self.logger.exception("unexpected failure in the poll loop")
                delivered = False
            if delivered:
                backoff = INITIAL_BACKOFF_SECONDS
                delay = self.poll_interval
            else:
                delay = backoff
                backoff = min(backoff * 2.0, MAXIMUM_BACKOFF_SECONDS)
                self.logger.info("retrying in %.0fs", delay)
            self.wait(delay)
        self.logger.info("stopped")
        return 0


def run_daemon(target: DeviceConfig, poll_interval: float = POLL_INTERVAL_SECONDS,
               verbose: bool = False) -> int:
    logger = build_logger(verbose=verbose)
    daemon = Daemon(target, logger, poll_interval=poll_interval)
    for received in (signal.SIGINT, signal.SIGTERM):
        signal.signal(received, daemon.request_stop)
    return daemon.run()
