import re
from pathlib import Path

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

    def latest_path(self, robot_id: str) -> Path:
        validate_robot_id(robot_id)
        return self._root / robot_id / "latest.png"
