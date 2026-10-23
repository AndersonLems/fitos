"""Run Streamlit in a fresh interpreter so settings never point at the user's DB."""
import os
import subprocess
import sys
from pathlib import Path


def test_streamlit_real_flows(tmp_path):
    env = dict(os.environ, FITOS_DATABASE_URL=f"sqlite:///{tmp_path / 'ui.db'}",
               FITOS_ACCESS_CODE="", GEMINI_API_KEY="", FITOS_UI_TEST_DIR=str(tmp_path))
    result = subprocess.run([sys.executable, str(Path(__file__).parent / 'ui_flow_runner.py')],
                            env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
