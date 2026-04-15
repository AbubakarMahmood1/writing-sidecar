from __future__ import annotations

import os
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings(
    "ignore",
    message=r"'asyncio\.iscoroutinefunction' is deprecated and slated for removal in Python 3\.16; use inspect\.iscoroutinefunction\(\) instead",
    category=DeprecationWarning,
)

from tests.helpers import fixture_workspace


@pytest.fixture
def witcher_fixture():
    with fixture_workspace("witcher_dc_representative", "Witcher-DC") as context:
        yield context


@pytest.fixture
def template_fixture():
    with fixture_workspace(
        "cdlc_template_not_built",
        "_project-template",
        build=False,
        invoke_from_project_root=True,
    ) as context:
        yield context


@pytest.fixture(scope="session")
def live_vault_root() -> Path | None:
    raw = os.environ.get("WRITING_SIDECAR_LIVE_VAULT")
    if not raw:
        return None
    if raw == "1":
        return Path(__file__).resolve().parents[2]
    return Path(raw).expanduser().resolve()


def pytest_collection_modifyitems(config, items):
    if os.environ.get("WRITING_SIDECAR_LIVE_VAULT"):
        return

    deselected = [item for item in items if "live_vault" in item.keywords]
    if not deselected:
        return

    config.hook.pytest_deselected(items=deselected)
    items[:] = [item for item in items if "live_vault" not in item.keywords]
