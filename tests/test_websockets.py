import pytest
from starlette.websockets import WebSocketDisconnect


def test_edge_pose_is_broadcast_to_dashboard(client):
    with client.websocket_connect("/ws/dashboard/TB3-01") as dashboard:
        snapshot = dashboard.receive_json()
        assert snapshot["type"] == "state.snapshot"
        assert snapshot["data"]["online"] is False

        with client.websocket_connect("/ws/edge/TB3-01?token=test-token") as edge:
            connected = dashboard.receive_json()
            assert connected["type"] == "robot.connection"
            assert connected["data"]["online"] is True

            edge.send_json({
                "type": "pose",
                "data": {
                    "x": 0.3,
                    "y": 1.35,
                    "yaw": 0.55,
                    "map_version": "map-sha256",
                },
            })
            event = dashboard.receive_json()
            assert event["type"] == "robot.pose"
            assert event["data"]["x"] == 0.3
            assert edge.receive_json()["type"] == "ack"


def test_localization_status_is_explicit(client):
    with client.websocket_connect("/ws/edge/TB3-01?token=test-token") as edge:
        edge.send_json({
            "type": "status",
            "data": {
                "ros_connected": True,
                "tf_available": True,
                "localization_available": True,
                "localization_method": "amcl",
                "map_version": "map-sha256",
            },
        })
        assert edge.receive_json()["type"] == "ack"

        response = client.get("/api/v1/robots/TB3-01/state")
        assert response.status_code == 200
        status = response.json()["status"]
        assert status["localization_available"] is True
        assert status["localization_method"] == "amcl"
        assert status["map_version"] == "map-sha256"


def test_dashboard_velocity_command_is_routed_to_edge(client):
    capabilities = client.get("/api/v1/control/capabilities")
    assert capabilities.json()["enabled"] is True

    with client.websocket_connect("/ws/dashboard/TB3-01") as dashboard:
        dashboard.receive_json()
        with client.websocket_connect("/ws/edge/TB3-01?token=test-token") as edge:
            assert dashboard.receive_json()["type"] == "robot.connection"

            dashboard.send_json({"type": "control.acquire", "data": {}})
            assert dashboard.receive_json()["type"] == "control.acquired"

            dashboard.send_json({
                "type": "control.velocity",
                "data": {"linear": 0.6, "angular": -0.2, "ttl_ms": 300},
            })
            command = edge.receive_json()
            assert command["type"] == "command.velocity"
            assert command["data"]["linear"] == 0.6
            assert command["data"]["angular"] == -0.2
            assert dashboard.receive_json()["type"] == "control.sent"

            edge.send_json({
                "type": "control.ack",
                "data": {"command_id": command["data"]["command_id"], "applied": True},
            })
            assert dashboard.receive_json()["type"] == "robot.control_ack"
            assert edge.receive_json()["type"] == "ack"

            dashboard.send_json({"type": "control.release", "data": {}})
            assert edge.receive_json()["type"] == "command.stop"
            assert dashboard.receive_json()["type"] == "control.released"


def test_edge_rejects_wrong_token(client):
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect("/ws/edge/TB3-01?token=wrong"),
    ):
        pass
    assert error.value.code == 1008


def test_webrtc_signaling_relays_offer_and_answer(client):
    with client.websocket_connect("/ws/webrtc/MINI-01/viewer") as viewer:
        first = viewer.receive_json()
        assert first["type"] == "webrtc.peer"
        assert first["data"] == {"role": "publisher", "online": False}

        with client.websocket_connect(
            "/ws/webrtc/MINI-01/publisher?token=test-token"
        ) as publisher:
            assert publisher.receive_json()["data"] == {"role": "viewer", "online": True}
            assert viewer.receive_json()["data"] == {"role": "publisher", "online": True}

            viewer.send_json({
                "type": "webrtc.offer",
                "data": {"sdp": {"type": "offer", "sdp": "viewer-sdp"}},
            })
            offer = publisher.receive_json()
            assert offer["type"] == "webrtc.offer"
            assert offer["data"]["sdp"]["sdp"] == "viewer-sdp"

            publisher.send_json({
                "type": "webrtc.answer",
                "data": {"sdp": {"type": "answer", "sdp": "publisher-sdp"}},
            })
            answer = viewer.receive_json()
            assert answer["type"] == "webrtc.answer"
            assert answer["data"]["sdp"]["sdp"] == "publisher-sdp"


def test_webrtc_publisher_requires_device_token(client):
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect("/ws/webrtc/MINI-01/publisher?token=wrong"),
    ):
        pass
    assert error.value.code == 1008


def test_mini_light_requires_owner_and_reports_state(client):
    with client.websocket_connect('/ws/dashboard/MINI-01') as dashboard:
        dashboard.receive_json()
        with client.websocket_connect('/ws/edge/MINI-01?token=test-token') as edge:
            dashboard.receive_json()
            edge.send_json({'type': 'status', 'data': {
                'headlight_available': True, 'headlight_on': False,
            }})
            assert edge.receive_json()['type'] == 'ack'
            dashboard.receive_json()
            dashboard.send_json({'type': 'control.light', 'data': {'on': True}})
            assert dashboard.receive_json()['type'] == 'error'
            dashboard.send_json({'type': 'control.acquire'})
            assert dashboard.receive_json()['type'] == 'control.acquired'
            dashboard.send_json({'type': 'control.light', 'data': {'on': 'false'}})
            assert dashboard.receive_json()['type'] == 'error'
            dashboard.send_json({'type': 'control.light', 'data': {'on': True}})
            command = edge.receive_json()
            assert command['type'] == 'command.light'
            assert command['data']['on'] is True
            assert dashboard.receive_json()['type'] == 'control.sent'
            with client.websocket_connect('/ws/dashboard/MINI-01') as other:
                other.receive_json()
                other.send_json({'type': 'control.acquire'})
                assert other.receive_json()['type'] == 'error'
                other.send_json({'type': 'control.light', 'data': {'on': False}})
                assert other.receive_json()['type'] == 'error'
            edge.send_json({'type': 'status', 'data': {'headlight_on': True}})
            assert edge.receive_json()['type'] == 'ack'
            assert dashboard.receive_json()['data']['headlight_on'] is True


def test_turtlebot_without_light_capability_rejects_light(client):
    with client.websocket_connect('/ws/dashboard/TB3-01') as dashboard:
        dashboard.receive_json()
        with client.websocket_connect('/ws/edge/TB3-01?token=test-token'):
            dashboard.receive_json()
            dashboard.send_json({'type': 'control.acquire'})
            assert dashboard.receive_json()['type'] == 'control.acquired'
            dashboard.send_json({'type': 'control.light', 'data': {'on': True}})
            assert dashboard.receive_json()['type'] == 'error'
