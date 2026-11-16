"""1.0.0 回归测试：管理员指令下线、已删玩法、面板接口与数据库结构。"""

import asyncio
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

import astrbot_stub

PLUGIN_DIR = Path(__file__).resolve().parents[1]
MAIN_SOURCE = (PLUGIN_DIR / "main.py").read_text(encoding="utf-8")

REMOVED_COMMANDS = [
    # 原管理员指令
    "修改金币", "修改高级货币", "奖励高级货币", "扣除高级货币", "全体奖励金币", "全体奖励高级货币",
    "全体扣除金币", "全体扣除高级货币", "奖励金币", "扣除金币", "开启钓鱼后台管理", "关闭钓鱼后台管理",
    "同步初始设定", "授予称号", "移除称号", "创建称号", "代理上线", "代理下线", "全体发放道具",
    "补充鱼池", "清理红包", "骰宝结算", "骰宝倒计时", "骰宝模式", "21点模式", "拉杆模式", "游戏开关", "所有借条",
    # 删除的玩法
    "擦弹", "擦弹记录", "命运之轮", "继续", "放弃", "开庄", "玩家开庄", "鸭大", "鸭小", "鸭豹子", "鸭17点",
    "骰宝状态", "骰宝帮助", "21点", "21点加入", "抽牌", "停牌", "拉杆", "连转", "奖池", "读博记录",
    "发红包", "领红包", "红包列表", "撤回红包", "系统借款", "确认借款", "借条", "一键还债", "还系统",
    "钓鱼银行", "钓鱼存款", "钓鱼取款", "钓鱼还税", "还税", "税收记录",
    "交易所", "持仓", "交易所升级", "升级交易所", "交易所扩容", "清仓",
]


def run(coro):
    return asyncio.run(coro)


class CommandSurfaceTests(unittest.TestCase):
    def test_no_admin_permission_commands_left(self):
        self.assertNotIn("PermissionType", MAIN_SOURCE)
        self.assertNotIn("permission_type", MAIN_SOURCE)

    def test_removed_commands_are_not_registered(self):
        names = set(re.findall(r'filter\.command\("([^"]+)"', MAIN_SOURCE))
        aliases = set()
        for group in re.findall(r"alias=\{([^}]*)\}", MAIN_SOURCE):
            aliases.update(re.findall(r'"([^"]+)"', group))
        for command in REMOVED_COMMANDS:
            self.assertNotIn(command, names | aliases, command)
        self.assertNotIn("filter.regex", MAIN_SOURCE)
        # 保留的核心玩法仍在
        for command in ("钓鱼", "鱼塘", "商店", "商店购买", "市场", "上架", "购买", "下架", "出售", "抽卡", "偷鱼", "排行榜", "转账"):
            self.assertIn(command, names)

    def test_removed_modules_are_gone(self):
        for path in (
            "handlers/admin_handlers.py", "handlers/sicbo_handlers.py", "handlers/blackjack_handlers.py",
            "handlers/slot_handlers.py", "handlers/loan_handlers.py", "handlers/red_packet_handlers.py",
            "core/services/sicbo_service.py", "core/services/blackjack_service.py", "core/services/slot_service.py",
            "core/services/loan_service.py", "core/services/red_packet_service.py", "manager/server.py",
            "handlers/bank_handlers.py", "core/services/bank_service.py", "core/repositories/sqlite_bank_repo.py",
            "core/repositories/bank_sql.py", "core/domain/bank_models.py",
            "handlers/exchange_handlers.py", "core/services/exchange_service.py",
            "core/repositories/sqlite_exchange_repo.py",
        ):
            self.assertFalse((PLUGIN_DIR / path).exists(), path)

    def test_schema_has_no_removed_config(self):
        schema = json.loads((PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8-sig"))
        for key in ("webui", "sicbo", "blackjack", "slot", "loan", "tax", "bank", "exchange"):
            self.assertNotIn(key, schema)
        self.assertEqual(schema["user"]["items"]["transfer_fee_rate"]["default"], 0.05)
        self.assertNotIn("wipe_bomb_attempts", schema["game"]["items"])
        self.assertNotIn("wheel_of_fate_daily_limit", schema["game"]["items"])

    def test_view_is_registered_with_bridge_endpoints_that_exist(self):
        view = PLUGIN_DIR / "views" / "admin"
        self.assertTrue((view / "index.html").is_file())
        app_js = (view / "app.js").read_text(encoding="utf-8")
        self.assertIn("AstrBotPluginView", app_js)
        self.assertNotIn("fetch(", app_js)
        used = set(re.findall(r"\b(?:get|post)\('([a-z/\-]+)'", app_js))
        astrbot_stub.install(Path(tempfile.mkdtemp()))
        import importlib
        import sys
        sys.path.insert(0, str(PLUGIN_DIR.parent))
        api_mod = importlib.import_module(f"{PLUGIN_DIR.name}.webui.admin_api")
        endpoints = {route[0] for route in api_mod.FishingAdminAPI(None).routes()}
        self.assertTrue(used, "未找到页面调用的接口")
        self.assertEqual(set(), used - endpoints)
        i18n = json.loads((PLUGIN_DIR / ".astrbot-plugin" / "i18n" / "zh-CN.json").read_text(encoding="utf-8"))
        self.assertIn("admin", i18n["views"])


class AdminApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.plugin, cls.context = astrbot_stub.load_plugin(Path(cls.tmp.name), {})
        cls.api = cls.plugin.admin_api
        import importlib
        cls.ApiError = importlib.import_module(f"{PLUGIN_DIR.name}.webui.admin_api").ApiError
        for uid, name in (("1001", "甲"), ("1002", "乙")):
            cls.plugin.user_service.register(uid, name)

    @classmethod
    def tearDownClass(cls):
        run(cls.plugin.terminate())
        cls.tmp.cleanup()

    def call(self, fn, query=None, body=None):
        return run(self.api.call(fn, query or {}, body or {}))

    def test_routes_are_prefixed_with_plugin_name(self):
        routes = [r[0] for r in self.context.registered_web_apis]
        self.assertTrue(routes)
        self.assertTrue(all(r.startswith("/astrbot_plugin_fishing/") for r in routes))
        self.assertEqual(len(routes), len(set(routes)))

    def test_fresh_database_has_gacha_items_and_no_wipe_bomb_content(self):
        pools = self.call(self.api.gacha_list)["rows"]
        self.assertGreater(sum(p["item_count"] for p in pools), 0)
        titles = {t["name"] for t in self.call(self.api.titles_list)["rows"]}
        for name in ("擦弹之王", "Lucky☆Star", "杂鱼~杂鱼~"):
            self.assertNotIn(name, titles)
        items = {i["name"] for i in self.call(self.api.catalog)["item"]}
        self.assertNotIn("擦弹许可证", items)

    def test_user_currency_modes(self):
        self.call(self.api.user_currency, body={"user_id": "1001", "currency": "coins", "mode": "set", "amount": 500})
        self.call(self.api.user_currency, body={"user_id": "1001", "currency": "coins", "mode": "add", "amount": 250})
        self.assertEqual(self.plugin.user_repo.get_by_id("1001").coins, 750)
        self.call(self.api.user_currency, body={"user_id": "1001", "currency": "coins", "mode": "subtract", "amount": 99999})
        self.assertEqual(self.plugin.user_repo.get_by_id("1001").coins, 0)
        with self.assertRaises(self.ApiError):
            self.call(self.api.user_currency, body={"user_id": "nobody", "currency": "coins", "mode": "add", "amount": 1})

    def test_broadcast_skips_system_accounts(self):
        before = {uid: self.plugin.user_repo.get_by_id(uid) for uid in ("MARKET",)}
        result = self.call(self.api.broadcast_currency, body={"currency": "premium_currency", "mode": "add", "amount": 7})
        self.assertEqual(result["affected"], 2)
        for uid, user in before.items():
            after = self.plugin.user_repo.get_by_id(uid)
            if user:
                self.assertEqual(after.premium_currency, user.premium_currency)

    def test_zone_create_keeps_specific_fish(self):
        fish = [f["id"] for f in self.call(self.api.catalog)["fish"][:3]]
        self.call(self.api.zone_save, body={
            "is_new": "1", "id": 42, "name": "测试区", "fishing_cost": 5, "daily_rare_fish_quota": 1,
            "rarity_distribution": [0.5, 0.3, 0.15, 0.04, 0.01, 0], "specific_fish_ids": fish,
        })
        zone = next(z for z in self.call(self.api.zones_list)["rows"] if z["id"] == 42)
        self.assertEqual(sorted(zone["specific_fish_ids"]), sorted(fish))
        with self.assertRaises(self.ApiError):
            self.call(self.api.zone_save, body={"id": 42, "name": "x", "rarity_distribution": [1, 1, 0, 0, 0, 0]})
        self.call(self.api.zone_delete, body={"id": 42})

    def test_template_validation_and_csv_import(self):
        with self.assertRaises(self.ApiError):
            self.call(self.api.template_save, body={"kind": "fish", "data": {"name": "坏鱼", "min_weight": 10, "max_weight": 1}})
        result = self.call(self.api.template_import, body={
            "kind": "fish", "csv": "﻿name,rarity,base_value,min_weight,max_weight\n导入鱼,2,30,10,20\n,1,1,1,1\n",
        })
        self.assertEqual((result["imported"], result["failed"]), (1, 1))
        with self.assertRaises(self.ApiError):
            self.call(self.api.template_import, body={"kind": "fish", "csv": "name\nx\n"})

    def test_template_in_use_cannot_be_deleted(self):
        self.plugin.user_service.add_item_to_user_inventory("1002", "bait", 1, 2)
        with self.assertRaises(self.ApiError) as ctx:
            self.call(self.api.template_delete, body={"kind": "baits", "id": 1})
        self.assertIn("玩家鱼饵", str(ctx.exception))
        self.call(self.api.template_save, body={"kind": "items", "data": {"name": "临时道具"}})
        item_id = next(i["id"] for i in self.call(self.api.catalog)["item"] if i["name"] == "临时道具")
        self.call(self.api.template_delete, body={"kind": "items", "id": item_id})

    def test_shop_item_with_costs_and_rewards(self):
        shop = self.call(self.api.shop_save, body={"name": "测试店", "shop_type": "normal"})["shop"]
        saved = self.call(self.api.shop_item_save, body={
            "shop_id": shop["shop_id"], "name": "礼包",
            "costs": [{"cost_type": "coins", "cost_amount": 10, "cost_relation": "and"},
                      {"cost_type": "fish", "cost_item_id": 1, "cost_amount": 2, "cost_relation": "or", "group_id": 1}],
            "rewards": [{"reward_type": "rod", "reward_item_id": 1, "reward_quantity": 1, "reward_refine_level": 3}],
        })
        rows = self.call(self.api.shop_items, query={"shop_id": shop["shop_id"]})["rows"]
        row = next(r for r in rows if r["item"]["item_id"] == saved["item_id"])
        self.assertEqual(len(row["costs"]), 2)
        self.assertEqual(row["rewards"][0]["reward_refine_level"], 3)
        with self.assertRaises(self.ApiError):
            self.call(self.api.shop_item_save, body={"shop_id": shop["shop_id"], "name": "空", "rewards": []})
        self.call(self.api.shop_delete, body={"shop_id": shop["shop_id"]})

    def test_transfer_charges_fee_without_bank_or_tax(self):
        self.assertFalse(hasattr(self.plugin, "bank_service"))
        self.assertNotIn("tax", self.plugin.game_config)
        self.call(self.api.user_currency, body={"user_id": "1001", "currency": "coins", "mode": "set", "amount": 1000})
        before = self.plugin.user_repo.get_by_id("1002").coins
        result = self.plugin.user_service.transfer_coins("1001", "1002", 100)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.plugin.user_repo.get_by_id("1001").coins, 895)
        self.assertEqual(self.plugin.user_repo.get_by_id("1002").coins, before + 100)
        routes = {r[0] for r in self.api.routes()}
        self.assertFalse({"bank", "tax", "tax/save", "exchange", "exchange/update"} & routes)

    def test_market_rejects_commodity_listings(self):
        self.assertFalse(hasattr(self.plugin, "exchange_service"))
        result = self.plugin.market_service.put_item_on_sale("1001", "commodity", 1, 100)
        self.assertFalse(result["success"])
        with self.assertRaises(self.ApiError):
            self.call(self.api.market_list, query={"item_type": "commodity"})

    def test_impersonation_maps_sender_to_player(self):
        self.call(self.api.impersonation_start, body={"admin_id": "9", "target_id": "1002"})

        class Event:
            def get_sender_id(self):
                return "9"

        self.assertEqual(self.plugin._get_effective_user_id(Event()), "1002")
        self.call(self.api.impersonation_stop, body={"admin_id": "9"})
        self.assertEqual(self.plugin._get_effective_user_id(Event()), "9")

    def test_every_read_endpoint_serializes(self):
        for name, query in (
            ("overview", {}), ("users", {}), ("market", {}),
            ("shops", {}), ("gacha", {}), ("zones", {}), ("titles", {}), ("meta", {}),
            ("templates", {"kind": "rods"}), ("users/inventory", {"user_id": "1001"}), ("users/detail", {"user_id": "1001"}),
        ):
            fn = next(r[2] for r in self.api.routes() if r[0] == name and r[1] == "GET")
            json.dumps(self.call(fn, query=query), ensure_ascii=False)


class DatabaseSchemaTests(unittest.TestCase):
    LEGACY_TABLES = {
        "bank_accounts", "bank_fixed_deposits", "bank_transactions", "bank_withdraw_reservations",
        "tax_debts", "taxes", "commodities", "exchange_prices", "user_commodities",
        "loans", "red_packets", "red_packet_records", "wipe_bomb_log",
    }

    def setUp(self):
        astrbot_stub.install(Path(tempfile.mkdtemp()))
        import importlib
        import sys
        sys.path.insert(0, str(PLUGIN_DIR.parent))
        self.migration = importlib.import_module(f"{PLUGIN_DIR.name}.core.database.migration")
        self.migrations_dir = str(PLUGIN_DIR / "core" / "database" / "migrations")
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.tmp.name) / "fish.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_schema_script(self):
        scripts = sorted(p.name for p in (PLUGIN_DIR / "core" / "database" / "migrations").glob("[0-9][0-9][0-9]_*.py"))
        self.assertEqual(scripts, ["001_initial_schema.py"])

    def test_fresh_database_has_no_legacy_tables_or_columns(self):
        self.migration.run_migrations(str(self.db), self.migrations_dir)
        conn = sqlite3.connect(self.db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertFalse(tables & self.LEGACY_TABLES)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        for name in columns:
            self.assertFalse(re.search(r"wipe_bomb|wof_|wheel_of_fate|sicbo|exchange", name), name)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM fishing_zones").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT version FROM schema_version").fetchone()[0], 1)
        conn.close()
        # 再跑一次不会把自己当成旧库
        self.assertIsNone(self.migration.retire_legacy_database(str(self.db)))

    def test_legacy_database_is_set_aside(self):
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL PRIMARY KEY);
            INSERT INTO schema_version VALUES (51);
            CREATE TABLE users (user_id TEXT PRIMARY KEY, coins INTEGER);
            INSERT INTO users VALUES ('old', 5);
        """)
        conn.close()
        self.migration.run_migrations(str(self.db), self.migrations_dir)
        backups = list(Path(self.tmp.name).glob("fish.db.legacy-*"))
        self.assertEqual(len([b for b in backups if not b.name.endswith(("-wal", "-shm"))]), 1)
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT value FROM db_meta WHERE key = 'schema'").fetchone()[0], "fishing-1.0")
        conn.close()


if __name__ == "__main__":
    unittest.main()
