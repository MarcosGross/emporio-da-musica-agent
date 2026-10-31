import pytest

from emporio_agent.data import load_data


@pytest.fixture(scope="session")
def data():
    return load_data()
