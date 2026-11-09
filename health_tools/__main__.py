"""Local demonstration: no API key, network, model, or storage required."""

import argparse
import json

from .cycle_history import analyze_cycle_history


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", help="Period starts, oldest first, YYYY-MM-DD")
    parser.add_argument("--as-of", help="User's local reference date, YYYY-MM-DD")
    args = parser.parse_args()
    result = analyze_cycle_history(args.dates, as_of=args.as_of)
    print(json.dumps(result.to_dict(), indent=2))
    if result.status == "error":
        parser.exit(2)


if __name__ == "__main__":
    main()
