# SPDX-License-Identifier: Apache-2.0
"""Test bootstrap for the reference tree. In the repo, use `pythonpath = ["src", "."]` in pyproject instead."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))
