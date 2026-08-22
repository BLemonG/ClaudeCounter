from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudecounter import protocol
from claudecounter import render as renderer
from claudecounter.snapshot import UsageSnapshot, utc_now_iso

FAILURES = []

BRIGHTNESS_GOLDEN = "01 04 00 74 2a a2 00 02"

SMILEY_GOLDEN = (
    "01 0e 01 44 00 0a 0a 04 aa 07 01 00 00 00 20 00 00 00 31 1c 00 83 5e 00 be 8b 03 cb 95 00 61 "
    "41 00 e2 b1 34 f0 da 7b fe eb 9c fb cf 6b 84 6b 28 53 55 53 b2 a3 7f c1 a1 48 e6 be 4e fa fc "
    "f9 33 66 9a b6 80 00 76 78 75 67 99 ca fa c2 3e a4 a1 91 c7 ab 61 a8 70 0d b6 a6 74 f3 c0 53 "
    "8d 56 00 ba 86 1c d1 99 30 22 0f 00 3b 22 00 7c 44 00 00 80 20 06 21 64 88 00 00 00 00 94 61 "
    "0e 42 e8 98 51 00 00 a0 90 84 10 42 08 a1 44 0a 00 41 ad b5 16 43 6c ad b5 54 00 62 35 e7 da "
    "3a ab 39 d7 96 00 60 99 07 dd 5a cb c1 67 16 00 51 9a 37 8d a4 d2 cc 67 64 04 b1 5a 4a 2d a3 "
    "d5 52 6a 6b 04 d7 61 c6 30 a5 19 33 86 dd 05 da 50 4a 29 a5 94 52 4a 8d 06 65 53 ca 73 ce 39 "
    "73 4a 77 01 5d 73 9a f7 de 7b 67 ca 75 07 c0 6b 9e 53 4a 29 65 ae 3d 00 00 f4 7f 79 4e 99 df "
    "df 01 00 00 00 10 fe d7 ff 07 00 00 00 00 00 00 00 00 00 00 00 00 00 b7 69 02"
)

DIVO_FOUR_COLOUR = (
    "015a0044000a0a04aa5300f4010004000000ff0000ff5500ffffffe40000c0000000300000000c000000030000c00000"
    "00300000000c000000030000c0000000300000000c000000030000c0000000300000000c00000003000000dc0c02"
)

DIVO_EIGHT_COLOUR = (
    "01860044000a0a04aa7f00f40100080000004dbbef2989c8c1c3c5ff9f00ffffff1f1f30bf5c15000020010000000024"
    "02000000002402000000004402000000904409000000922449b00140922449b20d64d22469420e64e22471420e27e324"
    "71c80ff89b2449ff0d00d6b6adb60d00a06d92b40d00a06d89a40100106d89a401001049893400512802"
)

DIVO_EIGHTEEN_COLOUR = (
    "01e40044000a0a04aadd00f401001212173dffffffff0000000000293268ffaa00f193ed7b757bffff02e547da00ff00"
    "5b585b00aaff6b74b2aa01ff909eddc1d9f2a5e6ff0004000000000000000000000000000000004000420821c618638c"
    "4108214208314a29659432c820a594518a31e38c31c619a594518c31e39c73ce1908a1518c49e38471c21808a1519231"
    "e38c71c6184aa9518c31c39cb38e194aa9518a49e3ac75d6198c31364a29658c31c6688c3176c618638c735a6bce39b7"
    "d67befbdb5de7bce39f7de7befbdf7c27b1042082184104218608031400821841042080384515d02"
)


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


def as_bytes(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


def split_packet(raw: bytes):
    declared_length = raw[1] | (raw[2] << 8)
    command = raw[3]
    arguments = raw[4:-3]
    trailing_checksum = raw[-3:-1]
    return declared_length, command, arguments, trailing_checksum


def split_frame(arguments: bytes):
    header = tuple(arguments[0:4])
    marker = arguments[4]
    declared_frame_length = arguments[5] | (arguments[6] << 8)
    body = arguments[7:]
    duration = tuple(body[0:2])
    palette_flag = body[2]
    declared_palette_size = body[3]
    palette_size = protocol.PALETTE_SIZE_ROLLOVER if declared_palette_size == 0 else declared_palette_size
    colors = [
        (body[4 + index * 3], body[5 + index * 3], body[6 + index * 3])
        for index in range(palette_size)
    ]
    packed = body[4 + palette_size * 3 :]
    return header, marker, declared_frame_length, duration, palette_flag, palette_size, colors, packed


def envelope_matches_the_reference(name: str, raw: bytes) -> None:
    declared_length, command, arguments, trailing_checksum = split_packet(raw)
    check(raw[0] == protocol.START_OF_PACKET, f"{name}: starts with 0x01")
    check(raw[-1] == protocol.END_OF_PACKET, f"{name}: ends with 0x02")
    check(declared_length == len(arguments) + 3, f"{name}: LEN equals len(args) + 3")
    check(
        bytes(trailing_checksum) == protocol.checksum(raw[1:-3]),
        f"{name}: CRC is the little endian sum over LEN, CMD and args",
    )
    check(command == protocol.COMMAND_SET_IMAGE, f"{name}: command is 0x44")


def reference_frame_re_encodes_byte_for_byte(name: str, text: str) -> None:
    print(f"reference frame {name}")
    raw = as_bytes(text)
    envelope_matches_the_reference(name, raw)

    _, _, arguments, _ = split_packet(raw)
    (
        header,
        marker,
        declared_frame_length,
        duration,
        palette_flag,
        palette_size,
        colors,
        packed,
    ) = split_frame(arguments)

    check(header == protocol.SINGLE_FRAME_HEADER, f"{name}: single frame header is 00 0a 0a 04")
    check(marker == protocol.FRAME_MARKER, f"{name}: frame marker is 0xaa")
    check(
        declared_frame_length == len(arguments) - 7 + 3,
        f"{name}: FLEN equals len(frame body) + 3",
    )
    check(palette_flag == 0x00, f"{name}: palette flag is 0x00")

    pixel_count = renderer.SIZE * renderer.SIZE
    expected_packed_length = -(-pixel_count * protocol.bits_per_pixel(palette_size) // 8)
    check(
        len(packed) == expected_packed_length,
        f"{name}: {palette_size} colours pack {pixel_count} pixels into {expected_packed_length} bytes",
    )

    indices = protocol.unpack_pixels(packed, palette_size, pixel_count)
    check(len(indices) == pixel_count, f"{name}: unpacks to exactly {pixel_count} indices")
    check(
        protocol.pack_pixels(indices, palette_size) == packed,
        f"{name}: pack is the exact inverse of unpack",
    )

    rebuilt_frame = protocol.encode_frame(colors, indices, duration)
    check(rebuilt_frame == arguments[4:], f"{name}: encoder reproduces the frame byte for byte")

    rebuilt_packet = protocol.packet(
        protocol.COMMAND_SET_IMAGE, bytes(protocol.SINGLE_FRAME_HEADER) + rebuilt_frame
    )
    check(rebuilt_packet == raw, f"{name}: encoder reproduces the whole packet byte for byte")


def brightness_matches_the_golden() -> None:
    print("brightness command")
    check(
        protocol.brightness_packet(42) == as_bytes(BRIGHTNESS_GOLDEN),
        "brightness 42 reproduces the hass-divoom Timebox golden",
    )
    check(protocol.brightness_packet(-10)[4] == 0, "negative brightness clamps to 0")
    check(protocol.brightness_packet(500)[4] == 100, "brightness above 100 clamps to 100")


def bit_width_follows_the_palette() -> None:
    print("bit width")
    for palette_size, expected in ((1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (8, 3), (32, 5), (256, 8)):
        check(
            protocol.bits_per_pixel(palette_size) == expected,
            f"{palette_size} colours need {expected} bit(s) per pixel",
        )


def packing_round_trips_for_every_width() -> None:
    print("pack round trip")
    for palette_size in (2, 3, 4, 7, 8, 16, 32, 100, 256):
        indices = [index % palette_size for index in range(renderer.SIZE * renderer.SIZE)]
        packed = protocol.pack_pixels(indices, palette_size)
        restored = protocol.unpack_pixels(packed, palette_size, len(indices))
        check(restored == indices, f"{palette_size} colours round trip through pack and unpack")


def rendered_frames_produce_valid_packets() -> None:
    print("rendered frames")
    fixed_now = datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc)
    cases = (
        (0.0, 0.0, False, None, None),
        (82.0, 41.0, False, None, None),
        (82.0, 41.0, False, 150, 84),
        (100.0, 97.0, True, 12, 3),
    )
    for session, weekly, stale, resets_in_minutes, weekly_resets_in_hours in cases:
        session_resets_at = None
        if resets_in_minutes is not None:
            session_resets_at = (fixed_now + timedelta(minutes=resets_in_minutes)).isoformat()
        weekly_resets_at = None
        if weekly_resets_in_hours is not None:
            weekly_resets_at = (fixed_now + timedelta(hours=weekly_resets_in_hours)).isoformat()
        snapshot = UsageSnapshot(
            session_pct=session,
            session_resets_at=session_resets_at,
            weekly_pct=weekly,
            weekly_resets_at=weekly_resets_at,
            fetched_at=fixed_now.isoformat(),
            stale=stale,
        )
        image = renderer.render(snapshot)
        raw = protocol.image_packet(image)
        label = f"session={int(session)} weekly={int(weekly)} stale={stale} marker={resets_in_minutes is not None}"

        declared_length, command, arguments, trailing_checksum = split_packet(raw)
        check(raw[0] == protocol.START_OF_PACKET and raw[-1] == protocol.END_OF_PACKET, f"{label}: framed by 0x01 and 0x02")
        check(command == protocol.COMMAND_SET_IMAGE, f"{label}: uses command 0x44")
        check(declared_length == len(arguments) + 3, f"{label}: LEN is consistent")
        check(bytes(trailing_checksum) == protocol.checksum(raw[1:-3]), f"{label}: CRC is consistent")

        (
            header,
            marker,
            declared_frame_length,
            duration,
            palette_flag,
            palette_size,
            colors,
            packed,
        ) = split_frame(arguments)
        check(header == protocol.SINGLE_FRAME_HEADER, f"{label}: carries the single frame header")
        check(marker == protocol.FRAME_MARKER, f"{label}: carries the frame marker")
        check(declared_frame_length == len(arguments) - 7 + 3, f"{label}: FLEN is consistent")
        check(duration == protocol.STILL_FRAME_DURATION, f"{label}: still frames declare zero duration")
        check(palette_size <= 8, f"{label}: palette stays at {palette_size} colours")

        indices = protocol.unpack_pixels(packed, palette_size, renderer.SIZE * renderer.SIZE)
        pixels = image.load()
        original = [
            pixels[x, y] for y in range(renderer.SIZE) for x in range(renderer.SIZE)
        ]
        decoded = [colors[index] for index in indices]
        check(decoded == original, f"{label}: decoding the packet reproduces every rendered pixel")

        check(len(raw) < 1024, f"{label}: packet is {len(raw)} bytes")


def main() -> int:
    brightness_matches_the_golden()
    reference_frame_re_encodes_byte_for_byte("hass-divoom Timebox smiley16", SMILEY_GOLDEN)
    reference_frame_re_encodes_byte_for_byte("divo 4 colour test", DIVO_FOUR_COLOUR)
    reference_frame_re_encodes_byte_for_byte("divo 8 colour test", DIVO_EIGHT_COLOUR)
    reference_frame_re_encodes_byte_for_byte("divo 18 colour test", DIVO_EIGHTEEN_COLOUR)
    bit_width_follows_the_palette()
    packing_round_trips_for_every_width()
    rendered_frames_produce_valid_packets()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
