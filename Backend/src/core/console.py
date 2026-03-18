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
    "timestamp": "dim white",
    "verbose": "dim cyan"
})

console = Console(theme=custom_theme)

# Global verbose flag within console module (can be set from main)
_IS_VERBOSE = False

def set_verbose_mode(is_verbose: bool):
    global _IS_VERBOSE
    _IS_VERBOSE = is_verbose

def is_verbose():
    return _IS_VERBOSE

def get_timestamp():
    return datetime.now().strftime("%H:%M:%S")

def print_step(step_name):
    if _IS_VERBOSE:
        console.print(f"[{get_timestamp()}] [bold blue]->[/] [bold white]{step_name}[/]")

def print_verbose(message):
    if _IS_VERBOSE:
        console.print(f"[{get_timestamp()}] [verbose][VERBOSE] {message}[/]")

def print_success(message):
    console.print(f"[{get_timestamp()}] [success][OK] {message}[/]")

def print_error(message):
    console.print(f"[{get_timestamp()}] [error][ERROR] {message}[/]")

def print_warning(message):
    console.print(f"[{get_timestamp()}] [warning][WARN] {message}[/]")

def print_info(message):
    if _IS_VERBOSE:
        console.print(f"[{get_timestamp()}] [info][INFO] {message}[/]")

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
