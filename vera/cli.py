"""
VERA CLI — small helper around the Unreal Engine editor integration.

The VERA agent runs *inside* the editor (open the VERA panel from the toolbar,
or talk to it over the MCP bridge). This CLI only offers local helpers that make
sense outside the editor, like checking whether the UE Python bridge is up.

Usage:
    vera --status
"""

import click
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """
    \b
    ██╗   ██╗███████╗██████╗  █████╗
    ██║   ██║██╔════╝██╔══██╗██╔══██╗
    ██║   ██║█████╗  ██████╔╝███████║
    ╚██╗ ██╔╝██╔══╝  ██╔══██╗██╔══██║
     ╚████╔╝ ███████╗██║  ██║██║  ██║
      ╚═══╝  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝

    Visual Editor Reasoning Agent for Unreal Engine 5

    The agent lives inside the editor — open the VERA panel from the toolbar to
    chat with it. Use `vera --status` to check the editor connection.
    """
    if ctx.invoked_subcommand:
        return
    click.echo(ctx.get_help())


@cli.command()
def status():
    """Check if VERA can connect to the Unreal Engine editor."""
    from vera.actions.ue_python import UEPythonBridge

    bridge = UEPythonBridge()
    if bridge.is_available():
        console.print("[green]✅ UE Python Bridge: Connected[/]")
    else:
        console.print("[yellow]⚠️  UE Python Bridge: Not running[/]")
        console.print("   → Open the VERA panel in the Unreal editor to start it.")


if __name__ == "__main__":
    cli()
