import sys
from pathlib import Path

from platform_api.contracts import write_all

root = Path(sys.argv[1] if len(sys.argv) > 1 else "../contracts")
for path in write_all(root):
    print(path)
