"""
VERA CLI — Command-line interface for talking to your Unreal Engine editor.

Usage:
    vera "Set default map to Lobby"
    vera "Configure Android build and launch on device"
    vera --recipe android-setup --map /Game/Lobby/Lobby
    vera --status
"""

import os
import sys
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

console = Console()


def load_config() -> dict:
    config_path = Path("vera.config.yaml")
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


@click.group(invoke_without_command=True)
@click.argument("command", required=False)
@click.option("--recipe", "-r", help="Run a built-in recipe by name")
@click.option("--map", "-m", "map_path", help="Map path for recipe (e.g. /Game/Lobby/Lobby)")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed execution log")
@click.pass_context
def cli(ctx, command, recipe, map_path, verbose):
    """
    \b
    ██╗   ██╗███████╗██████╗  █████╗
    ██║   ██║██╔════╝██╔══██╗██╔══██╗
    ██║   ██║█████╗  ██████╔╝███████║
    ╚██╗ ██╔╝██╔══╝  ██╔══██╗██╔══██║
     ╚████╔╝ ███████╗██║  ██║██║  ██║
      ╚═══╝  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝

    Visual Editor Reasoning Agent for Unreal Engine 5
    """
    if ctx.invoked_subcommand:
        return

    if not command and not recipe:
        click.echo(ctx.get_help())
        return

    from vera.core.agent import VERAAgent

    config = load_config()
    agent = VERAAgent(config=config)

    if recipe:
        _run_recipe(agent, recipe, map_path)
        return

    if command:
        console.print(Panel(f"[bold cyan]Command:[/] {command}", title="🤖 VERA"))
        with console.status("[bold green]Executing..."):
            result = agent.run(command)

        _print_result(result, verbose)


def _run_recipe(agent, recipe_name: str, map_path: str | None):
    """Run a built-in recipe."""
    from vera.recipes.android_setup import setup_android_lobby_build

    recipes = {
        "android-setup": lambda: setup_android_lobby_build(
            agent, map_path or "/Game/Lobby/Lobby"
        ),
    }

    runner = recipes.get(recipe_name)
    if not runner:
        console.print(f"[red]Unknown recipe: '{recipe_name}'[/]")
        console.print(f"Available: {', '.join(recipes.keys())}")
        sys.exit(1)

    console.print(Panel(f"[bold cyan]Recipe:[/] {recipe_name}", title="🤖 VERA"))
    with console.status("[bold green]Running recipe..."):
        result = runner()

    _print_result(result, verbose=False)


def _print_result(result: dict, verbose: bool):
    """Pretty-print the execution result."""
    success = result.get("success", False)
    from_cache = result.get("from_cache", False)
    tokens = result.get("tokens_used", 0)

    status = "[bold green]✅ SUCCESS[/]" if success else "[bold red]❌ FAILED[/]"
    cache_tag = " [dim](from cache)[/]" if from_cache else ""
    token_tag = f"[dim] | {tokens} tokens used[/]" if tokens else "[dim] | 0 tokens used[/]"

    console.print(f"\n{status}{cache_tag}{token_tag}\n")

    if not success and result.get("error"):
        console.print(f"[red]Error:[/] {result['error']}")

    if verbose and result.get("steps"):
        table = Table(title="Execution Steps", show_lines=True)
        table.add_column("Step", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Params", style="white")

        for i, step in enumerate(result["steps"], 1):
            params_str = str(step.get("params", {}))[:80]
            table.add_row(str(i), step.get("type", "?"), params_str)

        console.print(table)


@cli.command()
def status():
    """Check if VERA can connect to the Unreal Engine editor."""
    from vera.actions.ue_python import UEPythonBridge

    bridge = UEPythonBridge()
    if bridge.is_available():
        console.print("[green]✅ UE Python Bridge: Connected[/]")
    else:
        console.print("[yellow]⚠️  UE Python Bridge: Not running[/]")
        console.print("   → Run [bold]vera/tools/ue_bridge_server.py[/] in UE's Python console")


if __name__ == "__main__":
    cli()
