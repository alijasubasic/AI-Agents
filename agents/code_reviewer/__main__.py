"""Entry point so `python -m agents.code_reviewer` runs the CLI."""

from agents.code_reviewer.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
