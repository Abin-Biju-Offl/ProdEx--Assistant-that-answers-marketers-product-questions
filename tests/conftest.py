"""Shared pytest fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Tests must never pick up a developer's real .env or secrets.
os.environ.setdefault("GITHUB_SOURCE", "mock")
os.environ.setdefault("INTERNAL_API_KEY", "test-key")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def fixtures_repo() -> Path:
    return ROOT / "fixtures" / "repo"


@pytest.fixture
def long_markdown() -> str:
    """A document with a table, a code fence and a long list, big enough to force splits."""
    return """# Title

Intro paragraph under the H1.

## First section

This is a plain paragraph that should stay whole.

| Column | Meaning | Limit |
|---|---|---|
| rows | rows per export | 250000 |
| burst | requests per second | 20 |

```python
def export(workspace_id):
    # a code block that must never be split in half
    return client.get(f"/v2/exports/{workspace_id}")
```

- item one
- item two
  - nested item two-a
  - nested item two-b
- item three

""" + "\n\n".join(f"Paragraph {i}. " + "detail " * 40 for i in range(12)) + """
"""


@pytest.fixture
def db_available() -> bool:
    try:
        from app import db

        db.execute("SELECT 1")
        return True
    except Exception:
        return False