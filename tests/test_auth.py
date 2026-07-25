import asyncio
import base64
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import patch

from botocore.exceptions import ClientError
import pytest

from pyschlage.auth import Auth, _token_expires_at
from pyschlage.exceptions import NotAuthorizedError, UnknownError


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
def auth(cognito: FakeCognito) -> Auth:
    with patch("pycognito.Cognito", return_value=cognito):
        return Auth("username", "password")


class TestTokenExpiry:
    def test_decodes_exp(self) -> None:
        token = make_token(timedelta(hours=1))
        expires_at = _token_expires_at(token)
        assert timedelta(minutes=59) < expires_at - datetime.now(UTC)

    def test_handles_base64_padding(self) -> None:
        # Payload lengths vary, so the decoder must re-pad.
        for seconds in range(5):
            token = make_token(timedelta(seconds=seconds))
            assert _token_expires_at(token).tzinfo is UTC


class TestAsyncAccessToken:
    async def test_authenticates_when_no_token(
        self, auth: Auth, cognito: FakeCognito
    ) -> None:
        token = await auth.async_access_token()
        assert token == cognito.access_token
        assert cognito.authenticate_calls == 1
        assert cognito.renew_calls == 0

    async def test_reuses_valid_token(self, auth: Auth, cognito: FakeCognito) -> None:
        await auth.async_access_token()
        await auth.async_access_token()
        assert cognito.authenticate_calls == 1

    async def test_renews_expired_token(self, auth: Auth, cognito: FakeCognito) -> None:
        cognito.access_token = make_token(timedelta(seconds=-1))
        await auth.async_access_token()
        assert cognito.renew_calls == 1
        assert cognito.authenticate_calls == 0

    async def test_renews_within_expiry_skew(
        self, auth: Auth, cognito: FakeCognito
    ) -> None:
        # Still technically valid, but close enough that it could lapse in
        # flight.
        cognito.access_token = make_token(timedelta(seconds=30))
        await auth.async_access_token()
        assert cognito.renew_calls == 1

    async def test_reauthenticates_when_refresh_token_rejected(
        self, auth: Auth, cognito: FakeCognito
    ) -> None:
        cognito.access_token = make_token(timedelta(seconds=-1))
        cognito.renew_error = client_error("NotAuthorizedException")
        await auth.async_access_token()
        assert cognito.renew_calls == 1
        assert cognito.authenticate_calls == 1

    async def test_concurrent_callers_mint_once(
        self, auth: Auth, cognito: FakeCognito
    ) -> None:
        tokens = await asyncio.gather(*[auth.async_access_token() for _ in range(5)])
        assert cognito.authenticate_calls == 1
        assert len(set(tokens)) == 1


class TestErrorTranslation:
    @pytest.mark.parametrize(
        "code",
        [
            "NotAuthorizedException",
            "InvalidPasswordException",
            "PasswordResetRequiredException",
            "UserNotFoundException",
            "UserNotConfirmedException",
        ],
    )
    async def test_not_authorized(
        self, auth: Auth, cognito: FakeCognito, code: str
    ) -> None:
        cognito.authenticate_error = client_error(code)
        with pytest.raises(NotAuthorizedError, match=f"{code} happened"):
            await auth.async_access_token()

    async def test_unknown_error(self, auth: Auth, cognito: FakeCognito) -> None:
        cognito.authenticate_error = client_error("SomethingElseException")
        with pytest.raises(UnknownError):
            await auth.async_access_token()
