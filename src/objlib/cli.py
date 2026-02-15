"""CLI entry point for the Objectivism Library scanner."""

import typer

app = typer.Typer(help="Objectivism Library Scanner")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Objectivism Library scanner and metadata extractor."""
    if ctx.invoked_subcommand is None:
        typer.echo("Use --help to see available commands.")
