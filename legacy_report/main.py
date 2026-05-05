import typer

from legacy_report import __version__
from legacy_report.db import init_db

app = typer.Typer(add_completion=False, help="Legacy Report — Comic Book Collection Manager")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"Legacy Report {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Launch the Legacy Report interactive menu."""
    init_db()
    from legacy_report.tui import LegacyReportApp
    LegacyReportApp().run()



