from __future__ import annotations

from pickle import dumps, loads
from typing import Any

import pytest

from pyschlage import common
from pyschlage.auth import Auth


class MutableImpl(common.Mutable):
    @classmethod
    def from_json(cls, auth: Auth, json: dict[str, Any]) -> MutableImpl:
        return MutableImpl()


def test_pickle_unpickle() -> None:
    mut = MutableImpl()
    mut2 = loads(dumps(mut))
    assert mut2._mu is not None
    assert mut2._mu != mut._mu
    assert mut2._auth == mut._auth


@pytest.fixture
def json_dict() -> dict[Any, Any]:
    return {
        "a": "foo",
        "b": 1,
        "c": {
            "c0": "foo",
            "c1": 1,
            "c2": {
                "c20": "foo",
            },
            "c3": ["foo"],
        },
        "d": ["foo"],
    }


def test_redact_allow_asterisk(json_dict: dict[Any, Any]):
    assert common.redact(json_dict, allowed=["*"]) == json_dict


def test_redact_allow_all(json_dict: dict[Any, Any]):
    assert common.redact(json_dict, allowed=["a", "b", "c.*", "d"]) == json_dict
    assert (
        common.redact(
            json_dict, allowed=["a", "b", "c.c0", "c.c1", "c.c2", "c.c3", "d"]
        )
        == json_dict
    )
    assert common.redact(json_dict, allowed=["a", "b", "c", "d"]) == json_dict


def test_redact_all(json_dict: dict[Any, Any]):
    want = {
        "a": "<REDACTED>",
        "b": "<REDACTED>",
        "c": {
            "c0": "<REDACTED>",
            "c1": "<REDACTED>",
            "c2": {
                "c20": "<REDACTED>",
            },
            "c3": ["<REDACTED>"],
        },
        "d": ["<REDACTED>"],
    }
    assert common.redact(json_dict, allowed=[]) == want


def test_redact_partial(json_dict: dict[Any, Any]):
    want = {
        "a": "foo",
        "b": 1,
        "c": {
            "c0": "foo",
            "c1": "<REDACTED>",
            "c2": {
                "c20": "<REDACTED>",
            },
            "c3": ["<REDACTED>"],
        },
        "d": ["<REDACTED>"],
    }
    assert common.redact(json_dict, allowed=["a", "b", "c.c0"]) == want
