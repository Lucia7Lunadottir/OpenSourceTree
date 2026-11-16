import os


def repositories_from_arguments(arguments, start=None):
    """Folders given on the command line: `opensourcetree ~/Projects/game` opens that repository.

    The launcher scripts change into the program folder before starting Python, so a relative path is
    read against the folder the user started from (they pass it as OPENSOURCETREE_CWD).
    Pass QApplication.arguments()[1:]: Qt has already taken its own options (-platform, -style…) out.
    """
    start = start or os.environ.get("OPENSOURCETREE_CWD") or os.getcwd()
    return [os.path.abspath(os.path.join(start, os.path.expanduser(argument)))
            for argument in arguments if argument and not argument.startswith("-")]
