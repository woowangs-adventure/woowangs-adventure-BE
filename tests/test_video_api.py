def test_recorded_video_can_be_uploaded_and_streamed(client):
    content = b"test-mp4-content"
    response = client.put(
        "/api/v1/robots/MINI-01/video",
        headers={"X-Device-Token": "test-token"},
        files={"video": ("inspection.mp4", content, "video/mp4")},
    )

    assert response.status_code == 200
    metadata = response.json()
    assert metadata["robot_id"] == "MINI-01"
    assert metadata["mode"] == "recorded"
    assert metadata["content_type"] == "video/mp4"
    assert metadata["size_bytes"] == len(content)
    assert metadata["content_url"].startswith(
        "/api/v1/robots/MINI-01/video/content?v="
    )

    stored = client.get("/api/v1/robots/MINI-01/video")
    assert stored.status_code == 200
    assert stored.json()["version"] == metadata["version"]

    streamed = client.get("/api/v1/robots/MINI-01/video/content")
    assert streamed.status_code == 200
    assert streamed.headers["content-type"] == "video/mp4"
    assert streamed.content == content


def test_video_upload_requires_device_token(client):
    response = client.put(
        "/api/v1/robots/MINI-01/video",
        files={"video": ("inspection.webm", b"video", "video/webm")},
    )
    assert response.status_code == 401


def test_missing_video_returns_not_found(client):
    assert client.get("/api/v1/robots/MINI-01/video").status_code == 404
