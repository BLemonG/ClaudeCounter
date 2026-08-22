from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

START_OF_PACKET = 0x01
END_OF_PACKET = 0x02
FRAME_MARKER = 0xAA
SINGLE_FRAME_HEADER = (0x00, 0x0A, 0x0A, 0x04)

COMMAND_SET_IMAGE = 0x44
COMMAND_SET_ANIMATION_FRAME = 0x49
COMMAND_SET_BRIGHTNESS = 0x74

STILL_FRAME_DURATION = (0x00, 0x00)
PALETTE_SIZE_ROLLOVER = 256
ANIMATION_CHUNK_BYTES = 200
ANIMATION_MAXIMUM_CHUNKS = 256

Color = Tuple[int, int, int]


def little_endian_pair(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def checksum(payload: bytes) -> bytes:
    return little_endian_pair(sum(payload) & 0xFFFF)


def packet(command: int, arguments: bytes = b"") -> bytes:
    payload = little_endian_pair(len(arguments) + 3) + bytes((command,)) + arguments
    return bytes((START_OF_PACKET,)) + payload + checksum(payload) + bytes((END_OF_PACKET,))


def bits_per_pixel(palette_size: int) -> int:
    width = 1
    while (1 << width) < palette_size:
        width += 1
    return width


def pack_pixels(indices: Sequence[int], palette_size: int) -> bytes:
    width = bits_per_pixel(palette_size)
    mask = (1 << width) - 1
    accumulator = 0
    pending_bits = 0
    packed = bytearray()
    for index in indices:
        accumulator |= (index & mask) << pending_bits
        pending_bits += width
        while pending_bits >= 8:
            packed.append(accumulator & 0xFF)
            accumulator >>= 8
            pending_bits -= 8
    if pending_bits > 0:
        packed.append(accumulator & 0xFF)
    return bytes(packed)


def unpack_pixels(packed: bytes, palette_size: int, count: int) -> List[int]:
    width = bits_per_pixel(palette_size)
    mask = (1 << width) - 1
    accumulator = 0
    available_bits = 0
    indices: List[int] = []
    for byte in packed:
        accumulator |= byte << available_bits
        available_bits += 8
        while available_bits >= width and len(indices) < count:
            indices.append(accumulator & mask)
            accumulator >>= width
            available_bits -= width
    return indices


def quantize(image) -> Tuple[List[Color], List[int]]:
    pixels = image.load()
    palette: List[Color] = []
    index_by_color: Dict[Color, int] = {}
    indices: List[int] = []
    for y in range(image.height):
        for x in range(image.width):
            color = pixels[x, y]
            index = index_by_color.get(color)
            if index is None:
                index = len(palette)
                index_by_color[color] = index
                palette.append(color)
            indices.append(index)
    return palette, indices


def encode_frame(
    palette: Sequence[Color],
    indices: Sequence[int],
    duration: Sequence[int] = STILL_FRAME_DURATION,
) -> bytes:
    palette_size = len(palette)
    declared_size = 0 if palette_size >= PALETTE_SIZE_ROLLOVER else palette_size
    body = bytes(duration) + bytes((0x00, declared_size))
    for red, green, blue in palette:
        body += bytes((red, green, blue))
    body += pack_pixels(indices, palette_size)
    return bytes((FRAME_MARKER,)) + little_endian_pair(len(body) + 3) + body


def image_packet(image) -> bytes:
    palette, indices = quantize(image)
    frame = encode_frame(palette, indices)
    return packet(COMMAND_SET_IMAGE, bytes(SINGLE_FRAME_HEADER) + frame)


def animation_stream(frames: Iterable[Tuple[object, int]]) -> bytes:
    body = b""
    for image, milliseconds in frames:
        palette, indices = quantize(image)
        body += encode_frame(palette, indices, little_endian_pair(milliseconds))
    return body


def animation_packets(frames: Iterable[Tuple[object, int]]) -> List[bytes]:
    stream = animation_stream(frames)
    if not stream:
        return []
    chunk_count = -(-len(stream) // ANIMATION_CHUNK_BYTES)
    if chunk_count > ANIMATION_MAXIMUM_CHUNKS:
        raise ValueError(
            f"an animation of {len(stream)} bytes needs {chunk_count} packets, "
            f"the packet counter only reaches {ANIMATION_MAXIMUM_CHUNKS}"
        )
    total = little_endian_pair(len(stream))
    packets = []
    for number in range(chunk_count):
        start = number * ANIMATION_CHUNK_BYTES
        chunk = stream[start : start + ANIMATION_CHUNK_BYTES]
        arguments = total + bytes((number,)) + chunk
        packets.append(packet(COMMAND_SET_ANIMATION_FRAME, arguments))
    return packets


def brightness_packet(level: int) -> bytes:
    return packet(COMMAND_SET_BRIGHTNESS, bytes((max(0, min(100, int(level))),)))
