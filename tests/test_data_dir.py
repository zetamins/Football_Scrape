from football.data_dir import _PROJECT_ROOT, data_dir


def test_data_dir_is_project_root_data_directory():
    assert data_dir() == _PROJECT_ROOT / "data"
