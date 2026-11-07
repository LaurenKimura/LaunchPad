"""Retry, backoff, and conditional GET. The opener stands in for the network."""

from http_client import Conditional, HttpClient, HttpFailed


class Script:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def client(script, sleeps):
    return HttpClient(attempts=3, timeout=5, sleep=sleeps.append, rng=lambda: 0.0, opener=script)


def test_retries_then_returns_the_body():
    script = Script(
        [
            (503, {"ETag": '"old"'}, b""),
            TimeoutError("slow"),
            (200, {"ETag": '"abc"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"}, b"{}"),
        ]
    )
    sleeps = []
    result = client(script, sleeps).fetch("https://example.test/data")

    assert result.status == 200
    assert result.body == b"{}"
    assert result.etag == '"abc"'
    assert result.not_modified is False
    assert sleeps == [0.5, 1.0]
    assert len(script.calls) == 3


def test_client_error_is_not_retried_and_hides_the_query():
    script = Script([(403, {}, b"nope")])
    sleeps = []
    try:
        client(script, sleeps).fetch("https://api.nasa.gov/DONKI/FLR?api_key=super-secret")
    except HttpFailed as exc:
        message = str(exc)
    else:
        raise AssertionError("expected HttpFailed")

    assert sleeps == []
    assert len(script.calls) == 1
    assert "super-secret" not in message
    assert "status_403" in message


def test_not_modified_sends_validators_and_skips_retries():
    script = Script([(304, {"ETag": '"same"'}, b"")])
    sleeps = []
    result = client(script, sleeps).fetch(
        "https://example.test/data?api_key=super-secret",
        Conditional(etag="same", last_modified="Mon, 01 Jan 2024 00:00:00 GMT"),
    )

    assert result.not_modified is True
    assert result.body == b""
    assert sleeps == []
    sent = script.calls[0]["headers"]
    assert sent["If-None-Match"] == '"same"'
    assert sent["If-Modified-Since"] == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert "super-secret" not in sent["If-None-Match"]


def test_network_errors_use_backoff_then_fail():
    script = Script([OSError("down"), OSError("down"), OSError("down")])
    sleeps = []
    try:
        client(script, sleeps).fetch("https://example.test/data")
    except HttpFailed as exc:
        assert str(exc) == "network"
    else:
        raise AssertionError("expected HttpFailed")

    assert sleeps == [0.5, 1.0]
    assert len(script.calls) == 3
