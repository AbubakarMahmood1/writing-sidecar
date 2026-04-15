from __future__ import annotations

import os
from pathlib import Path

import pytest

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
