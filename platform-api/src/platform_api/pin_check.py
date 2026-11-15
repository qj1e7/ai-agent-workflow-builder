"""The pin check (ADR 0045): every node type, version and choice the pinned n8n image serves is
classed in `node_classes.json`, and the file classes nothing the image does not have. Moving the
pin therefore means classing again in the same change.

    python -m platform_api.pin_check <the image's /types/nodes.json, as n8n serves it>

scripts/pack-smoke.sh saves that file from the image with the allow list on, and runs this.
"""

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from platform_api.orchestration.node_classes import NODE_CLASSES


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m platform_api.pin_check <nodes.json>", file=sys.stderr)
        return 2
    problems = NODE_CLASSES.unclassed(json.loads(Path(args[0]).read_text()))
    for problem in problems:
        print(f"pin check: {problem}", file=sys.stderr)
    if problems:
        return 1
    loaded = len(NODE_CLASSES.loaded())
    print(f"pin check: every type, version and choice of the {loaded} n8n serves is classed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
