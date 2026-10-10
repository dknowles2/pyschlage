"""Tests for the request shapes shared by both API layers."""

from pyschlage import request


class TestKwargs:
    def test_omits_what_is_not_set(self) -> None:
        assert request.Request("get", "devices").kwargs == {}

    def test_passes_params_and_body(self) -> None:
        req = request.Request("put", "devices/abc", params={"a": 1}, json={"b": 2})
        assert req.kwargs == {"params": {"a": 1}, "json": {"b": 2}}

    def test_passes_an_alternate_base_url(self) -> None:
        req = request.Request("get", "x", base_url="https://example.test/v1")
        assert req.kwargs == {"base_url": "https://example.test/v1"}


class TestMintCat:
    def test_targets_the_catstar_service(self) -> None:
        req = request.mint_cat("__device_uuid__", "0a1b2c")
        assert req.method == "post"
        assert req.path == "catstar/__device_uuid__"
        assert req.json == {"value": "0a1b2c"}
        assert req.base_url == request.CATSTAR_BASE_URL

    def test_base_url_has_no_trailing_slash(self) -> None:
        # Request paths are joined onto the base with a "/", so a trailing
        # slash here would produce a doubled one.
        assert not request.CATSTAR_BASE_URL.endswith("/")
