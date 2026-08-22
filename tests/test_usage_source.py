from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claudecounter import usage_source
from claudecounter.snapshot import UsageSnapshot

FAILURES = []

SECRET_TOKEN = "placeholder-token-DO-NOT-LEAK-THIS-VALUE"

REALISTIC_PAYLOAD = {
    "five_hour": {"utilization": 82.4, "resets_at": "2026-08-22T20:00:00Z"},
    "seven_day": {"utilization": 41.0, "resets_at": "2026-08-26T13:00:00Z"},
    "seven_day_sonnet": {"utilization": 12.5, "resets_at": "2026-08-26T13:00:00Z"},
}


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


def expect_error(expected, call, description: str):
    try:
        call()
    except expected as failure:
        check(True, description)
        return failure
    except Exception as failure:
        check(False, f"{description} (raised {type(failure).__name__} instead)")
        return failure
    check(False, f"{description} (raised nothing)")
    return None


def credentials(expires_in_hours: float = 5.0, token: str = SECRET_TOKEN) -> dict:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
    return {
        "accessToken": token,
        "refreshToken": "refresh-" + token,
        "expiresAt": expires_at.timestamp() * 1000.0,
        "scopes": ["user:inference"],
    }


def the_documented_schema_maps_to_the_contract() -> None:
    print("schema mapping")
    snapshot = usage_source.snapshot_from_payload(REALISTIC_PAYLOAD)
    check(isinstance(snapshot, UsageSnapshot), "produces a UsageSnapshot")
    check(snapshot.session_pct == 82.4, "five_hour.utilization becomes session_pct")
    check(snapshot.weekly_pct == 41.0, "seven_day.utilization becomes weekly_pct")
    check(
        snapshot.session_resets_at == "2026-08-22T20:00:00Z",
        "five_hour.resets_at becomes session_resets_at",
    )
    check(
        snapshot.weekly_resets_at == "2026-08-26T13:00:00Z",
        "seven_day.resets_at becomes weekly_resets_at",
    )
    check(snapshot.stale is False, "a fresh read is not stale")
    check(bool(snapshot.fetched_at), "the snapshot carries a fetch timestamp")


def a_broken_schema_is_rejected_rather_than_guessed() -> None:
    print("schema validation")
    cases = (
        ({}, "an empty response"),
        ({"seven_day": REALISTIC_PAYLOAD["seven_day"]}, "a response without five_hour"),
        ({"five_hour": REALISTIC_PAYLOAD["five_hour"]}, "a response without seven_day"),
        ({"five_hour": [], "seven_day": {}}, "a five_hour that is not an object"),
        (
            {"five_hour": {"utilization": "82"}, "seven_day": REALISTIC_PAYLOAD["seven_day"]},
            "a utilization that is a string",
        ),
        (
            {"five_hour": {"utilization": True}, "seven_day": REALISTIC_PAYLOAD["seven_day"]},
            "a utilization that is a boolean",
        ),
        (
            {"five_hour": {}, "seven_day": REALISTIC_PAYLOAD["seven_day"]},
            "a five_hour without utilization",
        ),
    )
    for payload, description in cases:
        expect_error(
            usage_source.UnexpectedSchema,
            lambda payload=payload: usage_source.snapshot_from_payload(payload),
            f"{description} is refused",
        )

    without_reset = {
        "five_hour": {"utilization": 10.0},
        "seven_day": {"utilization": 20.0},
    }
    snapshot = usage_source.snapshot_from_payload(without_reset)
    check(snapshot.session_resets_at is None, "a missing reset timestamp becomes None")
    check(snapshot.weekly_resets_at is None, "a missing weekly reset becomes None")
    check(snapshot.session_pct == 10.0, "the utilization still comes through")

    integers = {"five_hour": {"utilization": 7}, "seven_day": {"utilization": 3}}
    check(
        usage_source.snapshot_from_payload(integers).session_pct == 7.0,
        "integer utilizations are accepted as numbers",
    )


def expiry_is_detected_before_the_request_goes_out() -> None:
    print("credential expiry")
    fresh = credentials(expires_in_hours=5.0)
    check(usage_source.access_token(fresh) == SECRET_TOKEN, "a valid token is returned")

    stale = credentials(expires_in_hours=-1.0)
    failure = expect_error(
        usage_source.ExpiredCredentials,
        lambda: usage_source.access_token(stale),
        "an expired token is refused without a network call",
    )
    check(
        SECRET_TOKEN not in str(failure),
        "the expiry message carries no token value",
    )

    without_expiry = {"accessToken": SECRET_TOKEN}
    check(
        usage_source.access_token(without_expiry) == SECRET_TOKEN,
        "credentials without an expiry field are still usable",
    )

    future = (datetime.now(timezone.utc) + timedelta(hours=5)).timestamp() * 1000.0
    expect_error(
        usage_source.MissingCredentials,
        lambda: usage_source.access_token({"expiresAt": future}),
        "unexpired credentials without a token are refused",
    )
    expect_error(
        usage_source.ExpiredCredentials,
        lambda: usage_source.access_token({"expiresAt": 0}),
        "an epoch expiry counts as expired, checked before the token",
    )


def a_rate_limit_carries_the_announced_pause() -> None:
    print("rate limit backoff")
    original = urllib.request.urlopen

    def responding(headers):
        def opener(request, timeout=None):
            raise urllib.error.HTTPError(
                usage_source.USAGE_URL, 429, "too many requests", headers, None
            )
        return opener

    try:
        urllib.request.urlopen = responding({"retry-after": "3578"})
        failure = expect_error(
            usage_source.RateLimited,
            lambda: usage_source.fetch_usage(SECRET_TOKEN),
            "HTTP 429 with a retry-after header raises RateLimited",
        )
        check(failure.retry_after == 3578.0, "the announced pause is taken from retry-after")

        for headers, description in (
            ({}, "a missing retry-after"),
            ({"retry-after": "soon"}, "an unparsable retry-after"),
            ({"retry-after": "0"}, "a zero retry-after"),
            ({"retry-after": "-5"}, "a negative retry-after"),
        ):
            urllib.request.urlopen = responding(headers)
            failure = expect_error(
                usage_source.RateLimited,
                lambda: usage_source.fetch_usage(SECRET_TOKEN),
                f"{description} still raises RateLimited",
            )
            check(
                failure.retry_after == usage_source.FALLBACK_RETRY_AFTER_SECONDS,
                f"{description} falls back to a safe pause",
            )
            check(
                SECRET_TOKEN not in str(failure),
                f"{description} produces a message without the token value",
            )
    finally:
        urllib.request.urlopen = original


def transport_failures_never_leak_the_token() -> None:
    print("request failures")
    original = urllib.request.urlopen

    def responding(status: int, body: bytes = b"{}"):
        def opener(request, timeout=None):
            raise urllib.error.HTTPError(
                usage_source.USAGE_URL, status, "failed", {}, None
            )
        return opener

    try:
        for status, expected in ((401, usage_source.ExpiredCredentials),
                                 (403, usage_source.ExpiredCredentials),
                                 (500, usage_source.EndpointUnavailable),
                                 (429, usage_source.RateLimited)):
            urllib.request.urlopen = responding(status)
            failure = expect_error(
                expected,
                lambda: usage_source.fetch_usage(SECRET_TOKEN),
                f"HTTP {status} raises {expected.__name__}",
            )
            check(
                SECRET_TOKEN not in str(failure),
                f"the HTTP {status} message carries no token value",
            )

        def unreachable(request, timeout=None):
            raise urllib.error.URLError("nodename nor servname provided")

        urllib.request.urlopen = unreachable
        failure = expect_error(
            usage_source.EndpointUnavailable,
            lambda: usage_source.fetch_usage(SECRET_TOKEN),
            "an unreachable endpoint raises EndpointUnavailable",
        )
        check(SECRET_TOKEN not in str(failure), "the network message carries no token value")

        class Body:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *arguments):
                return False

        def not_json(request, timeout=None):
            return Body(b"<html>nope</html>")

        urllib.request.urlopen = not_json
        expect_error(
            usage_source.UnexpectedSchema,
            lambda: usage_source.fetch_usage(SECRET_TOKEN),
            "a non JSON answer raises UnexpectedSchema",
        )

        def json_array(request, timeout=None):
            return Body(b"[1, 2, 3]")

        urllib.request.urlopen = json_array
        expect_error(
            usage_source.UnexpectedSchema,
            lambda: usage_source.fetch_usage(SECRET_TOKEN),
            "a JSON array raises UnexpectedSchema",
        )

        def good(request, timeout=None):
            check(
                request.get_header("Authorization") == f"Bearer {SECRET_TOKEN}",
                "the request carries the bearer token",
            )
            check(
                request.get_header("Anthropic-beta") == usage_source.OAUTH_BETA_HEADER,
                "the request carries the oauth beta header",
            )
            return Body(json.dumps(REALISTIC_PAYLOAD).encode())

        urllib.request.urlopen = good
        payload = usage_source.fetch_usage(SECRET_TOKEN)
        check(payload == REALISTIC_PAYLOAD, "a good answer is returned unchanged")
    finally:
        urllib.request.urlopen = original


def every_failure_is_one_family() -> None:
    print("error hierarchy")
    for name in ("MissingCredentials", "ExpiredCredentials", "EndpointUnavailable",
                 "UnexpectedSchema", "RateLimited"):
        check(
            issubclass(getattr(usage_source, name), usage_source.UsageError),
            f"{name} is a UsageError, so the daemon can catch one family",
        )


def main() -> int:
    the_documented_schema_maps_to_the_contract()
    a_broken_schema_is_rejected_rather_than_guessed()
    expiry_is_detected_before_the_request_goes_out()
    transport_failures_never_leak_the_token()
    a_rate_limit_carries_the_announced_pause()
    every_failure_is_one_family()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
