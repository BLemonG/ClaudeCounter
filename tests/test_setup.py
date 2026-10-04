from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from claudecounter import config, setup, transport

FAILURES = []


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


class Dialogue:
    def __init__(self, answers) -> None:
        self.answers = list(answers)
        self.said = []
        self.asked = []

    def say(self, line: str = "") -> None:
        self.said.append(line)

    def ask(self, question: str) -> str:
        self.asked.append(question)
        if not self.answers:
            raise AssertionError("the wizard asked more often than the test answers")
        return self.answers.pop(0)

    def spoken(self) -> str:
        return "\n".join(self.said).lower()


class Recorder:
    def __init__(self) -> None:
        self.saved = None
        self.declined = False
        self.shown = []

    def save_device(self, device):
        self.saved = device
        return Path("/tmp/config.json")

    def decline_display(self):
        self.declined = True
        return Path("/tmp/config.json")


ONE_DEVICE = [("AA:BB:CC:DD:EE:FF", "TimeBox Evo")]


def wizard(dialogue, recorder, devices=ONE_DEVICE, channel=1, arrives=True,
           at_a_terminal=True):
    return setup.run_setup(
        say=dialogue.say,
        ask=dialogue.ask,
        list_devices=lambda: devices,
        probe_channel=lambda mac: channel,
        show_test_image=lambda mac, channel: arrives,
        save_device=recorder.save_device,
        decline_display=recorder.decline_display,
        at_a_terminal=at_a_terminal,
    )


def a_chosen_device_is_stored() -> None:
    print("choosing the device")
    dialogue, recorder = Dialogue(["1", "y"]), Recorder()
    code = wizard(dialogue, recorder)
    check(code == 0, "the wizard finishes")
    check(recorder.saved is not None, "the device is stored")
    check(
        recorder.saved is not None and recorder.saved.mac == "AA:BB:CC:DD:EE:FF",
        "with the chosen address",
    )
    check(
        recorder.saved is not None and recorder.saved.channel == 1,
        "and the probed channel",
    )
    check(not recorder.declined, "and the display is not declined")


def choosing_no_device_is_stored_as_well() -> None:
    print("choosing no device")
    dialogue, recorder = Dialogue(["2"]), Recorder()
    code = wizard(dialogue, recorder)
    check(code == 0, "the wizard finishes")
    check(recorder.declined, "the answer is written down")
    check(recorder.saved is None, "and no device is stored")
    check("menu" in dialogue.spoken(), "the choice names the menu bar")


def a_test_image_that_never_arrives_asks_again() -> None:
    print("the test image never arrives")
    dialogue, recorder = Dialogue(["1", "n", "2"]), Recorder()
    code = wizard(dialogue, recorder, arrives=True)
    check(code == 0, "the wizard finishes")
    check(recorder.saved is None, "a device that showed nothing is not stored")
    check(recorder.declined, "the second answer is taken instead")


def a_device_without_a_serial_port_is_refused() -> None:
    print("device without a serial port")
    dialogue, recorder = Dialogue(["1", "2"]), Recorder()
    code = wizard(dialogue, recorder, channel=None)
    check(code == 0, "the wizard carries on")
    check(recorder.saved is None, "the device is not stored")
    check("serial port" in dialogue.spoken(), "and the reason is spoken out")


def unreadable_answers_are_asked_again() -> None:
    print("unreadable answer")
    dialogue, recorder = Dialogue(["nonsense", "7", "2"]), Recorder()
    code = wizard(dialogue, recorder)
    check(code == 0, "the wizard carries on")
    check(recorder.declined, "and takes the first answer it understands")
    check(len(dialogue.asked) == 3, "every unreadable answer is asked again")


def bluetooth_trouble_still_allows_the_menu_bar() -> None:
    print("bluetooth trouble")

    def no_bluetooth():
        raise transport.TransportError("bluetooth helper missing")

    dialogue, recorder = Dialogue(["1"]), Recorder()
    code = setup.run_setup(
        say=dialogue.say,
        ask=dialogue.ask,
        list_devices=no_bluetooth,
        probe_channel=lambda mac: 1,
        show_test_image=lambda mac, channel: True,
        save_device=recorder.save_device,
        decline_display=recorder.decline_display,
        at_a_terminal=True,
    )
    check(code == 0, "the wizard finishes")
    check(recorder.declined, "the menu bar is still on offer")


def without_a_terminal_nothing_changes() -> None:
    print("no terminal")
    dialogue, recorder = Dialogue([]), Recorder()
    code = wizard(dialogue, recorder, at_a_terminal=False)
    check(code == 1, "the wizard refuses")
    check(recorder.saved is None and not recorder.declined, "and changes nothing")
    check(not dialogue.asked, "and asks nothing")


def the_declined_display_survives_a_restart() -> None:
    print("the stored answer")
    with tempfile.TemporaryDirectory() as folder:
        kept_directory, kept_path = config.CONFIG_DIRECTORY, config.CONFIG_PATH
        config.CONFIG_DIRECTORY = Path(folder)
        config.CONFIG_PATH = Path(folder) / "config.json"
        try:
            check(not config.setup_was_done(), "a fresh machine has nothing stored")
            config.save_declined_display()
            check(config.display_was_declined(), "the declined display is remembered")
            check(config.setup_was_done(), "and counts as a finished setup")
            check(config.load_config() is None, "and leaves no device behind")
            config.save_config(config.DeviceConfig(mac="AA:BB:CC:DD:EE:FF", channel=1))
            check(not config.display_was_declined(), "a device overrules it")
            check(config.setup_was_done(), "and counts as a finished setup too")
        finally:
            config.CONFIG_DIRECTORY, config.CONFIG_PATH = kept_directory, kept_path


def main() -> int:
    a_chosen_device_is_stored()
    choosing_no_device_is_stored_as_well()
    a_test_image_that_never_arrives_asks_again()
    a_device_without_a_serial_port_is_refused()
    unreadable_answers_are_asked_again()
    bluetooth_trouble_still_allows_the_menu_bar()
    without_a_terminal_nothing_changes()
    the_declined_display_survives_a_restart()
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
