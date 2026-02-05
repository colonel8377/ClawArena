import os

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

pytest_plugins = ("pytest_asyncio.plugin",)
