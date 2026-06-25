"""publishers — post an Asset to one (platform, account).

To add a platform: create publishers/<platform>.py with a class implementing
core.models.Publisher (platform, accepts, publish(asset, copy, account, publish_at))
and register() an instance at import time, then add the module to
publishers.base._MODULES. The orchestrator resolves publishers by account.platform.
"""
