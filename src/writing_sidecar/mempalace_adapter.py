from __future__ import annotations

import importlib
import re
from importlib import metadata

SUPPORTED_MEMPALACE_SPEC = ">=3.1,<3.2"


class MempalaceCompatibilityError(RuntimeError):
    pass


def get_installed_mempalace_version() -> str | None:
    try:
        return metadata.version("mempalace")
    except metadata.PackageNotFoundError:
        return None


def is_supported_mempalace_version(version: str | None) -> bool:
    if not version:
        return False
    match = re.match(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?", version)
    if not match:
        return False
    major = int(match.group(1))
    minor = int(match.group(2))
    return major == 3 and minor == 1


def ensure_supported_mempalace_version() -> str:
    version = get_installed_mempalace_version()
    if not version:
        raise MempalaceCompatibilityError(
            "MemPalace is not installed. Install a supported version first."
        )
    if not is_supported_mempalace_version(version):
        raise MempalaceCompatibilityError(
            f"Unsupported MemPalace version: {version}. Expected {SUPPORTED_MEMPALACE_SPEC}."
        )
    return version


def normalize(path: str) -> str:
    ensure_supported_mempalace_version()
    module = importlib.import_module("mempalace.normalize")
    return module.normalize(path)


def search_memories(query: str, palace_path: str, wing=None, room=None, n_results: int = 5) -> dict:
    ensure_supported_mempalace_version()
    module = importlib.import_module("mempalace.searcher")
    return module.search_memories(
        query=query,
        palace_path=palace_path,
        wing=wing,
        room=room,
        n_results=n_results,
    )


def search(query: str, palace_path: str, wing=None, room=None, n_results: int = 5):
    ensure_supported_mempalace_version()
    module = importlib.import_module("mempalace.searcher")
    return module.search(
        query=query,
        palace_path=palace_path,
        wing=wing,
        room=room,
        n_results=n_results,
    )


def mine(
    project_dir: str,
    palace_path: str,
    wing_override=None,
    agent: str = "writing_sidecar",
    limit: int = 0,
    dry_run: bool = False,
    respect_gitignore: bool = True,
    include_ignored=None,
):
    ensure_supported_mempalace_version()
    module = importlib.import_module("mempalace.miner")
    return module.mine(
        project_dir=project_dir,
        palace_path=palace_path,
        wing_override=wing_override,
        agent=agent,
        limit=limit,
        dry_run=dry_run,
        respect_gitignore=respect_gitignore,
        include_ignored=include_ignored or [],
    )
