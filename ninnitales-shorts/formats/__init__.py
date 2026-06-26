"""formats — content builders. Each module produces an Asset and registers itself.

To add a format: create formats/<name>.py with a class implementing core.models.Format
(name, produces, build(niche, rng)) and call register() on an instance at import time,
then add the module to formats.base._MODULES. The orchestrator never changes.
"""
