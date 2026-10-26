from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from claudecounter import config, protocol
from claudecounter.displays import Device, registry, timebox
from claudecounter.snapshot import UsageSnapshot

FAILURES = []


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


def reading() -> UsageSnapshot:
    return UsageSnapshot(
        session_pct=42.0,
        session_resets_at=None,
        weekly_pct=17.0,
        weekly_resets_at=None,
        fetched_at="2026-10-26T10:00:00+00:00",
    )


class FakeSender:
    def __init__(self) -> None:
        self.sent = []

    def __call__(self, mac, channel, payloads) -> int:
        self.sent.append((mac, channel, list(payloads)))
        return sum(len(payload) for payload in payloads)


TIMEBOX = Device(kind=timebox.KIND, settings={"mac": "AA:BB:CC:DD:EE:FF", "channel": 1})


def the_timebox_is_a_known_kind() -> None:
    print("the register of kinds")
    check(timebox.KIND in registry.kinds(), "the timebox is registered")
    check(registry.module_for(timebox.KIND) is timebox, "and found by its kind")
    check(registry.module_for("made-up") is None, "an unknown kind is not invented")
    check(
        registry.driver_for(Device(kind="made-up", settings={})) is None,
        "and gets no driver",
    )


def candidates_say_what_they_are() -> None:
    print("what the wizard gets offered")
    found = timebox.candidates(
        list_devices=lambda: [("AA:BB:CC:DD:EE:FF", "TimeBox Evo")]
    )
    check(len(found) == 1, "one paired device makes one candidate")
    only = found[0]
    check(only.kind == timebox.KIND, "the candidate carries its kind")
    check(only.name == "TimeBox Evo", "and the device name")
    check(only.how == "Bluetooth", "and how it is reached")
    check(only.settings["mac"] == "AA:BB:CC:DD:EE:FF", "and the address to store")
    everything = registry.all_candidates(
        {timebox.KIND: lambda: timebox.candidates(
            list_devices=lambda: [("AA:BB:CC:DD:EE:FF", "TimeBox Evo")]
        )}
    )
    check(len(everything) == 1, "the register gathers candidates of every kind")


def a_driver_draws_and_sends() -> None:
    print("the driver")
    sender = FakeSender()
    driver = registry.driver_for(TIMEBOX, send_packets=sender)
    check(driver is not None, "a known kind has a driver")
    payloads, description = driver.frames_for(reading(), waiting=False)
    check(len(payloads) == 1, "a quiet reading is one packet")
    check("42" in description, "the description names the session percentage")
    breathing, breathing_description = driver.frames_for(reading(), waiting=True)
    check(len(breathing) > 1, "a waiting session breathes in several packets")
    check("waiting" in breathing_description, "and says so")

    written = driver.send(payloads)
    check(written > 0, "sending reports the written bytes")
    check(len(sender.sent) == 1, "the transport was asked once")
    mac, channel, sent = sender.sent[0]
    check(mac == "AA:BB:CC:DD:EE:FF" and channel == 1, "with the stored address")
    check(sent == payloads, "and the packets it was given")


def brightness_is_a_capability() -> None:
    print("brightness")
    driver = registry.driver_for(TIMEBOX, send_packets=FakeSender())
    check(timebox.SUPPORTS_BRIGHTNESS, "the timebox can be dimmed")
    check(
        driver.brightness_payload(40) == protocol.brightness_packet(40),
        "and the driver uses the known packet",
    )


def the_stored_device_keeps_its_kind() -> None:
    print("what config.json holds")
    with tempfile.TemporaryDirectory() as folder:
        kept_directory, kept_path = config.CONFIG_DIRECTORY, config.CONFIG_PATH
        config.CONFIG_DIRECTORY = Path(folder)
        config.CONFIG_PATH = Path(folder) / "config.json"
        try:
            config.save_device(TIMEBOX)
            stored = config.load_device()
            check(stored == TIMEBOX, "a saved device comes back unchanged")
            check(
                config.load_config() is not None,
                "and still reads as a timebox for the old commands",
            )

            config.CONFIG_PATH.write_text('{"mac": "11:22:33:44:55:66", "channel": 1}')
            old = config.load_device()
            check(
                old is not None and old.kind == timebox.KIND,
                "a file from before the kinds counts as a timebox",
            )
            check(
                old is not None and old.settings["mac"] == "11:22:33:44:55:66",
                "with its address kept",
            )

            config.save_declined_display()
            check(config.load_device() is None, "a declined display stores no device")
            check(config.display_was_declined(), "and is still remembered as declined")
        finally:
            config.CONFIG_DIRECTORY, config.CONFIG_PATH = kept_directory, kept_path


def main() -> int:
    the_timebox_is_a_known_kind()
    candidates_say_what_they_are()
    a_driver_draws_and_sends()
    brightness_is_a_capability()
    the_stored_device_keeps_its_kind()
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
