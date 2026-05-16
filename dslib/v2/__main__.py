"""CLI entry: ``python -m dslib.v2 <datasheet.pdf>``."""
import sys

sys.path.insert(0,'.')

from dslib.v2 import parse_datasheet


def main():
    if len(sys.argv) < 2:
        print("usage: python -m dslib.v2 <datasheet.pdf>", file=sys.stderr)
        sys.exit(2)
    ds = parse_datasheet(sys.argv[1])
    ds.print(show_cond=True, show_sources=True)


if __name__ == "__main__":
    main()
