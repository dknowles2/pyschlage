"""Push updates for Schlage WiFi devices.

The Schlage cloud service publishes device state changes over MQTT on a
WebSocket transport, which avoids polling :meth:`Lock.refresh()
<pyschlage.lock.Lock.refresh>`.

Two endpoints hand out connection details. :meth:`PushClient.get_topics`
with no arguments asks for the whole account, which is what the Schlage
Home app does; it returns a single MQTT wildcard topic
(``thincloud/users/{user_id}/devices/#``) covering every device. Passing a
``device_id`` asks for a single device, which the service appears to limit
to one device and one subscription per account at a time.

This requires the ``paho-mqtt`` package, which pyschlage does not install
by default::

    pip install 'pyschlage[push]'

Messages arrive on ``thincloud/users/{user_id}/devices/{device_id}`` with
a payload of ``{"reported": {...}}``, where the inner document has the same
shape as ``GET devices/{device_id}``. :meth:`Lock.update_from_push()
<pyschlage.lock.Lock.update_from_push>` applies one to a
:class:`Lock <pyschlage.lock.Lock>`.

Example::

    from pyschlage import Auth, Schlage
    from pyschlage.push import PushClient

    auth = Auth("username", "password")
    locks = {lock.device_id: lock for lock in Schlage(auth).locks()}

    def on_update(update):
        lock = locks.get(update.device_id)
        if lock is not None:
            lock.update_from_push(update.reported)
            print(lock.name, lock.is_locked)

    with PushClient(auth) as client:
        client.connect(on_update)
        client.run_forever()
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json as json_lib
import logging
from threading import Event
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self
from urllib.parse import urlparse

from .auth import Auth
from .exceptions import Error, UnknownError

if TYPE_CHECKING:  # pragma: no cover
    from paho.mqtt.client import Client as MqttClient

_LOGGER = logging.getLogger(__name__)

ID_TOKEN_HEADER = "X-Web-Identity-Token"
"""HTTP header carrying the Cognito identity token the wss endpoints need."""

DEFAULT_KEEPALIVE = 1800
"""Keep-alive interval (in seconds) used by the Schlage Home app."""

DEFAULT_CONNECT_TIMEOUT = 30.0
"""How long to wait for the broker to accept a connection and subscription."""

REPORTED = "reported"
"""Topic kind carrying state the device has reported."""

DESIRED = "desired"
"""Topic kind carrying state the service wants the device to adopt."""

DELTA = "delta"
"""Topic kind carrying the difference between desired and reported state."""

_MISSING_PAHO = (
    "Push updates require the paho-mqtt package. "
    "Install it with: pip install 'pyschlage[push]'"
)


class PushUnavailableError(Error):
    """Raised when push support is unavailable or the connection fails."""


def _import_mqtt():
    try:
        from paho.mqtt import client as mqtt
    except ImportError as ex:  # pragma: no cover
        raise PushUnavailableError(_MISSING_PAHO) from ex
    return mqtt


@dataclass(frozen=True)
class Topics:
    """Connection details for the push channel."""

    client_id: str
    """MQTT client id to connect with. Assigned by the service.

    The service returns the account's user id here, the same value on every
    request. MQTT brokers disconnect an existing session when a new
    connection presents the same client id, so **only one push consumer per
    account can be connected at a time**, and a second one takes the
    session over rather than sharing it.

    The Schlage Home phone app is such a consumer. Observed against a live
    account: with the app open, it and a second client disconnected each
    other about every 7 seconds, each reconnecting immediately, until the
    app's session went away. Updates are still delivered in the gaps, but
    expect this whenever someone in the household has the app open.
    """

    wss_uri: str
    """Pre-signed ``wss://`` URI to connect to.

    These are time limited. A reconnect needs freshly fetched Topics.
    """

    topics: tuple[str, ...] = ()
    """Every topic the service offers for this request."""

    message: str | None = None
    """Optional human-readable message returned alongside the topics."""

    @staticmethod
    def request_path(device_id: str | None = None) -> str:
        """Returns the request path for Topics.

        :meta private:
        """
        if device_id is None:
            return "users/wss"
        return "wss"

    @classmethod
    def from_json(cls, json: dict[str, Any]) -> Topics:
        """Creates a Topics from a JSON dict.

        :meta private:
        """
        return cls(
            client_id=json.get("clientId", ""),
            wss_uri=json.get("wssUri", ""),
            topics=tuple(json.get("topics") or ()),
            message=json.get("message"),
        )

    def of_kind(self, kind: str) -> tuple[str, ...]:
        """Returns the topics of the given kind.

        Matching is by substring, as the app does. Only the per-device
        request names its topics by kind; the account-wide request returns
        a single MQTT wildcard covering every device, which matches no
        kind. Subscribing to :attr:`topics` wholesale is usually what you
        want.

        :param kind: One of :data:`REPORTED`, :data:`DESIRED` or :data:`DELTA`.
        :type kind: str
        :rtype: tuple[str, ...]
        """
        return tuple(t for t in self.topics if kind in t)

    def is_valid(self) -> bool:
        """Returns whether these Topics can be connected to."""
        return bool(self.client_id and self.wss_uri)


@dataclass(frozen=True)
class DeviceUpdate:
    """A single pushed device update."""

    topic: str
    """The topic the update arrived on."""

    payload: dict[str, Any]
    """The decoded JSON payload."""

    received_at: datetime = field(
        default_factory=lambda: datetime.now(tz=UTC), compare=False
    )
    """The UTC time at which the update was received."""

    @property
    def reported(self) -> dict[str, Any]:
        """The reported device state, or an empty dict.

        Updates on a :data:`REPORTED` topic wrap the device JSON in a
        ``reported`` key.
        """
        reported = self.payload.get(REPORTED)
        return reported if isinstance(reported, dict) else {}

    @property
    def device_id(self) -> str | None:
        """The device the update is for, if the payload names one."""
        device_id = self.reported.get("deviceId") or self.payload.get("deviceId")
        return device_id if isinstance(device_id, str) else None


UpdateCallback = Callable[[DeviceUpdate], None]
"""Called for each pushed update. See :class:`DeviceUpdate`."""


class PushClient:
    """Subscribes to push updates for a Schlage account's devices."""

    def __init__(
        self,
        auth: Auth,
        keepalive: int = DEFAULT_KEEPALIVE,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        """Instantiates a PushClient.

        :param auth: Authentication and transport for the API.
        :type auth: pyschlage.Auth
        :param keepalive: MQTT keep-alive interval, in seconds.
        :type keepalive: int
        :param connect_timeout: How long :meth:`connect` waits for the broker
            to accept the connection and the subscription, in seconds.
        :type connect_timeout: float
        """
        self._auth = auth
        self._keepalive = keepalive
        self._connect_timeout = connect_timeout
        self._client: MqttClient | None = None
        self._stopped = Event()
        self._connected = Event()
        self._subscribed = Event()
        self._connect_error: str | None = None

    def get_topics(self, device_id: str | None = None) -> Topics:
        """Fetches connection details for the push channel.

        :param device_id: Request topics for a single device. If None,
            requests topics covering every device on the account.
        :type device_id: str or None
        :rtype: Topics
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        params = None if device_id is None else {"deviceId": device_id}
        resp = self._auth.request(
            "get",
            Topics.request_path(device_id),
            headers={ID_TOKEN_HEADER: self._auth.id_token},
            params=params,
        )
        return Topics.from_json(resp.json())

    def connect(
        self,
        on_update: UpdateCallback,
        topics: Topics | None = None,
        device_id: str | None = None,
        kinds: tuple[str, ...] | None = None,
    ) -> Topics:
        """Connects to the push channel and subscribes to its topics.

        Returns once the subscription is established. Updates are delivered
        on a background thread until :meth:`close` is called.

        :param on_update: Called with each :class:`DeviceUpdate` received.
        :type on_update: UpdateCallback
        :param topics: Connection details to use. If None, they are fetched.
        :type topics: Topics or None
        :param device_id: Passed to :meth:`get_topics` when fetching topics.
        :type device_id: str or None
        :param kinds: Narrow the subscription to these topic kinds. The
            default of None subscribes to every topic the service returned,
            as the app does. Only useful with a per-device request, whose
            topics are named by kind.
        :type kinds: tuple[str, ...] or None
        :rtype: Topics
        :raise PushUnavailableError: When paho-mqtt is missing, the service
            returns unusable connection details, or the connection fails.
        :raise pyschlage.exceptions.NotAuthorizedError: When authentication fails.
        :raise pyschlage.exceptions.UnknownError: On other errors.
        """
        mqtt = _import_mqtt()
        if topics is None:
            topics = self.get_topics(device_id)
        if not topics.is_valid():
            raise PushUnavailableError(
                f"Service returned unusable connection details: {topics}"
            )
        if kinds is None:
            wanted = topics.topics
        else:
            wanted = tuple(t for kind in kinds for t in topics.of_kind(kind))
        if not wanted:
            raise PushUnavailableError(
                f"No topics to subscribe to (kinds={kinds}) in {list(topics.topics)}"
            )

        url = urlparse(topics.wss_uri)
        if not url.hostname:
            raise PushUnavailableError(f"Could not parse wssUri: {topics.wss_uri}")
        path = url.path or "/mqtt"
        if url.query:
            path = f"{path}?{url.query}"

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=topics.client_id,
            transport="websockets",
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        client.ws_set_options(path=path)
        client.tls_set()
        client.enable_logger(_LOGGER)
        client.on_message = _make_on_message(on_update)
        client.on_connect = self._on_connect(wanted)
        client.on_subscribe = self._on_subscribe
        client.on_disconnect = self._on_disconnect
        self._client = client
        self._stopped.clear()
        self._connected.clear()
        self._subscribed.clear()
        self._connect_error = None

        try:
            client.connect_async(url.hostname, url.port or 443, self._keepalive)
            client.loop_start()
        except OSError as ex:
            self._drop_client()
            raise PushUnavailableError(
                f"Could not connect to {url.hostname}: {ex}"
            ) from ex

        # Subscribing happens in the on_connect callback, so that it is sent
        # only once the broker has accepted the connection, and again after
        # any reconnect.
        if not self._connected.wait(self._connect_timeout):
            self._drop_client()
            raise PushUnavailableError(
                f"Timed out after {self._connect_timeout}s waiting for the broker "
                f"at {url.hostname} to accept the connection"
            )
        if self._connect_error is not None:
            error = self._connect_error
            self._drop_client()
            raise PushUnavailableError(f"Broker refused the connection: {error}")
        if not self._subscribed.wait(self._connect_timeout):
            self._drop_client()
            raise PushUnavailableError(
                f"Connected, but the broker did not acknowledge the subscription "
                f"to {list(wanted)} within {self._connect_timeout}s"
            )
        _LOGGER.debug("Subscribed to %s", list(wanted))
        return topics

    def _on_connect(self, topics: tuple[str, ...]):
        def on_connect(client, userdata, flags, reason_code, properties=None) -> None:
            del userdata, flags, properties  # Unused.
            _LOGGER.debug("Connected: %s", reason_code)
            if getattr(reason_code, "is_failure", reason_code != 0):
                self._connect_error = str(reason_code)
            else:
                self._connect_error = None
                client.subscribe([(t, 0) for t in topics])
            self._connected.set()

        return on_connect

    def _on_subscribe(
        self, client, userdata, mid, reason_codes, properties=None
    ) -> None:
        del client, userdata, mid, properties  # Unused.
        _LOGGER.debug("Subscription acknowledged: %s", reason_codes)
        self._subscribed.set()

    def _on_disconnect(
        self, client, userdata, flags=None, reason_code=None, properties=None
    ) -> None:
        del client, userdata, flags, properties  # Unused.
        _LOGGER.debug("Disconnected: %s", reason_code)

    def _drop_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.loop_stop()

    def close(self) -> None:
        """Disconnects from the push channel."""
        self._stopped.set()
        client, self._client = self._client, None
        if client is None:
            return
        client.disconnect()
        client.loop_stop()

    def run_forever(self, timeout: float | None = None) -> None:
        """Blocks until :meth:`close` is called or ``timeout`` elapses.

        :param timeout: Seconds to wait, or None to wait indefinitely.
        :type timeout: float or None
        """
        self._stopped.wait(timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _make_on_message(on_update: UpdateCallback):
    def on_message(client, userdata, message) -> None:
        del client, userdata  # Unused.
        if message.retain or message.dup:
            # The app ignores these; they are not fresh state.
            return
        try:
            payload = json_lib.loads(message.payload)
        except ValueError as ex:
            raise UnknownError(f"Could not decode push payload: {ex}") from ex
        if not isinstance(payload, dict):
            raise UnknownError(f"Unexpected push payload: {payload!r}")
        on_update(DeviceUpdate(topic=message.topic, payload=payload))

    return on_message
