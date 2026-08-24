import json
import re
from pathlib import Path

from pydantic import ValidationError

from .models import MapState

ROBOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate_robot_id(robot_id: str) -> str:
    if not ROBOT_ID_PATTERN.fullmatch(robot_id):
        raise ValueError("robot_id must contain only letters, numbers, hyphens, or underscores")
    return robot_id


class MapStore:
    def __init__(self, data_dir: Path, max_bytes: int) -> None:
        self._root = data_dir / "maps"
        self._max_bytes = max_bytes

    def prepare(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def save_png(self, robot_id: str, content: bytes) -> Path:
        validate_robot_id(robot_id)
        if not content.startswith(PNG_SIGNATURE):
            raise ValueError("map image must be a valid PNG")
        if len(content) > self._max_bytes:
            raise ValueError(f"map image exceeds {self._max_bytes} bytes")
        robot_dir = self._root / robot_id
        robot_dir.mkdir(parents=True, exist_ok=True)
        target = robot_dir / "latest.png"
        temporary = robot_dir / "latest.tmp"
        temporary.write_bytes(content)
        temporary.replace(target)
        return target

    def save_metadata(self, robot_id: str, state: MapState) -> Path:
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

    def load_metadata(self, robot_id: str) -> MapState | None:
        validate_robot_id(robot_id)
        path = self._root / robot_id / "metadata.json"
        if not path.exists() or not self.latest_path(robot_id).exists():
            return None
        try:
            return MapState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            return None

    def load_all_metadata(self) -> dict[str, MapState]:
        if not self._root.exists():
            return {}
        states: dict[str, MapState] = {}
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

    def latest_path(self, robot_id: str) -> Path:
        validate_robot_id(robot_id)
        return self._root / robot_id / "latest.png"
