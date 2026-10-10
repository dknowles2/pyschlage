import asyncio
import base64
from datetime import UTC, datetime, timedelta
import json
from unittest import mock

from botocore.exceptions import ClientError
import pytest
import requests

from pyschlage import auth as _auth
from pyschlage.exceptions import NotAuthorizedError, UnknownError


@mock.patch("requests.Request")
@mock.patch("pycognito.utils.RequestsSrpAuth")
@mock.patch("pycognito.Cognito")
def test_authenticate(mock_cognito, mock_srp_auth, mock_request):
    auth = _auth.Auth("__username__", "__password__")

    mock_cognito.assert_called_once()
    assert mock_cognito.call_args.kwargs["username"] == "__username__"

    mock_srp_auth.assert_called_once_with(
        password="__password__", cognito=mock_cognito.return_value
    )

    auth.authenticate()
    mock_srp_auth.return_value.assert_called_once_with(mock_request.return_value)


@mock.patch("requests.request")
@mock.patch("pycognito.utils.RequestsSrpAuth")
@mock.patch("pycognito.Cognito")
def test_request(mock_cognito, mock_srp_auth, mock_request):
    auth = _auth.Auth("__username__", "__password__")
    auth.request("get", "/foo/bar", baz="bam")
    mock_request.assert_called_once_with(
        "get",
        "https://api.allegion.yonomi.cloud/v1/foo/bar",
        timeout=60,
        auth=mock_srp_auth.return_value,
        headers={"X-Api-Key": _auth.API_KEY},
        baz="bam",
    )


@mock.patch("requests.request", spec=True)
@mock.patch("pycognito.utils.RequestsSrpAuth", spec=True)
@mock.patch("pycognito.Cognito")
def test_request_not_authorized(mock_cognito, mock_srp_auth, mock_request):
    url = "https://api.allegion.yonomi.cloud/v1/foo/bar"
    auth = _auth.Auth("__username__", "__password__")
    mock_request.side_effect = ClientError(
        {
            "Error": {
                "Code": "NotAuthorizedException",
                "Message": f"Unauthorized for url: {url}",
            }
        },
        "foo-op",
    )

    with pytest.raises(NotAuthorizedError, match=f"Unauthorized for url: {url}"):
        auth.request("get", "/foo/bar", baz="bam")

    mock_request.assert_called_once_with(
        "get",
        url,
        timeout=60,
        auth=mock_srp_auth.return_value,
        headers={"X-Api-Key": _auth.API_KEY},
        baz="bam",
    )


@mock.patch("requests.request", spec=True)
@mock.patch("pycognito.utils.RequestsSrpAuth", spec=True)
@mock.patch("pycognito.Cognito")
def test_request_unknown_error(mock_cognito, mock_srp_auth, mock_request):
    url = "https://api.allegion.yonomi.cloud/v1/foo/bar"
    auth = _auth.Auth("__username__", "__password__")
    mock_resp = mock.create_autospec(requests.Response)
    mock_resp.raise_for_status.side_effect = requests.HTTPError(
        f"500 Server Error: Internal for url: {url}"
    )
    mock_resp.status_code = 500
    mock_resp.reason = "Internal"
    mock_resp.json.side_effect = requests.JSONDecodeError("msg", "doc", 1)
    mock_request.return_value = mock_resp

    with pytest.raises(UnknownError):
        auth.request("get", "/foo/bar", baz="bam")

    mock_request.assert_called_once_with(
        "get",
        url,
        timeout=60,
        auth=mock_srp_auth.return_value,
        headers={"X-Api-Key": _auth.API_KEY},
        baz="bam",
    )


@mock.patch("requests.request")
@mock.patch("pycognito.utils.RequestsSrpAuth")
@mock.patch("pycognito.Cognito")
def test_user_id(mock_cognito, mock_srp_auth, mock_request):
    auth = _auth.Auth("__username__", "__password__")
    mock_request.return_value = mock.Mock(
        json=mock.Mock(
            return_value={
                "consentRecords": [],
                "created": "2022-12-24T20:00:00.000Z",
                "email": "asdf@asdf.com",
                "friendlyName": "username",
                "identityId": "<user-id>",
                "lastUpdated": "2022-12-24T20:00:00.000Z",
            }
        )
    )
    assert auth.user_id == "<user-id>"
    mock_request.assert_called_once_with(
        "get",
        "https://api.allegion.yonomi.cloud/v1/users/@me",
        timeout=60,
        auth=mock_srp_auth.return_value,
        headers={"X-Api-Key": _auth.API_KEY},
    )


@mock.patch("requests.request")
@mock.patch("pycognito.utils.RequestsSrpAuth")
@mock.patch("pycognito.Cognito")
def test_user_id_is_cached(mock_cognito, mock_srp_auth, mock_request):
    auth = _auth.Auth("__username__", "__password__")
    mock_request.return_value = mock.Mock(
        json=mock.Mock(
            return_value={
                "consentRecords": [],
                "created": "2022-12-24T20:00:00.000Z",
                "email": "asdf@asdf.com",
                "friendlyName": "username",
                "identityId": "<user-id>",
                "lastUpdated": "2022-12-24T20:00:00.000Z",
            }
        )
    )
    assert auth.user_id == "<user-id>"
    mock_request.assert_called_once_with(
        "get",
        "https://api.allegion.yonomi.cloud/v1/users/@me",
        timeout=60,
        auth=mock_srp_auth.return_value,
        headers={"X-Api-Key": _auth.API_KEY},
    )
    mock_request.reset_mock()
    assert auth.user_id == "<user-id>"
    mock_request.assert_not_called()


def make_token(expires_in: timedelta) -> str:
    """Builds a JWT-shaped token with the given expiry."""
    exp = int((datetime.now(UTC) + expires_in).timestamp())
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode())
    return f"header.{payload.rstrip(b'=').decode()}.signature"


def client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": f"{code} happened"}}, "InitiateAuth"
    )


class FakeCognito:
    """A pycognito.Cognito that mints tokens without talking to AWS."""

    def __init__(self) -> None:
        self.access_token: str | None = None
        self.authenticate_calls = 0
        self.renew_calls = 0
        self.authenticate_error: Exception | None = None
        self.renew_error: Exception | None = None

    def authenticate(self, password: str) -> None:
        self.authenticate_calls += 1
        if self.authenticate_error:
            raise self.authenticate_error
        self.access_token = make_token(timedelta(hours=1))

    def renew_access_token(self) -> None:
        self.renew_calls += 1
        if self.renew_error:
            raise self.renew_error
        self.access_token = make_token(timedelta(hours=1))


@pytest.fixture
def cognito() -> FakeCognito:
    return FakeCognito()


@pytest.fixture
def async_auth(cognito: FakeCognito) -> _auth.Auth:
    with (
        mock.patch("pycognito.Cognito", return_value=cognito),
        mock.patch("pycognito.utils.RequestsSrpAuth"),
    ):
        return _auth.Auth("__username__", "__password__")


class TestTokenExpiry:
    def test_decodes_exp(self) -> None:
        expires_at = _auth._token_expires_at(make_token(timedelta(hours=1)))
        assert timedelta(minutes=59) < expires_at - datetime.now(UTC)

    def test_handles_base64_padding(self) -> None:
        # Payload lengths vary, so the decoder has to re-pad.
        for seconds in range(5):
            token = make_token(timedelta(seconds=seconds))
            assert _auth._token_expires_at(token).tzinfo is UTC


class TestAsyncAccessToken:
    async def test_authenticates_when_no_token(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        assert await async_auth.async_access_token() == cognito.access_token
        assert cognito.authenticate_calls == 1
        assert cognito.renew_calls == 0

    async def test_reuses_valid_token(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        await async_auth.async_access_token()
        await async_auth.async_access_token()
        assert cognito.authenticate_calls == 1

    async def test_renews_expired_token(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        cognito.access_token = make_token(timedelta(seconds=-1))
        await async_auth.async_access_token()
        assert cognito.renew_calls == 1
        assert cognito.authenticate_calls == 0

    async def test_renews_within_expiry_skew(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        # Still technically valid, but close enough that it could lapse in
        # flight.
        cognito.access_token = make_token(timedelta(seconds=30))
        await async_auth.async_access_token()
        assert cognito.renew_calls == 1

    async def test_reauthenticates_when_refresh_token_rejected(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        cognito.access_token = make_token(timedelta(seconds=-1))
        cognito.renew_error = client_error("NotAuthorizedException")
        await async_auth.async_access_token()
        assert cognito.renew_calls == 1
        assert cognito.authenticate_calls == 1

    async def test_concurrent_callers_mint_once(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        tokens = await asyncio.gather(
            *[async_auth.async_access_token() for _ in range(5)]
        )
        assert cognito.authenticate_calls == 1
        assert len(set(tokens)) == 1

    async def test_translates_not_authorized(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        cognito.authenticate_error = client_error("UserNotFoundException")
        with pytest.raises(NotAuthorizedError):
            await async_auth.async_access_token()
