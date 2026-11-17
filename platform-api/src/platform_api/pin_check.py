"""The pin check (ADR 0045, as ADR 0051 changed it): each row of `node_classes.json` still matches
the pinned n8n image. Every version and choice of a type the file turns on is classed, and the file
names nothing the image does not have. A type the file doesn't name needs no row, since n8n loads
every built-in block and the checker flags each one the file doesn't class. Moving the pin
therefore means checking the file's rows again in the same change.

    python -m platform_api.pin_check <the image's /types/nodes.json, as n8n serves it>

scripts/pack-smoke.sh saves that file from the image as the platform runs it, and runs this.
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
    named = len(NODE_CLASSES.names())
    print(f"pin check: each of the {named} types the class file names still matches the image.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
