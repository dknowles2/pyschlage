"""Authentication support for the Schlage WiFi cloud service."""

from __future__ import annotations

import json
import logging
from enum import Enum
from functools import partial, wraps
from typing import Callable
from urllib.parse import urlparse

import pycognito
import requests
from botocore.exceptions import ClientError
from paho.mqtt.client import Client as MQTTClient
from paho.mqtt.client import MQTTMessage
from pycognito import utils

from .exceptions import NotAuthorizedError, UnknownError

LOGGER = logging.getLogger(__package__)


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


class SubscriptionType(str, Enum):
    """Valid types of subscription modes."""

    REPORTED = "reported"
    DESIRED = "desired"
    DELTA = "delta"


def _translate_auth_errors(
    # pylint: disable=invalid-name
    fn: Callable[..., requests.Response],
    # pylint: enable=invalid-name
) -> Callable[..., requests.Response]:
    @wraps(fn)
    def wrapper(*args, **kwargs) -> requests.Response:
        try:
            return fn(*args, **kwargs)
        except ClientError as ex:
            resp_err = ex.response.get("Error", {})
            if resp_err.get("Code") in _NOT_AUTHORIZED_ERRORS:
                raise NotAuthorizedError(
                    resp_err.get("Message", "Not authorized")
                ) from ex
            raise UnknownError(str(ex)) from ex  # pragma: no cover

    return wrapper


def _translate_http_errors(
    # pylint: disable=invalid-name
    fn: Callable[..., requests.Response],
    # pylint: enable=invalid-name
) -> Callable[..., requests.Response]:
    @wraps(fn)
    def wrapper(*args, **kwargs) -> requests.Response:
        resp = fn(*args, **kwargs)
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
        self._mqtt_config: dict | None = None
        self._mqtt_clients: dict[str, MQTTClient] = {}
        self._callbacks: dict[tuple[str, str], Callable[[str, dict], None]] = {}
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
        subscription_type: SubscriptionType = SubscriptionType.REPORTED,
    ):
        """Subscribes to lock MQTT updates.

        :meta private:
        """
        # if device_id not in self._mqtt_clients:
        #    self._mqtt_clients[device_id] = self._make_mqtt(device_id)

        # mqtt = self._mqtt_clients[device_id]
        mqtt = self._make_mqtt(device_id)

        topic = f"thincloud/devices/{device_id}/{subscription_type.value}"
        if (device_id, topic) not in self._callbacks:
            self._callbacks[(device_id, topic)] = []
            mqtt.subscribe(topic)

        self._callbacks[(device_id, topic)].append(callback)

    def _get_mqtt_config(self, device_id: str) -> dict:
        self.authenticate()  # Ensure we have credentials.
        headers = {"X-Web-Identity-Token": self.cognito.id_token}
        params = {"deviceId": device_id}
        resp = self.request("get", "wss", headers=headers, params=params)
        return resp.json()

    def _make_mqtt(self, device_id: str) -> MQTTClient:
        conf = self._get_mqtt_config(device_id)
        LOGGER.debug("MQTT config: %s", conf)
        mqtt = MQTTClient(client_id=conf["clientId"], transport="websockets")
        uri = urlparse(conf["wssUri"])
        path = f"{uri.path}?{uri.query}"
        headers = {"Host": uri.netloc.rstrip(":443")}
        mqtt.tls_set()
        mqtt.ws_set_options(path=path, headers=headers)
        mqtt.on_connect = partial(self._on_connect, device_id)
        mqtt.on_disconnect = partial(self._on_disconnect, device_id)
        mqtt.on_message = partial(self._on_message, device_id)
        mqtt.connect(uri.netloc, 443)
        mqtt.loop_start()
        return mqtt

    def _on_connect(self, device_id: str, *args, **kwargs):
        LOGGER.debug("MQTT connected for device_id %s", device_id)

    def _on_disconnect(self, device_id: str, unused_mqtt, unused_userdata, rc):
        LOGGER.debug("MQTT disconnected for device_id %s with reason=%s", device_id, rc)

    def _on_message(
        self, device_id: str, unused_mqtt, unused_userdata, message: MQTTMessage
    ):
        if not message.payload:
            LOGGER.debug("Ignoring message for device id %s: no payload", device_id)
            return
        json_data = json.loads(message.payload)
        short_topic = message.topic.split("/")[-1]
        for cb in self._callbacks[(device_id, message.topic)]:
            cb(short_topic, json_data)
