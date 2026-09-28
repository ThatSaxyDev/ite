"""CSV to JSON conversion command with validation."""

import csv
import json
import sys
from pathlib import Path
from typing import Any

from ite.commands import Command, CommandContext, CommandRegistry
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


async def cmd_csv2json(ctx: CommandContext, args: list[str]) -> None:
    """Parse CSV, validate, and export to JSON with validation errors."""
    console = Console()
    
    if not args:
        console.print("[bold red]Usage:[/bold red] /csv2json <input.csv> [output.json] [--validate]")
        console.print("[dim]Example: /csv2json data.csv output.json --validate[/dim]")
        return

    input_file = args[0]
    output_file = None
    validate = False
    
    # Parse arguments
    for arg in args[1:]:
        if arg == "--validate":
            validate = True
        elif not arg.startswith("--") and output_file is None:
            output_file = arg

    input_path = Path(input_file)
    
    if not input_path.exists():
        console.print(f"[bold red]Error:[/bold red] File '{input_file}' not found")
        return

    try:
        # Read and parse CSV
        rows = []
        headers = []
        errors = []
        
        with open(input_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                row_data = {}
                row_errors = []
                
                for key, value in row.items():
                    if value is None:
                        value = ""
                    
                    # Basic validation: check for empty required fields
                    if validate and not value.strip():
                        row_errors.append(f"Empty value for '{key}'")
                    
                    row_data[key] = value
                
                if row_errors:
                    errors.append({
                        "row": row_num,
                        "data": row_data,
                        "errors": row_errors
                    })
                
                rows.append(row_data)

        # Build result
        result = {
            "metadata": {
                "input_file": str(input_path),
                "total_rows": len(rows),
                "total_errors": len(errors),
                "headers": headers
            },
            "data": rows
        }
        
        if validate:
            result["validation_errors"] = errors

        # Output to file or stdout
        if output_file:
            output_path = Path(output_file)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            console.print(f"[green]✓[/green] Exported to [bold]{output_file}[/bold]")
        else:
            console.print(json.dumps(result, indent=2))

        # Show summary table
        table = Table(title="CSV Parsing Summary", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="dim")
        table.add_column("Value", justify="right")
        
        table.add_row("Total Rows", str(len(rows)))
        table.add_row("Headers", ", ".join(headers) if headers else "None")
        table.add_row("Validation Errors", str(len(errors)))
        
        if validate and errors:
            error_table = Table(title="Validation Errors", show_header=True, header_style="bold red")
            error_table.add_column("Row", justify="right")
            error_table.add_column("Errors")
            
            for err in errors[:10]:  # Show first 10 errors
                error_table.add_row(
                    str(err["row"]),
                    "; ".join(err["errors"])
                )
            
            console.print(table)
            console.print(error_table)
            
            if len(errors) > 10:
                console.print(f"[dim]... and {len(errors) - 10} more errors[/dim]")
        else:
            console.print(table)

    except csv.Error as e:
        console.print(f"[bold red]CSV Error:[/bold red] {e}")
    except json.JSONDecodeError as e:
        console.print(f"[bold red]JSON Error:[/bold red] {e}")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")


def register(registry: CommandRegistry) -> None:
    registry.register(Command(
        name="/csv2json",
        description="Parse CSV and export to JSON with optional validation",
        handler=cmd_csv2json,
    ))