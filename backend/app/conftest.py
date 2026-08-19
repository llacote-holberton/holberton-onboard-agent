"""
Empty on purpose. Its only role is to mark backend/ as a rootdir pytest can
import from, so test modules can do `from app.config import ...` regardless
of the directory pytest is invoked from (bare `pytest`, `python -m pytest`,
or from an IDE test runner).
"""
