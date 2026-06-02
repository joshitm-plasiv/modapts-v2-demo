"""PMTS engines. Importing this package registers all available engines."""
from modapts.orchestrator import register_engine
from modapts.engines.uas.engine import UASEngine


def register_default_engines() -> None:
    """Idempotent: register every built engine into the orchestrator registry."""
    register_engine(UASEngine())


# Self-register on import so `import modapts.engines` makes engines selectable.
register_default_engines()
