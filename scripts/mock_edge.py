"""Send fake TurtleBot pose data to the development backend."""

import argparse
import asyncio
import json
import math
import time

from websockets.asyncio.client import connect


async def run(url: str, robot_id: str, token: str) -> None:
    endpoint = f"{url.rstrip('/')}/ws/edge/{robot_id}?token={token}"
    async with connect(endpoint) as socket:
        await socket.send(json.dumps({
            "type": "hello",
            "data": {"agent_version": "mock-0.1.0", "ros_distro": "humble"},
        }))
        await socket.recv()
        started = time.monotonic()
        while True:
            elapsed = time.monotonic() - started
            await socket.send(json.dumps({
                "type": "pose",
                "data": {
                    "x": round(math.cos(elapsed / 4), 4),
                    "y": round(math.sin(elapsed / 4), 4),
                    "yaw": round((elapsed / 4) % (2 * math.pi), 4),
                },
            }))
            await socket.recv()
            await asyncio.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8000")
    parser.add_argument("--robot-id", default="TB3-01")
    parser.add_argument("--token", default="change-this-device-token")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.robot_id, args.token))


if __name__ == "__main__":
    main()
