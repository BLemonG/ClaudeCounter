from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from claudecounter import config, setup
from claudecounter.displays import Candidate, Device

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

    def save(self, device):
        self.saved = device
        return Path("/tmp/config.json")

    def decline_display(self):
        self.declined = True
        return Path("/tmp/config.json")


ONE_DEVICE = [
    Candidate(
        kind="timebox-evo",
        name="TimeBox Evo",
        how="Bluetooth",
        settings={"mac": "AA:BB:CC:DD:EE:FF"},
    )
]

OTHER_KIND = Candidate(
    kind="fan-lcd", name="UNI FAN TL LCD", how="USB", settings={"serial": "7393"}
)


def wizard(dialogue, recorder, candidates=None, channel=1, arrives=True,
           at_a_terminal=True):
    offered = ONE_DEVICE if candidates is None else candidates

    def prepare(candidate):
        if channel is None:
            return None, "exposes no serial port service, it cannot show the numbers"
        return dict(candidate.settings, channel=channel), None

    return setup.run_setup(
        say=dialogue.say,
        ask=dialogue.ask,
        gather=lambda: offered,
        prepare=prepare,
        show_test_image=lambda kind, settings: arrives,
        save=recorder.save,
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
        recorder.saved is not None and recorder.saved.kind == "timebox-evo",
        "with the kind of device it is",
    )
    check(
        recorder.saved is not None
        and recorder.saved.settings["mac"] == "AA:BB:CC:DD:EE:FF",
        "the chosen address",
    )
    check(
        recorder.saved is not None and recorder.saved.settings["channel"] == 1,
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


def a_search_that_fails_still_allows_the_menu_bar() -> None:
    print("the search for displays fails")

    def no_search():
        raise RuntimeError("bluetooth helper missing")

    dialogue, recorder = Dialogue(["1"]), Recorder()
    code = setup.run_setup(
        say=dialogue.say,
        ask=dialogue.ask,
        gather=no_search,
        save=recorder.save,
        decline_display=recorder.decline_display,
        at_a_terminal=True,
    )
    check(code == 0, "the wizard finishes")
    check(recorder.declined, "the menu bar is still on offer")


def several_kinds_stand_side_by_side() -> None:
    print("more than one kind of display")
    dialogue, recorder = Dialogue(["2", "y"]), Recorder()
    code = wizard(dialogue, recorder, candidates=ONE_DEVICE + [OTHER_KIND])
    check(code == 0, "the wizard finishes")
    check(
        recorder.saved is not None and recorder.saved.kind == "fan-lcd",
        "the second kind can be chosen",
    )
    check("usb" in dialogue.spoken(), "and the list says how each one is reached")


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
            config.save_device(
                Device(kind="timebox-evo", settings={"mac": "AA:BB:CC:DD:EE:FF"})
            )
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
    a_search_that_fails_still_allows_the_menu_bar()
    several_kinds_stand_side_by_side()
    without_a_terminal_nothing_changes()
    the_declined_display_survives_a_restart()
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
