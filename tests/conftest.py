import os
import shutil
import tempfile
from pathlib import Path

# Isolate HOME/TMP before imports that may trigger Chroma or MemPalace initialization.
_original_env = {}
_repo_root = Path(__file__).resolve().parents[1]
_test_tmp_root = Path(os.environ.get("WRITING_SIDECAR_TEST_TMPDIR", _repo_root / ".tmp-tests"))
_test_tmp_root.mkdir(parents=True, exist_ok=True)
_session_tmp = tempfile.mkdtemp(prefix="writing_sidecar_session_", dir=str(_test_tmp_root))

for _var in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "TMP", "TEMP", "TMPDIR"):
    _original_env[_var] = os.environ.get(_var)

os.environ["HOME"] = _session_tmp
os.environ["USERPROFILE"] = _session_tmp
os.environ["HOMEDRIVE"] = os.path.splitdrive(_session_tmp)[0] or "C:"
os.environ["HOMEPATH"] = os.path.splitdrive(_session_tmp)[1] or _session_tmp
os.environ["TMP"] = _session_tmp
os.environ["TEMP"] = _session_tmp
os.environ["TMPDIR"] = _session_tmp
tempfile.tempdir = _session_tmp


def pytest_sessionfinish(session, exitstatus):
    for var, orig in _original_env.items():
        if orig is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = orig
    tempfile.tempdir = None
    shutil.rmtree(_session_tmp, ignore_errors=True)
