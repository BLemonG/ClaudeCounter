from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

import json

from . import protocol
from . import render as renderer
from . import transport
from . import daemon as daemon_module
from . import usage_source
from . import dayhours, weekdays
from .config import DEFAULT_RFCOMM_CHANNEL, DeviceConfig, load_config, save_config
from .snapshot import UsageSnapshot, utc_now_iso

MINIMUM_PREVIEW_SCALE = 16


def snapshot_from_args(args: argparse.Namespace) -> UsageSnapshot:
    fetched_at = utc_now_iso()
    session_resets_at = None
    minutes = getattr(args, "session_resets_in", None)
    if minutes is not None:
        session_resets_at = (
            datetime.now(timezone.utc) + timedelta(minutes=minutes)
        ).isoformat()
    weekly_resets_at = None
    hours = getattr(args, "weekly_resets_in", None)
    if hours is not None:
        weekly_resets_at = (
            datetime.now(timezone.utc) + timedelta(hours=hours)
        ).isoformat()
    return UsageSnapshot(
        session_pct=args.session,
        session_resets_at=session_resets_at,
        weekly_pct=args.weekly,
        weekly_resets_at=weekly_resets_at,
        fetched_at=fetched_at,
        stale=args.stale,
    )


def chosen_days(args: argparse.Namespace):
    named = getattr(args, "weekdays", None)
    if named:
        return weekdays.days_from_names(named)
    return weekdays.load_active_days()


def chosen_hours(args: argparse.Namespace):
    wanted = getattr(args, "hours", None)
    if wanted:
        return dayhours.hours_from_text(wanted)
    return dayhours.load_active_hours()


def default_preview_path(args: argparse.Namespace) -> str:
    suffix = "-stale" if args.stale else ""
    return f"preview-session{int(round(args.session))}-weekly{int(round(args.weekly))}{suffix}.png"


def resolve_target(args: argparse.Namespace) -> Optional[DeviceConfig]:
    if getattr(args, "mac", None):
        channel = getattr(args, "channel", None) or DEFAULT_RFCOMM_CHANNEL
        return DeviceConfig(mac=args.mac, channel=channel)
    stored = load_config()
    if stored is None:
        print(
            "no device configured, run: claudecounter configure --mac <ADDRESS>",
            file=sys.stderr,
        )
        return None
    if getattr(args, "channel", None):
        return DeviceConfig(mac=stored.mac, channel=args.channel)
    return stored


def cmd_preview(args: argparse.Namespace) -> int:
    snapshot = snapshot_from_args(args)
    days = chosen_days(args)
    if days is None:
        print(f"unknown weekday in {args.weekdays!r}", file=sys.stderr)
        return 1
    hours = chosen_hours(args)
    if hours is None:
        print(f"unreadable hour window in {args.hours!r}", file=sys.stderr)
        return 1
    image = renderer.render(snapshot, active_days=days, active_hours=hours)
    if args.ascii:
        print(renderer.ascii_art(image))
    scale = max(args.scale, MINIMUM_PREVIEW_SCALE)
    path = args.output or default_preview_path(args)
    renderer.scaled_preview(image, scale).save(path)
    print(f"wrote {path} ({renderer.SIZE * scale}x{renderer.SIZE * scale})")
    return 0


def cmd_list_devices(args: argparse.Namespace) -> int:
    try:
        devices = transport.list_devices()
    except transport.TransportError as failure:
        print(str(failure), file=sys.stderr)
        return 1
    if not devices:
        print("no paired bluetooth devices found")
        return 0
    print("paired devices:")
    for address, name in devices:
        print(f"  {address}  {name}")
    return 0


def cmd_configure(args: argparse.Namespace) -> int:
    channel = args.channel
    if channel is None:
        print(f"querying {args.mac} for a serial port service ...")
        try:
            channel = transport.probe_serial_port_channel(args.mac)
        except transport.TransportError as failure:
            print(str(failure), file=sys.stderr)
            return 1
        if channel is None:
            print(
                f"{args.mac} exposes no SPP service (UUID 0x1101), "
                "pass --channel explicitly if you know it",
                file=sys.stderr,
            )
            return 1
        print(f"found SPP on rfcomm channel {channel}")
    path = save_config(DeviceConfig(mac=args.mac, channel=channel))
    print(f"wrote {path}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    target = resolve_target(args)
    if target is None:
        return 1
    try:
        print(transport.describe_device(target.mac))
    except transport.TransportError as failure:
        print(str(failure), file=sys.stderr)
        return 1
    return 0


def deliver(target: DeviceConfig, payloads, description: str) -> int:
    if isinstance(payloads, (bytes, bytearray)):
        payloads = [bytes(payloads)]
    try:
        written = transport.send_packets(target.mac, target.channel, payloads)
    except transport.TransportError as failure:
        print(str(failure), file=sys.stderr)
        return 1
    print(
        f"sent {description}, {len(payloads)} packet(s) and {written} bytes "
        f"to {target.mac} channel {target.channel}"
    )
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    target = resolve_target(args)
    if target is None:
        return 1
    snapshot = snapshot_from_args(args)
    days = chosen_days(args)
    if days is None:
        print(f"unknown weekday in {args.weekdays!r}", file=sys.stderr)
        return 1
    hours = chosen_hours(args)
    if hours is None:
        print(f"unreadable hour window in {args.hours!r}", file=sys.stderr)
        return 1
    label = f"session={int(round(args.session))} weekly={int(round(args.weekly))}"
    if args.breathing:
        frames = renderer.breathing_frames(
            snapshot, active_days=days, active_hours=hours
        )
        if args.ascii:
            print(renderer.ascii_art(frames[len(frames) // 2][0]))
        return deliver(target, protocol.animation_packets(frames), label + " breathing")
    image = renderer.render(snapshot, active_days=days, active_hours=hours)
    if args.ascii:
        print(renderer.ascii_art(image))
    return deliver(target, protocol.image_packet(image), label)


def cmd_disconnect(args: argparse.Namespace) -> int:
    target = resolve_target(args)
    if target is None:
        return 1
    try:
        print(transport.disconnect(target.mac))
    except transport.TransportError as failure:
        print(str(failure), file=sys.stderr)
        return 1
    return 0


def cmd_waiting(args: argparse.Namespace) -> int:
    from . import attention, presence

    if args.clear:
        for session in attention.waiting_sessions():
            attention.clear_waiting(session)
        print("cleared every waiting marker")
        return 0

    front = presence.frontmost_bundle_id()
    idle = presence.seconds_since_input()
    print(f"frontmost app: {front or 'unknown'}")
    print(
        "last input: "
        + ("unknown" if idle is None else f"{idle:.0f}s ago")
        + (" (at the keyboard)" if presence.at_the_keyboard(idle) else " (away)")
    )
    markers = attention.waiting_markers()
    if not markers:
        print("no session is waiting for input")
        return 0
    print(f"{len(markers)} marker(s):")
    for session, owner in markers:
        print(f"  {session}  belongs to {owner or 'an unknown app'}")
    print("breathing now" if attention.a_session_is_waiting() else "not breathing")
    return 0


def cmd_send_raw(args: argparse.Namespace) -> int:
    target = resolve_target(args)
    if target is None:
        return 1
    source = args.hex
    if args.hex_file:
        source = open(args.hex_file).read()
    digits = "".join(character for character in source if character in "0123456789abcdefABCDEF")
    if not digits or len(digits) % 2:
        print("payload must be an even, non-zero number of hex digits", file=sys.stderr)
        return 1
    payload = bytes.fromhex(digits)
    return deliver(target, payload, f"raw packet ({len(payload)} bytes)")


def cmd_brightness(args: argparse.Namespace) -> int:
    target = resolve_target(args)
    if target is None:
        return 1
    return deliver(target, protocol.brightness_packet(args.level), f"brightness {args.level}")


def cmd_weekdays(args: argparse.Namespace) -> int:
    if args.every_day:
        wanted = weekdays.EVERY_DAY
    elif args.set:
        wanted = weekdays.days_from_names(args.set)
        if wanted is None:
            print(
                f"unknown weekday in {args.set!r}, "
                f"use names from {','.join(weekdays.DAY_NAMES)}",
                file=sys.stderr,
            )
            return 1
    else:
        stored = weekdays.load_active_days()
        print(f"the weekly time marker counts {weekdays.named(stored)}")
        return 0
    path = weekdays.save_active_days(wanted)
    print(f"the weekly time marker now counts {weekdays.named(wanted)}")
    print(f"wrote {path}")
    return 0


def cmd_hours(args: argparse.Namespace) -> int:
    if args.all_day:
        wanted = dayhours.WHOLE_DAY
    elif args.set:
        wanted = dayhours.hours_from_text(args.set)
        if wanted is None:
            print(
                f"unreadable hour window in {args.set!r}, "
                "use a span like 07:00-24:00",
                file=sys.stderr,
            )
            return 1
    else:
        stored = dayhours.load_active_hours()
        print(f"the weekly time marker counts {dayhours.spelled(stored)} of each day")
        return 0
    path = dayhours.save_active_hours(wanted)
    print(f"the weekly time marker now counts {dayhours.spelled(wanted)} of each day")
    print(f"wrote {path}")
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    try:
        if args.raw:
            print(json.dumps(usage_source.read_raw_usage(), indent=2, sort_keys=True))
        else:
            print(json.dumps(usage_source.read_usage().to_dict(), indent=2, sort_keys=True))
    except usage_source.UsageError as failure:
        print(f"{type(failure).__name__}: {failure}", file=sys.stderr)
        return 1
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    target = resolve_target(args)
    if target is None:
        return 1
    if args.once:
        logger = daemon_module.build_logger(verbose=args.verbose)
        return 0 if daemon_module.Daemon(target, logger).tick() else 1
    return daemon_module.run_daemon(target, poll_interval=args.interval, verbose=args.verbose)


def add_target_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mac", help="device address, defaults to the configured one")
    parser.add_argument("--channel", type=int, help="rfcomm channel, defaults to the configured one")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claudecounter")
    subcommands = parser.add_subparsers(dest="command", required=True)

    preview = subcommands.add_parser("preview", help="render a frame to PNG, no hardware needed")
    preview.add_argument("--session", type=float, default=0.0, help="5h session utilization in percent")
    preview.add_argument("--weekly", type=float, default=0.0, help="7d utilization in percent")
    preview.add_argument("--stale", action="store_true", help="render the stale indication")
    preview.add_argument(
        "--session-resets-in",
        type=float,
        help="minutes until the 5h session window resets, drives the time marker on the ring",
    )
    preview.add_argument(
        "--weekly-resets-in",
        type=float,
        help="hours until the 7d window resets, drives the time marker on the weekly bar",
    )
    preview.add_argument(
        "--weekdays",
        help="weekdays the weekly time marker counts, defaults to the stored choice",
    )
    preview.add_argument(
        "--hours",
        help="hours of a day the weekly time marker counts, for example 07:00-24:00",
    )
    preview.add_argument("--scale", type=int, default=MINIMUM_PREVIEW_SCALE, help="pixel scale factor")
    preview.add_argument("--ascii", action="store_true", help="also print the frame as text")
    preview.add_argument("-o", "--output", help="output PNG path")
    preview.set_defaults(func=cmd_preview)

    list_devices = subcommands.add_parser("list-devices", help="list paired bluetooth devices")
    list_devices.set_defaults(func=cmd_list_devices)

    configure = subcommands.add_parser("configure", help="store the device address and rfcomm channel")
    configure.add_argument("--mac", required=True, help="device address")
    configure.add_argument("--channel", type=int, help="rfcomm channel, probed via SDP when omitted")
    configure.set_defaults(func=cmd_configure)

    probe = subcommands.add_parser("probe", help="show the SDP service records of the device")
    add_target_arguments(probe)
    probe.set_defaults(func=cmd_probe)

    send = subcommands.add_parser("send", help="render a frame and push it to the device")
    send.add_argument("--session", type=float, default=0.0, help="5h session utilization in percent")
    send.add_argument("--weekly", type=float, default=0.0, help="7d utilization in percent")
    send.add_argument("--stale", action="store_true", help="render the stale indication")
    send.add_argument(
        "--session-resets-in",
        type=float,
        help="minutes until the 5h session window resets, drives the time marker on the ring",
    )
    send.add_argument(
        "--weekly-resets-in",
        type=float,
        help="hours until the 7d window resets, drives the time marker on the weekly bar",
    )
    send.add_argument(
        "--weekdays",
        help="weekdays the weekly time marker counts, defaults to the stored choice",
    )
    send.add_argument(
        "--hours",
        help="hours of a day the weekly time marker counts, for example 07:00-24:00",
    )
    send.add_argument("--ascii", action="store_true", help="also print the frame as text")
    send.add_argument(
        "--breathing",
        action="store_true",
        help="send the looping breath the device plays while a session waits for input",
    )
    add_target_arguments(send)
    send.set_defaults(func=cmd_send)

    send_raw = subcommands.add_parser("send-raw", help="push a raw packet, for protocol debugging")
    send_raw.add_argument("--hex", default="", help="packet as hex digits")
    send_raw.add_argument("--hex-file", help="file containing the packet as hex digits")
    add_target_arguments(send_raw)
    send_raw.set_defaults(func=cmd_send_raw)

    brightness = subcommands.add_parser("brightness", help="set the display brightness")
    brightness.add_argument("--level", type=int, required=True, help="brightness from 0 to 100")
    add_target_arguments(brightness)
    brightness.set_defaults(func=cmd_brightness)

    weekday_choice = subcommands.add_parser(
        "weekdays",
        help="choose which weekdays the time marker on the weekly bar counts",
    )
    weekday_choice.add_argument(
        "--set",
        help=f"comma separated weekdays, for example {','.join(weekdays.DAY_NAMES[:5])}",
    )
    weekday_choice.add_argument(
        "--every-day", action="store_true", help="count all seven days again"
    )
    weekday_choice.set_defaults(func=cmd_weekdays)

    hour_choice = subcommands.add_parser(
        "hours",
        help="choose which hours of a day the time marker on the weekly bar counts",
    )
    hour_choice.add_argument(
        "--set",
        help="hour span, for example 07:00-24:00",
    )
    hour_choice.add_argument(
        "--all-day", action="store_true", help="count every hour again"
    )
    hour_choice.set_defaults(func=cmd_hours)

    usage = subcommands.add_parser("usage", help="read the current usage from the Anthropic endpoint")
    usage.add_argument("--raw", action="store_true", help="print the untouched endpoint response")
    usage.set_defaults(func=cmd_usage)

    daemon = subcommands.add_parser("daemon", help="poll usage and keep the display up to date")
    daemon.add_argument(
        "--interval",
        type=float,
        default=daemon_module.POLL_INTERVAL_SECONDS,
        help="seconds between polls",
    )
    daemon.add_argument("--once", action="store_true", help="run a single cycle and exit")
    daemon.add_argument("--verbose", action="store_true", help="log at debug level")
    add_target_arguments(daemon)
    daemon.set_defaults(func=cmd_daemon)

    disconnect = subcommands.add_parser(
        "disconnect",
        help="drop the bluetooth link so macOS stops treating the device as a speaker",
    )
    add_target_arguments(disconnect)
    disconnect.set_defaults(func=cmd_disconnect)

    waiting = subcommands.add_parser("waiting", help="show which sessions wait for input")
    waiting.add_argument("--clear", action="store_true", help="forget every waiting marker")
    waiting.set_defaults(func=cmd_waiting)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
