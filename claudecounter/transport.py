from __future__ import annotations

import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

HELPER_BUNDLE = Path(__file__).resolve().parent / "bin" / "ClaudeCounterBluetooth.app"
SERIAL_PORT_MARKER = "[SPP 0x1101]"
CHANNEL_PATTERN = re.compile(r"rfcomm-channel=(\d+)")
WROTE_PATTERN = re.compile(r"^wrote (\d+) bytes", re.MULTILINE)
DONE_PATTERN = re.compile(r"^done (\d+)$", re.MULTILINE)
DEVICE_PATTERN = re.compile(r"^\s{2}([0-9a-fA-F:-]{17})\s\s(.*)$", re.MULTILINE)

DEFAULT_TIMEOUT = 90.0
POLL_INTERVAL = 0.1


class TransportError(RuntimeError):
    pass


def helper_is_available() -> bool:
    return HELPER_BUNDLE.is_dir()


def run_helper(arguments: List[str], timeout: float = DEFAULT_TIMEOUT) -> Tuple[str, str]:
    if not helper_is_available():
        raise TransportError(
            f"bluetooth helper missing at {HELPER_BUNDLE}, run tools/build_native.sh"
        )
    with tempfile.TemporaryDirectory(prefix="claudecounter-") as workspace:
        stdout_path = Path(workspace) / "stdout.txt"
        stderr_path = Path(workspace) / "stderr.txt"
        stdout_path.touch()
        stderr_path.touch()
        command = [
            "open",
            "-n",
            "-a",
            str(HELPER_BUNDLE),
            "--stdout",
            str(stdout_path),
            "--stderr",
            str(stderr_path),
            "--args",
            *arguments,
        ]
        launched = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if launched.returncode != 0:
            raise TransportError(
                f"could not launch the bluetooth helper: {launched.stderr.strip()}"
            )

        deadline = time.monotonic() + timeout
        while True:
            stdout = stdout_path.read_text()
            completion = DONE_PATTERN.search(stdout)
            if completion is not None:
                stderr = stderr_path.read_text()
                break
            if time.monotonic() >= deadline:
                raise TransportError(
                    f"bluetooth helper did not report completion within {timeout}s"
                )
            time.sleep(POLL_INTERVAL)

    exit_code = int(completion.group(1))
    if exit_code != 0:
        detail = stderr.strip() or stdout.strip() or "no output"
        raise TransportError(f"bluetooth helper failed with code {exit_code}: {detail}")
    return stdout, stderr


def list_devices() -> List[Tuple[str, str]]:
    stdout, _ = run_helper(["list"], timeout=30.0)
    return [(address, name.strip()) for address, name in DEVICE_PATTERN.findall(stdout)]


def probe_serial_port_channel(mac: str) -> Optional[int]:
    stdout, _ = run_helper(["sdp", mac], timeout=45.0)
    for line in stdout.splitlines():
        if SERIAL_PORT_MARKER in line:
            match = CHANNEL_PATTERN.search(line)
            if match:
                return int(match.group(1))
    return None


def describe_device(mac: str) -> str:
    stdout, _ = run_helper(["sdp", mac], timeout=45.0)
    return stdout.rstrip()


def send_packets(
    mac: str, channel: int, payloads: Sequence[bytes], timeout: float = DEFAULT_TIMEOUT
) -> int:
    if not payloads:
        return 0
    with tempfile.TemporaryDirectory(prefix="claudecounter-") as workspace:
        payload_path = Path(workspace) / "payload.hex"
        payload_path.write_text("\n".join(payload.hex() for payload in payloads) + "\n")
        stdout, stderr = run_helper(
            ["send", mac, str(channel), str(payload_path), "0"], timeout=timeout
        )
    match = WROTE_PATTERN.search(stdout)
    if not match:
        detail = stderr.strip() or stdout.strip() or "no output"
        raise TransportError(f"the device did not accept the packet: {detail}")
    return int(match.group(1))



def disconnect(mac: str, timeout: float = 30.0) -> str:
    stdout, _ = run_helper(["disconnect", mac], timeout=timeout)
    return stdout.rstrip()
