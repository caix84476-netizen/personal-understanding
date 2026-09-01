# Personal Understanding — packaging shim.
#
# The skill scripts are written as flat sibling modules (``from cli_runtime
# import ...``) so they can run directly out of a checked-out scripts/
# folder. When pip installs them under the ``personal_understanding`` package,
# that flat import style would break, so we put the package's own directory on
# sys.path first. This is pure packaging glue: it changes no behavior of the
# scripts themselves and is never imported when the skill runs from source.
from __future__ import annotations

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
