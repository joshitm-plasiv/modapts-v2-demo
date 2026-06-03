"""PMTS engines. Importing this package registers all available engines."""
from modapts.orchestrator import register_engine
from modapts.engines.uas.engine import UASEngine
from modapts.engines.mtm1.engine import MTM1Engine
from modapts.engines.most.engine import MOSTEngine
from modapts.engines.modapts_v3.engine import MODAPTSEngine


def register_default_engines() -> None:
    """Idempotent: register every built engine into the orchestrator registry."""
    register_engine(UASEngine())
    register_engine(MTM1Engine())
    register_engine(MOSTEngine())
    register_engine(MODAPTSEngine())


# Self-register on import so `import modapts.engines` makes engines selectable.
register_default_engines()
