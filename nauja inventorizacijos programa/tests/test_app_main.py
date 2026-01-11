import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch

import path_setup  # noqa: F401


class TestAppMain(unittest.TestCase):
    def test_main_requires_password(self):
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

        with patch.dict(sys.modules, {"streamlit": stub}):
            with patch.dict(os.environ, {}, clear=True):
                if "app" in sys.modules:
                    del sys.modules["app"]
                import app  # noqa: E402

                importlib.reload(app)

                with self.assertRaises(RuntimeError):
                    app.main()

        self.assertTrue(calls["error"])
