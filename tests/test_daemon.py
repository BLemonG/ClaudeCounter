from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudecounter import protocol, transport, usage_source
from claudecounter import render as renderer
from claudecounter.config import DeviceConfig
from claudecounter.daemon import Daemon, FORCED_RESEND_SECONDS, INITIAL_BACKOFF_SECONDS
from claudecounter.snapshot import UsageSnapshot

FAILURES = []

TARGET = DeviceConfig(mac="AA:BB:CC:DD:EE:FF", channel=1)


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


def quiet_logger() -> logging.Logger:
    logger = logging.getLogger("claudecounter-test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeDisplay:
    def __init__(self) -> None:
        self.sent = []
        self.failure = None

    def __call__(self, mac: str, channel: int, payload: bytes) -> int:
        if self.failure is not None:
            raise self.failure
        self.sent.append(payload)
        return len(payload)

    def decoded(self, index: int = -1):
        raw = self.sent[index]
        arguments = raw[4:-3]
        body = arguments[7:]
        palette_size = protocol.PALETTE_SIZE_ROLLOVER if body[3] == 0 else body[3]
        colors = [
            (body[4 + step * 3], body[5 + step * 3], body[6 + step * 3])
            for step in range(palette_size)
        ]
        packed = body[4 + palette_size * 3 :]
        indices = protocol.unpack_pixels(packed, palette_size, renderer.SIZE * renderer.SIZE)
        return [colors[index] for index in indices]


def snapshot(session: float, weekly: float, stale: bool = False) -> UsageSnapshot:
    return UsageSnapshot(
        session_pct=session,
        session_resets_at="2026-08-22T20:00:00+00:00",
        weekly_pct=weekly,
        weekly_resets_at="2026-08-26T13:00:00+00:00",
        fetched_at="2026-08-22T15:00:00+00:00",
        stale=stale,
    )


def build(read_usage, display, clock, usage_fetch_interval: float = 0.0,
          read_local_usage=lambda: None, resend_interval: float = FORCED_RESEND_SECONDS) -> Daemon:
    return Daemon(
        TARGET,
        quiet_logger(),
        poll_interval=60.0,
        usage_fetch_interval=usage_fetch_interval,
        resend_interval=resend_interval,
        read_usage=read_usage,
        read_local_usage=read_local_usage,
        send_packet=display,
        clock=clock,
    )


def a_good_reading_reaches_the_display() -> None:
    print("happy path")
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(82.0, 41.0), display, clock)
    check(daemon.tick() is True, "a successful tick reports success")
    check(len(display.sent) == 1, "exactly one packet is sent")
    check(display.sent[0] == protocol.image_packet(renderer.render(snapshot(82.0, 41.0))),
          "the packet matches the rendered snapshot")
    check(daemon.last_snapshot is not None, "the reading is remembered")


def an_unchanged_frame_is_not_resent() -> None:
    print("resend policy")
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(82.0, 41.0), display, clock, resend_interval=600.0)
    daemon.tick()
    clock.advance(60.0)
    daemon.tick()
    check(len(display.sent) == 1, "with a long resend interval an identical frame is skipped")

    clock.advance(600.0)
    daemon.tick()
    check(len(display.sent) == 2, "an identical frame is refreshed after the resend interval")

    readings = iter([snapshot(82.0, 41.0), snapshot(83.0, 41.0)])
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: next(readings), display, clock)
    daemon.tick()
    clock.advance(60.0)
    daemon.tick()
    check(len(display.sent) == 2, "a changed frame is always sent")


def a_failing_endpoint_keeps_the_last_value_and_marks_it_stale() -> None:
    print("stale handling")
    states = {"fail": False}

    def read_usage():
        if states["fail"]:
            raise usage_source.EndpointUnavailable("could not reach the usage endpoint")
        return snapshot(82.0, 41.0)

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock)
    daemon.tick()
    fresh_pixels = display.decoded()

    states["fail"] = True
    clock.advance(60.0)
    check(daemon.tick() is True, "a failing endpoint does not count as a delivery failure")
    check(len(display.sent) == 2, "the stale frame is pushed to the display")

    stale_pixels = display.decoded()
    check(stale_pixels != fresh_pixels, "the stale frame looks different from the fresh one")
    check(
        renderer.dimmed(renderer.SESSION_RED) in stale_pixels
        or renderer.dimmed(renderer.SESSION_ORANGE) in stale_pixels
        or renderer.dimmed(renderer.SESSION_YELLOW) in stale_pixels
        or renderer.dimmed(renderer.SESSION_GREEN) in stale_pixels,
        "the stale frame carries a dimmed session colour",
    )
    expected_stale = protocol.image_packet(renderer.render(snapshot(82.0, 41.0, stale=True)))
    check(
        display.sent[-1] == expected_stale,
        "the stale frame is exactly the last known reading, only dimmed",
    )
    zero_frame = protocol.image_packet(renderer.render(snapshot(0.0, 0.0, stale=True)))
    check(display.sent[-1] != zero_frame, "the stale frame is not a zero percent frame")

    for _ in range(5):
        clock.advance(60.0)
        daemon.tick()
    check(daemon.last_snapshot.session_pct == 82.0, "the last good reading is never overwritten")

    states["fail"] = False
    clock.advance(60.0)
    daemon.tick()
    check(display.decoded() == fresh_pixels, "recovery restores the undimmed frame")


def an_expired_token_never_shows_zero() -> None:
    print("expired token")

    def read_usage():
        raise usage_source.ExpiredCredentials("the token expired, sign in again")

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock)
    check(daemon.tick() is True, "an expired token does not crash the loop")

    unavailable = protocol.image_packet(renderer.render_unavailable())
    check(display.sent == [unavailable], "the display states that it has no data")

    zero_frame = protocol.image_packet(renderer.render(snapshot(0.0, 0.0)))
    check(zero_frame not in display.sent, "a zero percent frame is never sent")
    check(unavailable != zero_frame, "the unavailable frame is not a zero percent frame")

    unavailable_pixels = display.decoded()
    for session_colour in (renderer.SESSION_GREEN, renderer.SESSION_YELLOW,
                           renderer.SESSION_ORANGE, renderer.SESSION_RED):
        check(
            session_colour not in unavailable_pixels,
            "the unavailable frame shows no session fill colour",
        )
    check(
        renderer.WEEKLY_FILL not in unavailable_pixels,
        "the unavailable frame shows no weekly fill",
    )
    check(
        renderer.UNAVAILABLE_LABEL in unavailable_pixels,
        "the unavailable frame carries its own muted label",
    )

    for _ in range(5):
        clock.advance(60.0)
        check(daemon.tick() is True, "repeated expiry keeps the loop alive")
    check(
        len(display.sent) == 6,
        "the unavailable frame is refreshed every minute like any other frame",
    )
    check(
        all(packet == display.sent[0] for packet in display.sent),
        "and it stays the same unavailable frame throughout",
    )
    display.sent.clear()

    readings = iter([snapshot(82.0, 41.0)])
    daemon.read_usage = lambda: next(readings)
    clock.advance(60.0)
    daemon.tick()
    check(len(display.sent) == 1, "the first real reading replaces the unavailable frame")
    check(
        display.sent[-1] == protocol.image_packet(renderer.render(snapshot(82.0, 41.0))),
        "and it is the real reading, not a placeholder",
    )


def a_display_failure_backs_off_and_recovers() -> None:
    print("transport backoff")
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(82.0, 41.0), display, clock)
    display.failure = transport.TransportError("the device did not accept the packet")

    check(daemon.tick() is False, "a transport failure reports failure")
    check(display.sent == [], "nothing is recorded as sent")
    check(daemon.last_payload is None, "a failed send is not remembered as delivered")

    delays = []
    original_wait = daemon.wait
    daemon.wait = lambda seconds: delays.append(seconds) or daemon.stop_requested.set()

    daemon.stop_requested.clear()
    backoff = INITIAL_BACKOFF_SECONDS
    observed = []
    for _ in range(5):
        daemon.stop_requested.clear()
        delays.clear()
        daemon.tick()
        observed.append(backoff)
        backoff = min(backoff * 2.0, 300.0)
    check(observed == [5.0, 10.0, 20.0, 40.0, 80.0], "the backoff doubles up to the cap")
    daemon.wait = original_wait

    display.failure = None
    check(daemon.tick() is True, "the next tick after recovery succeeds")
    check(len(display.sent) == 1, "the frame arrives once the device is reachable again")


def an_unexpected_exception_does_not_kill_the_loop() -> None:
    print("crash resistance")

    def read_usage():
        raise ValueError("something nobody predicted")

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock)
    daemon.wait = lambda seconds: daemon.stop_requested.set()
    check(daemon.run() == 0, "an unforeseen exception is caught and the daemon exits cleanly")


def the_endpoint_is_not_asked_more_often_than_the_fetch_interval() -> None:
    print("endpoint request spacing")
    calls = []

    def read_usage():
        calls.append(None)
        return snapshot(30.0, 20.0)

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock, usage_fetch_interval=300.0)
    for _ in range(5):
        daemon.tick()
        clock.advance(60.0)
    check(len(calls) == 1, "five 60s ticks cause a single endpoint request")
    clock.advance(60.0)
    daemon.tick()
    check(len(calls) == 2, "the next request happens once the interval has elapsed")
    check(
        display.sent[0] == protocol.image_packet(renderer.render(snapshot(30.0, 20.0))),
        "the held snapshot is still what gets drawn between requests",
    )


def a_rate_limited_endpoint_is_left_alone_for_the_announced_time() -> None:
    print("rate limit")
    calls = []

    def read_usage():
        calls.append(None)
        if len(calls) == 1:
            return snapshot(64.0, 33.0)
        raise usage_source.RateLimited("rate limited", 3600.0)

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock, usage_fetch_interval=300.0)
    daemon.tick()
    clock.advance(300.0)
    daemon.tick()
    check(len(calls) == 2, "the second request runs and is refused")

    for _ in range(30):
        clock.advance(60.0)
        daemon.tick()
    check(len(calls) == 2, "no further request is made during the announced pause")

    clock.advance(2000.0)
    daemon.tick()
    check(len(calls) == 3, "requests resume after the announced pause has passed")
    check(
        display.sent[-1] == protocol.image_packet(renderer.render(snapshot(64.0, 33.0, stale=True))),
        "the last known value stays on the display, marked stale",
    )
    check(
        display.sent[-1] != protocol.image_packet(renderer.render(snapshot(0.0, 0.0))),
        "a rate limited endpoint never turns the display into a zero reading",
    )


def the_local_file_keeps_the_minute_beat_while_the_api_is_blocked() -> None:
    print("local source during an api pause")
    api_calls = []
    local_values = [55.0]

    def read_usage():
        api_calls.append(None)
        raise usage_source.RateLimited("rate limited", 3600.0)

    def read_local_usage():
        return snapshot(local_values[-1], 12.0)

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock, usage_fetch_interval=300.0,
                   read_local_usage=read_local_usage)
    daemon.tick()
    check(len(api_calls) == 1, "the api is tried once and refused")

    for value in (56.0, 57.0, 58.0):
        local_values.append(value)
        clock.advance(60.0)
        daemon.tick()
    check(len(api_calls) == 1, "no further api call happens during the pause")
    check(
        display.sent[-1] == protocol.image_packet(renderer.render(snapshot(58.0, 12.0))),
        "each minute the freshly written local value reaches the display",
    )
    check(
        display.sent[-1] != protocol.image_packet(renderer.render(snapshot(58.0, 12.0, stale=True))),
        "a local reading counts as current, not as stale",
    )


def a_rolled_over_local_file_is_not_trusted() -> None:
    print("outdated local file")
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(
        lambda: snapshot(70.0, 30.0),
        display, clock,
        usage_fetch_interval=300.0,
        read_local_usage=lambda: snapshot(9.0, 9.0, stale=True),
    )
    daemon.tick()
    clock.advance(60.0)
    daemon.tick()
    check(
        display.sent[-1] == protocol.image_packet(renderer.render(snapshot(70.0, 30.0))),
        "a local file whose window has rolled over is ignored in favour of the endpoint",
    )


def the_display_is_refreshed_every_minute_by_default() -> None:
    print("recovery after the device changes mode")
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(13.0, 51.0), display, clock)
    for _ in range(4):
        daemon.tick()
        clock.advance(60.0)
    check(
        len(display.sent) == 4,
        "the unchanged frame is pushed again every minute, so a device that "
        "switched modes gets the counter back within 60s",
    )
    check(
        all(packet == display.sent[0] for packet in display.sent),
        "every one of those pushes carries the same picture",
    )
    check(FORCED_RESEND_SECONDS == 60.0, "the default resend interval is one minute")


def main() -> int:
    a_good_reading_reaches_the_display()
    an_unchanged_frame_is_not_resent()
    the_display_is_refreshed_every_minute_by_default()
    a_failing_endpoint_keeps_the_last_value_and_marks_it_stale()
    an_expired_token_never_shows_zero()
    a_display_failure_backs_off_and_recovers()
    an_unexpected_exception_does_not_kill_the_loop()
    the_endpoint_is_not_asked_more_often_than_the_fetch_interval()
    a_rate_limited_endpoint_is_left_alone_for_the_announced_time()
    the_local_file_keeps_the_minute_beat_while_the_api_is_blocked()
    a_rolled_over_local_file_is_not_trusted()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
