"""测试用的最小 AstrBot 桩，只提供插件导入时用到的接口。"""

import json
import logging
import sys
import types
from pathlib import Path


class _Logger(logging.Logger):
    pass


def install(data_root: Path) -> None:
    if "astrbot" in sys.modules and getattr(sys.modules["astrbot"], "_fishing_stub", False):
        sys.modules["astrbot.api.star"].StarTools._root = Path(data_root)
        return

    logger = logging.getLogger("astrbot-stub")
    logger.addHandler(logging.NullHandler())
    logger.propagate = False

    astrbot = types.ModuleType("astrbot")
    astrbot._fishing_stub = True
    api = types.ModuleType("astrbot.api")
    api.logger = logger

    class AstrBotConfig(dict):
        saved = 0

        def save_config(self):
            AstrBotConfig.saved += 1

    api.AstrBotConfig = AstrBotConfig

    event = types.ModuleType("astrbot.api.event")

    class AstrMessageEvent:  # pragma: no cover - 只作类型占位
        pass

    class _Filter:
        registered = []

        def command(self, name, alias=None, **kwargs):
            def deco(fn):
                fn._fishing_command = (name, set(alias or ()))
                _Filter.registered.append(("command", name, fn))
                return fn
            return deco

        def regex(self, pattern, **kwargs):
            def deco(fn):
                fn._fishing_regex = pattern
                _Filter.registered.append(("regex", pattern, fn))
                return fn
            return deco

        def permission_type(self, *args, **kwargs):
            def deco(fn):
                fn._fishing_permission = args
                return fn
            return deco

        def __getattr__(self, name):
            def factory(*args, **kwargs):
                return lambda fn: fn
            return factory

    class MessageChain:
        def message(self, text):
            return self

        def file_image(self, path):
            return self

    event.AstrMessageEvent = AstrMessageEvent
    event.filter = _Filter()
    event.MessageChain = MessageChain

    star = types.ModuleType("astrbot.api.star")

    class Context:
        def __init__(self):
            self.registered_web_apis = []

        def register_web_api(self, route, handler, methods, desc):
            self.registered_web_apis.append((route, handler, methods, desc))

    class Star:
        def __init__(self, context):
            self.context = context

    class StarTools:
        _root = Path(data_root)

        @classmethod
        def get_data_dir(cls, plugin_name=None):
            path = cls._root / "plugin_data" / (plugin_name or "unknown")
            path.mkdir(parents=True, exist_ok=True)
            return path

    star.Context = Context
    star.Star = Star
    star.StarTools = StarTools

    components = types.ModuleType("astrbot.api.message_components")

    class _Comp:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        @classmethod
        def fromFileSystem(cls, path):
            return cls(path)

    components.Image = _Comp
    components.At = _Comp
    components.Plain = _Comp

    web = types.ModuleType("astrbot.api.web")
    web.request = None
    web.json_response = lambda data=None, **kw: data
    web.error_response = lambda message, **kw: {"status": "error", "message": message}

    core = types.ModuleType("astrbot.core")
    core_message = types.ModuleType("astrbot.core.message")
    core_components = types.ModuleType("astrbot.core.message.components")
    core_components.At = _Comp

    api.event = event
    api.star = star
    api.web = web
    api.message_components = components
    astrbot.api = api
    astrbot.core = core
    sys.modules.update({
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event,
        "astrbot.api.star": star,
        "astrbot.api.web": web,
        "astrbot.api.message_components": components,
        "astrbot.core": core,
        "astrbot.core.message": core_message,
        "astrbot.core.message.components": core_components,
    })


def load_plugin(data_root: Path, config: dict | None = None):
    """以包的形式导入插件并实例化，返回 (plugin, context)。"""
    install(data_root)
    plugin_dir = Path(__file__).resolve().parents[1]
    parent = str(plugin_dir.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    import importlib

    module = importlib.import_module(f"{plugin_dir.name}.main")
    from astrbot.api import AstrBotConfig
    from astrbot.api.star import Context

    context = Context()
    cfg = AstrBotConfig(json.loads(json.dumps(config or {})))
    plugin = module.FishingPlugin(context, cfg)
    return plugin, context
