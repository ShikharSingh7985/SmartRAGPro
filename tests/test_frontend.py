from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.conftest import authenticate


def test_streamlit_login_navigation_and_logout(stack, monkeypatch):
    client, _, _ = stack
    authenticate(client)

    def request(method, url, **kwargs):
        kwargs.pop("timeout", None)
        path = "/api/v1" + url.split("/api/v1", 1)[1]
        return client.request(method, path, **kwargs)

    monkeypatch.setattr("httpx.request", request)
    app = AppTest.from_file(str(Path("frontend/app.py").resolve()), default_timeout=20).run()
    assert not app.exception
    app.text_input[0].set_value("alice@example.com")
    app.text_input[1].set_value("strong-test-password")
    app.button[0].click().run()
    assert not app.exception
    assert any(title.value == "Ask your documents" for title in app.title)
    app.radio[0].set_value("Documents").run()
    assert any(title.value == "Your documents" for title in app.title)
    assert not app.exception
    next(button for button in app.button if button.label == "Log out").click().run()
    assert not app.exception
    assert app.title[0].value == "SmartRAG Pro"
    assert "token" not in app.session_state
