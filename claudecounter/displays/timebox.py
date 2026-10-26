from __future__ import annotations

from typing import List, Optional, Tuple

from .. import protocol, transport
from .. import render as renderer
from ..snapshot import UsageSnapshot
from . import Candidate

KIND = "timebox-evo"
NAME = "Divoom Timebox Evo"
HOW = "Bluetooth"
SUPPORTS_BRIGHTNESS = True
STEALS_AUDIO = True
DEFAULT_CHANNEL = 1


def candidates(list_devices=transport.list_devices) -> List[Candidate]:
    return [
        Candidate(kind=KIND, name=name, how=HOW, settings={"mac": address})
        for address, name in list_devices()
    ]


def prepare(settings: dict, probe_channel=transport.probe_serial_port_channel):
    mac = str(settings.get("mac", ""))
    if not mac:
        return None, "no address to talk to"
    channel = settings.get("channel")
    if channel is None:
        channel = probe_channel(mac)
    if channel is None:
        return None, "exposes no serial port service, it cannot show the numbers"
    return {"mac": mac, "channel": int(channel)}, None


class Driver:
    def __init__(self, settings: dict, send_packets=transport.send_packets) -> None:
        self.mac = str(settings.get("mac", ""))
        self.channel = int(settings.get("channel", DEFAULT_CHANNEL))
        self.send_packets = send_packets

    def spoken(self) -> str:
        return f"target {self.mac} channel {self.channel}"

    def frames_for(
        self,
        snapshot: Optional[UsageSnapshot],
        waiting: bool,
        active_days=None,
        active_hours=None,
    ) -> Tuple[List[bytes], str]:
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

    def brightness_payload(self, level: int) -> bytes:
        return protocol.brightness_packet(level)

    def send(self, payloads) -> int:
        return self.send_packets(self.mac, self.channel, payloads)


def show_test_image(settings: dict, send_packets=transport.send_packets) -> bool:
    driver = Driver(settings, send_packets=send_packets)
    picture = UsageSnapshot(
        session_pct=42.0,
        session_resets_at=None,
        weekly_pct=17.0,
        weekly_resets_at=None,
        fetched_at="",
    )
    payloads, _ = driver.frames_for(picture, waiting=False)
    try:
        driver.send(payloads)
    except transport.TransportError:
        return False
    return True
