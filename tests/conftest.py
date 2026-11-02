import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from emporio_agent.data import load_data


@pytest.fixture(scope="session")
def data():
    return load_data()


class ScriptedModel(GenericFakeChatModel):
    """Fake chat model that replays fixed messages and accepts bind_tools."""

    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def scripted():
    """Factory for a fake model that replays the given AI messages in order (no API calls)."""
    def make(*messages: AIMessage) -> ScriptedModel:
        return ScriptedModel(messages=iter(messages))
    return make
