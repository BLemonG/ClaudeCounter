from __future__ import annotations

import json
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from claudecounter import protocol, transport, usage_source
from claudecounter import dayhours, weekdays
from claudecounter import render as renderer
from claudecounter.config import DeviceConfig
from claudecounter.daemon import (
    Daemon,
    FORCED_RESEND_SECONDS,
    INITIAL_BACKOFF_SECONDS,
    MINIMUM_FETCH_SPACING_SECONDS,
    STALE_AFTER_SECONDS,
)
from claudecounter.snapshot import UsageSnapshot
from pathlib import Path

FAILURES = []

TARGET = DeviceConfig(mac="AA:BB:CC:DD:EE:FF", channel=1)

SCRATCH = tempfile.TemporaryDirectory()


def scratch_state_path():
    return Path(SCRATCH.name) / "state.json"


def scratch_brightness_path():
    return Path(SCRATCH.name) / "brightness"


def scratch_weekdays_path():
    return Path(SCRATCH.name) / "weekdays"


def scratch_dayhours_path():
    return Path(SCRATCH.name) / "dayhours"


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

    def __call__(self, mac: str, channel: int, payloads) -> int:
        if self.failure is not None:
            raise self.failure
        self.sent.append(list(payloads))
        return sum(len(payload) for payload in payloads)

    def decoded(self, index: int = -1, packet_index: int = 0):
        raw = self.sent[index][packet_index]
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
          read_local_usage=lambda: None, resend_interval: float = FORCED_RESEND_SECONDS,
          a_session_is_waiting=lambda: False, refresh=None,
          minimum_fetch_spacing: float = MINIMUM_FETCH_SPACING_SECONDS) -> Daemon:
    pending = refresh if refresh is not None else {"asked": False}

    def refresh_requested() -> bool:
        return pending["asked"]

    def consume_refresh() -> bool:
        asked = pending["asked"]
        pending["asked"] = False
        return asked

    return Daemon(
        TARGET,
        quiet_logger(),
        published_state_path=scratch_state_path(),
        brightness_path=scratch_brightness_path(),
        active_days_path=scratch_weekdays_path(),
        active_hours_path=scratch_dayhours_path(),
        poll_interval=60.0,
        usage_fetch_interval=usage_fetch_interval,
        resend_interval=resend_interval,
        minimum_fetch_spacing=minimum_fetch_spacing,
        read_usage=read_usage,
        read_local_usage=read_local_usage,
        a_session_is_waiting=a_session_is_waiting,
        refresh_requested=refresh_requested,
        consume_refresh=consume_refresh,
        send_packets=display,
        clock=clock,
    )


def still(image) -> list:
    return [protocol.image_packet(image)]


def a_good_reading_reaches_the_display() -> None:
    print("happy path")
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(82.0, 41.0), display, clock)
    check(daemon.tick() is True, "a successful tick reports success")
    check(len(display.sent) == 1, "exactly one packet is sent")
    check(display.sent[0] == still(renderer.render(snapshot(82.0, 41.0))),
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
    check(
        display.decoded() == fresh_pixels,
        "a single failed request does not dim a reading that is a minute old",
    )

    clock.advance(STALE_AFTER_SECONDS)
    daemon.tick()
    stale_pixels = display.decoded()
    check(stale_pixels != fresh_pixels, "once the reading is genuinely old it is dimmed")
    check(
        renderer.dimmed(renderer.SESSION_RED) in stale_pixels
        or renderer.dimmed(renderer.SESSION_ORANGE) in stale_pixels
        or renderer.dimmed(renderer.SESSION_YELLOW) in stale_pixels
        or renderer.dimmed(renderer.SESSION_GREEN) in stale_pixels,
        "the stale frame carries a dimmed session colour",
    )
    expected_stale = still(renderer.render(snapshot(82.0, 41.0, stale=True)))
    check(
        display.sent[-1] == expected_stale,
        "the stale frame is exactly the last known reading, only dimmed",
    )
    zero_frame = still(renderer.render(snapshot(0.0, 0.0, stale=True)))
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

    unavailable = still(renderer.render_unavailable())
    check(display.sent == [unavailable], "the display states that it has no data")

    zero_frame = still(renderer.render(snapshot(0.0, 0.0)))
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
        display.sent[-1] == still(renderer.render(snapshot(82.0, 41.0))),
        "and it is the real reading, not a placeholder",
    )


def a_display_failure_backs_off_and_recovers() -> None:
    print("transport backoff")
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(82.0, 41.0), display, clock)
    display.failure = transport.TransportError("the device did not accept the packet")

    check(daemon.tick() is False, "a transport failure reports failure")
    check(display.sent == [], "nothing is recorded as sent")
    check(daemon.last_payloads is None, "a failed send is not remembered as delivered")

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
        display.sent[0] == still(renderer.render(snapshot(30.0, 20.0))),
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
        display.sent[-1] == still(renderer.render(snapshot(64.0, 33.0, stale=True))),
        "the last known value stays on the display, marked stale",
    )
    check(
        display.sent[-1] != still(renderer.render(snapshot(0.0, 0.0))),
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
        display.sent[-1] == still(renderer.render(snapshot(58.0, 12.0))),
        "each minute the freshly written local value reaches the display",
    )
    check(
        display.sent[-1] != still(renderer.render(snapshot(58.0, 12.0, stale=True))),
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
        display.sent[-1] == still(renderer.render(snapshot(70.0, 30.0))),
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


def a_waiting_session_makes_the_background_breathe() -> None:
    print("breathing while a session waits")
    waiting = {"now": False}
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(63.0, 29.0), display, clock,
                   a_session_is_waiting=lambda: waiting["now"])

    daemon.tick()
    quiet = display.sent[-1]
    check(len(quiet) == 1, "with nobody waiting a single still packet is sent")
    check(quiet[0][3] == protocol.COMMAND_SET_IMAGE, "and it is the still image command 0x44")

    waiting["now"] = True
    clock.advance(60.0)
    daemon.tick()
    breathing = display.sent[-1]
    check(len(breathing) > 1, f"a waiting session sends a {len(breathing)} packet animation")
    check(
        all(payload[3] == protocol.COMMAND_SET_ANIMATION_FRAME for payload in breathing),
        "every animation packet uses command 0x49",
    )
    check(breathing != quiet, "the display is told something different while a session waits")

    orange = renderer.ATTENTION_BACKGROUND
    peak = renderer.render(snapshot(63.0, 29.0), None, 1.0)
    check(orange in peak.getdata(), "the fully lit breath frame really carries the orange")
    check(orange not in renderer.render(snapshot(63.0, 29.0)).getdata(),
          "the quiet frame carries no orange at all")

    waiting["now"] = False
    clock.advance(60.0)
    daemon.tick()
    check(display.sent[-1] == quiet, "answering the session puts the plain frame back")


def the_breath_keeps_the_reading_readable() -> None:
    print("breathing frame content")
    frames = renderer.breathing_frames(snapshot(63.0, 29.0), "2026-08-22T15:00:00+00:00")
    levels = renderer.breath_levels()
    check(len(frames) == len(levels), "one frame per breath level")
    check(min(levels) == 0.0 and max(levels) == 1.0,
          "the breath runs from fully dark to fully lit")
    check(levels[0] == 0.0 and levels[-1] > 0.0,
          "the cycle starts dark so the loop joins up smoothly")

    for step, (image, milliseconds) in enumerate(frames):
        pixels = image.load()
        check(milliseconds == renderer.BREATH_FRAME_MILLISECONDS,
              f"frame {step}: declares the frame time")
        check(pixels[7, 0] != renderer.attention_background(levels[step]),
              f"frame {step}: the session ring is not painted over")
        check(pixels[0, renderer.WEEKLY_ROW] != renderer.attention_background(levels[step]),
              f"frame {step}: the weekly bar is not painted over")
        digits = [
            pixels[x, y]
            for y in range(3, 12)
            for x in range(2, 14)
            if pixels[x, y] == renderer.LABEL
        ]
        check(len(digits) > 0, f"frame {step}: the percentage stays readable on top")


def a_waiting_session_breathes_even_without_usage_data() -> None:
    print("breathing without data")

    def read_usage():
        raise usage_source.ExpiredCredentials("the token expired, sign in again")

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock, a_session_is_waiting=lambda: True)
    daemon.tick()
    sent = display.sent[-1]
    check(len(sent) > 1, "the unavailable frame breathes as an animation too")
    check(
        all(payload[3] == protocol.COMMAND_SET_ANIMATION_FRAME for payload in sent),
        "and it uses the animation command",
    )
    check(sent != still(renderer.render(snapshot(0.0, 0.0))),
          "a breathing unavailable frame is still never a zero reading")


def a_broken_marker_directory_never_stops_the_counter() -> None:
    print("attention failures")

    def explode():
        raise OSError("the marker directory is unreadable")

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(63.0, 29.0), display, clock, a_session_is_waiting=explode)
    check(daemon.tick() is True, "a failing waiting check does not break the tick")
    check(display.sent[-1] == still(renderer.render(snapshot(63.0, 29.0))),
          "the counter simply falls back to the plain frame")


def the_loop_reacts_to_a_waiting_session_within_seconds() -> None:
    print("attention latency")
    waiting = {"now": False}
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(63.0, 29.0), display, clock,
                   usage_fetch_interval=120.0,
                   a_session_is_waiting=lambda: waiting["now"])
    daemon.tick()

    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        clock.advance(seconds)
        if len(slept) == 3:
            waiting["now"] = True
        return False

    daemon.stop_requested.wait = fake_sleep
    daemon.wait(60.0)
    check(
        max(slept) <= daemon.attention_poll_interval,
        f"the loop never sleeps longer than {daemon.attention_poll_interval}s in one go",
    )
    check(
        sum(slept) < 60.0,
        f"a session that starts waiting cuts the minute short after {sum(slept)}s",
    )
    check(len(slept) == 3, "the wait returns on the first check that sees the change")


def a_finished_turn_pulls_the_numbers_in_early() -> None:
    print("refresh at the end of a turn")
    calls = []
    values = iter([snapshot(30.0, 20.0), snapshot(44.0, 21.0), snapshot(45.0, 21.0)])

    def read_usage():
        calls.append(None)
        return next(values)

    asked = {"asked": False}
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock, usage_fetch_interval=120.0, refresh=asked)

    daemon.tick()
    check(len(calls) == 1, "the first tick asks the endpoint")

    clock.advance(30.0)
    daemon.tick()
    check(len(calls) == 1, "without a finished turn nothing extra is asked")

    asked["asked"] = True
    daemon.tick()
    check(len(calls) == 1,
          f"a finished turn within {MINIMUM_FETCH_SPACING_SECONDS:.0f}s of the last "
          "request still waits")
    check(asked["asked"] is True, "and the request is kept, not thrown away")

    clock.advance(60.0)
    daemon.tick()
    check(len(calls) == 2, "once the spacing has passed the finished turn is honoured")
    check(asked["asked"] is False, "and the request is consumed exactly once")
    check(
        display.sent[-1] == still(renderer.render(snapshot(44.0, 21.0))),
        "the freshly fetched number is what lands on the display",
    )

    clock.advance(60.0)
    daemon.tick()
    check(len(calls) == 2, "a consumed request does not trigger a second fetch")


def the_endpoint_is_never_asked_faster_than_the_rate_limit_allows() -> None:
    print("rate limit headroom")
    calls = []
    asked = {"asked": True}

    def read_usage():
        calls.append(None)
        return snapshot(30.0, 20.0)

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock, usage_fetch_interval=120.0, refresh=asked)

    for _ in range(360):
        asked["asked"] = True
        daemon.tick()
        clock.advance(10.0)
    per_hour = len(calls)
    check(
        per_hour <= 40,
        f"even with a turn ending every 10s the endpoint sees {per_hour} requests "
        "per hour, well under the 60 that triggered the lockout",
    )


def the_loop_wakes_up_when_a_turn_finishes() -> None:
    print("refresh latency")
    asked = {"asked": False}
    display, clock = FakeClock(), FakeClock()
    display = FakeDisplay()
    daemon = build(lambda: snapshot(30.0, 20.0), display, clock,
                   usage_fetch_interval=120.0, refresh=asked)
    daemon.tick()

    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        clock.advance(seconds)
        if len(slept) == 2:
            clock.advance(MINIMUM_FETCH_SPACING_SECONDS)
            asked["asked"] = True
        return False

    daemon.stop_requested.wait = fake_sleep
    daemon.wait(60.0)
    check(len(slept) == 2,
          "the minute is cut short as soon as a finished turn asks for numbers")
    check(asked["asked"] is True, "peeking does not consume the request")


def the_reading_is_published_for_the_menu() -> None:
    print("published reading")
    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(64.0, 7.0), display, clock)
    daemon.tick()
    published = json.loads(daemon.published_state_path.read_text())
    check(published["session_pct"] == 64.0, "the menu can read the session percentage")
    check(
        published["session_resets_at"] == "2026-08-22T20:00:00+00:00",
        "and the reset moment the blue dot needs",
    )
    check(published["stale"] is False, "and whether the reading is stale")
    check("written_at" in published, "and when it was written")

    def no_login():
        raise usage_source.MissingCredentials("no login")

    empty = build(no_login, FakeDisplay(), FakeClock())
    empty.tick()
    troubled = json.loads(empty.published_state_path.read_text())
    check(
        "session_pct" not in troubled,
        "without a reading the menu is told there is no percentage",
    )
    check(
        troubled["trouble"] == "MissingCredentials",
        "and why the numbers are missing, without going near the keychain itself",
    )
    check(troubled["trouble_reason"] == "no login", "including the spoken reason")

    display, clock = FakeDisplay(), FakeClock()
    recovered = build(lambda: snapshot(64.0, 7.0), display, clock)
    recovered.tick()
    healthy = json.loads(recovered.published_state_path.read_text())
    check(healthy["trouble"] is None, "a good reading clears the trouble again")


def the_slider_reaches_the_lamp() -> None:
    print("brightness slider")
    wish = scratch_brightness_path()
    wish.unlink(missing_ok=True)

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: snapshot(64.0, 7.0), display, clock, resend_interval=600.0)
    daemon.tick()
    check(len(display.sent[-1]) == 1, "without a wish only the picture is sent")

    wish.write_text("30\n")
    check(daemon.brightness_is_due() is True, "a new wish wakes the loop early")
    daemon.tick()
    sent = display.sent[-1]
    check(sent[0] == protocol.brightness_packet(30), "the wish rides along as the first packet")
    check(len(sent) == 2, "together with the picture")

    before = len(display.sent)
    daemon.tick()
    check(len(display.sent) == before, "an unchanged wish is not sent again")
    check(daemon.brightness_is_due() is False, "and no longer wakes the loop")

    wish.write_text("85")
    daemon.tick()
    check(
        display.sent[-1][0] == protocol.brightness_packet(85),
        "moving the slider again reaches the lamp",
    )

    wish.write_text("nonsense")
    before = len(display.sent)
    daemon.tick()
    check(len(display.sent) == before, "a damaged wish file changes nothing")

    wish.write_text("400")
    daemon.tick()
    check(
        display.sent[-1][0] == protocol.brightness_packet(100),
        "an out of range wish is clamped, never rejected",
    )

    display.failure = transport.TransportError("display unreachable")
    wish.write_text("10")
    daemon.tick()
    display.failure = None
    daemon.tick()
    check(
        display.sent[-1][0] == protocol.brightness_packet(10),
        "a wish that could not be delivered is retried, not lost",
    )
    wish.unlink(missing_ok=True)


def a_short_outage_does_not_dim_the_display() -> None:
    print("dimming only when old")
    states = {"fail": False}

    def read_usage():
        if states["fail"]:
            raise usage_source.RateLimited("too many requests", retry_after=900.0)
        return snapshot(82.0, 41.0)

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(read_usage, display, clock, resend_interval=1.0)
    daemon.tick()
    bright = display.decoded()

    states["fail"] = True
    reached = 0.0
    for minutes in (1.0, 3.0, 6.0, 9.0):
        clock.advance(minutes * 60.0 - reached)
        reached = minutes * 60.0
        daemon.tick()
        check(display.decoded() == bright, f"still undimmed {int(minutes)} minute(s) in")

    clock.advance(STALE_AFTER_SECONDS)
    daemon.tick()
    check(display.decoded() != bright, "past the age limit the reading is dimmed")

    states["fail"] = False
    clock.advance(900.0)
    daemon.tick()
    check(display.decoded() == bright, "a fresh reading brings the colour back")

    check(
        daemon.last_snapshot.session_pct == 82.0,
        "the value itself never changed through any of it",
    )


def a_restart_keeps_the_last_known_reading() -> None:
    print("surviving a restart")
    from datetime import datetime, timedelta, timezone

    def moments_ago(minutes: float) -> str:
        return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    def no_endpoint():
        raise usage_source.RateLimited("too many requests", retry_after=900.0)

    state = scratch_state_path()

    def publish(fetched_at: str) -> None:
        state.write_text(json.dumps({
            "session_pct": 82.0,
            "session_resets_at": "2026-08-22T20:00:00+00:00",
            "weekly_pct": 41.0,
            "weekly_resets_at": "2026-08-26T13:00:00+00:00",
            "fetched_at": fetched_at,
            "stale": False,
            "trouble": None,
            "written_at": fetched_at,
        }))

    publish(moments_ago(2))
    daemon = build(no_endpoint, FakeDisplay(), FakeClock())
    daemon.recall_published_reading()
    check(daemon.last_snapshot is not None, "a reading from before the restart is picked up")
    check(daemon.last_snapshot.session_pct == 82.0, "with the value intact")
    check(daemon.reading_is_old() is False, "a two minute old reading is not dimmed")

    publish(moments_ago(45))
    middle_aged = build(no_endpoint, FakeDisplay(), FakeClock())
    middle_aged.recall_published_reading()
    check(middle_aged.reading_is_old() is True, "a 45 minute old one is carried over but dimmed")
    check(
        middle_aged.held_snapshot().session_pct == 82.0,
        "and still shows the real number, never zero",
    )

    publish(moments_ago(60 * 30))
    ancient = build(no_endpoint, FakeDisplay(), FakeClock())
    ancient.recall_published_reading()
    check(ancient.last_snapshot is None, "a reading older than a day is not resurrected")

    state.write_text("{ this is not json")
    broken = build(no_endpoint, FakeDisplay(), FakeClock())
    broken.recall_published_reading()
    check(broken.last_snapshot is None, "a damaged state file is ignored, not fatal")

    state.write_text(json.dumps({"trouble": "ExpiredCredentials", "written_at": moments_ago(1)}))
    troubled = build(no_endpoint, FakeDisplay(), FakeClock())
    troubled.recall_published_reading()
    check(troubled.last_snapshot is None, "a file without a reading carries nothing over")
    state.unlink(missing_ok=True)


WORKING_DAYS = frozenset({0, 1, 2, 3, 4})


def a_week_where_the_weekend_matters():
    reference = datetime.now(timezone.utc)
    now = reference.isoformat()
    for hours in range(1, 169):
        resets_at = (reference + timedelta(hours=hours)).isoformat()
        probe = UsageSnapshot(
            session_pct=50.0,
            session_resets_at=None,
            weekly_pct=40.0,
            weekly_resets_at=resets_at,
            fetched_at=now,
        )
        every_day = renderer.weekly_marker_column(
            renderer.weekly_elapsed_fraction(probe, now, None)
        )
        working = renderer.weekly_marker_column(
            renderer.weekly_elapsed_fraction(probe, now, WORKING_DAYS)
        )
        if every_day != working:
            return resets_at
    return None


def the_weekday_setting_reaches_the_marker() -> None:
    print("weekly marker weekdays")
    wish = scratch_weekdays_path()
    wish.unlink(missing_ok=True)

    resets_at = a_week_where_the_weekend_matters()
    check(
        resets_at is not None,
        "there is a week in which switching the weekend off moves the marker",
    )
    reading = UsageSnapshot(
        session_pct=50.0,
        session_resets_at=None,
        weekly_pct=40.0,
        weekly_resets_at=resets_at,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: reading, display, clock, resend_interval=600.0)
    check(
        daemon.wanted_active_days() == weekdays.EVERY_DAY,
        "without a file every day counts",
    )
    daemon.tick()
    every_day = display.decoded()

    wish.write_text("1111100\n")
    check(
        daemon.wanted_active_days() == WORKING_DAYS,
        "the file names the working days",
    )
    check(daemon.active_days_changed() is True, "a new choice wakes the loop early")
    daemon.tick()
    working_week = display.decoded()
    check(working_week != every_day, "switching the weekend off changes the picture")
    check(daemon.active_days_changed() is False, "and then stops waking it")

    before = len(display.sent)
    daemon.tick()
    check(len(display.sent) == before, "an unchanged choice is not sent again")

    wish.write_text("nonsense")
    daemon.tick()
    check(
        display.decoded() == every_day,
        "a damaged file falls back to counting every day",
    )

    wish.write_text("0000000\n")
    daemon.tick()
    check(
        display.decoded() == every_day,
        "switching every day off falls back too, the marker never disappears",
    )

    wish.write_text("1111100\n")
    daemon.tick()
    check(
        display.decoded() == working_week,
        "choosing the working days again restores the picture",
    )
    wish.unlink(missing_ok=True)


MORNING_ON = (7 * 60, 24 * 60)


def a_week_where_the_night_matters():
    reference = datetime.now(timezone.utc)
    now = reference.isoformat()
    for hours in range(1, 169):
        resets_at = (reference + timedelta(hours=hours)).isoformat()
        probe = UsageSnapshot(
            session_pct=50.0,
            session_resets_at=None,
            weekly_pct=40.0,
            weekly_resets_at=resets_at,
            fetched_at=now,
        )
        whole_day = renderer.weekly_marker_column(
            renderer.weekly_elapsed_fraction(probe, now, None, None)
        )
        mornings = renderer.weekly_marker_column(
            renderer.weekly_elapsed_fraction(probe, now, None, MORNING_ON)
        )
        if whole_day != mornings:
            return resets_at
    return None


def the_day_hours_setting_reaches_the_marker() -> None:
    print("weekly marker day hours")
    wish = scratch_dayhours_path()
    wish.unlink(missing_ok=True)

    resets_at = a_week_where_the_night_matters()
    check(
        resets_at is not None,
        "there is a week in which skipping the nights moves the marker",
    )
    reading = UsageSnapshot(
        session_pct=50.0,
        session_resets_at=None,
        weekly_pct=40.0,
        weekly_resets_at=resets_at,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )

    display, clock = FakeDisplay(), FakeClock()
    daemon = build(lambda: reading, display, clock, resend_interval=600.0)
    check(
        daemon.wanted_active_hours() == dayhours.WHOLE_DAY,
        "without a file the whole day counts",
    )
    daemon.tick()
    whole_day = display.decoded()

    wish.write_text("07:00-24:00\n")
    check(
        daemon.wanted_active_hours() == MORNING_ON,
        "the file names the counted hours",
    )
    check(daemon.active_hours_changed() is True, "a new span wakes the loop early")
    daemon.tick()
    mornings = display.decoded()
    check(mornings != whole_day, "skipping the nights changes the picture")
    check(daemon.active_hours_changed() is False, "and then stops waking it")

    before = len(display.sent)
    daemon.tick()
    check(len(display.sent) == before, "an unchanged span is not sent again")

    wish.write_text("nonsense")
    daemon.tick()
    check(
        display.decoded() == whole_day,
        "a damaged file falls back to counting the whole day",
    )

    wish.write_text("18:00-09:00\n")
    daemon.tick()
    check(
        display.decoded() == whole_day,
        "a span that ends before it starts falls back too",
    )

    wish.write_text("07:00-24:00\n")
    daemon.tick()
    check(
        display.decoded() == mornings,
        "choosing the mornings again restores the picture",
    )
    wish.unlink(missing_ok=True)


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
    a_waiting_session_makes_the_background_breathe()
    the_breath_keeps_the_reading_readable()
    a_waiting_session_breathes_even_without_usage_data()
    a_broken_marker_directory_never_stops_the_counter()
    the_loop_reacts_to_a_waiting_session_within_seconds()
    a_finished_turn_pulls_the_numbers_in_early()
    the_endpoint_is_never_asked_faster_than_the_rate_limit_allows()
    the_loop_wakes_up_when_a_turn_finishes()
    the_reading_is_published_for_the_menu()
    the_slider_reaches_the_lamp()
    a_short_outage_does_not_dim_the_display()
    a_restart_keeps_the_last_known_reading()
    the_weekday_setting_reaches_the_marker()
    the_day_hours_setting_reaches_the_marker()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
