'''Unit tests for the shared logging policy, as seen from a controller subprocess.'''

import subprocess
import sys

CONTROLLER = '''
import structlog
import anya  # configures logging when ANYA_JOB_ID is set
log = structlog.get_logger()
log.debug("debug noise")
log.warning("TAVILY_API_KEY not set")
api_key = "sk-SECRET-VALUE"
try:
    raise RuntimeError("boom")
except RuntimeError:
    log.exception("failed")
print("REPORT")
'''


def test_controller_logs_go_to_stderr_without_locals(tmp_path):
    # Regression: in controllers, structlog printed to stdout (the report) and its default
    # Rich tracebacks showed local variables, such as API keys.
    env = {'ANYA_JOB_ID': 'j', 'PATH': '/usr/bin:/bin'}
    proc = subprocess.run([sys.executable, '-c', CONTROLLER], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == 'REPORT'
    assert 'TAVILY_API_KEY not set' in proc.stderr
    assert 'RuntimeError: boom' in proc.stderr
    assert 'sk-SECRET-VALUE' not in proc.stderr
    assert 'debug noise' not in proc.stderr
