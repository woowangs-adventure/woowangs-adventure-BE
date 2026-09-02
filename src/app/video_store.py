import hashlib
import json
from pathlib import Path

from fastapi import UploadFile
from pydantic import ValidationError

from .map_store import validate_robot_id
from .models import VideoState

SUPPORTED_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
}


class VideoStore:
    def __init__(self, data_dir: Path, max_bytes: int) -> None:
        self._root = data_dir / "videos"
        self._max_bytes = max_bytes

    def prepare(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    async def save_upload(
        self,
        robot_id: str,
        upload: UploadFile,
    ) -> tuple[Path, int, str]:
        validate_robot_id(robot_id)
        suffix = SUPPORTED_VIDEO_TYPES.get(upload.content_type or "")
        if suffix is None:
            raise ValueError("video must use video/mp4 or video/webm")

        robot_dir = self._root / robot_id
        robot_dir.mkdir(parents=True, exist_ok=True)
        temporary = robot_dir / "upload.tmp"
        target = robot_dir / f"latest{suffix}"
        digest = hashlib.sha256()
        size = 0

        try:
            with temporary.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise ValueError(f"video exceeds {self._max_bytes} bytes")
                    digest.update(chunk)
                    output.write(chunk)
            if size == 0:
                raise ValueError("video must not be empty")
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        return target, size, digest.hexdigest()

    def save_metadata(self, robot_id: str, state: VideoState) -> Path:
        validate_robot_id(robot_id)
        robot_dir = self._root / robot_id
        robot_dir.mkdir(parents=True, exist_ok=True)
        target = robot_dir / "metadata.json"
        temporary = robot_dir / "metadata.tmp"
        temporary.write_text(
            json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def load_metadata(self, robot_id: str) -> VideoState | None:
        validate_robot_id(robot_id)
        path = self._root / robot_id / "metadata.json"
        if not path.exists():
            return None
        try:
            state = VideoState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            return None
        return state if self.content_path(robot_id, state).exists() else None

    def load_all_metadata(self) -> dict[str, VideoState]:
        if not self._root.exists():
            return {}
        states: dict[str, VideoState] = {}
        for robot_dir in self._root.iterdir():
            if not robot_dir.is_dir():
                continue
            try:
                state = self.load_metadata(robot_dir.name)
            except ValueError:
                continue
            if state is not None:
                states[robot_dir.name] = state
        return states

    def content_path(self, robot_id: str, state: VideoState) -> Path:
        validate_robot_id(robot_id)
        suffix = SUPPORTED_VIDEO_TYPES.get(state.content_type)
        if suffix is None:
            raise ValueError("unsupported stored video type")
        return self._root / robot_id / f"latest{suffix}"
