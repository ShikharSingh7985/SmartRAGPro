from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from backend.app.core.config import get_settings
from backend.app.services.resources import GeminiGenerator


@pytest.mark.parametrize(
    "content",
    [
        "Revenue is 42 million. [1]",
        [{"type": "text", "text": "Revenue is 42 million. [1]"}],
    ],
)
def test_gemini_accepts_text_and_content_block_responses(stack, monkeypatch, content):
    transport = Mock()
    transport.invoke.return_value = AIMessage(content=content)
    monkeypatch.setattr(
        "backend.app.services.resources.ChatGoogleGenerativeAI", Mock(return_value=transport)
    )
    settings = get_settings().model_copy(
        update={
            "gemini_api_key": SecretStr("isolated-transport-test-only"),
        }
    )
    generator = GeminiGenerator(settings)
    assert (
        generator.answer("Revenue?", "[1] Revenue is 42 million.") == "Revenue is 42 million. [1]"
    )


def test_missing_live_credentials_fail_instead_of_fake_answer(stack):
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiGenerator(get_settings())
