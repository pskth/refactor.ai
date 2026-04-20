import typer
from refactor.tree import print_tree
from importlib.metadata import version as get_version

app = typer.Typer(no_args_is_help=True)

@app.command()
def version():
    """Print Version Information"""
    print(get_version("refactor-cli"))

@app.command()
def tree(path: str = "."):
    """Print folder structure"""
    print_tree(path)

if __name__ == "__main__":
    app()