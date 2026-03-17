from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from datetime import datetime
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "title": "bold gold3",
    "subtitle": "italic cyan",
    "highlight": "bold white",
    "timestamp": "dim white"
})
console = Console(theme=custom_theme)
def get_timestamp():
    return datetime.now().strftime("%H:%M:%S")
def print_step(step_name):
    console.print(f"[{get_timestamp()}] [bold blue]➔[/] [bold white]{step_name}[/]")
def print_success(message):
    console.print(f"[{get_timestamp()}] [success]✔ {message}[/]")
def print_error(message):
    console.print(f"[{get_timestamp()}] [error]✖ {message}[/]")
def print_warning(message):
    console.print(f"[{get_timestamp()}] [warning]⚠ {message}[/]")
def print_info(message):
    console.print(f"[{get_timestamp()}] [info]ℹ {message}[/]")
def create_panel(content, title=None, style="blue", subtitle=None):
    return Panel(
        content,
        title=f"[title]{title}[/]" if title else None,
        subtitle=subtitle,
        border_style=style,
        box=box.ROUNDED,
        padding=(1, 2)
    )
def create_table(headers, title=None):
    table = Table(title=title, box=box.ROUNDED, header_style="bold cyan", border_style="blue")
    for header in headers:
        table.add_column(header)
    return table
