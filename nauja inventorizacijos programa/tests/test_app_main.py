import importlib
import sys
import types

import pytest


def test_main_requires_password(monkeypatch):
    calls = {"error": False}

    def error(msg):
        calls["error"] = True

    def stop():
        raise RuntimeError("stopped")

    stub = types.SimpleNamespace(
        set_page_config=lambda **kwargs: None,
        error=error,
        stop=stop,
    )

    sys.modules["streamlit"] = stub
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    import app  # noqa: E402

    importlib.reload(app)

    with pytest.raises(RuntimeError):
        app.main()

    assert calls["error"] is True
