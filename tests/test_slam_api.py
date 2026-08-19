import json
import struct
import zlib


def png(width: int = 2, height: int = 2) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    pixels = b"\x00\x00\x7f\x00\xcd\xff"
    return (
        signature
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def test_upload_and_read_latest_map(client):
    metadata = {
        "width": 2,
        "height": 2,
        "resolution": 0.05,
        "origin_x": -1.7,
        "origin_y": -0.75,
        "origin_yaw": 0.0,
    }
    response = client.put(
        "/api/v1/robots/TB3-01/map",
        headers={"X-Device-Token": "test-token"},
        data={"metadata": json.dumps(metadata)},
        files={"image": ("map.png", png(), "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["resolution"] == 0.05
    assert response.json()["image_url"].startswith(
        "/api/v1/robots/TB3-01/map/latest?v="
    )

    image_response = client.get("/api/v1/robots/TB3-01/map/latest")
    assert image_response.status_code == 200
    assert image_response.content.startswith(b"\x89PNG")

    state_response = client.get("/api/v1/robots/TB3-01/state")
    assert state_response.status_code == 200
    assert state_response.json()["map"]["width"] == 2


def test_map_upload_requires_edge_token(client):
    response = client.put(
        "/api/v1/robots/TB3-01/map",
        data={"metadata": "{}"},
        files={"image": ("map.png", png(), "image/png")},
    )
    assert response.status_code == 401
