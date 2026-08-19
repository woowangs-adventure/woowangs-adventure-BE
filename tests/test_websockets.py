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
                "data": {"x": 0.3, "y": 1.35, "yaw": 0.55},
            })
            event = dashboard.receive_json()
            assert event["type"] == "robot.pose"
            assert event["data"]["x"] == 0.3
            assert edge.receive_json()["type"] == "ack"


def test_edge_rejects_wrong_token(client):
    with (
        pytest.raises(WebSocketDisconnect) as error,
        client.websocket_connect("/ws/edge/TB3-01?token=wrong"),
    ):
        pass
    assert error.value.code == 1008
