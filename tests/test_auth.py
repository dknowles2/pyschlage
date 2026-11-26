import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import threading
import time
from unittest import mock

from botocore.exceptions import ClientError
import pycognito
from pycognito import utils
import pytest
import requests

from pyschlage import auth as _auth
from pyschlage.exceptions import NotAuthorizedError, UnknownError


def _make_jwt(exp: float) -> str:
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode())
        .rstrip(b"=")
        .decode()
    )
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.signature"


def test_auth_subclass_types():
    with mock.patch("boto3.client"):
        auth = _auth.Auth("__username__", "__password__")
    assert isinstance(auth.cognito, pycognito.Cognito)
    assert isinstance(auth.auth, utils.RequestsSrpAuth)


@mock.patch("requests.Request")
@mock.patch("pyschlage.auth._ThreadSafeRequestsSrpAuth")
@mock.patch("pyschlage.auth._Cognito")
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
@mock.patch("pyschlage.auth._ThreadSafeRequestsSrpAuth")
@mock.patch("pyschlage.auth._Cognito")
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
@mock.patch("pyschlage.auth._ThreadSafeRequestsSrpAuth", spec=True)
@mock.patch("pyschlage.auth._Cognito")
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
@mock.patch("pyschlage.auth._ThreadSafeRequestsSrpAuth", spec=True)
@mock.patch("pyschlage.auth._Cognito")
def test_request_client_error_unknown(mock_cognito, mock_srp_auth, mock_request):
    auth = _auth.Auth("__username__", "__password__")
    mock_request.side_effect = ClientError(
        {
            "Error": {
                "Code": "TooManyRequestsException",
                "Message": "Rate exceeded",
            }
        },
        "InitiateAuth",
    )

    with pytest.raises(UnknownError, match="TooManyRequestsException") as exc_info:
        auth.request("get", "/foo/bar")
    assert exc_info.value.status_code is None


@mock.patch("requests.request", spec=True)
@mock.patch("pyschlage.auth._ThreadSafeRequestsSrpAuth", spec=True)
@mock.patch("pyschlage.auth._Cognito")
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

    with pytest.raises(UnknownError) as exc_info:
        auth.request("get", "/foo/bar", baz="bam")
    assert exc_info.value.status_code == 500

    mock_request.assert_called_once_with(
        "get",
        url,
        timeout=60,
        auth=mock_srp_auth.return_value,
        headers={"X-Api-Key": _auth.API_KEY},
        baz="bam",
    )


@mock.patch("requests.request")
@mock.patch("pyschlage.auth._ThreadSafeRequestsSrpAuth")
@mock.patch("pyschlage.auth._Cognito")
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
@mock.patch("pyschlage.auth._ThreadSafeRequestsSrpAuth")
@mock.patch("pyschlage.auth._Cognito")
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


def _make_cognito(access_token: str | None = None) -> _auth._Cognito:
    with mock.patch("boto3.client"):
        return _auth._Cognito(
            username="__username__",
            user_pool_region=_auth.USER_POOL_REGION,
            user_pool_id=_auth.USER_POOL_ID,
            client_id=_auth.CLIENT_ID,
            client_secret=_auth.CLIENT_SECRET,
            access_token=access_token,
        )


def test_check_token_no_access_token():
    cognito = _make_cognito(access_token=None)
    with pytest.raises(AttributeError, match="Access Token Required"):
        cognito.check_token()


def test_check_token_not_expired():
    now = 1_700_000_000.0
    cognito = _make_cognito(access_token=_make_jwt(now + 3600))
    with (
        mock.patch("pyschlage.auth.time.time", return_value=now),
        mock.patch.object(cognito, "renew_access_token") as mock_renew,
    ):
        assert cognito.check_token(renew=True) is False
        mock_renew.assert_not_called()


@pytest.mark.parametrize("now_offset", [0.0, 1.0])
def test_check_token_expired_renews(now_offset):
    exp = 1_700_000_000.0
    cognito = _make_cognito(access_token=_make_jwt(exp))
    with (
        mock.patch("pyschlage.auth.time.time", return_value=exp + now_offset),
        mock.patch.object(cognito, "renew_access_token") as mock_renew,
    ):
        assert cognito.check_token(renew=True) is True
        mock_renew.assert_called_once_with()


def test_check_token_expired_no_renew():
    exp = 1_700_000_000.0
    cognito = _make_cognito(access_token=_make_jwt(exp))
    with (
        mock.patch("pyschlage.auth.time.time", return_value=exp + 10),
        mock.patch.object(cognito, "renew_access_token") as mock_renew,
    ):
        assert cognito.check_token(renew=False) is True
        mock_renew.assert_not_called()


def test_check_token_dst_fallback(monkeypatch):
    """Verify tokens issued during a DST fall-back hour are not treated as expired."""
    # 2026-11-01 01:50:23 EDT (UTC-4) -> exp is 2026-11-01 01:50:23 EST (UTC-5)
    t_issued = datetime.datetime(
        2026, 11, 1, 5, 50, 23, tzinfo=datetime.UTC
    ).timestamp()
    t_now = t_issued + 1
    t_exp = t_issued + 3600
    cognito = _make_cognito(access_token=_make_jwt(t_exp))

    monkeypatch.setenv("TZ", "America/New_York")
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        if hasattr(time, "tzset"):
            # Confirm naive local comparison reproduces the upstream pycognito bug.
            assert datetime.datetime.fromtimestamp(
                t_now
            ) > datetime.datetime.fromtimestamp(t_exp)
        with (
            mock.patch("pyschlage.auth.time.time", return_value=t_now),
            mock.patch.object(cognito, "renew_access_token") as mock_renew,
        ):
            assert cognito.check_token(renew=True) is False
            mock_renew.assert_not_called()
    finally:
        monkeypatch.undo()
        if hasattr(time, "tzset"):
            time.tzset()


def test_thread_safe_srp_auth_serializes_refresh():
    now = time.time()
    expired_token = _make_jwt(now - 10)
    fresh_token = _make_jwt(now + 3600)
    cognito = _make_cognito(access_token=expired_token)
    srp_auth = _auth._ThreadSafeRequestsSrpAuth(
        password="__password__", cognito=cognito
    )

    renew_calls = 0

    def fake_renew() -> None:
        nonlocal renew_calls
        renew_calls += 1
        time.sleep(0.05)
        cognito.access_token = fresh_token

    num_threads = 5
    barrier = threading.Barrier(num_threads)

    def invoke() -> requests.Request:
        req = requests.Request()
        barrier.wait(timeout=5)
        return srp_auth(req)

    with (
        mock.patch.object(cognito, "renew_access_token", side_effect=fake_renew),
        ThreadPoolExecutor(max_workers=num_threads) as pool,
    ):
        futures = [pool.submit(invoke) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    assert renew_calls == 1
    for req in results:
        assert req.headers["Authorization"] == f"Bearer {fresh_token}"


def test_thread_safe_srp_auth_serializes_initial_auth():
    fresh_token = _make_jwt(time.time() + 3600)
    cognito = _make_cognito(access_token=None)
    srp_auth = _auth._ThreadSafeRequestsSrpAuth(
        password="__password__", cognito=cognito
    )

    auth_calls = 0

    def fake_authenticate(password: str) -> None:
        nonlocal auth_calls
        auth_calls += 1
        time.sleep(0.05)
        cognito.access_token = fresh_token

    num_threads = 5
    barrier = threading.Barrier(num_threads)

    def invoke() -> requests.Request:
        req = requests.Request()
        barrier.wait(timeout=5)
        return srp_auth(req)

    with (
        mock.patch.object(cognito, "authenticate", side_effect=fake_authenticate),
        ThreadPoolExecutor(max_workers=num_threads) as pool,
    ):
        futures = [pool.submit(invoke) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    assert auth_calls == 1
    for req in results:
        assert req.headers["Authorization"] == f"Bearer {fresh_token}"


@mock.patch("requests.request")
@mock.patch("pyschlage.auth._ThreadSafeRequestsSrpAuth")
@mock.patch("pyschlage.auth._Cognito")
def test_user_id_thread_safe(mock_cognito, mock_srp_auth, mock_request):
    auth = _auth.Auth("__username__", "__password__")

    def fake_request(*args, **kwargs):
        time.sleep(0.05)
        return mock.Mock(json=mock.Mock(return_value={"identityId": "<user-id>"}))

    mock_request.side_effect = fake_request

    num_threads = 5
    barrier = threading.Barrier(num_threads)

    def get_user_id() -> str:
        barrier.wait(timeout=5)
        return auth.user_id

    with ThreadPoolExecutor(max_workers=num_threads) as pool:
        futures = [pool.submit(get_user_id) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    assert results == ["<user-id>"] * num_threads
    mock_request.assert_called_once()


def make_token(expires_in: datetime.timedelta) -> str:
    """Builds a JWT-shaped token with the given expiry."""
    exp = int((datetime.datetime.now(datetime.UTC) + expires_in).timestamp())
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
        self.access_token = make_token(datetime.timedelta(hours=1))

    def renew_access_token(self) -> None:
        self.renew_calls += 1
        if self.renew_error:
            raise self.renew_error
        self.access_token = make_token(datetime.timedelta(hours=1))

    def check_token(self, renew: bool = True) -> bool:
        assert self.access_token
        expired = _auth._token_expires_at(self.access_token) <= datetime.datetime.now(
            datetime.UTC
        )
        if expired and renew:
            self.renew_access_token()
        return expired


@pytest.fixture
def cognito() -> FakeCognito:
    return FakeCognito()


@pytest.fixture
def async_auth(cognito: FakeCognito) -> _auth.Auth:
    # Only the Cognito client is faked. The SRP auth wrapper is the real one, so
    # that its renewal lock is the one the async path has to share.
    with mock.patch("pyschlage.auth._Cognito", return_value=cognito):
        return _auth.Auth("__username__", "__password__")


class TestTokenExpiry:
    def test_decodes_exp(self) -> None:
        expires_at = _auth._token_expires_at(make_token(datetime.timedelta(hours=1)))
        assert datetime.timedelta(minutes=59) < expires_at - datetime.datetime.now(
            datetime.UTC
        )

    def test_handles_base64_padding(self) -> None:
        # Payload lengths vary, so the decoder has to re-pad.
        for seconds in range(5):
            token = make_token(datetime.timedelta(seconds=seconds))
            assert _auth._token_expires_at(token).tzinfo is datetime.UTC


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
        cognito.access_token = make_token(datetime.timedelta(seconds=-1))
        await async_auth.async_access_token()
        assert cognito.renew_calls == 1
        assert cognito.authenticate_calls == 0

    async def test_renews_within_expiry_skew(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        # Still technically valid, but close enough that it could lapse in
        # flight.
        cognito.access_token = make_token(datetime.timedelta(seconds=30))
        await async_auth.async_access_token()
        assert cognito.renew_calls == 1

    async def test_reauthenticates_when_refresh_token_rejected(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        cognito.access_token = make_token(datetime.timedelta(seconds=-1))
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

    async def test_waits_for_a_renewal_on_the_sync_path(
        self, async_auth: _auth.Auth, cognito: FakeCognito
    ) -> None:
        # A thread on the synchronous path holds the renewal lock and renews.
        # The async path must wait for it and then use that token, rather than
        # renewing the same tokens a second time alongside it.
        cognito.access_token = make_token(datetime.timedelta(seconds=-1))
        async_auth.auth._lock.acquire()
        try:
            task = asyncio.create_task(async_auth.async_access_token())
            await asyncio.sleep(0.05)
            assert not task.done()
            cognito.renew_access_token()
        finally:
            async_auth.auth._lock.release()
        assert await task == cognito.access_token
        assert cognito.renew_calls == 1
        assert cognito.authenticate_calls == 0
