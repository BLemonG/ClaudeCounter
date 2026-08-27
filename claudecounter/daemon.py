from __future__ import annotations

import json
import logging
import logging.handlers
import signal
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from . import attention
from . import protocol
from . import render as renderer
from . import transport
from . import usage_source
from . import dayhours, weekdays
from .config import DeviceConfig
from .snapshot import UsageSnapshot, utc_now_iso

POLL_INTERVAL_SECONDS = 60.0
USAGE_FETCH_INTERVAL_SECONDS = 120.0
MINIMUM_FETCH_SPACING_SECONDS = 90.0
INITIAL_BACKOFF_SECONDS = 5.0
MAXIMUM_BACKOFF_SECONDS = 300.0
FORCED_RESEND_SECONDS = 60.0
ATTENTION_POLL_SECONDS = 5.0
FAILURE_HEARTBEAT_EVERY = 60
STALE_AFTER_SECONDS = 10 * 60
RECALL_MAX_AGE_SECONDS = 24 * 60 * 60

PUBLISHED_STATE_PATH = attention.ATTENTION_DIRECTORY / "state.json"
BRIGHTNESS_PATH = attention.ATTENTION_DIRECTORY / "brightness"
ACTIVE_DAYS_PATH = weekdays.ACTIVE_DAYS_PATH
ACTIVE_HOURS_PATH = dayhours.ACTIVE_HOURS_PATH

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
        resend_interval: float = FORCED_RESEND_SECONDS,
        attention_poll_interval: float = ATTENTION_POLL_SECONDS,
        minimum_fetch_spacing: float = MINIMUM_FETCH_SPACING_SECONDS,
        stale_after: float = STALE_AFTER_SECONDS,
        published_state_path: Path = PUBLISHED_STATE_PATH,
        brightness_path: Path = BRIGHTNESS_PATH,
        active_days_path: Path = ACTIVE_DAYS_PATH,
        active_hours_path: Path = ACTIVE_HOURS_PATH,
        read_usage=usage_source.read_usage,
        read_local_usage=usage_source.read_local_usage,
        a_session_is_waiting=attention.a_session_is_waiting,
        refresh_requested=attention.refresh_requested,
        consume_refresh=attention.consume_refresh,
        send_packets=transport.send_packets,
        clock=None,
    ) -> None:
        self.target = target
        self.logger = logger
        self.poll_interval = poll_interval
        self.usage_fetch_interval = usage_fetch_interval
        self.resend_interval = resend_interval
        self.attention_poll_interval = attention_poll_interval
        self.minimum_fetch_spacing = minimum_fetch_spacing
        self.stale_after = stale_after
        self.published_state_path = published_state_path
        self.brightness_path = brightness_path
        self.active_days_path = active_days_path
        self.active_hours_path = active_hours_path
        self.applied_brightness: Optional[int] = None
        self.drawn_active_days: Optional[frozenset] = None
        self.drawn_active_hours = None
        self.read_usage = read_usage
        self.read_local_usage = read_local_usage
        self.a_session_is_waiting = a_session_is_waiting
        self.refresh_requested = refresh_requested
        self.consume_refresh = consume_refresh
        self.send_packets = send_packets
        self.clock = clock or __import__("time").monotonic
        self.stop_requested = threading.Event()
        self.last_snapshot: Optional[UsageSnapshot] = None
        self.last_snapshot_at: Optional[float] = None
        self.last_payloads: Optional[List[bytes]] = None
        self.last_sent_at: Optional[float] = None
        self.consecutive_usage_failures = 0
        self.last_trouble: Optional[str] = None
        self.last_trouble_reason: Optional[str] = None
        self.next_usage_fetch_at: Optional[float] = None
        self.last_usage_fetch_at: Optional[float] = None

    def request_stop(self, *arguments) -> None:
        self.stop_requested.set()

    def spacing_allows_a_fetch(self) -> bool:
        if self.last_usage_fetch_at is None:
            return True
        return (self.clock() - self.last_usage_fetch_at) >= self.minimum_fetch_spacing

    def a_turn_asked_for_fresh_numbers(self, peek_only: bool = False) -> bool:
        try:
            if peek_only:
                return bool(self.refresh_requested())
            return bool(self.consume_refresh())
        except Exception:
            return False

    def usage_fetch_is_due(self, peek_only: bool = False) -> bool:
        if self.next_usage_fetch_at is None:
            return True
        if self.clock() >= self.next_usage_fetch_at:
            return True
        if not self.spacing_allows_a_fetch():
            return False
        return self.a_turn_asked_for_fresh_numbers(peek_only)

    def age_of(self, moment: Optional[str]) -> Optional[float]:
        parsed = renderer.parse_timestamp(moment)
        if parsed is None:
            return None
        return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())

    def recall_published_reading(self) -> None:
        try:
            published = json.loads(self.published_state_path.read_text())
        except (OSError, ValueError):
            return
        if not isinstance(published, dict) or "session_pct" not in published:
            return
        try:
            remembered = UsageSnapshot.from_dict(published)
        except (TypeError, ValueError):
            return
        age = self.age_of(remembered.fetched_at)
        if age is None or age > RECALL_MAX_AGE_SECONDS:
            return
        self.remember_reading(remembered, age)
        self.logger.info(
            "carrying over the reading from %s, %d minute(s) old",
            remembered.fetched_at,
            int(age // 60),
        )

    def reading_is_old(self) -> bool:
        if self.last_snapshot_at is None:
            return True
        return (self.clock() - self.last_snapshot_at) >= self.stale_after

    def remember_reading(self, snapshot: UsageSnapshot, age: float = 0.0) -> None:
        self.last_snapshot = snapshot
        self.last_snapshot_at = self.clock() - age

    def held_snapshot(self) -> Optional[UsageSnapshot]:
        if self.last_snapshot is None:
            return None
        if self.reading_is_old():
            return self.last_snapshot.marked_stale()
        return self.last_snapshot

    def wanted_brightness(self) -> Optional[int]:
        try:
            digits = self.brightness_path.read_text().strip()
        except OSError:
            return None
        try:
            return max(0, min(100, int(digits)))
        except ValueError:
            return None

    def brightness_is_due(self) -> bool:
        wanted = self.wanted_brightness()
        return wanted is not None and wanted != self.applied_brightness

    def wanted_active_days(self):
        return weekdays.load_active_days(self.active_days_path)

    def active_days_changed(self) -> bool:
        if self.drawn_active_days is None:
            return False
        return self.wanted_active_days() != self.drawn_active_days

    def wanted_active_hours(self):
        return dayhours.load_active_hours(self.active_hours_path)

    def active_hours_changed(self) -> bool:
        if self.drawn_active_hours is None:
            return False
        return self.wanted_active_hours() != self.drawn_active_hours

    def remember_trouble(self, failure: Exception) -> None:
        self.last_trouble = type(failure).__name__
        self.last_trouble_reason = str(failure)

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
                self.remember_reading(local)
                return local
            return self.held_snapshot()
        self.last_usage_fetch_at = self.clock()
        self.a_turn_asked_for_fresh_numbers()
        try:
            snapshot = self.read_usage()
        except usage_source.RateLimited as failure:
            self.consecutive_usage_failures += 1
            self.remember_trouble(failure)
            self.pause_usage_requests(failure.retry_after)
            self.logger.warning(
                "usage endpoint rate limited, pausing requests for %ds",
                int(failure.retry_after),
            )
            return self.held_snapshot()
        except usage_source.UsageError as failure:
            self.consecutive_usage_failures += 1
            self.remember_trouble(failure)
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
        self.last_trouble = None
        self.last_trouble_reason = None
        self.remember_reading(snapshot)
        return snapshot

    def payloads_are_due(self, payloads: List[bytes]) -> bool:
        if payloads != self.last_payloads:
            return True
        if self.last_sent_at is None:
            return True
        return (self.clock() - self.last_sent_at) >= self.resend_interval

    def attention_is_wanted(self) -> bool:
        try:
            return bool(self.a_session_is_waiting())
        except Exception:
            return False

    def frames_to_send(
        self,
        snapshot: Optional[UsageSnapshot],
        waiting: bool,
        active_days=None,
        active_hours=None,
    ):
        if snapshot is None:
            description = "no usage data, showing the unavailable frame"
            if waiting:
                return protocol.animation_packets(
                    renderer.breathing_unavailable_frames()
                ), description + ", breathing"
            return [protocol.image_packet(renderer.render_unavailable())], description
        description = "session %.1f%% weekly %.1f%%%s" % (
            snapshot.session_pct,
            snapshot.weekly_pct,
            " (stale)" if snapshot.stale else "",
        )
        if waiting:
            return protocol.animation_packets(
                renderer.breathing_frames(
                    snapshot, active_days=active_days, active_hours=active_hours
                )
            ), description + ", a session is waiting for input"
        return [
            protocol.image_packet(
                renderer.render(
                    snapshot, active_days=active_days, active_hours=active_hours
                )
            )
        ], description

    def publish_snapshot(self, snapshot: Optional[UsageSnapshot]) -> None:
        try:
            self.published_state_path.parent.mkdir(parents=True, exist_ok=True)
            published = dict(snapshot.to_dict()) if snapshot is not None else {}
            published["trouble"] = self.last_trouble
            published["trouble_reason"] = self.last_trouble_reason
            published["written_at"] = utc_now_iso()
            beside = self.published_state_path.with_name(
                self.published_state_path.name + ".writing"
            )
            beside.write_text(json.dumps(published, indent=2, sort_keys=True) + "\n")
            beside.replace(self.published_state_path)
        except OSError:
            self.logger.debug("could not publish the current reading")

    def tick(self) -> bool:
        snapshot = self.current_snapshot()
        self.publish_snapshot(snapshot)
        waiting = self.attention_is_wanted()
        active_days = self.wanted_active_days()
        if self.drawn_active_days is not None and active_days != self.drawn_active_days:
            self.logger.info(
                "the weekly marker now counts %s", weekdays.named(active_days)
            )
        self.drawn_active_days = active_days
        active_hours = self.wanted_active_hours()
        if (
            self.drawn_active_hours is not None
            and active_hours != self.drawn_active_hours
        ):
            self.logger.info(
                "the weekly marker now counts %s of each day",
                dayhours.spelled(active_hours),
            )
        self.drawn_active_hours = active_hours
        frames, description = self.frames_to_send(
            snapshot, waiting, active_days, active_hours
        )

        wanted = self.wanted_brightness()
        turning_the_lamp = wanted is not None and wanted != self.applied_brightness
        if turning_the_lamp:
            payloads = [protocol.brightness_packet(wanted)] + frames
            description += f", brightness {wanted}"
        elif self.payloads_are_due(frames):
            payloads = frames
        else:
            self.logger.debug("frame unchanged, nothing to send")
            return True

        try:
            written = self.send_packets(self.target.mac, self.target.channel, payloads)
        except transport.TransportError as failure:
            self.logger.warning("could not reach the display: %s", failure)
            return False

        if turning_the_lamp:
            self.applied_brightness = wanted
        self.last_payloads = frames
        self.last_sent_at = self.clock()
        self.logger.info(
            "%s, %d packet(s) and %d bytes sent", description, len(payloads), written
        )
        return True

    def wait(self, seconds: float) -> None:
        known = self.attention_is_wanted()
        deadline = self.clock() + seconds
        while not self.stop_requested.is_set():
            remaining = deadline - self.clock()
            if remaining <= 0.0:
                return
            self.stop_requested.wait(min(self.attention_poll_interval, remaining))
            if self.attention_is_wanted() != known:
                return
            if self.usage_fetch_is_due(peek_only=True):
                return
            if self.brightness_is_due():
                return
            if self.active_days_changed():
                return
            if self.active_hours_changed():
                return

    def run(self) -> int:
        self.recall_published_reading()
        chosen_days = self.wanted_active_days()
        if not weekdays.counts_every_day(chosen_days):
            self.logger.info(
                "the weekly marker counts %s only", weekdays.named(chosen_days)
            )
        chosen_hours = self.wanted_active_hours()
        if not dayhours.covers_whole_day(chosen_hours):
            self.logger.info(
                "the weekly marker counts %s of each day only",
                dayhours.spelled(chosen_hours),
            )
        self.logger.info(
            "starting, target %s channel %d, redrawing every %.0fs, "
            "asking the usage endpoint at most every %.0fs, "
            "watching for waiting sessions every %.0fs, "
            "and asking early when a turn ends, never closer than %.0fs",
            self.target.mac,
            self.target.channel,
            self.poll_interval,
            self.usage_fetch_interval,
            self.attention_poll_interval,
            self.minimum_fetch_spacing,
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
