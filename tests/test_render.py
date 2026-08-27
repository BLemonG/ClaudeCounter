from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from claudecounter import render as renderer
from claudecounter.snapshot import UsageSnapshot, utc_now_iso

FAILURES = []


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


FIXED_NOW = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)


def snapshot_at(
    session: float,
    weekly: float,
    stale: bool = False,
    resets_in_minutes=None,
    weekly_resets_in_hours=None,
):
    session_resets_at = None
    if resets_in_minutes is not None:
        session_resets_at = (FIXED_NOW + timedelta(minutes=resets_in_minutes)).isoformat()
    weekly_resets_at = None
    if weekly_resets_in_hours is not None:
        weekly_resets_at = (FIXED_NOW + timedelta(hours=weekly_resets_in_hours)).isoformat()
    return UsageSnapshot(
        session_pct=session,
        session_resets_at=session_resets_at,
        weekly_pct=weekly,
        weekly_resets_at=weekly_resets_at,
        fetched_at=FIXED_NOW.isoformat(),
        stale=stale,
    )


def frame(
    session: float,
    weekly: float,
    stale: bool = False,
    resets_in_minutes=None,
    weekly_resets_in_hours=None,
):
    return renderer.render(
        snapshot_at(session, weekly, stale, resets_in_minutes, weekly_resets_in_hours),
        FIXED_NOW.isoformat(),
    ).load()


def ring_is_disjoint_from_weekly_row() -> None:
    print("ring geometry")
    positions = renderer.ring_positions()
    check(len(positions) == 58, "ring has 58 pixels over rows 0..14")
    check(len(set(positions)) == 58, "no ring pixel appears twice")
    check(all(y <= renderer.RING_BOTTOM_ROW for _, y in positions), "ring never enters the weekly row")
    check(positions[0] == (8, 0), "ring starts at top centre")
    check(positions[1] == (9, 0), "ring runs clockwise")


def ring_fill_tracks_percentage() -> None:
    print("ring fill")
    total = len(renderer.ring_positions())
    check(renderer.lit_count(0.0, total) == 0, "0 percent lights no ring pixel")
    check(renderer.lit_count(0.4, total) == 1, "any non-zero percent lights at least one pixel")
    check(renderer.lit_count(50.0, total) == 29, "50 percent lights half the ring")
    check(renderer.lit_count(100.0, total) == total, "100 percent lights the whole ring")

    pixels = frame(82.0, 0.0)
    positions = renderer.ring_positions()
    lit = renderer.lit_count(82.0, len(positions))
    expected = renderer.SESSION_ORANGE
    check(pixels[positions[lit - 1]] == expected, "last lit ring pixel carries the threshold colour")
    check(pixels[positions[lit]] == renderer.RING_TRACK, "first unlit ring pixel falls back to the track")


def threshold_colours_follow_the_spec() -> None:
    print("threshold colours")
    check(renderer.session_color(0.0) == renderer.SESSION_GREEN, "0 is green")
    check(renderer.session_color(59.0) == renderer.SESSION_GREEN, "59 is green")
    check(renderer.session_color(60.0) == renderer.SESSION_YELLOW, "60 is yellow")
    check(renderer.session_color(79.0) == renderer.SESSION_YELLOW, "79 is yellow")
    check(renderer.session_color(80.0) == renderer.SESSION_ORANGE, "80 is orange")
    check(renderer.session_color(94.0) == renderer.SESSION_ORANGE, "94 is orange")
    check(renderer.session_color(95.0) == renderer.SESSION_RED, "95 is red")
    check(renderer.session_color(100.0) == renderer.SESSION_RED, "100 is red")


def label_stays_two_characters() -> None:
    print("centre label")
    check(renderer.session_label(0.0) == "00", "0 renders as 00")
    check(renderer.session_label(7.0) == "07", "single digits are padded")
    check(renderer.session_label(82.0) == "82", "82 renders as 82")
    check(renderer.session_label(99.4) == "99", "99.4 rounds down to 99")
    check(renderer.session_label(99.6) == "!!", "values rounding to 100 switch to !!")
    check(renderer.session_label(100.0) == "!!", "100 renders as !!")
    check(renderer.label_width("82") == 12, "two glyphs are 12 pixels wide")

    pixels = frame(82.0, 0.0)
    label_pixels = [
        (x, y)
        for y in range(renderer.SIZE)
        for x in range(renderer.SIZE)
        if pixels[x, y] == renderer.LABEL
    ]
    rows = {y for _, y in label_pixels}
    columns = {x for x, _ in label_pixels}
    check(rows == set(range(3, 12)), "label occupies rows 3..11")
    check(min(columns) == 2 and max(columns) == 13, "label occupies columns 2..13")
    check(
        min(columns) > renderer.INTERIOR_FIRST_COLUMN
        and max(columns) < renderer.INTERIOR_LAST_COLUMN,
        "label keeps a free pixel to the ring on both sides",
    )
    check(
        min(rows) > renderer.INTERIOR_FIRST_ROW and max(rows) < renderer.INTERIOR_LAST_ROW,
        "label keeps free pixels to the ring above and below",
    )
    check(
        min(rows) >= renderer.INTERIOR_FIRST_ROW and max(rows) <= renderer.INTERIOR_LAST_ROW,
        "label never collides with the ring",
    )
    for digit, glyph in renderer.GLYPHS_5X9.items():
        check(
            len(glyph) == renderer.GLYPH_HEIGHT
            and all(len(row) == renderer.GLYPH_WIDTH for row in glyph),
            f"glyph {digit} is {renderer.GLYPH_WIDTH}x{renderer.GLYPH_HEIGHT}",
        )


def weekly_bar_owns_the_last_row() -> None:
    print("weekly bar")
    pixels = frame(0.0, 41.0)
    lit = renderer.lit_count(41.0, renderer.SIZE)
    check(lit == 7, "41 percent lights 7 of 16 pixels")
    row = [pixels[x, renderer.WEEKLY_ROW] for x in range(renderer.SIZE)]
    check(row[:lit] == [renderer.WEEKLY_FILL] * lit, "lit part uses the violet accent")
    check(row[lit:] == [renderer.WEEKLY_TRACK] * (renderer.SIZE - lit), "rest uses the violet track")

    empty = frame(0.0, 0.0)
    check(
        all(empty[x, renderer.WEEKLY_ROW] == renderer.WEEKLY_TRACK for x in range(renderer.SIZE)),
        "0 percent still shows the track so the row reads as a bar",
    )
    full = frame(0.0, 100.0)
    check(
        all(full[x, renderer.WEEKLY_ROW] == renderer.WEEKLY_FILL for x in range(renderer.SIZE)),
        "100 percent fills the whole row",
    )


def weekly_never_uses_a_session_colour() -> None:
    print("colour separation")
    session_colours = {
        renderer.SESSION_GREEN,
        renderer.SESSION_YELLOW,
        renderer.SESSION_ORANGE,
        renderer.SESSION_RED,
    }
    check(renderer.WEEKLY_FILL not in session_colours, "weekly accent is not a session colour")
    check(renderer.TIME_MARKER not in session_colours, "the marker is not a session colour")
    check(renderer.TIME_MARKER != renderer.WEEKLY_FILL, "the marker is not the weekly accent")
    check(renderer.TIME_MARKER != renderer.RING_TRACK, "the marker is not the ring track")
    check(renderer.TIME_MARKER != renderer.LABEL, "the marker is not the label colour")
    check(renderer.dimmed(renderer.WEEKLY_FILL) not in session_colours, "dimmed accent stays distinct")
    for percent in (0.0, 30.0, 70.0, 90.0, 100.0):
        pixels = frame(percent, 55.0)
        row = {pixels[x, renderer.WEEKLY_ROW] for x in range(renderer.SIZE)}
        check(not (row & session_colours), f"weekly row avoids session colours at {int(percent)} percent")


def weekly_marker_can_skip_night_hours() -> None:
    print("weekly marker with a daily hour window")
    reset_moment = datetime(2026, 8, 31, 0, 0).astimezone()
    week = UsageSnapshot(
        session_pct=0.0,
        session_resets_at=None,
        weekly_pct=40.0,
        weekly_resets_at=reset_moment.isoformat(),
        fetched_at=FIXED_NOW.isoformat(),
    )
    week_start = reset_moment - timedelta(days=7)
    working_days = {0, 1, 2, 3, 4}
    morning_on = (7 * 60, 24 * 60)
    office = (9 * 60, 18 * 60)

    def fraction(days, hours, offset):
        return renderer.weekly_elapsed_fraction(
            week, (week_start + offset).isoformat(), days, hours
        )

    check(
        renderer.active_seconds_between(week_start, reset_moment, None, morning_on)
        == 7 * 17 * 60 * 60,
        "seven days from 07:00 hold seventeen hours each",
    )
    check(
        renderer.active_seconds_between(
            week_start, reset_moment, working_days, office
        )
        == 5 * 9 * 60 * 60,
        "five office days hold nine hours each",
    )
    check(
        renderer.active_seconds_between(week_start, reset_moment, None, None)
        == renderer.active_seconds_between(
            week_start, reset_moment, None, (0, 24 * 60)
        ),
        "the whole day window counts the same as no window at all",
    )
    check(
        fraction(None, morning_on, timedelta(hours=3)) == 0.0,
        "nothing has passed while the night is still running",
    )
    check(
        fraction(None, morning_on, timedelta(hours=3))
        == fraction(None, morning_on, timedelta(hours=6)),
        "the marker holds its place all through the skipped night",
    )
    check(
        abs(fraction(None, morning_on, timedelta(hours=15.5)) - 0.5 / 7) < 1e-9,
        "half of the first counted day is half of one seventh",
    )
    check(
        abs(fraction(working_days, office, timedelta(days=2, hours=13.5)) - 0.5) < 1e-9,
        "midday on Wednesday is halfway through a five day office week",
    )
    check(
        fraction(working_days, office, timedelta(days=4, hours=20))
        == fraction(working_days, office, timedelta(days=6, hours=20)),
        "once Friday evening is over the marker stands still until the reset",
    )
    check(
        renderer.weekly_marker_column(
            fraction(working_days, office, timedelta(days=6, hours=20))
        )
        == renderer.SIZE - 1,
        "a used up office week rests on the rightmost pixel",
    )
    friday_noon = (week_start + timedelta(days=4, hours=12)).isoformat()
    check(
        renderer.render(week, friday_noon, 0.0, working_days, office)
        != renderer.render(week, friday_noon, 0.0, working_days, None),
        "the hour window reaches the drawn frame",
    )


def stale_dims_data_but_keeps_the_number_readable() -> None:
    print("stale state")
    fresh = frame(82.0, 41.0, stale=False)
    stale = frame(82.0, 41.0, stale=True)
    positions = renderer.ring_positions()
    check(
        stale[positions[0]] == renderer.dimmed(renderer.SESSION_ORANGE),
        "stale dims the ring fill",
    )
    check(
        stale[0, renderer.WEEKLY_ROW] == renderer.dimmed(renderer.WEEKLY_FILL),
        "stale dims the weekly fill",
    )
    label_positions = [
        (x, y)
        for y in range(renderer.SIZE)
        for x in range(renderer.SIZE)
        if fresh[x, y] == renderer.LABEL
    ]
    check(
        all(stale[position] == renderer.LABEL for position in label_positions),
        "stale keeps the percentage at full brightness",
    )
    check(fresh[positions[0]] != stale[positions[0]], "stale is visually distinct from fresh")


def time_marker_tracks_the_session_window() -> None:
    print("time marker")
    total = len(renderer.ring_positions())

    check(
        renderer.session_elapsed_fraction(snapshot_at(0.0, 0.0, resets_in_minutes=300), FIXED_NOW.isoformat()) == 0.0,
        "a full 5h remaining means nothing has elapsed",
    )
    check(
        renderer.session_elapsed_fraction(snapshot_at(0.0, 0.0, resets_in_minutes=150), FIXED_NOW.isoformat()) == 0.5,
        "150 minutes remaining is half the window",
    )
    check(
        renderer.session_elapsed_fraction(snapshot_at(0.0, 0.0, resets_in_minutes=0), FIXED_NOW.isoformat()) == 0.0,
        "a reset that is due starts the next window at nothing elapsed",
    )
    check(
        renderer.session_elapsed_fraction(snapshot_at(0.0, 0.0, resets_in_minutes=-30), FIXED_NOW.isoformat()) == 0.1,
        "an overdue reset keeps counting inside the window that followed it",
    )
    check(
        renderer.session_elapsed_fraction(snapshot_at(0.0, 0.0, resets_in_minutes=-2550), FIXED_NOW.isoformat()) == 0.5,
        "a reset that is days old still lands where the clock says",
    )
    check(
        renderer.session_elapsed_fraction(snapshot_at(0.0, 0.0, resets_in_minutes=600), FIXED_NOW.isoformat()) == 0.0,
        "a reset beyond the window clamps to nothing elapsed",
    )
    check(
        renderer.session_elapsed_fraction(snapshot_at(0.0, 0.0), FIXED_NOW.isoformat()) is None,
        "without a reset timestamp there is no marker",
    )

    check(renderer.time_marker_position(0.0) == (8, 0), "a fresh window marks top centre")
    check(
        renderer.time_marker_position(1.0) == renderer.ring_positions()[0],
        "a spent window wraps back to top centre",
    )
    check(
        renderer.time_marker_position((total - 1) / total) == renderer.ring_positions()[total - 1],
        "the last slice of the window marks the last ring pixel",
    )
    check(
        renderer.time_marker_position(0.5) == renderer.ring_positions()[total // 2],
        "half a window marks the opposite side of the ring",
    )
    check(
        all(
            renderer.time_marker_position(step / 100.0)[1] <= renderer.RING_BOTTOM_ROW
            for step in range(101)
        ),
        "the marker never lands in the weekly row",
    )

    without_marker = frame(82.0, 41.0)
    with_marker = frame(82.0, 41.0, resets_in_minutes=150)
    marker_pixels = [
        (x, y)
        for y in range(renderer.SIZE)
        for x in range(renderer.SIZE)
        if with_marker[x, y] == renderer.TIME_MARKER
    ]
    check(len(marker_pixels) == 1, "exactly one pixel carries the marker colour")
    check(
        marker_pixels[0] == renderer.time_marker_position(0.5),
        "the marker sits where the elapsed fraction says",
    )
    differing = [
        (x, y)
        for y in range(renderer.SIZE)
        for x in range(renderer.SIZE)
        if without_marker[x, y] != with_marker[x, y]
    ]
    check(differing == marker_pixels, "the marker changes nothing but its own pixel")

    stale_marker = frame(82.0, 41.0, stale=True, resets_in_minutes=150)
    check(
        stale_marker[marker_pixels[0]] == renderer.dimmed(renderer.TIME_MARKER),
        "stale dims the marker like the rest of the ring data",
    )


def weekly_marker_tracks_the_seven_day_window() -> None:
    print("weekly marker")
    check(
        renderer.weekly_elapsed_fraction(snapshot_at(0.0, 0.0, weekly_resets_in_hours=168), FIXED_NOW.isoformat()) == 0.0,
        "a full week remaining means nothing has elapsed",
    )
    check(
        renderer.weekly_elapsed_fraction(snapshot_at(0.0, 0.0, weekly_resets_in_hours=84), FIXED_NOW.isoformat()) == 0.5,
        "84 hours remaining is half the week",
    )
    check(
        renderer.weekly_elapsed_fraction(snapshot_at(0.0, 0.0, weekly_resets_in_hours=0), FIXED_NOW.isoformat()) == 0.0,
        "a weekly reset that is due starts the next week at nothing elapsed",
    )
    check(
        renderer.weekly_elapsed_fraction(snapshot_at(0.0, 0.0, weekly_resets_in_hours=-84), FIXED_NOW.isoformat()) == 0.5,
        "an overdue weekly reset keeps counting inside the week that followed it",
    )
    check(
        renderer.weekly_elapsed_fraction(snapshot_at(0.0, 0.0), FIXED_NOW.isoformat()) is None,
        "without a weekly reset timestamp there is no marker",
    )

    check(renderer.weekly_marker_column(0.0) == 0, "a fresh week marks the leftmost pixel")
    check(
        renderer.weekly_marker_column(1.0) == renderer.SIZE - 1,
        "a week with no active time left rests on the rightmost pixel",
    )
    check(
        renderer.weekly_marker_column((renderer.SIZE - 1) / renderer.SIZE) == renderer.SIZE - 1,
        "the last slice of the week marks the rightmost pixel",
    )
    check(renderer.weekly_marker_column(0.5) == renderer.SIZE // 2, "half a week marks the middle")

    without_marker = frame(82.0, 41.0)
    with_marker = frame(82.0, 41.0, weekly_resets_in_hours=84)
    marker_pixels = [
        (x, y)
        for y in range(renderer.SIZE)
        for x in range(renderer.SIZE)
        if with_marker[x, y] == renderer.TIME_MARKER
    ]
    check(len(marker_pixels) == 1, "exactly one pixel carries the weekly marker")
    check(marker_pixels[0][1] == renderer.WEEKLY_ROW, "the weekly marker stays in the weekly row")
    check(
        marker_pixels[0][0] == renderer.weekly_marker_column(0.5),
        "the weekly marker sits where the elapsed fraction says",
    )
    differing = [
        (x, y)
        for y in range(renderer.SIZE)
        for x in range(renderer.SIZE)
        if without_marker[x, y] != with_marker[x, y]
    ]
    check(differing == marker_pixels, "the weekly marker changes nothing but its own pixel")

    stale_marker = frame(82.0, 41.0, stale=True, weekly_resets_in_hours=84)
    check(
        stale_marker[marker_pixels[0]] == renderer.dimmed(renderer.TIME_MARKER),
        "stale dims the weekly marker too",
    )

    both = frame(82.0, 41.0, resets_in_minutes=150, weekly_resets_in_hours=84)
    both_markers = [
        (x, y)
        for y in range(renderer.SIZE)
        for x in range(renderer.SIZE)
        if both[x, y] == renderer.TIME_MARKER
    ]
    check(len(both_markers) == 2, "ring and weekly bar can carry a marker at the same time")
    check(
        {position[1] == renderer.WEEKLY_ROW for position in both_markers} == {True, False},
        "the two markers sit on different rows",
    )


def both_values_are_visible_at_once() -> None:
    print("simultaneous readout")
    pixels = frame(82.0, 41.0)
    ring_lit = any(
        pixels[position] == renderer.SESSION_ORANGE for position in renderer.ring_positions()
    )
    weekly_lit = any(
        pixels[x, renderer.WEEKLY_ROW] == renderer.WEEKLY_FILL for x in range(renderer.SIZE)
    )
    label_lit = any(
        pixels[x, y] == renderer.LABEL for x in range(renderer.SIZE) for y in range(renderer.SIZE)
    )
    check(ring_lit and weekly_lit and label_lit, "ring, label and weekly bar are all present in one frame")


def palette_stays_small_enough_for_one_packet() -> None:
    print("palette size")
    for stale in (False, True):
        for session in (0.0, 45.0, 82.0, 100.0):
            pixels = frame(
                session, 63.0, stale=stale, resets_in_minutes=150, weekly_resets_in_hours=84
            )
            colours = {
                pixels[x, y] for x in range(renderer.SIZE) for y in range(renderer.SIZE)
            }
            check(
                len(colours) <= 8,
                f"session={int(session)} stale={stale} uses {len(colours)} colours (<= 8)",
            )


def snapshot_contract_round_trips() -> None:
    print("data contract")
    snapshot = UsageSnapshot(
        session_pct=82.0,
        session_resets_at="2026-08-22T15:00:00+00:00",
        weekly_pct=41.0,
        weekly_resets_at="2026-08-26T13:00:00+00:00",
        fetched_at="2026-08-22T12:00:00+00:00",
        stale=False,
    )
    payload = snapshot.to_dict()
    check(
        sorted(payload) == [
            "fetched_at",
            "session_pct",
            "session_resets_at",
            "stale",
            "weekly_pct",
            "weekly_resets_at",
        ],
        "snapshot exposes exactly the keys from the spec",
    )
    check(UsageSnapshot.from_dict(payload) == snapshot, "snapshot round trips through a dict")
    check(snapshot.marked_stale().stale is True, "marked_stale flips the flag")
    check(snapshot.marked_stale().session_pct == 82.0, "marked_stale keeps the last known values")


def out_of_range_input_is_clamped() -> None:
    print("input clamping")
    check(renderer.clamp_percent(-5.0) == 0.0, "negative percentages clamp to 0")
    check(renderer.clamp_percent(140.0) == 100.0, "percentages above 100 clamp to 100")
    pixels = frame(140.0, 140.0)
    positions = renderer.ring_positions()
    check(
        all(pixels[position] == renderer.SESSION_RED for position in positions),
        "an over-range session still renders a full red ring",
    )


def the_marker_follows_the_clock_not_the_fetch() -> None:
    print("marker follows real time")
    reading = snapshot_at(50.0, 50.0, resets_in_minutes=300, weekly_resets_in_hours=168)
    at_fetch = renderer.session_elapsed_fraction(reading, FIXED_NOW.isoformat())
    later = renderer.session_elapsed_fraction(
        reading, (FIXED_NOW + timedelta(minutes=150)).isoformat()
    )
    check(at_fetch == 0.0, "at fetch time nothing of the window has elapsed")
    check(later == 0.5, "150 minutes later the window is half gone, without a new reading")
    check(
        renderer.time_marker_position(at_fetch) != renderer.time_marker_position(later),
        "the marker moves on the ring as time passes",
    )
    week_later = renderer.weekly_elapsed_fraction(
        reading, (FIXED_NOW + timedelta(hours=84)).isoformat()
    )
    check(week_later == 0.5, "the weekly marker advances from the clock too")


def weekly_marker_can_skip_days() -> None:
    print("weekly marker with days switched off")
    reset_moment = datetime(2026, 8, 31, 0, 0).astimezone()
    week = UsageSnapshot(
        session_pct=0.0,
        session_resets_at=None,
        weekly_pct=40.0,
        weekly_resets_at=reset_moment.isoformat(),
        fetched_at=FIXED_NOW.isoformat(),
    )
    week_start = reset_moment - timedelta(days=7)
    working_days = {0, 1, 2, 3, 4}

    def fraction(days, offset):
        return renderer.weekly_elapsed_fraction(
            week, (week_start + offset).isoformat(), days
        )

    check(
        renderer.active_seconds_between(week_start, reset_moment, working_days)
        == 5 * 24 * 60 * 60,
        "five working days hold exactly five days of active time",
    )
    check(
        renderer.active_seconds_between(week_start, reset_moment, None)
        == 7 * 24 * 60 * 60,
        "with every day switched on the whole week counts",
    )
    check(
        fraction(working_days, timedelta(0)) == 0.0,
        "the start of the week is still the start of the week",
    )
    check(
        fraction(working_days, timedelta(days=2, hours=12)) == 0.5,
        "midday on Wednesday is halfway through a five day week",
    )
    check(
        fraction(None, timedelta(days=2, hours=12)) != 0.5,
        "the same moment is not halfway when every day counts",
    )

    saturday = fraction(working_days, timedelta(days=5, hours=12))
    sunday = fraction(working_days, timedelta(days=6, hours=20))
    check(saturday == 1.0, "once Friday is over the working week is used up")
    check(saturday == sunday, "the marker stands still through a skipped weekend")
    check(
        renderer.weekly_marker_column(saturday) == renderer.SIZE - 1,
        "a used up working week rests on the rightmost pixel, not back at the start",
    )
    check(
        fraction(None, timedelta(days=5, hours=12))
        != fraction(None, timedelta(days=6, hours=20)),
        "with every day switched on the marker keeps moving over the weekend",
    )

    midweek_off = {0, 1, 3, 4}
    check(
        fraction(midweek_off, timedelta(days=3)) == 0.5,
        "a day off in the middle counts as no time passing",
    )
    check(
        fraction(midweek_off, timedelta(days=2))
        == fraction(midweek_off, timedelta(days=2, hours=23)),
        "the marker holds its place all through the skipped Wednesday",
    )

    check(
        fraction(set(), timedelta(days=2, hours=12))
        == fraction(None, timedelta(days=2, hours=12)),
        "switching every day off falls back to counting every day",
    )
    check(
        fraction(range(7), timedelta(days=2, hours=12))
        == fraction(None, timedelta(days=2, hours=12)),
        "naming all seven days is the same as naming none",
    )

    moment = (week_start + timedelta(days=2, hours=12)).isoformat()
    plain_row = renderer.render(week, moment).load()
    working_row = renderer.render(week, moment, 0.0, working_days).load()
    plain_marker = [
        x
        for x in range(renderer.SIZE)
        if plain_row[x, renderer.WEEKLY_ROW] == renderer.TIME_MARKER
    ]
    working_marker = [
        x
        for x in range(renderer.SIZE)
        if working_row[x, renderer.WEEKLY_ROW] == renderer.TIME_MARKER
    ]
    check(len(working_marker) == 1, "the drawn frame still carries exactly one marker")
    check(
        working_marker[0] == renderer.weekly_marker_column(0.5),
        "the drawn marker sits where the working week says",
    )
    check(
        plain_marker != working_marker,
        "switching the weekend off actually moves the drawn marker",
    )

    beside_the_marker = [
        x for x in range(renderer.SIZE) if x not in (plain_marker[0], working_marker[0])
    ]
    check(
        all(
            plain_row[x, renderer.WEEKLY_ROW] == working_row[x, renderer.WEEKLY_ROW]
            for x in beside_the_marker
        ),
        "away from the marker the weekly bar is untouched by the setting",
    )


def main() -> int:
    ring_is_disjoint_from_weekly_row()
    ring_fill_tracks_percentage()
    threshold_colours_follow_the_spec()
    label_stays_two_characters()
    weekly_bar_owns_the_last_row()
    weekly_never_uses_a_session_colour()
    time_marker_tracks_the_session_window()
    weekly_marker_tracks_the_seven_day_window()
    weekly_marker_can_skip_days()
    weekly_marker_can_skip_night_hours()
    stale_dims_data_but_keeps_the_number_readable()
    both_values_are_visible_at_once()
    palette_stays_small_enough_for_one_packet()
    snapshot_contract_round_trips()
    out_of_range_input_is_clamped()
    the_marker_follows_the_clock_not_the_fetch()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
