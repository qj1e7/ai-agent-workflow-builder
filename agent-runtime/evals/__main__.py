import argparse
import sys
from pathlib import Path

from evals.runner import main

parser = argparse.ArgumentParser(description="Score every configured model on the golden set.")
parser.add_argument("--out", type=Path, default=Path(__file__).parent / "out" / "results.json")
sys.exit(main(parser.parse_args().out))
