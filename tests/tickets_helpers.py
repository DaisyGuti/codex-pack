"""Shared by the ticket-script tests: load a pack script by name, and a filled-in registry.

The scripts are not a package, so each is loaded from its path. Import this as
`from tickets_helpers import load_script`; pytest's default import mode puts this folder on
sys.path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PACK = Path(__file__).resolve().parents[1]
SCRIPTS = PACK / "scripts"

# A registry as a team would fill in `registry.example.md`: every section the parser reads, a
# real clone folder and no example values. Built here, not copied from the example, so these
# tests do not depend on the wording of a file people edit. `{clone}` is the clone folder.
REGISTRY_TEXT = """\
# Ticket registry

## Tracker

- Tracker: `github`
- Host: `github.com`

## Board

### GitHub

- Owner: `acme`
- Number: `1`
- Name: Engineering

### GitLab

- Scope: `group`
- Path: `acme-team`
- Board: `Development`
- Lanes: `labels`

## Lanes

| Role | GitHub (Status option) | GitLab (label, or Status name) | Meaning |
| --- | --- | --- | --- |
| backlog | `Backlog` | `status::backlog` | Filed, not yet queued |
| ready | `Ready` | `status::ready` | Groomed and queued |
| in_progress | `In progress` | `status::in-progress` | A worker has started |
| blocked | `Blocked` | `status::blocked` | Held |
| review | `In review` | `status::in-review` | Optional |
| done | `Done` | `status::done` | Shipped and closed |

## Priority

| Role | GitHub (Priority option) | GitLab (label) | Meaning |
| --- | --- | --- | --- |
| P0 | `P0` | `priority::0` | Active blocker |
| P1 | `P1` | `priority::1` | On the launch path |
| P2 | `P2` | `priority::2` | Important |
| P3 | `P3` | `priority::3` | Nice to have |

## Labels

| Role | Label | Color | Description |
| --- | --- | --- | --- |
| blocked | `blocked` | `b60205` | Held: a comment says what it is waiting for |
| run_worker | `run:worker` | `0e8a16` | A worker can finish this end to end |
| run_solo | `run:solo` | `fbca04` | A person does the whole ticket |

## Model labels

| Tier | Label | Color | Weight |
| --- | --- | --- | --- |
| fast | `model:fast` | `ededed` | 1 |
| workhorse | `model:workhorse` | `ededed` | 3 |
| frontier | `model:frontier` | `ededed` | 5 |

## Batches

- Batching: `off`
- Batch size: `5`

## Repos

| Name | Remote | Local clone | Product brief | Focus |
| --- | --- | --- | --- | --- |
| `shop-app` | `acme/shop-app` | `{clone}` | `{clone}/README.md` | active |
"""


def filled_registry_text(clone: Path) -> str:
    """The registry above with `clone` as the repo's local clone."""
    return REGISTRY_TEXT.replace("{clone}", str(clone))


def load_script(name: str) -> ModuleType:
    """Import scripts/<name>.py as `tickets_<name>`."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))  # watch_board imports registry and ticket_state by name
    spec = importlib.util.spec_from_file_location(f"tickets_{name}", SCRIPTS / f"{name}.py")
    assert spec and spec.loader, f"cannot load {name}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
