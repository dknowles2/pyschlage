from datetime import datetime

from pyschlage.common import fromisoformat, redact


def test_fromisoformat() -> None:
    assert fromisoformat("2023-03-01T17:26:47.366Z") == datetime.fromisoformat(
        "2023-03-01T17:26:47.366Z"
    )


class TestRedact:
    def test_allow_all(self) -> None:
        json = {"foo": "bar", "baz": [1, 2]}
        assert redact(json, allowed=["*"]) == json

    def test_redacts_scalars(self) -> None:
        assert redact({"foo": "bar", "baz": "qux"}, allowed=["foo"]) == {
            "foo": "bar",
            "baz": "<REDACTED>",
        }

    def test_redacts_lists(self) -> None:
        assert redact({"foo": [1, 2, 3]}, allowed=[]) == {"foo": ["<REDACTED>"]}

    def test_allows_lists(self) -> None:
        assert redact({"foo": [1, 2, 3]}, allowed=["foo"]) == {"foo": [1, 2, 3]}

    def test_recurses_into_dicts(self) -> None:
        json = {"a": {"b": "keep", "c": "drop"}}
        assert redact(json, allowed=["a.b"]) == {"a": {"b": "keep", "c": "<REDACTED>"}}

    def test_redacts_whole_subtree(self) -> None:
        json = {"a": {"b": "drop"}}
        assert redact(json, allowed=[]) == {"a": {"b": "<REDACTED>"}}

    def test_does_not_mutate_input(self) -> None:
        json = {"a": {"b": "keep"}, "c": "drop"}
        redact(json, allowed=["a"])
        assert json == {"a": {"b": "keep"}, "c": "drop"}
