def test_swagger_documents_every_http_api(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    expected_paths = {
        "/health",
        "/ready",
        "/api/v1/control/capabilities",
        "/api/v1/robots",
        "/api/v1/robots/{robot_id}/state",
        "/api/v1/maps/current",
        "/api/v1/robots/{robot_id}/map",
        "/api/v1/robots/{robot_id}/map/latest",
        "/api/v1/robots/{robot_id}/video",
        "/api/v1/robots/{robot_id}/video/content",
    }

    assert expected_paths == set(schema["paths"])


def test_swagger_video_upload_uses_file_picker_and_authorization(client):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/robots/{robot_id}/video"]["put"]
    request_schema = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    request_model = schema["components"]["schemas"][request_schema["$ref"].split("/")[-1]]
    video_property = request_model["properties"]["video"]

    assert video_property["type"] == "string"
    assert (
        video_property.get("format") == "binary"
        or video_property.get("contentMediaType") == "application/octet-stream"
    )
    assert operation["security"] == [{"EdgeDeviceToken": []}]
    security_scheme = schema["components"]["securitySchemes"]["EdgeDeviceToken"]
    assert security_scheme["type"] == "apiKey"
    assert security_scheme["in"] == "header"
    assert security_scheme["name"] == "X-Device-Token"
