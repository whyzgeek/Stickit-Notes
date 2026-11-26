"""``python -m stickit``. Kept syntax-compatible with old Pythons so it can explain itself."""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - this guard exists for old interpreters
    # Hooks must not fail loudly on an old interpreter (macOS ships 3.9).
    if len(sys.argv) > 1 and sys.argv[1] == "hook":
        sys.exit(0)
    found = ".".join(str(part) for part in sys.version_info[:2])
    sys.stderr.write(f"stickit-notes needs Python 3.11 or newer (found {found})\n")
    sys.exit(1)

from stickit.cli import main

sys.exit(main())
