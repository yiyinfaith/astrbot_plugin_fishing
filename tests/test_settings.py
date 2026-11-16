"""数值配置：默认值与原来写死的数值一致，自定义值生效，写错时回退到默认值。"""

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

import astrbot_stub

PLUGIN_DIR = Path(__file__).resolve().parents[1]

# 原来写在代码里的精炼表：星级 -> (费用倍率, 精炼到 2～10 级的成功率)
OLD_REFINE = {
    1: (0.10, [0.95, 0.90, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50]),
    2: (0.15, [0.95, 0.90, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50]),
    3: (0.20, [0.90, 0.85, 0.85, 0.80, 0.75, 0.65, 0.55, 0.45, 0.35]),
    4: (0.25, [0.85, 0.80, 0.80, 0.75, 0.70, 0.60, 0.50, 0.40, 0.30]),
    5: (0.50, [0.85, 0.80, 0.75, 0.65, 0.50, 0.40, 0.35, 0.30, 0.25]),
    6: (0.70, [0.80, 0.75, 0.70, 0.60, 0.45, 0.35, 0.30, 0.25, 0.20]),
    8: (1.00, [0.8, 0.8, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]),
}
OLD_BASE_COSTS = [10000, 30000, 50000, 100000, 200000, 500000, 1000000, 2000000, 5000000]


def run(coro):
    return asyncio.run(coro)


class SettingsParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        astrbot_stub.install(Path(tempfile.mkdtemp()))
        sys.path.insert(0, str(PLUGIN_DIR.parent))
        cls.s = importlib.import_module(f"{PLUGIN_DIR.name}.core.game_settings")

    def test_default_refine_tables_match_previous_values(self):
        refine = self.s.build_refine({})
        for rarity, (multiplier, rates) in OLD_REFINE.items():
            costs, success = self.s.refine_tables_for_rarity(refine, rarity)
            self.assertEqual(costs, {i + 1: int(c * multiplier) for i, c in enumerate(OLD_BASE_COSTS)}, rarity)
            self.assertEqual(success, {i + 2: r for i, r in enumerate(rates)}, rarity)

    def test_bad_values_fall_back_to_defaults(self):
        refine = self.s.build_refine({"base_costs": "1,2,3", "success_rates_5": "abc"})
        self.assertEqual(refine["base_costs"][1], 10000)
        self.assertEqual(refine["success_rates"]["r5"][2], 0.85)
        self.assertEqual(self.s.build_pond_upgrades({"capacities": "500,400", "upgrade_costs": "1"})[0],
                         {"from": 480, "to": 1000, "cost": 20000})
        self.assertEqual(self.s.build_signin({"min_reward": 500, "max_reward": 100}), {"min_reward": 100, "max_reward": 500})
        rules = self.s.build_fishing_rules({"base_success_rate": 5, "mythic_weights": "0,0,0"})
        self.assertEqual(rules, {"base_success_rate": 0.7, "mythic_weights": {6: 15, 7: 4, 8: 1}})
        # 中文逗号也能识别
        self.assertEqual(self.s.parse_numbers("1，2", "9", "x", integer=True), [1, 2])


class CustomSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.plugin, _ = astrbot_stub.load_plugin(Path(cls.tmp.name), {
            "fishing": {"base_success_rate": 1.0, "mythic_weights": "0,0,1"},
            "signin": {"min_reward": 7, "max_reward": 7},
            "pond": {"capacities": "100,300", "upgrade_costs": "50"},
            "electric_fish": {"max_catch": 3, "base_success_rate": 1.0},
        })
        cls.plugin.fishing_service.stop_auto_fishing_task()

    @classmethod
    def tearDownClass(cls):
        run(cls.plugin.terminate())
        cls.tmp.cleanup()

    def test_custom_values_apply(self):
        p = self.plugin
        p.user_service.register("a", "甲")
        user = p.user_repo.get_by_id("a")
        self.assertEqual(user.fish_pond_capacity, 100)
        self.assertIn("获得 7 金币", p.user_service.daily_sign_in("a")["message"])

        info = p.inventory_service.get_user_fish_pond_capacity("a")
        self.assertEqual((info["next_capacity"], info["next_cost"]), (300, 50))
        self.assertTrue(p.inventory_service.upgrade_fish_pond("a")["success"])
        self.assertEqual(p.user_repo.get_by_id("a").fish_pond_capacity, 300)
        self.assertFalse(p.inventory_service.upgrade_fish_pond("a")["success"])

        zone = p.inventory_repo.get_zone_by_id(3)
        self.assertEqual({p.fishing_service._get_random_high_rarity(zone) for _ in range(50)}, {8})
        result = p.fishing_service.go_fish("a")
        self.assertTrue(result["success"], result)

        p.user_service.register("b", "乙")
        p.inventory_repo.add_fish_to_inventory("b", 1, 200)
        stolen = p.game_mechanics_service.electric_fish("a", "b")
        self.assertTrue(stolen["success"], stolen)
        self.assertIn("捕获了3条鱼", stolen["message"])


if __name__ == "__main__":
    unittest.main()
