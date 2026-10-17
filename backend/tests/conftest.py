import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LEVITATE_DB", str(Path(tempfile.mkdtemp()) / "test.sqlite"))
os.environ["LEVITATE_IGNORE_MEASURED"] = "1"     # tests use the documented assumptions, not bench overlays
