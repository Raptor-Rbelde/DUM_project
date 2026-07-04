from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sentinel.privacy.sequence_tagger import DEFAULT_SEQUENCE_MODEL_PATH, train_default_sequence_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Sentinel's final local sequence-tagging privacy detector.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SEQUENCE_MODEL_PATH,
        help="Path where the local model artifact will be written.",
    )
    args = parser.parse_args()

    result = train_default_sequence_model(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
