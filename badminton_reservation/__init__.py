"""Pure Python badminton reservation, order lookup and campus-card payment."""
__version__ = '0.8.0'


def book(config=None, *, submit=False, credentials=None, credentials_file=None, session_file=None,
         pay_after=False, expected_amount=None):
    """Run the shared authenticated reservation workflow; default only validates."""
    from .workflow import book as run
    return run(config, submit=submit, credentials=credentials,
               credentials_file=credentials_file, session_file=session_file,
               pay_after=pay_after, expected_amount=expected_amount)
