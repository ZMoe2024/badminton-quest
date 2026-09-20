"""Translate legacy command lines to the single authenticated CLI."""
import sys
from .cli import main


def booking_main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    submit = '--submit' in arguments
    arguments = [arg for arg in arguments if arg != '--submit']
    return main(['submit' if submit else 'check', *arguments])


def catalog_main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith('-'):
        arguments.insert(0, 'list')
    return main(arguments)
