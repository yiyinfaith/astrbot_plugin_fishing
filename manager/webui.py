"""AstrBot-native dashboard API for the fishing plugin.

The old release started a separate Quart server from an administrator command.  The
management page now lives in ``pages/dashboard`` and is opened by AstrBot at
``/plugin-view/astrbot_plugin_fishing/dashboard``.  This module only registers the
same-origin API under the matching ``dashboard`` prefix.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from collections.abc import Callable
from typing import Any

try:
    from quart import Response, request
except ImportError:  # pragma: no cover - only for lightweight unit tests
    Response = None  # type: ignore[assignment]
    request = None  # type: ignore[assignment]

from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_fishing"


class FishingWebUI:
    """Register the fishing dashboard API under AstrBot's plugin route."""

    def __init__(self, context: Any, plugin: Any):
        self.context = context
        self.plugin = plugin
        self._register_routes()

    def _register_routes(self) -> None:
        routes: tuple[tuple[str, Callable[..., Any], list[str], str], ...] = (
            ("overview", self.overview, ["GET"], "Fishing overview"),
            ("users", self.users, ["GET"], "Fishing users"),
            ("titles", self.titles, ["GET"], "Fishing titles"),
            ("templates", self.templates, ["GET"], "Fishing item templates"),
            ("zones", self.zones, ["GET"], "Fishing zones"),
            ("shops", self.shops, ["GET"], "Fishing shops"),
            ("gacha", self.gacha, ["GET"], "Fishing gacha pools"),
            ("market", self.market, ["GET"], "Fishing market"),
            ("action", self.action, ["POST"], "Fishing administration action"),
        )
        for endpoint, handler, methods, description in routes:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/dashboard/{endpoint}", handler, methods, description
            )

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if dataclasses.is_dataclass(value):
            return FishingWebUI._json_safe(dataclasses.asdict(value))
        if isinstance(value, dict):
            return {str(key): FishingWebUI._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [FishingWebUI._json_safe(item) for item in value]
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if hasattr(value, "__dict__") and not isinstance(value, (str, bytes)):
            return FishingWebUI._json_safe(
                {key: item for key, item in vars(value).items() if not key.startswith("_")}
            )
        return value

    @staticmethod
    def _response(payload: Any, status: int = 200) -> Any:
        """Return a Quart response when available, otherwise a plain test value."""
        safe = FishingWebUI._json_safe(payload)
        if Response is None:
            return safe
        return safe, status

    async def overview(self):
        p = self.plugin
        users = p.user_repo.get_all_user_ids()
        result = {
            "success": True,
            "plugin": {"name": PLUGIN_NAME, "display_name": "全能钓鱼"},
            "counts": {
                "users": len(users),
                "fish": len(p.item_template_repo.get_all_fish()),
                "rods": len(p.item_template_repo.get_all_rods()),
                "baits": len(p.item_template_repo.get_all_baits()),
                "accessories": len(p.item_template_repo.get_all_accessories()),
                "items": len(p.item_template_repo.get_all_items()),
                "titles": len(p.item_template_repo.get_all_titles()),
                "zones": len(p.inventory_repo.get_all_zones()),
                "shops": len(p.shop_repo.get_all_shops()),
                "gacha": len(p.gacha_repo.get_all_pools()),
            },
            "disabled_features": ["擦弹", "命运之轮", "骰宝游戏", "鸭下注"],
        }
        return self._response(result)

    async def users(self):
        query = request.args if request is not None else {}
        search = str(query.get("search", "") or "").strip().casefold()
        try:
            limit = min(200, max(1, int(query.get("limit", 100) or 100)))
            offset = max(0, int(query.get("offset", 0) or 0))
        except (TypeError, ValueError):
            return self._response({"success": False, "message": "分页参数无效。"}, 400)
        rows = []
        for user in self.plugin.user_repo.get_all_users(limit=10000, offset=0):
            row = self._json_safe(user)
            if search and search not in " ".join(
                str(row.get(key, "")) for key in ("user_id", "nickname", "platform")
            ).casefold():
                continue
            rows.append(row)
        total = len(rows)
        return self._response({"success": True, "rows": rows[offset : offset + limit], "total": total})

    async def titles(self):
        return self._response({"success": True, "rows": self.plugin.user_service.get_all_titles_for_admin().get("titles", [])})

    async def templates(self):
        repo = self.plugin.item_template_repo
        return self._response({
            "success": True,
            "fish": repo.get_all_fish(),
            "rods": repo.get_all_rods(),
            "baits": repo.get_all_baits(),
            "accessories": repo.get_all_accessories(),
            "items": repo.get_all_items(),
        })

    async def zones(self):
        return self._response({"success": True, "rows": self.plugin.fishing_zone_service.get_all_zones()})

    async def shops(self):
        return self._response({"success": True, "rows": self.plugin.shop_repo.get_all_shops()})

    async def gacha(self):
        return self._response({"success": True, "rows": self.plugin.gacha_repo.get_all_pools()})

    async def market(self):
        return self._response({
            "success": True,
            "rows": self.plugin.market_service.get_all_market_listings_for_admin(page=1, per_page=100),
        })

    async def _payload(self) -> dict[str, Any]:
        if request is None:
            return {}
        try:
            payload = await request.get_json(silent=True)
        except TypeError:
            payload = await request.get_json()
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _positive_int(payload: dict[str, Any], key: str) -> int:
        value = int(payload.get(key, 0))
        if value <= 0:
            raise ValueError(f"{key} 必须是正整数")
        return value

    def _replenish_zones(self) -> dict[str, Any]:
        reset = []
        for zone in self.plugin.inventory_repo.get_all_zones():
            if int(getattr(zone, "daily_rare_fish_quota", 0) or 0) > 0:
                zone.rare_fish_caught_today = 0
                self.plugin.inventory_repo.update_fishing_zone(zone)
                reset.append({"id": zone.id, "name": zone.name, "quota": zone.daily_rare_fish_quota})
        return {"success": True, "message": f"已补充 {len(reset)} 个鱼塘。", "rows": reset}

    def _bulk_item_reward(self, payload: dict[str, Any]) -> dict[str, Any]:
        item_type = str(payload.get("item_type", "")).strip()
        item_id = self._positive_int(payload, "item_id")
        quantity = self._positive_int(payload, "quantity")
        quality_level = max(0, int(payload.get("quality_level", 0) or 0))
        if item_type not in {"fish", "rod", "accessory", "bait", "item"}:
            raise ValueError("不支持的道具类型")
        user_ids = self.plugin.user_repo.get_all_user_ids()
        ok = 0
        failed = 0
        for user_id in user_ids:
            result = self.plugin.user_service.add_item_to_user_inventory(
                user_id, item_type, item_id, quantity, quality_level
            )
            if result.get("success"):
                ok += 1
            else:
                failed += 1
        return {"success": True, "message": f"已向 {ok} 位用户发放道具，失败 {failed} 位。", "updated": ok, "failed": failed}

    async def action(self):
        payload = await self._payload()
        action = str(payload.get("action", "")).strip()
        try:
            p = self.plugin
            if action == "set_user":
                user_id = str(payload.get("user_id", "")).strip()
                updates = payload.get("updates")
                if not user_id or not isinstance(updates, dict):
                    raise ValueError("需要 user_id 和 updates")
                return self._response(p.user_service.update_user_for_admin(user_id, updates))
            if action == "adjust_currency":
                user_id = str(payload.get("user_id", "")).strip()
                currency = str(payload.get("currency", "coins")).strip()
                amount = int(payload.get("amount", 0))
                mode = str(payload.get("mode", "set")).strip()
                user = p.user_repo.get_by_id(user_id)
                if not user or currency not in {"coins", "premium_currency"}:
                    raise ValueError("用户或货币类型无效")
                current = int(getattr(user, currency, 0) or 0)
                next_value = amount if mode == "set" else current + amount
                if next_value < 0:
                    raise ValueError("货币数量不能为负数")
                setattr(user, currency, next_value)
                p.user_repo.update(user)
                return self._response({"success": True, "message": f"{currency} 已更新为 {next_value}。", "value": next_value})
            if action in {"grant_title", "revoke_title"}:
                user_id = str(payload.get("user_id", "")).strip()
                title = str(payload.get("title", "")).strip()
                if not user_id or not title:
                    raise ValueError("需要用户 ID 和称号名称")
                result = (p.user_service.grant_title_to_user_by_name if action == "grant_title" else p.user_service.revoke_title_from_user_by_name)(user_id, title)
                return self._response(result)
            if action == "create_title":
                name = str(payload.get("name", "")).strip()
                description = str(payload.get("description", "")).strip()
                display_format = str(payload.get("display_format", "{name}")).strip() or "{name}"
                if not name:
                    raise ValueError("称号名称不能为空")
                return self._response(p.user_service.create_custom_title(name, description or f"自定义称号：{name}", display_format))
            if action == "sync_initial_data":
                p.data_setup_service.sync_all_initial_data()
                return self._response({"success": True, "message": "初始设定已同步。"})
            if action == "replenish_zones":
                return self._response(self._replenish_zones())
            if action == "reward_all_items":
                return self._response(self._bulk_item_reward(payload))
            if action == "cleanup_red_packets":
                count = p.red_packet_service.cleanup_expired_packets()
                return self._response({"success": True, "message": f"已清理 {count} 个过期红包。", "count": count})
            if action == "template":
                kind = str(payload.get("kind", "")).strip()
                operation = str(payload.get("operation", "")).strip()
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                method_map = {
                    "fish": ("fish", int), "rod": ("rod", int), "bait": ("bait", int),
                    "accessory": ("accessory", int), "item": ("item", int), "title": ("title", int),
                }
                if kind not in method_map or operation not in {"create", "update", "delete"}:
                    raise ValueError("模板类型或操作无效")
                noun, cast = method_map[kind]
                service = p.item_template_service
                if operation == "create":
                    if noun == "title":
                        p.item_template_repo.add_title_template(data)
                    else:
                        getattr(service, f"add_{noun}_template")(data)
                else:
                    ident = cast(payload.get("id"))
                    if operation == "update":
                        getattr(service, f"update_{noun}_template")(ident, data)
                    else:
                        getattr(service, f"delete_{noun}_template")(ident)
                return self._response({"success": True, "message": "模板操作已完成。"})
            if action == "zone":
                operation = str(payload.get("operation", "")).strip()
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                if operation == "create":
                    return self._response({"success": True, **p.fishing_zone_service.create_zone(data)})
                ident = int(payload.get("id"))
                if operation == "update":
                    p.fishing_zone_service.update_zone(ident, data)
                elif operation == "delete":
                    p.fishing_zone_service.delete_zone(ident)
                else:
                    raise ValueError("鱼塘操作无效")
                return self._response({"success": True, "message": "鱼塘操作已完成。"})
            return self._response({"success": False, "message": "未知的管理操作。"}, 400)
        except (TypeError, ValueError, KeyError) as exc:
            return self._response({"success": False, "message": str(exc)}, 400)
        except Exception as exc:  # pragma: no cover - defensive boundary for admin UI
            logger.exception("钓鱼管理操作失败: %s", exc)
            return self._response({"success": False, "message": "操作失败，请查看 AstrBot 日志。"}, 500)


def create_webui(context: Any, plugin: Any) -> FishingWebUI:
    return FishingWebUI(context, plugin)
