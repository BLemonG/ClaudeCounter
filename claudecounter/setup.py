from __future__ import annotations

import sys
from typing import List, Optional

from .config import save_declined_display, save_device
from .displays import Candidate, Device, registry

AGREEING_ANSWERS = {"y", "yes", "j", "ja"}


def offer_the_choices(candidates: List[Candidate], say) -> int:
    say("")
    say("Which display should ClaudeCounter draw on?")
    for number, candidate in enumerate(candidates, start=1):
        say(f"  {number}) {candidate.spoken()}")
    without = len(candidates) + 1
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
    gather=registry.all_candidates,
    prepare=registry.prepare,
    show_test_image=registry.show_test_image,
    save=save_device,
    decline_display=save_declined_display,
    at_a_terminal: Optional[bool] = None,
) -> int:
    if at_a_terminal is None:
        at_a_terminal = sys.stdin.isatty()
    if not at_a_terminal:
        say("setup needs a terminal, run it by hand: python3 -m claudecounter setup")
        return 1

    try:
        candidates = list(gather())
    except Exception:
        say("could not look for displays, offering the menu bar only")
        candidates = []

    while True:
        without = offer_the_choices(candidates, say)
        chosen = chosen_number(ask(f"choose 1-{without}: "), without)
        if chosen is None:
            say(f"please answer with a number between 1 and {without}")
            continue

        if chosen == without:
            path = decline_display()
            say(f"wrote {path}, the numbers will only show in the menu bar")
            return 0

        candidate = candidates[chosen - 1]
        settings, trouble = prepare(candidate)
        if settings is None:
            say(f"{candidate.name} {trouble}")
            continue

        say(f"sending a test image to {candidate.name} ...")
        if not show_test_image(candidate.kind, settings):
            say(f"the test image did not go through to {candidate.name}")
            continue

        if ask("did the display show a ring with 42 in it? [y/n] ").strip().lower() not in AGREEING_ANSWERS:
            say("then that was the wrong device")
            continue

        path = save(Device(kind=candidate.kind, settings=settings))
        say(f"wrote {path}, ClaudeCounter will draw on {candidate.name}")
        return 0
