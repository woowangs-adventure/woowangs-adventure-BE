from app.orm import Base


def test_robot_and_map_tables_define_persistent_state():
    assert set(Base.metadata.tables) == {"robots", "maps"}

    robots = Base.metadata.tables["robots"]
    assert {
        "robot_id",
        "pose_x",
        "pose_y",
        "pose_yaw",
        "localization_available",
        "localization_method",
        "map_version",
    }.issubset(robots.columns.keys())

    maps = Base.metadata.tables["maps"]
    assert {
        "version",
        "robot_id",
        "resolution",
        "origin_x",
        "origin_y",
        "local_path",
        "is_current",
    }.issubset(maps.columns.keys())
