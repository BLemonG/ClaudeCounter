from __future__ import annotations

from typing import Dict, List, Optional

from . import Candidate, Device, timebox

MODULES = {timebox.KIND: timebox}


def kinds() -> List[str]:
    return sorted(MODULES)


def module_for(kind: str):
    return MODULES.get(kind)


def driver_for(device: Optional[Device], **arguments):
    if device is None:
        return None
    module = module_for(device.kind)
    if module is None:
        return None
    return module.Driver(dict(device.settings), **arguments)


def all_candidates(gatherers: Optional[Dict[str, object]] = None) -> List[Candidate]:
    sources = gatherers or {kind: MODULES[kind].candidates for kind in MODULES}
    found: List[Candidate] = []
    for gather in sources.values():
        try:
            found.extend(gather())
        except Exception:
            continue
    return found


def supports_brightness(device: Optional[Device]) -> bool:
    if device is None:
        return False
    module = module_for(device.kind)
    return bool(module and getattr(module, "SUPPORTS_BRIGHTNESS", False))


def steals_audio(device: Optional[Device]) -> bool:
    if device is None:
        return False
    module = module_for(device.kind)
    return bool(module and getattr(module, "STEALS_AUDIO", False))


def spoken_name(device: Optional[Device]) -> str:
    if device is None:
        return "no display"
    module = module_for(device.kind)
    return getattr(module, "NAME", device.kind)


def prepare(candidate: Candidate, **arguments):
    module = module_for(candidate.kind)
    if module is None:
        return None, "is a kind this version does not know"
    return module.prepare(dict(candidate.settings), **arguments)


def show_test_image(kind: str, settings: dict, **arguments) -> bool:
    module = module_for(kind)
    if module is None:
        return False
    return module.show_test_image(dict(settings), **arguments)
