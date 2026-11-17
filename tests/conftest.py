import pytest


@pytest.fixture(autouse=True)
def facesort_home(tmp_path, monkeypatch):
    home = tmp_path / "_home"
    monkeypatch.setenv("FACESORT_HOME", str(home))
    return home
