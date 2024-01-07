"""Authentication support for the Schlage WiFi cloud service."""

from __future__ import annotations

from functools import wraps
import json
from typing import Any, Callable, Union
from urllib.parse import urlparse

from botocore.exceptions import ClientError
from paho.mqtt import client as mqtt_client
import pycognito
from pycognito import utils
import requests

from .exceptions import NotAuthorizedError, UnknownError

_DEFAULT_TIMEOUT = 60
_NOT_AUTHORIZED_ERRORS = (
    "NotAuthorizedException",
    "InvalidPasswordException",
    "PasswordResetRequiredException",
    "UserNotFoundException",
    "UserNotConfirmedException",
)
API_KEY = "hnuu9jbbJr7MssFDWm5nU2Z7nG5Q5rxsaqWsE7e9"
BASE_URL = "https://api.allegion.yonomi.cloud/v1"
CLIENT_ID = "t5836cptp2s1il0u9lki03j5"
CLIENT_SECRET = "1kfmt18bgaig51in4j4v1j3jbe7ioqtjhle5o6knqc5dat0tpuvo"
USER_POOL_REGION = "us-west-2"
USER_POOL_ID = USER_POOL_REGION + "_2zhrVs9d4"


def _translate_auth_errors(
    # pylint: disable=invalid-name
    fn: Callable[..., Union[requests.Request, requests.Response]]
    # pylint: enable=invalid-name
) -> Callable[..., Union[requests.Request, requests.Response]]:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ClientError as ex:
            resp_err = ex.response.get("Error", {})
            if resp_err.get("Code") in _NOT_AUTHORIZED_ERRORS:
                raise NotAuthorizedError(
                    resp_err.get("Message", "Not authorized")
                ) from ex
            raise UnknownError(str(ex)) from ex

    return wrapper


def _translate_http_errors(
    # pylint: disable=invalid-name
    fn: Callable[..., requests.Response]
    # pylint: enable=invalid-name
) -> Callable[..., requests.Response]:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        resp: requests.Response = fn(*args, **kwargs)
        try:
            resp.raise_for_status()
            return resp
        except requests.HTTPError as ex:
            try:
                message = resp.json().get("message", resp.reason)
            except requests.JSONDecodeError:
                message = resp.reason
            raise UnknownError(message) from ex

    return wrapper


class Auth:
    """Handles authentication for the Schlage WiFi cloud service."""

    def __init__(self, username: str, password: str) -> None:
        """Initializes an Auth object.

        :param username: The username associated with the Schlage account.
        :type username: str
        :param password: The password for the account.
        :type password: str
        """
        self.cognito = pycognito.Cognito(
            username=username,
            user_pool_region=USER_POOL_REGION,
            user_pool_id=USER_POOL_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
        )
        self.auth = utils.RequestsSrpAuth(
            password=password,
            cognito=self.cognito,
        )
        self.mqtt = None
        self._callbacks = {}
        self._user_id: str | None = None

    @_translate_auth_errors
    def authenticate(self):
        """Performs authentication with AWS.

        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        self.auth(requests.Request())

    @property
    def user_id(self) -> str:
        """Returns the unique user id for the authenticated user."""
        if self._user_id is None:
            self._user_id = self._get_user_id()
        return self._user_id

    def _get_user_id(self) -> str:
        resp = self.request("get", "users/@me")
        return resp.json()["identityId"]

    @_translate_http_errors
    @_translate_auth_errors
    def request(
        self, method: str, path: str, base_url: str = BASE_URL, **kwargs
    ) -> requests.Response:
        """Performs a request against the Schlage WiFi cloud service.

        :meta private:
        """
        kwargs["auth"] = self.auth
        if "headers" not in kwargs:
            kwargs["headers"] = {}
        kwargs["headers"]["X-Api-Key"] = API_KEY
        kwargs.setdefault("timeout", _DEFAULT_TIMEOUT)
        # pylint: disable=missing-timeout
        return requests.request(method, f"{base_url}/{path.lstrip('/')}", **kwargs)

    def subscribe(
        self,
        device_id: str,
        callback: Callable[[str, dict], None],
        topic: str = "reported",
    ):
        """Subscribes to updates to a lock."""
        if self.mqtt is None:
            self.mqtt = self._make_mqtt(device_id)
        if topic not in ("reported", "desired", "delta"):
            raise ValueError(f"Invalid topic: {topic}")
        topic = f"thincloud/devices/{device_id}/{topic}"
        if topic not in self._callbacks:
            self._callbacks[topic] = []
            self.mqtt.subscribe(topic)
        self._callbacks[topic].append(callback)

    def _get_mqtt_config(self, device_id: str) -> dict:
        self.authenticate()  # Ensure we have credentials.
        headers = {"X-Web-Identity-Token": self.cognito.id_token}
        params = {"deviceId": device_id}
        resp = self.request("get", "wss", headers=headers, params=params)
        return resp.json()

    def _make_mqtt(self, device_id: str) -> mqtt_client.Client:
        conf = self._get_mqtt_config(device_id)
        mqtt = mqtt_client.Client(client_id=conf["clientId"], transport="websockets")
        uri = urlparse(conf["wssUri"])
        path = f"{uri.path}?{uri.query}"
        headers = {"Host": uri.netloc.rstrip(":443")}
        mqtt.tls_set()
        mqtt.ws_set_options(path=path, headers=headers)
        mqtt.on_message = self._on_message
        mqtt.connect(uri.netloc, 443)
        # TODO: Add support for async event loops.
        mqtt.loop_start()
        return mqtt

    def _on_message(self, unused_mqtt, unused_userdata, msg: mqtt_client.MQTTMessage):
        if not msg.payload:
            return
        json_data = json.loads(msg.payload)
        short_topic = msg.topic.split("/")[-1]
        for cb in self._callbacks[msg.topic]:
            cb(short_topic, json_data)
