from __future__ import annotations

import sys
from typing import Callable, List, Optional, Tuple

from . import protocol, transport
from . import render as renderer
from .config import DeviceConfig, save_config, save_declined_display
from .snapshot import UsageSnapshot, utc_now_iso

TEST_IMAGE_SESSION = 42.0
TEST_IMAGE_WEEKLY = 17.0

AGREEING_ANSWERS = {"y", "yes", "j", "ja"}


def test_image_snapshot() -> UsageSnapshot:
    return UsageSnapshot(
        session_pct=TEST_IMAGE_SESSION,
        session_resets_at=None,
        weekly_pct=TEST_IMAGE_WEEKLY,
        weekly_resets_at=None,
        fetched_at=utc_now_iso(),
    )


def show_test_image(mac: str, channel: int) -> bool:
    packet = protocol.image_packet(renderer.render(test_image_snapshot()))
    try:
        transport.send_packets(mac, channel, [packet])
    except transport.TransportError:
        return False
    return True


def paired_devices(list_devices: Callable[[], List[Tuple[str, str]]], say) -> List[Tuple[str, str]]:
    try:
        return list(list_devices())
    except transport.TransportError as failure:
        say(f"could not look at the paired bluetooth devices: {failure}")
        return []


def offer_the_choices(devices, say) -> int:
    say("")
    say("Which display should ClaudeCounter draw on?")
    for number, (address, name) in enumerate(devices, start=1):
        say(f"  {number}) {name}  {address}")
    without = len(devices) + 1
    say(f"  {without}) no display, only the menu bar")
    say("")
    return without


def chosen_number(answer: str, highest: int) -> Optional[int]:
    try:
        number = int(answer.strip())
    except ValueError:
        return None
    return number if 1 <= number <= highest else None


def run_setup(
    say=print,
    ask=input,
    list_devices=transport.list_devices,
    probe_channel=transport.probe_serial_port_channel,
    show_test_image=show_test_image,
    save_device=save_config,
    decline_display=save_declined_display,
    at_a_terminal: Optional[bool] = None,
) -> int:
    if at_a_terminal is None:
        at_a_terminal = sys.stdin.isatty()
    if not at_a_terminal:
        say("setup needs a terminal, run it by hand: python3 -m claudecounter setup")
        return 1

    devices = paired_devices(list_devices, say)

    while True:
        without = offer_the_choices(devices, say)
        chosen = chosen_number(ask(f"choose 1-{without}: "), without)
        if chosen is None:
            say(f"please answer with a number between 1 and {without}")
            continue

        if chosen == without:
            path = decline_display()
            say(f"wrote {path}, the numbers will only show in the menu bar")
            return 0

        address, name = devices[chosen - 1]
        try:
            channel = probe_channel(address)
        except transport.TransportError as failure:
            say(f"could not ask {name} for its services: {failure}")
            continue
        if channel is None:
            say(f"{name} exposes no serial port service, it cannot show the numbers")
            continue

        say(f"sending a test image to {name} on rfcomm channel {channel} ...")
        if not show_test_image(address, channel):
            say(f"the test image did not go through to {name}")
            continue

        if ask("did the display show a ring with 42 in it? [y/n] ").strip().lower() not in AGREEING_ANSWERS:
            say("then that was the wrong device")
            continue

        path = save_device(DeviceConfig(mac=address, channel=channel))
        say(f"wrote {path}, ClaudeCounter will draw on {name}")
        return 0
