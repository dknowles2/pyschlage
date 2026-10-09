from __future__ import annotations

import sys
from typing import Any
from unittest.mock import Mock, call, patch

import pytest

from pyschlage.exceptions import UnknownError
from pyschlage.push import (
    DELTA,
    DESIRED,
    ID_TOKEN_HEADER,
    REPORTED,
    DeviceUpdate,
    PushClient,
    PushUnavailableError,
    Topics,
)


class TestTopics:
    def test_request_path_for_user(self) -> None:
        assert Topics.request_path() == "users/wss"

    def test_request_path_for_device(self) -> None:
        assert Topics.request_path("__device_id__") == "wss"

    def test_from_json(self, topics_json: dict[str, Any]) -> None:
        topics = Topics.from_json(topics_json)
        assert topics.client_id == "__client_id__"
        assert topics.wss_uri == "wss://iot.example.com/mqtt?X-Amz-Signature=abc"
        assert topics.topics == (
            "schlage/__wifi_uuid__/reported",
            "schlage/__wifi_uuid__/desired",
            "schlage/__wifi_uuid__/delta",
            "schlage/__ble_uuid__/reported",
        )
        assert topics.message == "ok"

    def test_from_json_empty(self) -> None:
        topics = Topics.from_json({})
        assert topics.client_id == ""
        assert topics.wss_uri == ""
        assert topics.topics == ()
        assert topics.message is None
        assert not topics.is_valid()

    def test_from_json_null_topics(self, topics_json: dict[str, Any]) -> None:
        topics_json["topics"] = None
        assert Topics.from_json(topics_json).topics == ()

    def test_of_kind(self, topics_json: dict[str, Any]) -> None:
        topics = Topics.from_json(topics_json)
        assert topics.of_kind(REPORTED) == (
            "schlage/__wifi_uuid__/reported",
            "schlage/__ble_uuid__/reported",
        )
        assert topics.of_kind(DESIRED) == ("schlage/__wifi_uuid__/desired",)
        assert topics.of_kind(DELTA) == ("schlage/__wifi_uuid__/delta",)

    def test_is_valid(self, topics_json: dict[str, Any]) -> None:
        assert Topics.from_json(topics_json).is_valid()

    def test_is_valid_no_client_id(self, topics_json: dict[str, Any]) -> None:
        topics_json["clientId"] = ""
        assert not Topics.from_json(topics_json).is_valid()

    def test_is_valid_no_wss_uri(self, topics_json: dict[str, Any]) -> None:
        topics_json["wssUri"] = ""
        assert not Topics.from_json(topics_json).is_valid()


class TestDeviceUpdate:
    def test_reported(self) -> None:
        update = DeviceUpdate(
            topic="schlage/__wifi_uuid__/reported",
            payload={"reported": {"deviceId": "__wifi_uuid__", "connected": True}},
        )
        assert update.reported == {"deviceId": "__wifi_uuid__", "connected": True}
        assert update.device_id == "__wifi_uuid__"

    def test_device_id_at_top_level(self) -> None:
        update = DeviceUpdate(topic="t", payload={"deviceId": "__wifi_uuid__"})
        assert update.reported == {}
        assert update.device_id == "__wifi_uuid__"

    def test_no_device_id(self) -> None:
        update = DeviceUpdate(topic="t", payload={"reported": {}})
        assert update.device_id is None

    def test_reported_not_a_dict(self) -> None:
        update = DeviceUpdate(topic="t", payload={"reported": "nope"})
        assert update.reported == {}
        assert update.device_id is None

    def test_device_id_not_a_string(self) -> None:
        update = DeviceUpdate(topic="t", payload={"deviceId": 42})
        assert update.device_id is None

    def test_received_at_is_set(self) -> None:
        assert DeviceUpdate(topic="t", payload={}).received_at is not None


class TestGetTopics:
    def test_for_user(self, mock_auth: Mock, topics_json: dict[str, Any]) -> None:
        mock_auth.request.return_value = Mock(json=Mock(return_value=topics_json))
        topics = PushClient(mock_auth).get_topics()
        mock_auth.request.assert_called_once_with(
            "get",
            "users/wss",
            headers={ID_TOKEN_HEADER: "__id_token__"},
            params=None,
        )
        assert topics.client_id == "__client_id__"

    def test_for_device(self, mock_auth: Mock, topics_json: dict[str, Any]) -> None:
        mock_auth.request.return_value = Mock(json=Mock(return_value=topics_json))
        PushClient(mock_auth).get_topics("__wifi_uuid__")
        mock_auth.request.assert_called_once_with(
            "get",
            "wss",
            headers={ID_TOKEN_HEADER: "__id_token__"},
            params={"deviceId": "__wifi_uuid__"},
        )


class TestConnect:
    def test_connect(self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock) -> None:
        on_update = Mock()
        client = PushClient(mock_auth)
        assert client.connect(on_update, topics=topics) == topics

        mock_mqtt.Client.assert_called_once_with(
            mock_mqtt.CallbackAPIVersion.VERSION2,
            client_id="__client_id__",
            transport="websockets",
            protocol=mock_mqtt.MQTTv311,
            clean_session=True,
        )
        mqtt_client = mock_mqtt.Client.return_value
        mqtt_client.ws_set_options.assert_called_once_with(
            path="/mqtt?X-Amz-Signature=abc"
        )
        mqtt_client.tls_set.assert_called_once_with()
        mqtt_client.connect.assert_called_once_with("iot.example.com", 443, 1800)
        mqtt_client.subscribe.assert_called_once_with(
            [
                ("schlage/__wifi_uuid__/reported", 0),
                ("schlage/__ble_uuid__/reported", 0),
            ]
        )
        mqtt_client.loop_start.assert_called_once_with()

    def test_connect_fetches_topics(
        self, mock_auth: Mock, topics_json: dict[str, Any], mock_mqtt: Mock
    ) -> None:
        mock_auth.request.return_value = Mock(json=Mock(return_value=topics_json))
        PushClient(mock_auth).connect(Mock())
        mock_auth.request.assert_called_once()

    def test_connect_custom_keepalive(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        PushClient(mock_auth, keepalive=60).connect(Mock(), topics=topics)
        mock_mqtt.Client.return_value.connect.assert_called_once_with(
            "iot.example.com", 443, 60
        )

    def test_connect_explicit_port(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        topics = Topics(
            client_id=topics.client_id,
            wss_uri="wss://iot.example.com:8443/mqtt",
            topics=topics.topics,
        )
        PushClient(mock_auth).connect(Mock(), topics=topics)
        mock_mqtt.Client.return_value.connect.assert_called_once_with(
            "iot.example.com", 8443, 1800
        )
        mock_mqtt.Client.return_value.ws_set_options.assert_called_once_with(
            path="/mqtt"
        )

    def test_connect_no_path(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        topics = Topics(
            client_id=topics.client_id,
            wss_uri="wss://iot.example.com",
            topics=topics.topics,
        )
        PushClient(mock_auth).connect(Mock(), topics=topics)
        mock_mqtt.Client.return_value.ws_set_options.assert_called_once_with(
            path="/mqtt"
        )

    def test_connect_multiple_kinds(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        PushClient(mock_auth).connect(Mock(), topics=topics, kinds=(REPORTED, DELTA))
        mock_mqtt.Client.return_value.subscribe.assert_called_once_with(
            [
                ("schlage/__wifi_uuid__/reported", 0),
                ("schlage/__ble_uuid__/reported", 0),
                ("schlage/__wifi_uuid__/delta", 0),
            ]
        )

    def test_connect_invalid_topics(self, mock_auth: Mock, mock_mqtt: Mock) -> None:
        with pytest.raises(PushUnavailableError, match="unusable connection details"):
            PushClient(mock_auth).connect(Mock(), topics=Topics("", ""))

    def test_connect_no_matching_topics(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        topics = Topics(
            client_id=topics.client_id,
            wss_uri=topics.wss_uri,
            topics=("schlage/__wifi_uuid__/desired",),
        )
        with pytest.raises(PushUnavailableError, match="No topics of kind"):
            PushClient(mock_auth).connect(Mock(), topics=topics)

    def test_connect_unparseable_uri(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        topics = Topics(
            client_id=topics.client_id,
            wss_uri="not a uri",
            topics=topics.topics,
        )
        with pytest.raises(PushUnavailableError, match="Could not parse wssUri"):
            PushClient(mock_auth).connect(Mock(), topics=topics)

    def test_connect_fails(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        mock_mqtt.Client.return_value.connect.side_effect = OSError("refused")
        client = PushClient(mock_auth)
        with pytest.raises(PushUnavailableError, match="Could not connect to"):
            client.connect(Mock(), topics=topics)
        # The failed client is dropped, so close() is a no-op.
        client.close()
        mock_mqtt.Client.return_value.disconnect.assert_not_called()

    def test_paho_missing(self, mock_auth: Mock, topics: Topics) -> None:
        with (
            patch.dict(sys.modules, {"paho.mqtt": None, "paho.mqtt.client": None}),
            pytest.raises(PushUnavailableError, match="paho-mqtt"),
        ):
            PushClient(mock_auth).connect(Mock(), topics=topics)


class TestOnMessage:
    def test_dispatches_update(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        on_update = Mock()
        PushClient(mock_auth).connect(on_update, topics=topics)
        on_message = mock_mqtt.Client.return_value.on_message
        on_message(
            None,
            None,
            Mock(
                topic="schlage/__wifi_uuid__/reported",
                payload=b'{"reported": {"deviceId": "__wifi_uuid__"}}',
                retain=False,
                dup=False,
            ),
        )
        assert on_update.call_count == 1
        update = on_update.call_args.args[0]
        assert update.topic == "schlage/__wifi_uuid__/reported"
        assert update.device_id == "__wifi_uuid__"

    @pytest.mark.parametrize(("retain", "dup"), [(True, False), (False, True)])
    def test_ignores_retained_and_duplicate(
        self,
        mock_auth: Mock,
        topics: Topics,
        mock_mqtt: Mock,
        retain: bool,
        dup: bool,
    ) -> None:
        on_update = Mock()
        PushClient(mock_auth).connect(on_update, topics=topics)
        mock_mqtt.Client.return_value.on_message(
            None, None, Mock(topic="t", payload=b"{}", retain=retain, dup=dup)
        )
        on_update.assert_not_called()

    def test_undecodable_payload(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        PushClient(mock_auth).connect(Mock(), topics=topics)
        with pytest.raises(UnknownError, match="Could not decode push payload"):
            mock_mqtt.Client.return_value.on_message(
                None,
                None,
                Mock(topic="t", payload=b"not json", retain=False, dup=False),
            )

    def test_non_object_payload(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        PushClient(mock_auth).connect(Mock(), topics=topics)
        with pytest.raises(UnknownError, match="Unexpected push payload"):
            mock_mqtt.Client.return_value.on_message(
                None, None, Mock(topic="t", payload=b"[1, 2]", retain=False, dup=False)
            )


class TestClose:
    def test_close(self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock) -> None:
        client = PushClient(mock_auth)
        client.connect(Mock(), topics=topics)
        client.close()
        assert mock_mqtt.Client.return_value.mock_calls[-2:] == [
            call.disconnect(),
            call.loop_stop(),
        ]

    def test_close_without_connect(self, mock_auth: Mock, mock_mqtt: Mock) -> None:
        PushClient(mock_auth).close()
        mock_mqtt.Client.assert_not_called()

    def test_context_manager_closes(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        with PushClient(mock_auth) as client:
            client.connect(Mock(), topics=topics)
        mock_mqtt.Client.return_value.disconnect.assert_called_once_with()

    def test_run_forever_returns_on_close(
        self, mock_auth: Mock, topics: Topics, mock_mqtt: Mock
    ) -> None:
        client = PushClient(mock_auth)
        client.connect(Mock(), topics=topics)
        client.close()
        # Already stopped, so this returns immediately.
        client.run_forever()

    def test_run_forever_times_out(self, mock_auth: Mock) -> None:
        PushClient(mock_auth).run_forever(timeout=0.01)
