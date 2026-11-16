"""钓鱼插件的面板管理接口。

管理页放在 ``views/admin`` 下，由 AstrBot 以受限 iframe 加载，页面通过
``window.AstrBotPluginView`` bridge 调用这里注册的接口。登录与鉴权由 AstrBot
面板负责，插件不再开放独立端口、独立登录页或管理员消息指令。

每个接口都是一个普通方法 ``fn(query, body) -> dict``，由 :meth:`_wrap` 统一
完成参数读取、错误转换和 JSON 序列化，便于在测试中直接调用。
"""

from __future__ import annotations

import asyncio
import csv
import dataclasses
import inspect
import io
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from astrbot.api import logger

# 市场托管与系统账号不参与全体发放/扣除
SYSTEM_USER_IDS = {"MARKET", "SYSTEM"}

DEFAULT_TAX_CONFIG = {
    "is_tax": True,
    "threshold": 1_000_000,
    "asset_scope": "wallet",
    "deduct_scope": "wallet",
    "taxable_mode": "total",
    "debt_surcharge_rate": 0.02,
    "step_coins": 100_000,
    "step_rate": 0.01,
    "min_rate": 0.001,
    "max_rate": 0.2,
    "transfer_tax_rate": 0.05,
    "tax_record_retention_days": 90,
    "tax_record_cleanup_batch_size": 1000,
}

ASSET_SCOPE_LABELS = {
    "wallet": "只统计钱包",
    "wallet_bank": "钱包 + 银行活期",
    "wallet_bank_fixed": "钱包 + 银行活期 + 定期本金",
}
DEDUCT_SCOPE_LABELS = {
    "wallet": "只从钱包扣",
    "bank": "只从银行活期可用余额扣",
    "wallet_bank": "钱包优先，不足再扣银行活期",
}
TAXABLE_MODE_LABELS = {
    "total": "达到起征点后按全部统计资产征税",
    "excess": "只对超过起征点的部分征税",
}

ITEM_TYPE_LABELS = {
    "fish": "鱼类",
    "rod": "鱼竿",
    "bait": "鱼饵",
    "accessory": "饰品",
    "item": "道具",
    "coins": "金币",
    "premium": "高级货币",
    "titles": "称号",
    "commodity": "大宗商品",
}

# 物品模板的字段定义：后端用它校验和转换，前端用它渲染表格与表单。
# 字段格式：key, label, type, 额外参数
TEMPLATE_KINDS: Dict[str, Dict[str, Any]] = {
    "fish": {
        "label": "鱼类",
        "id_field": "fish_id",
        "csv_required": ["name", "rarity", "base_value", "min_weight", "max_weight"],
        "columns": ["name", "rarity", "base_value", "min_weight", "max_weight"],
        "fields": [
            {"key": "name", "label": "名称", "type": "text", "required": True},
            {"key": "rarity", "label": "稀有度", "type": "int", "default": 1, "min": 1, "max": 10},
            {"key": "base_value", "label": "基础价值", "type": "int", "default": 10, "min": 0},
            {"key": "min_weight", "label": "最小重量 (g)", "type": "int", "default": 100, "min": 0},
            {"key": "max_weight", "label": "最大重量 (g)", "type": "int", "default": 500, "min": 0},
            {"key": "icon_url", "label": "图标 URL", "type": "text", "optional": True},
            {"key": "description", "label": "描述", "type": "textarea", "optional": True},
        ],
    },
    "rods": {
        "label": "鱼竿",
        "id_field": "rod_id",
        "csv_required": [
            "name", "rarity", "source", "bonus_fish_quality_modifier",
            "bonus_fish_quantity_modifier", "bonus_rare_fish_chance",
        ],
        "columns": [
            "name", "rarity", "source", "purchase_cost", "bonus_fish_quality_modifier",
            "bonus_fish_quantity_modifier", "bonus_rare_fish_chance", "durability",
        ],
        "fields": [
            {"key": "name", "label": "名称", "type": "text", "required": True},
            {"key": "rarity", "label": "稀有度", "type": "int", "default": 1, "min": 1, "max": 10},
            {
                "key": "source", "label": "来源", "type": "select", "default": "shop",
                "options": [["shop", "商店"], ["gacha", "抽卡"], ["event", "活动"]],
            },
            {"key": "purchase_cost", "label": "购买成本", "type": "int", "optional": True, "min": 0, "hint": "留空表示不可直接购买"},
            {"key": "bonus_fish_quality_modifier", "label": "品质加成", "type": "float", "default": 1.0, "hint": "1.1 表示 +10%"},
            {"key": "bonus_fish_quantity_modifier", "label": "数量加成", "type": "float", "default": 1.0},
            {"key": "bonus_rare_fish_chance", "label": "稀有加成", "type": "float", "default": 0.0, "hint": "0.05 表示 +5%"},
            {"key": "durability", "label": "耐久度", "type": "int", "optional": True, "min": 0, "hint": "留空表示无限耐久"},
            {"key": "icon_url", "label": "图标 URL", "type": "text", "optional": True},
            {"key": "description", "label": "描述", "type": "textarea", "optional": True},
        ],
    },
    "baits": {
        "label": "鱼饵",
        "id_field": "bait_id",
        "csv_required": ["name"],
        "columns": ["name", "rarity", "cost", "duration_minutes", "effect_description", "is_consumable"],
        "fields": [
            {"key": "name", "label": "名称", "type": "text", "required": True},
            {"key": "rarity", "label": "稀有度", "type": "int", "default": 1, "min": 1, "max": 10},
            {"key": "cost", "label": "购买成本", "type": "int", "default": 0, "min": 0},
            {"key": "required_rod_rarity", "label": "要求鱼竿稀有度", "type": "int", "default": 0, "min": 0},
            {"key": "duration_minutes", "label": "持续分钟", "type": "int", "default": 0, "min": 0, "hint": "0 表示一次性"},
            {"key": "success_rate_modifier", "label": "成功率加成", "type": "float", "default": 0.0, "hint": "0.1 表示 +10%"},
            {"key": "rare_chance_modifier", "label": "稀有率加成", "type": "float", "default": 0.0, "hint": "0.05 表示 +5%"},
            {"key": "garbage_reduction_modifier", "label": "垃圾减少率", "type": "float", "default": 0.0, "hint": "0.5 表示减少 50%"},
            {"key": "value_modifier", "label": "价值乘数", "type": "float", "default": 1.0, "hint": "1.1 表示 +10%"},
            {"key": "quantity_modifier", "label": "数量乘数", "type": "float", "default": 1.0, "hint": "2.0 表示双倍"},
            {"key": "weight_modifier", "label": "重量潜力乘数", "type": "float", "default": 1.0, "hint": "1.2 表示 +20%"},
            {"key": "is_consumable", "label": "一次性消耗品", "type": "bool", "default": True},
            {"key": "description", "label": "描述", "type": "textarea", "optional": True},
            {"key": "effect_description", "label": "效果描述", "type": "textarea", "optional": True},
        ],
    },
    "accessories": {
        "label": "饰品",
        "id_field": "accessory_id",
        "csv_required": [
            "name", "rarity", "slot_type", "bonus_fish_quality_modifier",
            "bonus_fish_quantity_modifier", "bonus_rare_fish_chance", "bonus_coin_modifier",
        ],
        "columns": [
            "name", "rarity", "slot_type", "bonus_fish_quality_modifier", "bonus_fish_quantity_modifier",
            "bonus_rare_fish_chance", "bonus_coin_modifier",
        ],
        "fields": [
            {"key": "name", "label": "名称", "type": "text", "required": True},
            {"key": "rarity", "label": "稀有度", "type": "int", "default": 1, "min": 1, "max": 10},
            {"key": "slot_type", "label": "装备槽类型", "type": "text", "default": "general"},
            {"key": "bonus_fish_quality_modifier", "label": "品质加成", "type": "float", "default": 1.0},
            {"key": "bonus_fish_quantity_modifier", "label": "数量加成", "type": "float", "default": 1.0},
            {"key": "bonus_rare_fish_chance", "label": "稀有加成", "type": "float", "default": 0.0},
            {"key": "bonus_coin_modifier", "label": "金币加成", "type": "float", "default": 1.0},
            {"key": "other_bonus_description", "label": "其他效果描述", "type": "text", "optional": True},
            {"key": "icon_url", "label": "图标 URL", "type": "text", "optional": True},
            {"key": "description", "label": "描述", "type": "textarea", "optional": True},
        ],
    },
    "items": {
        "label": "道具",
        "id_field": "item_id",
        "csv_required": ["name"],
        "columns": ["name", "rarity", "cost", "is_consumable", "effect_description"],
        "fields": [
            {"key": "name", "label": "名称", "type": "text", "required": True},
            {"key": "rarity", "label": "稀有度", "type": "int", "default": 1, "min": 1, "max": 10},
            {"key": "cost", "label": "价格", "type": "int", "default": 0, "min": 0},
            {"key": "is_consumable", "label": "消耗品", "type": "bool", "default": True},
            {"key": "icon_url", "label": "图标 URL", "type": "text", "optional": True},
            {"key": "description", "label": "描述", "type": "textarea", "optional": True},
            {"key": "effect_description", "label": "效果描述", "type": "textarea", "optional": True},
        ],
    },
}

USER_EDITABLE_FIELDS = {
    "nickname": "str",
    "coins": "int",
    "premium_currency": "int",
    "total_fishing_count": "int",
    "total_weight_caught": "int",
    "total_coins_earned": "int",
    "consecutive_login_days": "int",
    "fish_pond_capacity": "int",
    "fishing_zone_id": "int",
    "auto_fishing_enabled": "bool",
}


# 删除模板前检查的引用：(表, 列, 附加条件, 说明)。物品模板表没有开启外键，
# 不拦截的话删除后玩家库存、卡池和商店里会留下指向空模板的记录。
TEMPLATE_REFERENCES = {
    "fish": [
        ("user_fish_inventory", "fish_id", "", "玩家鱼塘"),
        ("user_aquarium", "fish_id", "", "玩家水族箱"),
        ("fishing_records", "fish_id", "", "钓鱼记录"),
        ("market", "item_id", "AND item_type = 'fish'", "市场挂单"),
        ("gacha_pool_items", "item_id", "AND item_type = 'fish'", "卡池"),
        ("shop_item_costs", "cost_item_id", "AND cost_type = 'fish'", "商店消耗"),
        ("shop_item_rewards", "reward_item_id", "AND reward_type = 'fish'", "商店奖励"),
    ],
    "rods": [
        ("user_rods", "rod_id", "", "玩家鱼竿"),
        ("gacha_pool_items", "item_id", "AND item_type = 'rod'", "卡池"),
        ("shop_item_costs", "cost_item_id", "AND cost_type = 'rod'", "商店消耗"),
        ("shop_item_rewards", "reward_item_id", "AND reward_type = 'rod'", "商店奖励"),
    ],
    "baits": [
        ("user_bait_inventory", "bait_id", "AND quantity > 0", "玩家鱼饵"),
        ("users", "current_bait_id", "", "正在使用的鱼饵"),
        ("gacha_pool_items", "item_id", "AND item_type = 'bait'", "卡池"),
        ("shop_item_rewards", "reward_item_id", "AND reward_type = 'bait'", "商店奖励"),
    ],
    "accessories": [
        ("user_accessories", "accessory_id", "", "玩家饰品"),
        ("gacha_pool_items", "item_id", "AND item_type = 'accessory'", "卡池"),
        ("shop_item_costs", "cost_item_id", "AND cost_type = 'accessory'", "商店消耗"),
        ("shop_item_rewards", "reward_item_id", "AND reward_type = 'accessory'", "商店奖励"),
    ],
    "items": [
        ("user_items", "item_id", "AND quantity > 0", "玩家道具"),
        ("market", "item_id", "AND item_type = 'item'", "市场挂单"),
        ("gacha_pool_items", "item_id", "AND item_type = 'item'", "卡池"),
        ("shop_item_costs", "cost_item_id", "AND cost_type = 'item'", "商店消耗"),
        ("shop_item_rewards", "reward_item_id", "AND reward_type = 'item'", "商店奖励"),
        ("fishing_zones", "required_item_id", "AND requires_pass = 1", "钓鱼区域通行证"),
    ],
}


class ApiError(Exception):
    """可以直接展示给管理员的业务错误。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# 通用转换
# ---------------------------------------------------------------------------

def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, sqlite3.Row):
        return {k: to_jsonable(value[k]) for k in value.keys()}
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return {k: to_jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
    return str(value)


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _int(value: Any, label: str, *, default: Any = ..., minimum: Optional[int] = None,
         maximum: Optional[int] = None, optional: bool = False) -> Optional[int]:
    if _blank(value):
        if optional:
            return None
        if default is not ...:
            return default
        raise ApiError(f"请填写{label}")
    if isinstance(value, bool):
        raise ApiError(f"{label}必须是整数")
    try:
        number = float(value) if isinstance(value, str) else value
        if isinstance(number, float):
            if not number.is_integer():
                raise ValueError
            number = int(number)
        number = int(number)
    except (TypeError, ValueError):
        raise ApiError(f"{label}必须是整数")
    if minimum is not None and number < minimum:
        raise ApiError(f"{label}不能小于 {minimum}")
    if maximum is not None and number > maximum:
        raise ApiError(f"{label}不能大于 {maximum}")
    return number


def _float(value: Any, label: str, *, default: Any = ..., minimum: Optional[float] = None,
           maximum: Optional[float] = None) -> float:
    if _blank(value):
        if default is not ...:
            return default
        raise ApiError(f"请填写{label}")
    if isinstance(value, bool):
        raise ApiError(f"{label}必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(f"{label}必须是数字")
    if minimum is not None and number < minimum:
        raise ApiError(f"{label}不能小于 {minimum}")
    if maximum is not None and number > maximum:
        raise ApiError(f"{label}不能大于 {maximum}")
    return number


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)


def _text(value: Any, label: str = "", *, required: bool = False, max_len: int = 2000) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    if not text:
        if required:
            raise ApiError(f"请填写{label}")
        return None
    if len(text) > max_len:
        raise ApiError(f"{label}不能超过 {max_len} 个字符")
    return text


def _check(result: Any, default_message: str = "操作失败") -> Any:
    """把服务层 {"success": False, "message": ...} 结果转换成错误。"""
    if isinstance(result, dict) and result.get("success") is False:
        raise ApiError(str(result.get("message") or default_message))
    return result


def _clean_datetime(value: Any) -> Optional[str]:
    """把 datetime-local 字符串规范成 ISO 文本，留空返回 None。"""
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "")).isoformat(timespec="minutes")
    except ValueError:
        raise ApiError(f"时间格式无效：{text}")


def _clean_clock(value: Any, label: str) -> Optional[str]:
    text = _text(value)
    if not text:
        return None
    try:
        datetime.strptime(text, "%H:%M")
    except ValueError:
        raise ApiError(f"{label}格式应为 HH:MM")
    return text


class FishingAdminAPI:
    """注册并实现面板管理接口。"""

    def __init__(self, plugin: Any):
        self.plugin = plugin

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def routes(self) -> List[tuple]:
        return [
            ("overview", "GET", self.overview, "概览"),
            ("meta", "GET", self.meta, "管理页元数据"),
            ("catalog", "GET", self.catalog, "物品与称号目录"),
            # 用户
            ("users", "GET", self.users_list, "用户列表"),
            ("users/detail", "GET", self.user_detail, "用户详情"),
            ("users/create", "POST", self.user_create, "创建用户"),
            ("users/update", "POST", self.user_update, "编辑用户"),
            ("users/delete", "POST", self.user_delete, "删除用户"),
            ("users/currency", "POST", self.user_currency, "调整用户货币"),
            ("users/inventory", "GET", self.user_inventory, "用户库存"),
            ("users/inventory/add", "POST", self.user_inventory_add, "添加库存"),
            ("users/inventory/remove", "POST", self.user_inventory_remove, "移除库存"),
            ("users/inventory/rod", "POST", self.user_rod_update, "编辑鱼竿实例"),
            ("users/inventory/accessory", "POST", self.user_accessory_update, "编辑饰品实例"),
            ("users/titles/grant", "POST", self.user_title_grant, "授予称号"),
            ("users/titles/revoke", "POST", self.user_title_revoke, "移除称号"),
            # 全服操作
            ("broadcast/currency", "POST", self.broadcast_currency, "全体发放或扣除货币"),
            ("broadcast/item", "POST", self.broadcast_item, "全体发放物品"),
            ("ops/sync", "POST", self.ops_sync, "同步初始设定"),
            ("ops/replenish", "POST", self.ops_replenish, "补充鱼池"),
            ("ops/impersonation", "GET", self.impersonation_list, "代理列表"),
            ("ops/impersonation/start", "POST", self.impersonation_start, "开始代理"),
            ("ops/impersonation/stop", "POST", self.impersonation_stop, "结束代理"),
            # 物品模板与称号
            ("templates", "GET", self.templates_list, "物品模板列表"),
            ("templates/save", "POST", self.template_save, "保存物品模板"),
            ("templates/delete", "POST", self.template_delete, "删除物品模板"),
            ("templates/import", "POST", self.template_import, "导入物品模板"),
            ("titles", "GET", self.titles_list, "称号列表"),
            ("titles/save", "POST", self.title_save, "保存称号"),
            ("titles/delete", "POST", self.title_delete, "删除称号"),
            # 抽卡
            ("gacha", "GET", self.gacha_list, "卡池列表"),
            ("gacha/save", "POST", self.gacha_save, "保存卡池"),
            ("gacha/copy", "POST", self.gacha_copy, "复制卡池"),
            ("gacha/delete", "POST", self.gacha_delete, "删除卡池"),
            ("gacha/items", "GET", self.gacha_items, "卡池物品"),
            ("gacha/items/save", "POST", self.gacha_item_save, "保存卡池物品"),
            ("gacha/items/delete", "POST", self.gacha_item_delete, "删除卡池物品"),
            # 钓鱼区域
            ("zones", "GET", self.zones_list, "钓鱼区域"),
            ("zones/save", "POST", self.zone_save, "保存钓鱼区域"),
            ("zones/delete", "POST", self.zone_delete, "删除钓鱼区域"),
            # 商店
            ("shops", "GET", self.shops_list, "商店列表"),
            ("shops/save", "POST", self.shop_save, "保存商店"),
            ("shops/delete", "POST", self.shop_delete, "删除商店"),
            ("shops/items", "GET", self.shop_items, "商店商品"),
            ("shops/items/save", "POST", self.shop_item_save, "保存商店商品"),
            ("shops/items/delete", "POST", self.shop_item_delete, "删除商店商品"),
            # 市场与交易所
            ("market", "GET", self.market_list, "玩家市场"),
            ("market/price", "POST", self.market_price, "修改挂单价格"),
            ("market/remove", "POST", self.market_remove, "下架挂单"),
            ("exchange", "GET", self.exchange_status, "交易所"),
            ("exchange/update", "POST", self.exchange_update, "刷新交易所价格"),
            ("exchange/reset", "POST", self.exchange_reset, "重置交易所价格"),
            # 银行与税收
            ("bank", "GET", self.bank_overview, "银行"),
            ("bank/adjust", "POST", self.bank_adjust, "调整银行余额"),
            ("bank/cancel-reservation", "POST", self.bank_cancel_reservation, "取消取款预约"),
            ("tax", "GET", self.tax_overview, "税收"),
            ("tax/save", "POST", self.tax_save, "保存税收设置"),
            ("tax/waive", "POST", self.tax_waive, "减免欠税"),
        ]

    def register(self, context: Any, plugin_name: str) -> None:
        for endpoint, method, fn, desc in self.routes():
            context.register_web_api(
                f"/{plugin_name}/{endpoint}", self._wrap(fn, method), [method], f"钓鱼管理：{desc}"
            )

    def _wrap(self, fn: Callable, method: str) -> Callable:
        async def handler(**_path_params):
            from astrbot.api.web import error_response, json_response, request

            query = {key: value for key, value in request.query.items()}
            body = await request.json(default={}) if method == "POST" else {}
            if not isinstance(body, dict):
                return error_response("请求体必须是 JSON 对象")
            try:
                result = await self.call(fn, query, body)
            except ApiError as exc:
                return error_response(str(exc), status_code=exc.status)
            except Exception as exc:  # pragma: no cover - 记录意外错误
                logger.error(f"[钓鱼管理] 接口 {fn.__name__} 出错: {exc}", exc_info=True)
                return error_response(f"服务器内部错误：{exc}", status_code=500)
            return json_response(result)

        handler.__name__ = f"fishing_admin_{fn.__name__}"
        return handler

    async def call(self, fn: Callable, query: Optional[dict] = None, body: Optional[dict] = None) -> Any:
        """执行一个接口方法并返回可 JSON 序列化的结果（测试也走这里）。"""
        result = fn(query or {}, body or {})
        if inspect.isawaitable(result):
            result = await result
        return to_jsonable(result)

    # ------------------------------------------------------------------
    # 便捷访问
    # ------------------------------------------------------------------

    @property
    def p(self):
        return self.plugin

    def _user_or_error(self, user_id: Any):
        uid = _text(user_id, "用户 ID", required=True, max_len=128)
        user = self.p.user_repo.get_by_id(uid)
        if not user:
            raise ApiError(f"用户 {uid} 不存在", 404)
        return user

    def _template(self, item_type: str, item_id: Any):
        repo = self.p.item_template_repo
        getters = {
            "fish": repo.get_fish_by_id,
            "rod": repo.get_rod_by_id,
            "bait": repo.get_bait_by_id,
            "accessory": repo.get_accessory_by_id,
            "item": repo.get_item_by_id,
            "titles": repo.get_title_by_id,
        }
        getter = getters.get(item_type)
        if not getter:
            return None
        try:
            return getter(int(item_id))
        except (TypeError, ValueError):
            return None

    def _template_name(self, item_type: str, item_id: Any) -> tuple:
        if item_type == "coins":
            return "金币", None
        if item_type == "premium":
            return "高级货币", None
        template = self._template(item_type, item_id)
        if not template:
            return f"{ITEM_TYPE_LABELS.get(item_type, item_type)}#{item_id}（已删除）", None
        return template.name, getattr(template, "rarity", None)

    def _real_user_ids(self) -> List[str]:
        return [uid for uid in self.p.user_repo.get_all_user_ids() if uid not in SYSTEM_USER_IDS]

    def _version(self) -> str:
        try:
            meta = Path(__file__).resolve().parents[1] / "metadata.yaml"
            for line in meta.read_text(encoding="utf-8-sig").splitlines():
                if line.startswith("version:"):
                    return line.split(":", 1)[1].strip().strip("\"'")
        except OSError:
            pass
        return ""

    # ------------------------------------------------------------------
    # 概览与元数据
    # ------------------------------------------------------------------

    def overview(self, query, body):
        p = self.p
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tax_today = p.log_repo.get_tax_summary_for_admin(start_time=today, end_time=today + timedelta(days=1))
        market = p.market_service.get_all_market_listings_for_admin(page=1, per_page=1)
        user_ids = self._real_user_ids()
        coins_total = 0
        premium_total = 0
        auto_count = 0
        for uid in user_ids:
            user = p.user_repo.get_by_id(uid)
            if user:
                coins_total += user.coins or 0
                premium_total += user.premium_currency or 0
                auto_count += 1 if user.auto_fishing_enabled else 0
        zones = p.fishing_zone_service.get_all_zones()
        return {
            "version": self._version(),
            "users": len(user_ids),
            "auto_fishing_users": auto_count,
            "coins_total": coins_total,
            "premium_total": premium_total,
            "bank": p.bank_service.get_admin_totals(),
            "tax_today": tax_today,
            "market": (market.get("stats") if market.get("success") else {}) or {},
            "counts": {
                "fish": len(p.item_template_service.get_all_fish()),
                "rods": len(p.item_template_service.get_all_rods()),
                "baits": len(p.item_template_service.get_all_baits()),
                "accessories": len(p.item_template_service.get_all_accessories()),
                "items": len(p.item_template_service.get_all_items()),
                "titles": len(p.item_template_repo.get_all_titles()),
                "zones": len(zones),
                "active_zones": len([z for z in zones if z.get("is_active")]),
                "shops": len(p.shop_repo.get_all_shops()),
                "gacha_pools": len(p.item_template_service.get_all_gacha_pools()),
            },
            "tax_enabled": bool(self._tax_config().get("is_tax")),
            "impersonations": len(p.impersonation_map),
        }

    def meta(self, query, body):
        return {
            "version": self._version(),
            "template_kinds": {
                kind: {k: v for k, v in spec.items() if k != "csv_required"} | {"csv_required": spec["csv_required"]}
                for kind, spec in TEMPLATE_KINDS.items()
            },
            "item_type_labels": ITEM_TYPE_LABELS,
            "tax_labels": {
                "asset_scope": ASSET_SCOPE_LABELS,
                "deduct_scope": DEDUCT_SCOPE_LABELS,
                "taxable_mode": TAXABLE_MODE_LABELS,
            },
        }

    def catalog(self, query, body):
        svc = self.p.item_template_service
        brief = lambda rows, key: [  # noqa: E731
            {"id": getattr(r, key), "name": r.name, "rarity": getattr(r, "rarity", None)} for r in rows
        ]
        return {
            "fish": brief(svc.get_all_fish(), "fish_id"),
            "rod": brief(svc.get_all_rods(), "rod_id"),
            "bait": brief(svc.get_all_baits(), "bait_id"),
            "accessory": brief(svc.get_all_accessories(), "accessory_id"),
            "item": brief(svc.get_all_items(), "item_id"),
            "titles": [
                {"id": t.title_id, "name": t.name, "rarity": None}
                for t in self.p.item_template_repo.get_all_titles()
            ],
            "zones": [{"id": z["id"], "name": z["name"]} for z in self.p.fishing_zone_service.get_all_zones()],
        }

    # ------------------------------------------------------------------
    # 用户
    # ------------------------------------------------------------------

    def users_list(self, query, body):
        page = _int(query.get("page"), "页码", default=1, minimum=1)
        per_page = _int(query.get("per_page"), "每页数量", default=20, minimum=1, maximum=100)
        search = _text(query.get("search"), "搜索", max_len=64)
        result = _check(self.p.user_service.get_users_for_admin(page=page, per_page=per_page, search=search))
        users = result["users"]
        return {
            "users": users,
            "bank": self.p.bank_service.get_admin_summary_for_users(users),
            "pagination": result["pagination"],
        }

    def user_detail(self, query, body):
        user = self._user_or_error(query.get("user_id"))
        result = _check(self.p.user_service.get_user_details_for_admin(user.user_id))
        return {
            "user": result["user"],
            "bank": self.p.bank_service.get_admin_summary_for_users([result["user"]]).get(user.user_id, {}),
            "equipped_rod": result["equipped_rod"],
            "equipped_accessory": result["equipped_accessory"],
            "current_title": result["current_title"],
            "titles": result.get("titles", []),
            "impersonated_by": [a for a, t in self.p.impersonation_map.items() if t == user.user_id],
        }

    def _user_fields(self, data: dict) -> dict:
        updates = {}
        for key, kind in USER_EDITABLE_FIELDS.items():
            if key not in data:
                continue
            value = data[key]
            if kind == "int":
                if _blank(value):
                    continue
                updates[key] = _int(value, key, minimum=0 if key != "fishing_zone_id" else 1)
            elif kind == "bool":
                updates[key] = _bool(value)
            else:
                text = _text(value, "昵称", max_len=32)
                if text:
                    updates[key] = text
        return updates

    def user_create(self, query, body):
        user_id = _text(body.get("user_id"), "用户 ID", required=True, max_len=128)
        data = {"user_id": user_id, **self._user_fields(body)}
        _check(self.p.user_service.create_user_for_admin(data))
        return {"message": f"玩家 {data.get('nickname') or user_id} 已创建"}

    def user_update(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        updates = self._user_fields(body)
        if not updates:
            raise ApiError("没有需要更新的字段")
        return _check(self.p.user_service.update_user_for_admin(user.user_id, updates))

    def user_delete(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        self.p.impersonation_map = {
            admin: target for admin, target in self.p.impersonation_map.items() if target != user.user_id
        }
        return _check(self.p.user_service.delete_user_for_admin(user.user_id))

    def user_currency(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        currency = body.get("currency")
        if currency not in ("coins", "premium_currency"):
            raise ApiError("货币类型无效")
        mode = body.get("mode")
        if mode not in ("set", "add", "subtract"):
            raise ApiError("调整方式无效")
        amount = _int(body.get("amount"), "数量", minimum=0)
        label = "金币" if currency == "coins" else "高级货币"
        before = getattr(user, currency) or 0
        if mode == "set":
            after = amount
        elif mode == "add":
            if amount <= 0:
                raise ApiError("增加数量必须大于 0")
            after = before + amount
        else:
            if amount <= 0:
                raise ApiError("扣除数量必须大于 0")
            after = max(0, before - amount)
        setattr(user, currency, after)
        self.p.user_repo.update(user)
        logger.info(f"[钓鱼管理] {user.user_id} 的{label}：{before} -> {after}")
        return {"message": f"{user.nickname or user.user_id} 的{label}已从 {before:,} 调整为 {after:,}", "value": after}

    def user_inventory(self, query, body):
        user = self._user_or_error(query.get("user_id"))
        return _check(self.p.user_service.get_user_inventory_for_admin(user.user_id))

    def _item_args(self, body: dict, allow_fish_quality: bool = True):
        item_type = body.get("item_type")
        if item_type not in ("fish", "rod", "accessory", "bait", "item"):
            raise ApiError("物品类型无效")
        item_id = _int(body.get("item_id"), "物品", minimum=1)
        quantity = _int(body.get("quantity"), "数量", default=1, minimum=1, maximum=100000)
        quality = _int(body.get("quality_level"), "品质", default=0, minimum=0, maximum=1) if allow_fish_quality else 0
        return item_type, item_id, quantity, quality if item_type == "fish" else 0

    def user_inventory_add(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        item_type, item_id, quantity, quality = self._item_args(body)
        return _check(self.p.user_service.add_item_to_user_inventory(user.user_id, item_type, item_id, quantity, quality))

    def user_inventory_remove(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        item_type, item_id, quantity, _ = self._item_args(body, allow_fish_quality=False)
        return _check(self.p.user_service.remove_item_from_user_inventory(user.user_id, item_type, item_id, quantity))

    def user_rod_update(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        instance_id = _int(body.get("instance_id"), "鱼竿实例", minimum=1)
        updates = {"refine_level": _int(body.get("refine_level"), "精炼等级", minimum=1, maximum=10)}
        if "durability" in body:
            updates["durability"] = _int(body.get("durability"), "耐久度", minimum=0, optional=True)
        return _check(self.p.user_service.update_user_rod_instance_for_admin(user.user_id, instance_id, updates))

    def user_accessory_update(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        instance_id = _int(body.get("instance_id"), "饰品实例", minimum=1)
        updates = {"refine_level": _int(body.get("refine_level"), "精炼等级", minimum=1, maximum=10)}
        return _check(self.p.user_service.update_user_accessory_instance_for_admin(user.user_id, instance_id, updates))

    def user_title_grant(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        name = _text(body.get("title_name"), "称号名称", required=True, max_len=64)
        return _check(self.p.user_service.grant_title_to_user_by_name(user.user_id, name))

    def user_title_revoke(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        name = _text(body.get("title_name"), "称号名称", required=True, max_len=64)
        return _check(self.p.user_service.revoke_title_from_user_by_name(user.user_id, name))

    # ------------------------------------------------------------------
    # 全服操作
    # ------------------------------------------------------------------

    def broadcast_currency(self, query, body):
        currency = body.get("currency")
        if currency not in ("coins", "premium_currency"):
            raise ApiError("货币类型无效")
        mode = body.get("mode")
        if mode not in ("add", "subtract"):
            raise ApiError("操作类型无效")
        amount = _int(body.get("amount"), "数量", minimum=1)
        label = "金币" if currency == "coins" else "高级货币"
        affected = 0
        total = 0
        for uid in self._real_user_ids():
            user = self.p.user_repo.get_by_id(uid)
            if not user:
                continue
            current = getattr(user, currency) or 0
            change = amount if mode == "add" else min(current, amount)
            if change <= 0:
                continue
            setattr(user, currency, current + change if mode == "add" else current - change)
            self.p.user_repo.update(user)
            affected += 1
            total += change
        logger.info(f"[钓鱼管理] 全体{'发放' if mode == 'add' else '扣除'}{label} {amount}，影响 {affected} 人")
        if mode == "add":
            message = f"已向 {affected} 位玩家每人发放 {amount:,} {label}"
        else:
            message = f"已从 {affected} 位玩家共扣除 {total:,} {label}（每人至多 {amount:,}）"
        return {"message": message, "affected": affected, "total": total}

    def broadcast_item(self, query, body):
        item_type, item_id, quantity, quality = self._item_args(body)
        template = self._template(item_type, item_id)
        if not template:
            raise ApiError("物品不存在，请检查类型和 ID")
        name = template.name
        success = 0
        failed = 0
        for uid in self._real_user_ids():
            try:
                result = self.p.user_service.add_item_to_user_inventory(uid, item_type, item_id, quantity, quality)
                if result.get("success"):
                    success += 1
                else:
                    failed += 1
            except Exception as exc:  # pragma: no cover - 单个玩家失败不影响其他人
                failed += 1
                logger.error(f"[钓鱼管理] 给 {uid} 发放物品失败: {exc}")
        message = f"已向 {success} 位玩家发放 {name} x{quantity}"
        if failed:
            message += f"，{failed} 位失败"
        return {"message": message, "success_count": success, "failed_count": failed}

    def ops_sync(self, query, body):
        self.p.data_setup_service.sync_all_initial_data()
        return {"message": "初始设定已同步"}

    def ops_replenish(self, query, body):
        zones = self.p.inventory_repo.get_all_zones()
        reset = []
        for zone in zones:
            if zone.daily_rare_fish_quota > 0:
                zone.rare_fish_caught_today = 0
                self.p.inventory_repo.update_fishing_zone(zone)
                reset.append(zone.name)
        if not reset:
            raise ApiError("没有设置了稀有鱼配额的钓鱼区域")
        logger.info(f"[钓鱼管理] 补充鱼池：{', '.join(reset)}")
        return {"message": f"已重置 {len(reset)} 个区域的稀有鱼配额", "zones": reset}

    def impersonation_list(self, query, body):
        rows = []
        for admin_id, target_id in self.p.impersonation_map.items():
            user = self.p.user_repo.get_by_id(target_id)
            rows.append({
                "admin_id": admin_id,
                "target_id": target_id,
                "target_nickname": user.nickname if user else None,
            })
        return {"rows": rows}

    def impersonation_start(self, query, body):
        admin_id = _text(body.get("admin_id"), "管理员账号 ID", required=True, max_len=128)
        target = self._user_or_error(body.get("target_id"))
        if admin_id == target.user_id:
            raise ApiError("不能代理自己")
        self.p.impersonation_map[admin_id] = target.user_id
        logger.info(f"[钓鱼管理] {admin_id} 开始代理 {target.user_id}")
        return {"message": f"{admin_id} 发送的游戏指令将以 {target.nickname or target.user_id} 的身份执行"}

    def impersonation_stop(self, query, body):
        admin_id = _text(body.get("admin_id"), "管理员账号 ID", required=True, max_len=128)
        if self.p.impersonation_map.pop(admin_id, None) is None:
            raise ApiError("该账号当前没有代理任何玩家")
        logger.info(f"[钓鱼管理] {admin_id} 结束代理")
        return {"message": f"{admin_id} 已结束代理"}

    # ------------------------------------------------------------------
    # 物品模板
    # ------------------------------------------------------------------

    def _kind(self, value: Any) -> tuple:
        if value not in TEMPLATE_KINDS:
            raise ApiError("模板类型无效")
        return value, TEMPLATE_KINDS[value]

    def _template_service_calls(self, kind: str):
        svc = self.p.item_template_service
        return {
            "fish": (svc.get_all_fish, svc.add_fish_template, svc.update_fish_template, svc.delete_fish_template),
            "rods": (svc.get_all_rods, svc.add_rod_template, svc.update_rod_template, svc.delete_rod_template),
            "baits": (svc.get_all_baits, svc.add_bait_template, svc.update_bait_template, svc.delete_bait_template),
            "accessories": (
                svc.get_all_accessories, svc.add_accessory_template,
                svc.update_accessory_template, svc.delete_accessory_template,
            ),
            "items": (svc.get_all_items, svc.add_item_template, svc.update_item_template, svc.delete_item_template),
        }[kind]

    @staticmethod
    def _coerce_template(spec: dict, data: dict) -> dict:
        clean = {}
        for field in spec["fields"]:
            key, label, kind = field["key"], field["label"], field["type"]
            value = data.get(key)
            if kind in ("text", "textarea"):
                clean[key] = _text(value, label, required=field.get("required", False))
                if clean[key] is None and "default" in field:
                    clean[key] = field["default"]
            elif kind == "int":
                clean[key] = _int(
                    value, label, default=field.get("default", ...), minimum=field.get("min"),
                    maximum=field.get("max"), optional=field.get("optional", False),
                )
            elif kind == "float":
                clean[key] = _float(value, label, default=field.get("default", ...))
            elif kind == "bool":
                clean[key] = _bool(value) if value is not None else bool(field.get("default", False))
            elif kind == "select":
                options = [opt[0] for opt in field["options"]]
                clean[key] = value if value in options else field.get("default", options[0])
        if "min_weight" in clean and "max_weight" in clean and clean["min_weight"] > clean["max_weight"]:
            raise ApiError("最小重量不能大于最大重量")
        return clean

    def templates_list(self, query, body):
        kind, spec = self._kind(query.get("kind"))
        rows = self._template_service_calls(kind)[0]()
        return {"kind": kind, "rows": rows}

    def template_save(self, query, body):
        kind, spec = self._kind(body.get("kind"))
        data = self._coerce_template(spec, body.get("data") or {})
        _, add, update, _ = self._template_service_calls(kind)
        template_id = _int(body.get("id"), "ID", optional=True, minimum=1)
        if template_id:
            update(template_id, data)
            return {"message": f"{spec['label']} {data['name']} 已更新"}
        add(data)
        return {"message": f"{spec['label']} {data['name']} 已添加"}

    def _template_references(self, kind: str, template_id: int) -> List[str]:
        db_path = os.path.join(self.p.data_dir, "fish.db")
        found = []
        with sqlite3.connect(db_path) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table, column, extra, label in TEMPLATE_REFERENCES[kind]:
                if table not in tables:
                    continue
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    continue
                count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ? {extra}", (template_id,)).fetchone()[0]
                if count:
                    found.append(f"{label} {count} 条")
        return found

    def template_delete(self, query, body):
        kind, spec = self._kind(body.get("kind"))
        template_id = _int(body.get("id"), "ID", minimum=1)
        references = self._template_references(kind, template_id)
        if references:
            raise ApiError(f"该{spec['label']}仍在使用中（{'、'.join(references)}），请先移除后再删除")
        try:
            self._template_service_calls(kind)[3](template_id)
        except sqlite3.IntegrityError:
            raise ApiError(f"该{spec['label']}仍被钓鱼记录等历史数据引用，无法删除")
        return {"message": f"{spec['label']} #{template_id} 已删除"}

    def template_import(self, query, body):
        kind, spec = self._kind(body.get("kind"))
        content = body.get("csv")
        if not isinstance(content, str) or not content.strip():
            raise ApiError("CSV 内容为空")
        if len(content) > 2_000_000:
            raise ApiError("CSV 文件过大")
        reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
        columns = {c.strip() for c in reader.fieldnames or []}
        missing = [c for c in spec["csv_required"] if c not in columns]
        if missing:
            raise ApiError(f"CSV 缺少列：{', '.join(missing)}")
        add = self._template_service_calls(kind)[1]
        ok, failed, errors = 0, 0, []
        for line_no, row in enumerate(reader, start=2):
            row = {(k or "").strip(): v for k, v in row.items()}
            try:
                add(self._coerce_template(spec, row))
                ok += 1
            except Exception as exc:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"第 {line_no} 行：{exc}")
        if not ok and failed:
            raise ApiError("没有导入任何记录。" + "；".join(errors))
        message = f"成功导入 {ok} 条{spec['label']}"
        if failed:
            message += f"，失败 {failed} 条"
        return {"message": message, "imported": ok, "failed": failed, "errors": errors}

    # ------------------------------------------------------------------
    # 称号
    # ------------------------------------------------------------------

    def titles_list(self, query, body):
        return {"rows": _check(self.p.user_service.get_all_titles_for_admin())["titles"]}

    def title_save(self, query, body):
        name = _text(body.get("name"), "称号名称", required=True, max_len=64)
        description = _text(body.get("description"), "描述", max_len=200) or f"自定义称号：{name}"
        display_format = _text(body.get("display_format"), "显示格式", max_len=100) or "{name}"
        title_id = _int(body.get("title_id"), "称号 ID", optional=True, minimum=1)
        if not title_id:
            return _check(self.p.user_service.create_custom_title(name, description, display_format))
        svc = self.p.item_template_service
        if not svc.get_title_by_id(title_id):
            raise ApiError(f"称号 #{title_id} 不存在", 404)
        same_name = svc.get_title_by_name(name)
        if same_name and same_name.title_id != title_id:
            raise ApiError(f"称号名称 {name} 已被其他称号使用")
        svc.update_title_template(title_id, {"name": name, "description": description, "display_format": display_format})
        return {"message": f"称号 {name} 已更新"}

    def title_delete(self, query, body):
        title_id = _int(body.get("title_id"), "称号 ID", minimum=1)
        try:
            self.p.item_template_service.delete_title_template(title_id)
        except sqlite3.IntegrityError:
            raise ApiError("该称号仍被玩家持有，无法删除")
        return {"message": f"称号 #{title_id} 已删除"}

    # ------------------------------------------------------------------
    # 抽卡
    # ------------------------------------------------------------------

    def gacha_list(self, query, body):
        pools = self.p.item_template_service.get_all_gacha_pools()
        return {"rows": [{**to_jsonable(pool), "item_count": len(pool.items or [])} for pool in pools]}

    def gacha_save(self, query, body):
        name = _text(body.get("name"), "卡池名称", required=True, max_len=64)
        currency = body.get("currency_type", "coins")
        if currency not in ("coins", "premium"):
            raise ApiError("消耗货币无效")
        amount = _int(body.get("cost_amount"), "消耗数量", default=0, minimum=0)
        limited = _bool(body.get("is_limited_time"))
        open_until = _clean_datetime(body.get("open_until")) if limited else None
        if limited and not open_until:
            raise ApiError("限时卡池需要填写截止时间")
        payload = {
            "name": name,
            "description": _text(body.get("description"), "描述", max_len=500),
            "cost_coins": amount if currency == "coins" else 0,
            "cost_premium_currency": amount if currency == "premium" else 0,
            "is_limited_time": limited,
            "open_until": open_until,
        }
        pool_id = _int(body.get("pool_id"), "卡池 ID", optional=True, minimum=1)
        if pool_id:
            self.p.item_template_service.update_pool_template(pool_id, payload)
            return {"message": f"卡池 {name} 已更新"}
        self.p.item_template_service.add_pool_template(payload)
        return {"message": f"卡池 {name} 已创建"}

    def gacha_copy(self, query, body):
        pool_id = _int(body.get("pool_id"), "卡池 ID", minimum=1)
        new_id = self.p.item_template_service.copy_pool_template(pool_id)
        return {"message": f"已复制卡池 #{pool_id}，新卡池 ID 为 {new_id}", "pool_id": new_id}

    def gacha_delete(self, query, body):
        pool_id = _int(body.get("pool_id"), "卡池 ID", minimum=1)
        self.p.item_template_service.delete_pool_template(pool_id)
        return {"message": f"卡池 #{pool_id} 已删除"}

    def gacha_items(self, query, body):
        pool_id = _int(query.get("pool_id"), "卡池 ID", minimum=1)
        pool = self.p.gacha_repo.get_pool_by_id(pool_id)
        if not pool:
            raise ApiError("卡池不存在", 404)
        total_weight = sum(item.weight for item in pool.items) or 1
        rows = []
        for item in pool.items:
            name, rarity = self._template_name(item.item_type, item.item_id)
            if item.item_type == "coins":
                name = f"{item.quantity:,} 金币"
            rows.append({
                **to_jsonable(item),
                "item_name": name,
                "rarity": rarity,
                "probability": item.weight / total_weight,
            })
        return {"pool": pool, "rows": rows}

    def gacha_item_save(self, query, body):
        item_type = body.get("item_type")
        if item_type not in ("rod", "accessory", "bait", "item", "coins", "titles"):
            raise ApiError("物品类型无效")
        item_id = 0 if item_type == "coins" else _int(body.get("item_id"), "物品", minimum=1)
        data = {
            "item_full_id": f"{item_type}-{item_id}",
            "quantity": _int(body.get("quantity"), "数量", default=1, minimum=1),
            "weight": _int(body.get("weight"), "权重", default=10, minimum=1),
        }
        item_pool_id = _int(body.get("gacha_pool_item_id"), "卡池物品 ID", optional=True, minimum=1)
        if item_pool_id:
            self.p.item_template_service.update_pool_item(item_pool_id, data)
            return {"message": "卡池物品已更新"}
        pool_id = _int(body.get("pool_id"), "卡池 ID", minimum=1)
        self.p.item_template_service.add_item_to_pool(pool_id, data)
        return {"message": "已向卡池添加物品"}

    def gacha_item_delete(self, query, body):
        item_pool_id = _int(body.get("gacha_pool_item_id"), "卡池物品 ID", minimum=1)
        self.p.item_template_service.delete_pool_item(item_pool_id)
        return {"message": "卡池物品已删除"}

    # ------------------------------------------------------------------
    # 钓鱼区域
    # ------------------------------------------------------------------

    def zones_list(self, query, body):
        zones = self.p.fishing_zone_service.get_all_zones()
        raw = {zone.id: zone for zone in self.p.inventory_repo.get_all_zones()}
        for zone in zones:
            source = raw.get(zone["id"])
            zone["rare_fish_caught_today"] = getattr(source, "rare_fish_caught_today", 0) if source else 0
        return {"rows": zones}

    def zone_save(self, query, body):
        is_new = _bool(body.get("is_new"))
        zone_id = _int(body.get("id"), "区域 ID", minimum=1)
        distribution = body.get("rarity_distribution") or []
        if not isinstance(distribution, list) or len(distribution) != 6:
            raise ApiError("稀有度分布需要 6 个数值")
        distribution = [_float(v, f"{i + 1} 星概率", default=0.0, minimum=0, maximum=1) for i, v in enumerate(distribution)]
        total = sum(distribution)
        if abs(total - 1) > 0.001:
            raise ApiError(f"稀有度分布总和应为 1，当前为 {total:.3f}")
        fish_ids = body.get("specific_fish_ids") or []
        if not isinstance(fish_ids, list):
            raise ApiError("限定鱼类格式无效")
        fish_ids = sorted({_int(v, "鱼类 ID", minimum=1) for v in fish_ids})
        requires_pass = _bool(body.get("requires_pass"))
        required_item_id = _int(body.get("required_item_id"), "通行证道具", optional=True, minimum=1) if requires_pass else None
        if requires_pass and not required_item_id:
            raise ApiError("需要通行证时请选择通行证道具")
        limited = _bool(body.get("limit_time"))
        available_from = _clean_datetime(body.get("available_from")) if limited else None
        available_until = _clean_datetime(body.get("available_until")) if limited else None
        if available_from and available_until and available_from >= available_until:
            raise ApiError("结束时间必须晚于开放时间")
        data = {
            "id": zone_id,
            "name": _text(body.get("name"), "区域名称", required=True, max_len=64),
            "description": _text(body.get("description"), "描述", max_len=500) or "",
            "daily_rare_fish_quota": _int(body.get("daily_rare_fish_quota"), "稀有鱼每日配额", default=0, minimum=0),
            "fishing_cost": _int(body.get("fishing_cost"), "钓鱼消耗", default=10, minimum=1),
            "is_active": _bool(body.get("is_active", True)),
            "available_from": available_from,
            "available_until": available_until,
            "configs": {"rarity_distribution": distribution},
            "specific_fish_ids": fish_ids,
            "requires_pass": requires_pass,
            "required_item_id": required_item_id,
        }
        service = self.p.fishing_zone_service
        if is_new:
            try:
                service.create_zone(data)
            except ValueError as exc:
                raise ApiError(str(exc), 409)
        elif not self.p.inventory_repo.get_zone_by_id(zone_id):
            raise ApiError("钓鱼区域不存在", 404)
        # 创建后也要写入限定鱼类，旧后台在创建时会丢掉这部分设置
        service.update_zone(zone_id, data)
        return {"message": f"钓鱼区域 {data['name']} 已{'创建' if is_new else '更新'}"}

    def zone_delete(self, query, body):
        zone_id = _int(body.get("id"), "区域 ID", minimum=1)
        if zone_id == 1:
            raise ApiError("1 号区域是默认钓鱼地，不能删除")
        self.p.fishing_zone_service.delete_zone(zone_id)
        return {"message": f"钓鱼区域 #{zone_id} 已删除"}

    # ------------------------------------------------------------------
    # 商店
    # ------------------------------------------------------------------

    def shops_list(self, query, body):
        shops = self.p.shop_repo.get_all_shops()
        shops.sort(key=lambda x: (x.get("sort_order", 999), x.get("shop_id", 999)))
        for shop in shops:
            shop["item_count"] = len(self.p.shop_repo.get_shop_items(shop["shop_id"]))
        return {"rows": shops}

    def shop_save(self, query, body):
        shop_type = body.get("shop_type", "normal")
        if shop_type not in ("normal", "premium", "limited"):
            raise ApiError("商店类型无效")
        start_time = _clean_datetime(body.get("start_time"))
        end_time = _clean_datetime(body.get("end_time"))
        if start_time and end_time and start_time >= end_time:
            raise ApiError("结束时间必须晚于开始时间")
        data = {
            "name": _text(body.get("name"), "商店名称", required=True, max_len=64),
            "description": _text(body.get("description"), "描述", max_len=500),
            "shop_type": shop_type,
            "is_active": _bool(body.get("is_active", True)),
            "start_time": start_time,
            "end_time": end_time,
            "daily_start_time": _clean_clock(body.get("daily_start_time"), "每日开始时间"),
            "daily_end_time": _clean_clock(body.get("daily_end_time"), "每日结束时间"),
            "sort_order": _int(body.get("sort_order"), "排序", default=100),
        }
        shop_id = _int(body.get("shop_id"), "商店 ID", optional=True, minimum=1)
        if shop_id:
            if not self.p.shop_repo.get_shop_by_id(shop_id):
                raise ApiError("商店不存在", 404)
            self.p.shop_repo.update_shop(shop_id, data)
            return {"message": f"商店 {data['name']} 已更新"}
        created = self.p.shop_repo.create_shop(data)
        return {"message": f"商店 {data['name']} 已创建", "shop": created}

    def shop_delete(self, query, body):
        shop_id = _int(body.get("shop_id"), "商店 ID", minimum=1)
        self.p.shop_repo.delete_shop(shop_id)
        return {"message": f"商店 #{shop_id} 已删除"}

    def shop_items(self, query, body):
        shop_id = _int(query.get("shop_id"), "商店 ID", minimum=1)
        repo = self.p.shop_repo
        shop = repo.get_shop_by_id(shop_id)
        if not shop:
            raise ApiError("商店不存在", 404)
        rows = []
        for item in repo.get_shop_items(shop_id):
            costs = repo.get_item_costs(item["item_id"])
            rewards = repo.get_item_rewards(item["item_id"])
            for cost in costs:
                cost["name"] = self._template_name(cost["cost_type"], cost.get("cost_item_id"))[0]
            for reward in rewards:
                reward["name"] = self._template_name(reward["reward_type"], reward.get("reward_item_id"))[0]
            rows.append({"item": item, "costs": costs, "rewards": rewards})
        return {"shop": shop, "rows": rows}

    def shop_item_save(self, query, body):
        repo = self.p.shop_repo
        shop_id = _int(body.get("shop_id"), "商店 ID", minimum=1)
        if not repo.get_shop_by_id(shop_id):
            raise ApiError("商店不存在", 404)
        start_time = _clean_datetime(body.get("start_time"))
        end_time = _clean_datetime(body.get("end_time"))
        if start_time and end_time and start_time >= end_time:
            raise ApiError("结束时间必须晚于开始时间")
        item_data = {
            "name": _text(body.get("name"), "商品名称", required=True, max_len=64),
            "description": _text(body.get("description"), "描述", max_len=500) or "",
            "category": _text(body.get("category"), "分类", max_len=32) or "general",
            "stock_total": _int(body.get("stock_total"), "库存", optional=True, minimum=0),
            "stock_sold": _int(body.get("stock_sold"), "已售数量", default=0, minimum=0),
            "per_user_limit": _int(body.get("per_user_limit"), "每人总限购", optional=True, minimum=1),
            "per_user_daily_limit": _int(body.get("per_user_daily_limit"), "每人每日限购", optional=True, minimum=1),
            "is_active": _bool(body.get("is_active", True)),
            "start_time": start_time,
            "end_time": end_time,
            "sort_order": _int(body.get("sort_order"), "排序", default=100),
        }
        costs = self._parse_costs(body.get("costs") or [])
        rewards = self._parse_rewards(body.get("rewards") or [])
        if not rewards:
            raise ApiError("至少需要设置一个奖励")
        item_id = _int(body.get("item_id"), "商品 ID", optional=True, minimum=1)
        if item_id:
            if not repo.get_shop_item_by_id(item_id):
                raise ApiError("商品不存在", 404)
            repo.update_shop_item(item_id, item_data)
            for cost in repo.get_item_costs(item_id):
                repo.delete_item_cost(cost["cost_id"])
            for reward in repo.get_item_rewards(item_id):
                repo.delete_item_reward(reward["reward_id"])
        else:
            item_id = repo.create_shop_item(shop_id, item_data)["item_id"]
        for cost in costs:
            repo.add_item_cost(item_id, cost)
        for reward in rewards:
            repo.add_item_reward(item_id, reward)
        return {"message": f"商品 {item_data['name']} 已保存", "item_id": item_id}

    @staticmethod
    def _parse_costs(rows: Any) -> List[dict]:
        if not isinstance(rows, list):
            raise ApiError("消耗设置格式无效")
        costs = []
        for index, row in enumerate(rows, start=1):
            cost_type = row.get("cost_type")
            if cost_type not in ("coins", "premium", "fish", "item", "rod", "accessory"):
                raise ApiError(f"第 {index} 条消耗的类型无效")
            relation = row.get("cost_relation", "and")
            if relation not in ("and", "or"):
                raise ApiError(f"第 {index} 条消耗的关系无效")
            cost = {
                "cost_type": cost_type,
                "cost_amount": _int(row.get("cost_amount"), f"第 {index} 条消耗的数量", minimum=1),
                "cost_relation": relation,
                "group_id": _int(row.get("group_id"), f"第 {index} 条消耗的组 ID", optional=True, minimum=1),
                "quality_level": _int(row.get("quality_level"), "品质", default=0, minimum=0, maximum=1) if cost_type == "fish" else 0,
            }
            if cost_type in ("fish", "item", "rod", "accessory"):
                cost["cost_item_id"] = _int(row.get("cost_item_id"), f"第 {index} 条消耗的物品", minimum=1)
            costs.append(cost)
        return costs

    @staticmethod
    def _parse_rewards(rows: Any) -> List[dict]:
        if not isinstance(rows, list):
            raise ApiError("奖励设置格式无效")
        rewards = []
        for index, row in enumerate(rows, start=1):
            reward_type = row.get("reward_type")
            if reward_type not in ("rod", "bait", "accessory", "item", "fish"):
                raise ApiError(f"第 {index} 条奖励的类型无效")
            rewards.append({
                "reward_type": reward_type,
                "reward_item_id": _int(row.get("reward_item_id"), f"第 {index} 条奖励的物品", minimum=1),
                "reward_quantity": _int(row.get("reward_quantity"), f"第 {index} 条奖励的数量", default=1, minimum=1),
                "reward_refine_level": (
                    _int(row.get("reward_refine_level"), "精炼等级", optional=True, minimum=1, maximum=10)
                    if reward_type in ("rod", "accessory") else None
                ),
                "quality_level": _int(row.get("quality_level"), "品质", default=0, minimum=0, maximum=1) if reward_type == "fish" else 0,
            })
        return rewards

    def shop_item_delete(self, query, body):
        item_id = _int(body.get("item_id"), "商品 ID", minimum=1)
        self.p.shop_repo.delete_shop_item(item_id)
        return {"message": f"商品 #{item_id} 已删除"}

    # ------------------------------------------------------------------
    # 市场与交易所
    # ------------------------------------------------------------------

    def market_list(self, query, body):
        item_type = query.get("item_type") or None
        if item_type and item_type not in ("fish", "rod", "accessory", "item", "commodity"):
            raise ApiError("物品类型无效")
        min_price = _int(query.get("min_price"), "最低价格", optional=True, minimum=0)
        max_price = _int(query.get("max_price"), "最高价格", optional=True, minimum=0)
        result = _check(self.p.market_service.get_all_market_listings_for_admin(
            page=_int(query.get("page"), "页码", default=1, minimum=1),
            per_page=20,
            item_type=item_type,
            min_price=min_price,
            max_price=max_price,
            search=_text(query.get("search"), "搜索", max_len=64),
        ))
        return {"rows": result["listings"], "pagination": result["pagination"], "stats": result["stats"]}

    def market_price(self, query, body):
        market_id = _int(body.get("market_id"), "挂单 ID", minimum=1)
        price = _int(body.get("price"), "价格", minimum=1)
        return _check(self.p.market_service.update_market_item_price(market_id, price))

    def market_remove(self, query, body):
        market_id = _int(body.get("market_id"), "挂单 ID", minimum=1)
        return _check(self.p.market_service.remove_market_item_by_admin(market_id))

    def exchange_status(self, query, body):
        service = self.p.exchange_service
        return {
            "status": service.get_market_status(),
            "history": service.get_price_history(days=7),
            "holdings": service.get_user_commodity_stats(),
        }

    def exchange_update(self, query, body):
        _check(self.p.exchange_service.manual_update_prices(), "价格更新失败")
        return {"message": "交易所价格已刷新"}

    def exchange_reset(self, query, body):
        _check(self.p.exchange_service.reset_prices_to_initial(), "价格重置失败")
        return {"message": "交易所价格已重置为初始值"}

    # ------------------------------------------------------------------
    # 银行
    # ------------------------------------------------------------------

    def bank_overview(self, query, body):
        bank = self.p.bank_service
        page = _int(query.get("page"), "页码", default=1, minimum=1)
        search = _text(query.get("search"), "搜索", max_len=64)
        result = _check(self.p.user_service.get_users_for_admin(page=page, per_page=20, search=search))
        users = result["users"]
        return {
            "users": users,
            "summaries": bank.get_admin_summary_for_users(users),
            "pagination": result["pagination"],
            "totals": bank.get_admin_totals(),
            "fixed_deposits": bank.get_fixed_deposits_for_admin(search=search, limit=100),
            "fixed_terms": bank.get_fixed_terms(),
            "transactions": bank.get_transactions(user_id=search, limit=100),
            "enabled": bool(self.p.game_config.get("bank", {}).get("enabled", True)),
        }

    def bank_adjust(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        delta = _int(body.get("delta"), "调整金额")
        if delta == 0:
            raise ApiError("调整金额不能为 0")
        remark = _text(body.get("remark"), "备注", max_len=200) or ""
        return _check(self.p.bank_service.admin_adjust_balance(user.user_id, delta, remark))

    def bank_cancel_reservation(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        reservation_id = _int(body.get("reservation_id"), "预约编号", minimum=1)
        return _check(self.p.bank_service.admin_cancel_reservation(user.user_id, reservation_id))

    # ------------------------------------------------------------------
    # 税收
    # ------------------------------------------------------------------

    def _tax_config(self) -> dict:
        config = dict(DEFAULT_TAX_CONFIG)
        config.update(self.p.game_config.get("tax", {}) or {})
        return config

    @staticmethod
    def _tax_preview(config: dict, levels: int = 8) -> List[dict]:
        threshold = int(config.get("threshold", DEFAULT_TAX_CONFIG["threshold"]))
        step = max(int(config.get("step_coins", DEFAULT_TAX_CONFIG["step_coins"])), 1)
        step_rate = float(config.get("step_rate", DEFAULT_TAX_CONFIG["step_rate"]))
        min_rate = float(config.get("min_rate", DEFAULT_TAX_CONFIG["min_rate"]))
        max_rate = float(config.get("max_rate", DEFAULT_TAX_CONFIG["max_rate"]))
        rows = []
        for index in range(levels):
            lower = threshold + index * step
            rate = min(min_rate + index * step_rate, max_rate)
            rows.append({"lower": lower, "upper": lower + step - 1, "rate": rate})
            if rate >= max_rate:
                break
        return rows

    def tax_overview(self, query, body):
        config = self._tax_config()
        user_id = _text(query.get("user_id"), "用户 ID", max_len=128)
        tax_type = _text(query.get("tax_type"), "税种", max_len=32)
        limit = _int(query.get("limit"), "条数", default=200, minimum=20, maximum=1000)
        today = date.today().isoformat()
        start_date = _text(query.get("start_date")) or today
        end_date = _text(query.get("end_date")) or start_date
        try:
            start_time = datetime.fromisoformat(start_date)
            end_time = datetime.fromisoformat(end_date) + timedelta(days=1)
        except ValueError:
            raise ApiError("日期格式无效")
        if end_time <= start_time:
            raise ApiError("结束日期不能早于开始日期")
        log_repo = self.p.log_repo
        summary = log_repo.get_tax_summary_for_admin(start_time=start_time, end_time=end_time, user_id=user_id)
        return {
            "config": config,
            "preview": self._tax_preview(config),
            "summary": summary,
            "records": log_repo.get_tax_records_for_admin(
                user_id=user_id, start_time=start_time, end_time=end_time, tax_type=tax_type, limit=limit,
            ),
            "debt_summary": self.p.bank_service.get_tax_debt_summary(user_id=user_id),
            "debts": self.p.bank_service.get_tax_debts_for_admin(user_id=user_id, limit=50),
            "filters": {
                "user_id": user_id or "", "tax_type": tax_type or "", "start_date": start_date,
                "end_date": end_date, "limit": limit,
            },
        }

    async def tax_save(self, query, body):
        asset_scope = body.get("asset_scope")
        deduct_scope = body.get("deduct_scope")
        taxable_mode = body.get("taxable_mode")
        if asset_scope not in ASSET_SCOPE_LABELS:
            raise ApiError("资产统计范围无效")
        if deduct_scope not in DEDUCT_SCOPE_LABELS:
            raise ApiError("扣款来源无效")
        if taxable_mode not in TAXABLE_MODE_LABELS:
            raise ApiError("计税模式无效")
        d = DEFAULT_TAX_CONFIG
        tax = {
            "is_tax": _bool(body.get("is_tax")),
            "threshold": _int(body.get("threshold"), "起征点", default=d["threshold"], minimum=0),
            "asset_scope": asset_scope,
            "deduct_scope": deduct_scope,
            "taxable_mode": taxable_mode,
            "step_coins": _int(body.get("step_coins"), "金额档位步长", default=d["step_coins"], minimum=1),
            "step_rate": _float(body.get("step_rate"), "每档增加税率", default=d["step_rate"], minimum=0, maximum=1),
            "min_rate": _float(body.get("min_rate"), "起点税率", default=d["min_rate"], minimum=0, maximum=1),
            "max_rate": _float(body.get("max_rate"), "最高税率", default=d["max_rate"], minimum=0, maximum=1),
            "transfer_tax_rate": _float(body.get("transfer_tax_rate"), "转账手续费率", default=d["transfer_tax_rate"], minimum=0, maximum=1),
            "debt_surcharge_rate": _float(body.get("debt_surcharge_rate"), "欠税滞纳金率", default=d["debt_surcharge_rate"], minimum=0, maximum=1),
            "tax_record_retention_days": _int(body.get("tax_record_retention_days"), "税收记录保留天数", default=d["tax_record_retention_days"], minimum=1),
            "tax_record_cleanup_batch_size": _int(body.get("tax_record_cleanup_batch_size"), "单次清理条数", default=d["tax_record_cleanup_batch_size"], minimum=1),
        }
        if tax["min_rate"] > tax["max_rate"]:
            raise ApiError("起点税率不能大于最高税率")

        plugin = self.p
        plugin.game_config["tax"] = tax
        plugin.is_tax = tax["is_tax"]
        saved = self._persist_tax_config(tax)
        if hasattr(plugin.log_repo, "set_tax_record_retention"):
            plugin.log_repo.set_tax_record_retention(
                tax["tax_record_retention_days"], tax["tax_record_cleanup_batch_size"]
            )
        if tax["is_tax"]:
            plugin.fishing_service.start_daily_tax_task()
        else:
            # stop 会 join 线程最多 5 秒，放到线程池里避免卡住面板请求
            await asyncio.to_thread(plugin.fishing_service.stop_daily_tax_task)
        if not saved:
            return {"message": "税收设置已在当前进程生效，但未能写入配置文件，重启后会恢复原值"}
        return {"message": "税收设置已保存并立即生效"}

    def _persist_tax_config(self, tax: dict) -> bool:
        config = getattr(self.p, "astrbot_config", None)
        if config is None:
            return False
        try:
            merged = dict(config.get("tax", {}) or {})
            merged.update(tax)
            config["tax"] = merged
            if hasattr(config, "save_config"):
                config.save_config()
                return True
        except Exception as exc:
            logger.warning(f"[钓鱼管理] 保存税收配置失败: {exc}")
        return False

    def tax_waive(self, query, body):
        user = self._user_or_error(body.get("user_id"))
        amount = _int(body.get("amount"), "减免金额", optional=True, minimum=1)
        return _check(self.p.bank_service.admin_waive_tax_debt(user.user_id, amount))
