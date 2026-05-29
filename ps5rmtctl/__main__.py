"""Enable `python -m ps5rmtctl`."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
