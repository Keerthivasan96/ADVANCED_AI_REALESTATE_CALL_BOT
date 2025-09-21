import logging
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import FALLBACK_REPLY, _sessions, app
from app.voice2 import OptimizedVoiceAssistant


@pytest.fixture(autouse=True)
def clear_sessions():
    _sessions.clear()
    yield
    _sessions.clear()


def test_process_timeout_uses_fallback(monkeypatch, caplog):
    client = TestClient(app)
    call_sid = "CA123TIMEOUT"

    def slow_generate(self, user_input, intent):
        time.sleep(5)
        return "This should not be used"

    monkeypatch.setattr(
        OptimizedVoiceAssistant, "generate_fast_response", slow_generate
    )
    caplog.set_level(logging.WARNING)

    client.post("/voice", data={"CallSid": call_sid, "From": "+100", "To": "+200"})

    response = client.post(
        "/process",
        data={"CallSid": call_sid, "SpeechResult": "Tell me about ROI"},
    )

    assert response.status_code == 200
    body = response.text
    assert FALLBACK_REPLY in body
    assert "<Gather" in body
    assert call_sid in "".join(caplog.messages)
    assert call_sid in _sessions
