import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if getattr(sys, "frozen", False):
    bundle_dir = Path(sys.executable).resolve().parent
    meipass_dir = Path(getattr(sys, "_MEIPASS", ""))

    for extra_path in [bundle_dir, meipass_dir, meipass_dir / "core", meipass_dir / "ui"]:
        if extra_path and str(extra_path) not in sys.path and extra_path.exists():
            sys.path.insert(0, str(extra_path))

    env_file = bundle_dir / ".env"
    if not env_file.exists() and meipass_dir.exists():
        env_file = meipass_dir / ".env"
    if env_file.exists():
        os.environ.setdefault("CEO_TRADE_ENV_FILE", str(env_file))

from ui.main import main


if __name__ == "__main__":
    raise SystemExit(main())
