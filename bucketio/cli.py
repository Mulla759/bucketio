"""BucketIO CLI (Pass 0: scaffold; commands are filled in by later passes)."""

from __future__ import annotations

import typer

from . import __version__

app = typer.Typer(
    name="bucketio",
    help="Local contact store in front of Treg: cheap verifies, learned email patterns.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root() -> None:
    """BucketIO — cheap contact lookups: cache first, verify second, find last."""


@app.command()
def version() -> None:
    """Print the BucketIO version."""
    typer.echo(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
