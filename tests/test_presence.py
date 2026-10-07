from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudecounter import presence

FAILURES = []


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


SHORT_SPELLING = """[ NULL ]  ASN:0x0-0x25025: (in front)
    bundleID="com.github.GitHubClient"
    bundle path=[ NULL ]
    executable path=[ NULL ]
 !cgsConnection !signalled type=[ NULL ]  flavor=[ NULL ]  Version=[ NULL ]  Arch=!!none
"""

LONG_SPELLING = """ASN:0x0-0x25025: "Claude"
    "CFBundleIdentifier"="com.anthropic.claudefordesktop"
"""


def both_spellings_are_understood() -> None:
    print("the two spellings lsappinfo uses")
    check(
        presence.bundle_id_from(SHORT_SPELLING) == "com.github.GitHubClient",
        "bundleID= is read",
    )
    check(
        presence.bundle_id_from(LONG_SPELLING) == "com.anthropic.claudefordesktop",
        'and "CFBundleIdentifier"= as well',
    )


def nonsense_is_no_bundle_id() -> None:
    print("output without a bundle id")
    check(presence.bundle_id_from("") is None, "empty output gives nothing")
    check(presence.bundle_id_from("[ NULL ]") is None, "and so does a blank entry")
    check(presence.bundle_id_from('bundleID=""') is None, "an empty name counts as none")


def the_frontmost_app_is_found_on_this_mac() -> None:
    print("the mac answering right now")
    found = presence.frontmost_bundle_id()
    check(found is not None, "lsappinfo names the frontmost app")
    check(
        found is None or "." in found,
        f"and it looks like a bundle id ({found})",
    )


def main() -> int:
    both_spellings_are_understood()
    nonsense_is_no_bundle_id()
    the_frontmost_app_is_found_on_this_mac()
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
