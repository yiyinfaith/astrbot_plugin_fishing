"""1.0.0 规则调整的回归测试：刷钱漏洞、区域门槛、通行证续期、自动钓鱼效率等。"""

import asyncio
import shutil
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import astrbot_stub

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PASS_NAME = "前往神秘海域的通行证"


def run(coro):
    return asyncio.run(coro)


class GameRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.plugin, _ = astrbot_stub.load_plugin(Path(cls.tmp.name), {})
        cls.plugin.fishing_service.stop_auto_fishing_task()
        cls.templates = cls.plugin.item_template_repo
        cls.inventory = cls.plugin.inventory_repo

    @classmethod
    def tearDownClass(cls):
        run(cls.plugin.terminate())
        cls.tmp.cleanup()

    _next_uid = 2000

    def new_user(self, coins=0):
        GameRuleTests._next_uid += 1
        uid = str(GameRuleTests._next_uid)
        self.plugin.user_service.register(uid, f"玩家{uid}")
        user = self.plugin.user_repo.get_by_id(uid)
        user.coins = coins
        self.plugin.user_repo.update(user)
        return uid

    def coins(self, uid):
        return self.plugin.user_repo.get_by_id(uid).coins

    def shop_item(self, name):
        for item in self.plugin.shop_repo.get_shop_items(1):
            if item["name"] == name:
                return item["item_id"]
        raise AssertionError(name)

    def template_id(self, getter, name, field):
        return next(getattr(t, field) for t in getter() if t.name == name)

    def give_and_equip_rod(self, uid, name):
        rod_id = self.template_id(self.templates.get_all_rods, name, "rod_id")
        self.plugin.user_service.add_item_to_user_inventory(uid, "rod", rod_id, 1)
        instance = max(self.inventory.get_user_rod_instances(uid), key=lambda r: r.rod_instance_id)
        result = self.plugin.inventory_service.equip_item(uid, instance.rod_instance_id, "rod")
        self.assertTrue(result["success"], result)

    def pass_count(self, uid):
        pass_id = self.template_id(self.templates.get_all_items, PASS_NAME, "item_id")
        return self.inventory.get_user_item_inventory(uid).get(pass_id, 0)

    # 1. 买鱼竿再卖给系统不能赚钱
    def test_shop_rod_resale_is_not_profitable(self):
        uid = self.new_user(coins=5000)
        result = self.plugin.shop_service.purchase_item(uid, self.shop_item("新手木竿"), 10)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.coins(uid), 4500)
        # 送的那根已装备，不会被一起卖掉
        self.plugin.inventory_service.sell_all_rods(uid)
        self.assertEqual(self.coins(uid), 4750)

    # 2. 卡池的金币奖励低于单抽价格，每日补给池有内容
    def test_gacha_coin_rewards_are_below_cost(self):
        for pool in self.plugin.gacha_repo.get_all_pools():
            items = self.plugin.gacha_repo.get_pool_items(pool.gacha_pool_id)
            self.assertTrue(items, pool.name)
            for item in items:
                if item.item_type == "coins" and pool.cost_coins:
                    self.assertLess(item.quantity, pool.cost_coins, pool.name)

    def test_daily_supply_is_once_per_day_without_draw_history(self):
        from concurrent.futures import ThreadPoolExecutor
        from datetime import date
        from unittest.mock import patch

        uid = self.new_user()
        gacha = self.plugin.gacha_service
        pool_id = gacha.get_daily_free_pool().gacha_pool_id
        with patch(f"{PLUGIN_DIR.name}.core.services.gacha_service.get_today", return_value=date(2026, 11, 18)):
            self.assertFalse(gacha.perform_draw(uid, pool_id, 10)["success"])
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: gacha.perform_draw(uid, pool_id), range(2)))
            self.assertEqual(sum(result["success"] for result in results), 1)
        with patch(f"{PLUGIN_DIR.name}.core.services.gacha_service.get_today", return_value=date(2026, 11, 19)):
            with patch.object(gacha, "_grant_reward", side_effect=RuntimeError("reward failed")):
                with self.assertRaisesRegex(RuntimeError, "reward failed"):
                    gacha.perform_draw(uid, pool_id)
            self.assertTrue(gacha.perform_draw(uid, pool_id)["success"])
        with sqlite3.connect(self.plugin.gacha_repo.db_path) as conn:
            self.assertEqual(
                conn.execute("SELECT gacha_pool_id, claim_date FROM daily_supply_claims WHERE user_id = ?", (uid,)).fetchall(),
                [(pool_id, "2026-11-19")],
            )

    def test_sign_in_rolls_back_and_only_one_concurrent_claim_credits_coins(self):
        uid = self.new_user(coins=100)
        user_service = self.plugin.user_service
        with patch.object(self.plugin.log_repo, "add_check_in", side_effect=RuntimeError("check-in failed")):
            with self.assertRaisesRegex(RuntimeError, "check-in failed"):
                user_service.daily_sign_in(uid)
        self.assertEqual(self.coins(uid), 100)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(user_service.daily_sign_in, (uid, uid)))
        success, = [result for result in results if result["success"]]
        self.assertEqual(self.coins(uid), 100 + success["coins_reward"] + success["bonus_coins"])

    def test_paid_draw_rolls_back_currency_and_previously_granted_rewards(self):
        uid = self.new_user(coins=100_000)
        pool = next(pool for pool in self.plugin.gacha_repo.get_all_pools() if pool.cost_coins)
        gacha = self.plugin.gacha_service
        original = gacha._grant_reward
        grants = 0

        def fail_after_first(*args):
            nonlocal grants
            grants += 1
            if grants == 2:
                raise RuntimeError("reward failed")
            return original(*args)

        before = self.plugin.user_service.get_user_inventory_for_admin(uid)
        with patch.object(gacha, "_grant_reward", side_effect=fail_after_first):
            with self.assertRaisesRegex(RuntimeError, "reward failed"):
                gacha.perform_draw(uid, pool.gacha_pool_id, 10)
        self.assertEqual(grants, 2)
        self.assertEqual(self.coins(uid), 100_000)
        self.assertEqual(self.plugin.user_service.get_user_inventory_for_admin(uid), before)

    def test_shop_rolls_back_items_coins_and_stock_on_record_failure(self):
        uid = self.new_user(coins=1000)
        item_id = self.shop_item("新手木竿")
        shop = self.plugin.shop_repo
        stock_sold = shop.get_shop_item_by_id(item_id)["stock_sold"]
        with patch.object(shop, "add_purchase_record", side_effect=RuntimeError("record failed")):
            with self.assertRaisesRegex(RuntimeError, "record failed"):
                self.plugin.shop_service.purchase_item(uid, item_id, 2)
        self.assertEqual(self.coins(uid), 1000)
        self.assertEqual(len(self.inventory.get_user_rod_instances(uid)), 1)
        self.assertEqual(shop.get_shop_item_by_id(item_id)["stock_sold"], stock_sold)

    def test_shop_combines_coin_choice_and_both_fish_qualities_and_grants_all_equipment(self):
        uid = self.new_user(coins=1000)
        fish_id = self.templates.get_all_fish()[0].fish_id
        rod_id = self.templates.get_all_rods()[0].rod_id
        shop = self.plugin.shop_repo
        offer_id = shop.create_shop_item(1, {"name": "品质兑换测试"})["item_id"]
        self.addCleanup(shop.delete_shop_item, offer_id)
        for row in (
            {"cost_type": "fish", "cost_item_id": fish_id, "cost_amount": 1, "quality_level": 0},
            {"cost_type": "fish", "cost_item_id": fish_id, "cost_amount": 1, "quality_level": 1},
            {"cost_type": "coins", "cost_amount": 10, "group_id": 1, "cost_relation": "or"},
            {"cost_type": "rod", "cost_item_id": rod_id, "cost_amount": 1, "group_id": 1, "cost_relation": "or"},
        ):
            shop.add_item_cost(offer_id, row)
        shop.add_item_reward(offer_id, {"reward_type": "rod", "reward_item_id": rod_id, "reward_quantity": 2})
        self.inventory.add_fish_to_inventory(uid, fish_id, 1, 0)
        self.inventory.add_fish_to_aquarium(uid, fish_id, 1, 1)
        result = self.plugin.shop_service.purchase_item(uid, offer_id)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.coins(uid), 990)
        self.assertEqual(len(self.inventory.get_user_rod_instances(uid)), 3)
        self.assertEqual(self.inventory.get_fish_inventory(uid), [])
        self.assertEqual(self.inventory.get_aquarium_inventory(uid), [])

    def test_shop_can_choose_a_fish_exchange_to_make_room_in_full_aquarium(self):
        uid = self.new_user(coins=100)
        source, reward = self.templates.get_all_fish()[:2]
        user = self.plugin.user_repo.get_by_id(uid)
        user.aquarium_capacity = 1
        self.plugin.user_repo.update(user)
        self.inventory.add_fish_to_aquarium(uid, source.fish_id, 1)
        shop = self.plugin.shop_repo
        offer = shop.create_shop_item(1, {"name": "容量兑换测试"})["item_id"]
        self.addCleanup(shop.delete_shop_item, offer)
        shop.add_item_cost(offer, {"cost_type": "coins", "cost_amount": 10, "group_id": 1, "cost_relation": "or"})
        shop.add_item_cost(offer, {"cost_type": "fish", "cost_item_id": source.fish_id, "cost_amount": 1, "group_id": 1, "cost_relation": "or"})
        shop.add_item_reward(offer, {"reward_type": "fish", "reward_item_id": reward.fish_id, "reward_quantity": 1})
        result = self.plugin.shop_service.purchase_item(uid, offer)
        self.assertTrue(result["success"], result)
        self.assertEqual(self.coins(uid), 100)
        fish, = self.inventory.get_aquarium_inventory(uid)
        self.assertEqual((fish.fish_id, fish.quantity), (reward.fish_id, 1))

    def test_market_failure_rolls_back_then_only_one_buyer_can_settle(self):
        seller = self.new_user(coins=100)
        buyers = [self.new_user(coins=100) for _ in range(2)]
        item = self.templates.get_all_items()[0]
        self.inventory.update_item_quantity(seller, item.item_id, 1)
        service = self.plugin.market_service
        self.assertTrue(service.put_item_on_sale(seller, "item", item.item_id, 50)["success"])
        seller_after_fee = 100 - int(50 * service.config["market"]["listing_tax_rate"])
        listing = next(row for row in self.plugin.market_repo.get_all_listings()[0] if row.user_id == seller)
        with patch.object(self.plugin.market_repo, "remove_listing", side_effect=RuntimeError("listing failed")):
            with self.assertRaisesRegex(RuntimeError, "listing failed"):
                service.buy_market_item(buyers[0], listing.market_id)
        self.assertEqual(self.coins(seller), seller_after_fee)
        self.assertEqual([self.coins(buyer) for buyer in buyers], [100, 100])
        self.assertEqual(self.inventory.get_user_item_inventory(buyers[0]), {})
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda buyer: service.buy_market_item(buyer, listing.market_id), buyers))
        self.assertEqual(sum(bool(result["success"]) for result in results), 1)
        self.assertEqual(self.coins(seller), seller_after_fee + 50)
        self.assertEqual(sorted(self.coins(buyer) for buyer in buyers), [50, 100])
        self.assertEqual(sum(self.inventory.get_user_item_inventory(buyer).get(item.item_id, 0) for buyer in buyers), 1)

    def test_market_expiration_prevents_purchase_and_returns_inventory(self):
        from datetime import timedelta
        from importlib import import_module

        market_module = import_module(f"{PLUGIN_DIR.name}.core.services.market_service")
        seller = self.new_user(coins=100)
        buyer = self.new_user(coins=100)
        item = self.templates.get_all_items()[0]
        self.inventory.update_item_quantity(seller, item.item_id, 1)
        service = self.plugin.market_service
        with patch.object(market_module, "get_now", return_value=market_module.get_now() - timedelta(days=6)):
            self.assertTrue(service.put_item_on_sale(seller, "item", item.item_id, 50)["success"])
        listing = next(row for row in self.plugin.market_repo.get_all_listings()[0] if row.user_id == seller)
        result = service.buy_market_item(buyer, listing.market_id)
        self.assertFalse(result["success"])
        self.assertIn("过期", result["message"])
        self.assertEqual(self.coins(buyer), 100)
        self.assertEqual(self.inventory.get_user_item_inventory(seller)[item.item_id], 1)
        self.assertIsNone(self.plugin.market_repo.get_listing_by_id(listing.market_id))

    def test_aquarium_transfer_does_not_lose_fish_and_respects_pond_capacity(self):
        uid = self.new_user()
        fish = self.templates.get_all_fish()[0]
        user = self.plugin.user_repo.get_by_id(uid)
        user.fish_pond_capacity = 2
        self.plugin.user_repo.update(user)
        self.inventory.add_fish_to_inventory(uid, fish.fish_id, 2, 1)
        service = self.plugin.aquarium_service
        with patch.object(self.inventory, "add_fish_to_aquarium", side_effect=RuntimeError("transfer failed")):
            with self.assertRaisesRegex(RuntimeError, "transfer failed"):
                service.add_fish_to_aquarium(uid, fish.fish_id, 1, 1)
        self.assertEqual(self.inventory.get_fish_inventory(uid)[0].quantity, 2)
        self.assertTrue(service.add_fish_to_aquarium(uid, fish.fish_id, 1, 1)["success"])
        self.inventory.add_fish_to_inventory(uid, fish.fish_id, 1, 0)
        self.assertFalse(service.remove_fish_from_aquarium(uid, fish.fish_id, 1, 1)["success"])
        self.assertEqual(self.inventory.get_aquarium_inventory(uid)[0].quantity, 1)

    def test_manual_and_auto_cast_share_cooldown_and_charge_first_disposable_bait(self):
        uid = self.new_user(coins=100)
        bait = next(bait for bait in self.templates.get_all_baits() if not bait.duration_minutes and not bait.required_rod_rarity)
        self.inventory.update_bait_quantity(uid, bait.bait_id, 2)
        self.plugin.user_repo.set_auto_fishing_enabled(uid, True)
        with patch(f"{PLUGIN_DIR.name}.core.services.fishing_service.random.random", return_value=0.9999):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda auto: self.plugin.fishing_service.go_fish(uid, auto=auto), (False, True)))
        self.assertEqual(sum("fishing_cost" in result for result in results), 1)
        self.assertEqual(self.coins(uid), 90)
        self.assertEqual(self.inventory.get_user_bait_inventory(uid)[bait.bait_id], 1)

    def test_multiple_catches_update_pokedex_count_and_total_weight(self):
        from importlib import import_module

        get_now = import_module(f"{PLUGIN_DIR.name}.core.utils").get_now
        uid = self.new_user(coins=100)
        fish = self.templates.get_all_fish()[0]
        self.assertTrue(self.inventory.settle_fishing_catch(
            user_id=uid, fish_id=fish.fish_id, total_catches=3, quality_level=0,
            weight=100, earned_value=fish.base_value * 3, fishing_cost=10,
            fish_pond_capacity=480, timestamp=get_now(),
        ))
        user = self.plugin.user_repo.get_by_id(uid)
        stat = self.plugin.log_repo.get_user_fish_stat(uid, fish.fish_id)
        self.assertEqual((user.total_fishing_count, user.total_weight_caught), (3, 300))
        self.assertEqual((stat.total_caught, stat.total_weight, stat.max_weight, stat.min_weight), (3, 300, 100, 100))

    def test_electric_fishing_preserves_high_quality_and_total_fish_count(self):
        victim = self.new_user(coins=100)
        thief = self.new_user(coins=100)
        fish = next(fish for fish in self.templates.get_all_fish() if fish.rarity < 5)
        self.inventory.add_fish_to_inventory(victim, fish.fish_id, 100, 1)
        with patch(f"{PLUGIN_DIR.name}.core.services.game_mechanics_service.random.random", return_value=0.1):
            result = self.plugin.game_mechanics_service.electric_fish(thief, victim)
        self.assertTrue(result["success"], result)
        caught, = self.inventory.get_fish_inventory(thief)
        remaining, = self.inventory.get_fish_inventory(victim)
        self.assertEqual((caught.quality_level, remaining.quality_level), (1, 1))
        self.assertEqual(caught.quantity + remaining.quantity, 100)

    def test_open_all_money_bags_keeps_invalid_stack_and_consumes_working_ones(self):
        uid = self.new_user(coins=100)
        bag = next(item for item in self.templates.get_all_items() if item.effect_type == "ADD_COINS")
        self.inventory.update_item_quantity(uid, bag.item_id, 2)
        getter = self.templates.get_item_by_id
        with patch.object(self.templates, "get_item_by_id", side_effect=lambda item_id: replace(getter(item_id), effect_payload="[]")):
            failed = self.plugin.inventory_service.open_all_money_bags(uid)
        self.assertFalse(failed["success"])
        self.assertEqual(self.inventory.get_user_item_inventory(uid)[bag.item_id], 2)
        self.assertEqual(self.coins(uid), 100)
        success = self.plugin.inventory_service.open_all_money_bags(uid)
        self.assertEqual(success["opened_bags"], 2)
        self.assertEqual(self.coins(uid), 100 + success["total_gained"])
        self.assertNotIn(bag.item_id, self.inventory.get_user_item_inventory(uid))

    def test_cast_item_only_consumes_for_casts_that_could_take_place(self):
        uid = self.new_user(coins=10)
        item = next(item for item in self.templates.get_all_items() if item.effect_type == "RESET_FISHING_COOLDOWN")
        self.inventory.update_item_quantity(uid, item.item_id, 2)
        with patch(f"{PLUGIN_DIR.name}.core.services.fishing_service.random.random", return_value=0.9999):
            result = self.plugin.inventory_service.use_item(uid, item.item_id, 2)
        self.assertEqual(result["quantity_used"], 1)
        self.assertEqual(self.inventory.get_user_item_inventory(uid)[item.item_id], 1)
        self.assertEqual(self.coins(uid), 0)

    def test_refinement_prefers_unrestricted_shield_and_keeps_main_equipment(self):
        uid = self.new_user(coins=1_000_000)
        template = next(rod for rod in self.templates.get_all_rods() if rod.rarity == 3)
        target = self.inventory.add_rod_instance(uid, template.rod_id, template.durability, 6)
        self.inventory.add_rod_instance(uid, template.rod_id, template.durability)
        shields = [item for item in self.templates.get_all_items() if item.effect_type == "REFINE_DESTRUCTION_SHIELD"]
        limited = next(item for item in shields if "max_rarity" in item.effect_payload and '"keep"' in item.effect_payload)
        unlimited = next(item for item in shields if "max_rarity" not in item.effect_payload and '"keep"' in item.effect_payload)
        self.inventory.update_item_quantity(uid, limited.item_id, 1)
        self.inventory.update_item_quantity(uid, unlimited.item_id, 1)
        original = self.templates.get_all_items

        def templates_with_null_limit():
            return [
                replace(item, effect_payload='{"mode":"keep","max_rarity":null}')
                if item.item_id == unlimited.item_id else item
                for item in original()
            ]

        service = self.plugin.inventory_service
        with (
            patch.object(self.templates, "get_all_items", side_effect=templates_with_null_limit),
            patch.object(service, "_determine_failure_type", return_value="destruction"),
            patch(f"{PLUGIN_DIR.name}.core.services.inventory_service.random.random", return_value=0.9999),
        ):
            result = service.refine(uid, target.rod_instance_id, "rod")
        self.assertTrue(result["failed"])
        self.assertFalse(result["destroyed"])
        self.assertEqual(self.inventory.get_user_rod_instance_by_id(uid, target.rod_instance_id).refine_level, 6)
        self.assertEqual(self.inventory.get_user_item_inventory(uid).get(limited.item_id), 1)
        self.assertNotIn(unlimited.item_id, self.inventory.get_user_item_inventory(uid))

    # 3. 区域二要 2 星鱼竿，区域三要 3 星鱼竿和通行证
    def test_zone_gates(self):
        service = self.plugin.fishing_service
        uid = self.new_user(coins=100000)
        result = service.set_user_fishing_zone(uid, 2)
        self.assertFalse(result["success"])
        self.assertIn("2 星", result["message"])
        self.give_and_equip_rod(uid, "竹制鱼竿")
        self.assertTrue(service.set_user_fishing_zone(uid, 2)["success"])

        self.assertIn("3 星", service.set_user_fishing_zone(uid, 3)["message"])
        self.give_and_equip_rod(uid, "碳素纤维竿")
        self.assertIn("通行证", service.set_user_fishing_zone(uid, 3)["message"])
        self.assertTrue(self.plugin.shop_service.purchase_item(uid, self.shop_item(PASS_NAME), 2)["success"])
        self.assertEqual(self.coins(uid), 96000)
        # 进入时不消耗
        self.assertTrue(service.set_user_fishing_zone(uid, 3)["success"])
        self.assertEqual(self.pass_count(uid), 2)
        self.assertFalse(service.set_user_fishing_zone(uid, 3)["success"])

    # 3. 通行证在当天第一次钓鱼时消耗，当天有效；没有通行证这一竿不钓也不扣钱
    def test_pass_is_used_once_per_day(self):
        service = self.plugin.fishing_service
        uid = self.new_user(coins=100000)
        self.give_and_equip_rod(uid, "碳素纤维竿")
        self.plugin.shop_service.purchase_item(uid, self.shop_item(PASS_NAME), 1)
        self.assertTrue(service.set_user_fishing_zone(uid, 3)["success"])

        first = service.go_fish(uid)
        self.assertIn("已使用 1 个", "".join(first.get("notices", [])))
        self.assertEqual(self.pass_count(uid), 0)
        for _ in range(3):
            self.assertFalse(service.go_fish(uid).get("zone_requirement_failed"))
        self.assertEqual(self.pass_count(uid), 0)

        # 到了第二天：标记过期，背包里没有通行证
        with self.plugin.buff_repo._get_connection() as conn:
            conn.execute("UPDATE user_buffs SET expires_at = '2000-01-01 00:00:00' WHERE user_id = ?", (uid,))
            conn.commit()
        coins = self.coins(uid)
        blocked = service.go_fish(uid)
        self.assertTrue(blocked["zone_requirement_failed"])
        self.assertEqual(self.coins(uid), coins)

        # 自动钓鱼遇到这种情况会回到新手港湾继续钓
        user = self.plugin.user_repo.get_by_id(uid)
        user.last_fishing_time = None
        user.auto_fishing_enabled = True
        self.plugin.user_repo.update(user)
        service._process_auto_fishing_user(uid)
        self.assertEqual(self.plugin.user_repo.get_by_id(uid).fishing_zone_id, 1)

    # 10. 新手木竿永久耐久，注册时免费送并装备
    def test_starter_rod(self):
        uid = self.new_user()
        rods = self.inventory.get_user_rod_instances(uid)
        self.assertEqual(len(rods), 1)
        self.assertTrue(rods[0].is_equipped)
        self.assertIsNone(rods[0].current_durability)
        self.assertEqual(self.inventory.get_user_equipped_rod(uid).rod_instance_id, rods[0].rod_instance_id)

    # 4. 区域三有 6 星以上的概率，星级越高越难出
    def test_zone_three_can_yield_mythic_fish(self):
        zone = self.inventory.get_zone_by_id(3)
        dist = zone.configs["rarity_distribution"]
        self.assertEqual(len(dist), 6)
        self.assertGreater(dist[5], 0)
        self.assertAlmostEqual(sum(dist), 1.0)
        picks = [self.plugin.fishing_service._get_random_high_rarity(zone) for _ in range(4000)]
        self.assertGreater(picks.count(6), picks.count(7))
        self.assertGreater(picks.count(7), picks.count(8))
        self.assertGreater(picks.count(8), 0)

    # 5. 没有稀有鱼配额
    def test_no_rare_fish_quota(self):
        with self.inventory._connection_manager.get_connection() as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(fishing_zones)")}
        self.assertNotIn("daily_rare_fish_quota", columns)
        self.assertNotIn("rare_fish_caught_today", columns)
        uid = self.new_user(coins=1000)
        result = self.plugin.fishing_service.go_fish(uid)
        self.assertNotIn("zone_requirement_failed", result)
        self.assertIn("message" if not result["success"] else "fish", result)

    # 6 与 12. 自动钓鱼按效率放慢；冷却倍率来自饰品属性而不是名字
    def test_cooldowns(self):
        service = self.plugin.fishing_service
        uid = self.new_user()
        self.assertEqual(service.get_cooldown_seconds(uid), 180)
        self.assertEqual(service.get_cooldown_seconds(uid, auto=True), 360)
        heart = self.template_id(self.templates.get_all_accessories, "海洋之心", "accessory_id")
        self.plugin.user_service.add_item_to_user_inventory(uid, "accessory", heart, 1)
        instance = self.inventory.get_user_accessory_instances(uid)[0]
        self.plugin.inventory_service.equip_item(uid, instance.accessory_instance_id, "accessory")
        self.assertEqual(service.get_cooldown_seconds(uid), 90)
        self.assertEqual(service.get_cooldown_seconds(uid, auto=True), 180)

    def test_sign_in(self):
        uid = self.new_user()
        result = self.plugin.user_service.daily_sign_in(uid)
        self.assertTrue(result["success"], result)
        self.assertIn("每日补给", result["message"])
        self.assertGreaterEqual(self.coins(uid), 100)

    # 8. 没有商品的商店默认关闭
    def test_empty_shops_are_closed(self):
        for shop in self.plugin.shop_repo.get_all_shops():
            has_items = bool(self.plugin.shop_repo.get_shop_items(shop["shop_id"]))
            self.assertEqual(bool(shop["is_active"]), has_items, shop["name"])

    # 9. 电鱼失败的罚款有上限
    def test_electric_fish_penalty_is_capped(self):
        mechanics = self.plugin.game_mechanics_service
        thief, victim = self.new_user(coins=1_000_000), self.new_user()
        self.inventory.add_fish_to_inventory(victim, 1, 150)
        mechanics.config["electric_fish"]["base_success_rate"] = 0.0
        try:
            result = mechanics.electric_fish(thief, victim)
        finally:
            mechanics.config["electric_fish"]["base_success_rate"] = 0.6
        self.assertFalse(result["success"])
        self.assertGreaterEqual(self.coins(thief), 1_000_000 - 5000)

    # 审计：装备类商品一次最多买 100 件，避免长时间占住数据库
    def test_equipment_purchase_is_capped(self):
        uid = self.new_user(coins=1_000_000)
        offer = self.shop_item("新手木竿")
        self.assertFalse(self.plugin.shop_service.purchase_item(uid, offer, 101)["success"])
        self.assertTrue(self.plugin.shop_service.purchase_item(uid, offer, 100)["success"])

    # 审计：重复签到要有回复；参数里的数字过大不会让指令没反应
    def test_command_replies(self):
        uid = self.new_user()

        class Event:
            def __init__(self, text):
                self.message_str = text

            def get_sender_id(self):
                return uid

            def plain_result(self, text):
                return text

        async def say(method, text):
            return [r async for r in getattr(self.plugin, method)(Event(text))]

        self.assertIn("签到成功", run(say("sign_in", "钓鱼签到"))[0])
        self.assertIn("已经签到过了", run(say("sign_in", "钓鱼签到"))[0])
        self.assertIn("数字太大", run(say("view_gacha_pool", "查看卡池 99999999999999999999"))[0])

    def test_state_and_forwarded_backpack_render_their_information(self):
        from importlib import import_module
        from unittest.mock import AsyncMock, patch

        from PIL import ImageDraw

        uid = self.new_user()
        rod = next(rod for rod in self.templates.get_all_rods() if rod.name == "新手木竿")
        accessory = self.templates.get_all_accessories()[0]
        bait = next(bait for bait in self.templates.get_all_baits() if bait.name == "普通蚯蚓")
        item = self.templates.get_all_items()[0]
        for kind, item_id, quantity in (
            ("rod", rod.rod_id, 12), ("accessory", accessory.accessory_id, 1),
            ("bait", bait.bait_id, 5), ("item", item.item_id, 3),
        ):
            self.assertTrue(self.plugin.user_service.add_item_to_user_inventory(uid, kind, item_id, quantity)["success"])
        owned_accessory = self.inventory.get_user_accessory_instances(uid)[0]
        self.assertTrue(self.plugin.inventory_service.equip_item(uid, owned_accessory.accessory_instance_id, "accessory")["success"])
        self.assertTrue(self.plugin.inventory_service.use_bait(uid, bait.bait_id)["success"])

        class Event:
            def __init__(self, text):
                self.message_str = text

            def get_sender_id(self):
                return uid

            def get_self_id(self):
                return "123456"

            def get_platform_name(self):
                return "aiocqhttp"

            def plain_result(self, text):
                return text

            def chain_result(self, elements):
                return elements

        async def say(method, text):
            return [result async for result in method(Event(text))][0]

        text_calls = []
        draw_text = ImageDraw.ImageDraw.text

        def record_text(draw, xy, text, *args, **kwargs):
            text_calls.append(text)
            return draw_text(draw, xy, text, *args, **kwargs)

        state_draw = import_module(f"{PLUGIN_DIR.name}.draw.state")
        inventory_handlers = import_module(f"{PLUGIN_DIR.name}.handlers.inventory_handlers")
        with (
            patch.object(state_draw, "get_user_avatar", AsyncMock(return_value=None)),
            patch.object(inventory_handlers, "get_user_avatar", AsyncMock(return_value=None)),
            patch.object(ImageDraw.ImageDraw, "text", record_text),
        ):
            result = run(say(self.plugin.state, "钓鱼状态"))
            self.assertTrue(result[0].args[0].startswith(b"\x89PNG"))
            for expected in ("新手木竿", accessory.name, bait.name, "0 / 480", "下一档 1,000 条 · 20,000 金币"):
                self.assertIn(expected, "\n".join(text_calls))

            text_calls.clear()
            result = run(say(self.plugin.user_backpack, "钓鱼背包"))
            self.assertEqual(len(result), 1)
            nodes = result[0].args[0]
            self.assertEqual(len(nodes), 2)
            for node in nodes:
                self.assertEqual(node.kwargs["uin"], "123456")
                self.assertTrue(node.kwargs["content"][0].args[0].startswith(b"\x89PNG"))
            for expected in (accessory.name, f"ID: B{bait.bait_id}", f"ID: D{item.item_id}"):
                self.assertIn(expected, "\n".join(text_calls))
            for rod in self.plugin.inventory_service.get_user_rod_inventory(uid)["rods"]:
                self.assertIn(f"ID: {rod['display_code']}", text_calls)
            self.assertNotIn("页", "\n".join(text_calls))
            self.assertIn("查看全部物品", run(say(self.plugin.user_backpack, "钓鱼背包 2")))

    # 审计：指令写回玩家数据时不覆盖后台线程同时做的原子更新
    def test_user_update_keeps_concurrent_changes(self):
        from datetime import datetime
        uid = self.new_user(coins=1000)
        stale = self.plugin.user_repo.get_by_id(uid)
        # 后台自动钓鱼在这期间扣了一竿的钱
        fished_at = datetime(2030, 1, 1, 12, 0, 0)
        self.assertTrue(self.plugin.user_repo.record_failed_fishing(uid, 10, fished_at))
        stale.coins += 100
        stale.nickname = "新名字"
        self.plugin.user_repo.update(stale)
        fresh = self.plugin.user_repo.get_by_id(uid)
        self.assertEqual(fresh.coins, 1090)
        self.assertEqual(fresh.nickname, "新名字")
        self.assertEqual(fresh.last_fishing_time.replace(tzinfo=None), fished_at)
        # 同一个对象再次写回不会重复加钱
        self.plugin.user_repo.update(stale)
        self.assertEqual(self.plugin.user_repo.get_by_id(uid).coins, 1090)
        self.assertGreaterEqual(self.plugin.user_repo.get_by_id(uid).max_coins, 1090)

    # 10. 除了新手木竿，内置鱼竿都有耐久
    def test_rod_durability(self):
        for rod in self.templates.get_all_rods():
            if rod.name == "新手木竿":
                self.assertIsNone(rod.durability)
            else:
                self.assertGreater(rod.durability or 0, 0, rod.name)


class UpgradeMigrationTests(unittest.TestCase):
    """已有的 1.0.0 库升级后内置内容换成新数值，管理员改过的不动。"""

    def setUp(self):
        astrbot_stub.install(Path(tempfile.mkdtemp()))
        import importlib
        import sys
        sys.path.insert(0, str(PLUGIN_DIR.parent))
        self.migration = importlib.import_module(f"{PLUGIN_DIR.name}.core.database.migration")
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.tmp.name) / "fish.db"
        self.migrations_dir = PLUGIN_DIR / "core" / "database" / "migrations"

    def tearDown(self):
        self.tmp.cleanup()

    def test_upgrade_from_first_schema(self):
        only_first = Path(self.tmp.name) / "m1"
        only_first.mkdir()
        shutil.copy(self.migrations_dir / "001_initial_schema.py", only_first)
        self.migration.run_migrations(str(self.db), str(only_first))

        conn = sqlite3.connect(self.db)
        conn.executescript(f"""
            INSERT INTO rods (rod_id, name, rarity, source, durability) VALUES (1, '新手木竿', 1, 'shop', NULL),
                (5, '海神之赐', 5, 'gacha', NULL), (6, '自定义竿', 2, 'shop', NULL);
            INSERT INTO users (user_id, nickname) VALUES ('u', 'u'), ('v', 'v');
            INSERT INTO user_rods (user_id, rod_id, refine_level) VALUES ('u', 1, 2), ('u', 5, 10);
            INSERT INTO items (item_id, name, rarity, effect_description) VALUES (5, '{PASS_NAME}', 5, '进入特定钓鱼区域时自动消耗。');
            INSERT INTO items (item_id, name, rarity) VALUES (2, '幸运药水', 3);
            INSERT INTO baits (bait_id, name, rarity) VALUES (1, '普通蚯蚓', 1);
            INSERT INTO accessories (accessory_id, name, rarity) VALUES (4, '海洋之心', 5);
            INSERT INTO gacha_pools (gacha_pool_id, name, cost_coins) VALUES (1, '稀有鱼竿池', 5000), (2, '珍贵饰品池', 10000), (3, '每日补给池', 0);
            INSERT INTO gacha_pool_items (gacha_pool_id, item_type, item_id, quantity, weight) VALUES
                (1, 'coins', 0, 10000, 57), (2, 'coins', 0, 15000, 80);
            INSERT INTO shops (shop_id, name) VALUES (1, '海鸥港杂货铺'), (2, '七海珍宝阁');
        """)
        conn.commit()
        conn.close()

        self.migration.run_migrations(str(self.db), str(self.migrations_dir))
        conn = sqlite3.connect(self.db)
        q = lambda sql, *a: conn.execute(sql, a).fetchall()
        self.assertEqual(q("SELECT version FROM schema_version")[0][0], 3)
        self.assertEqual(dict(q("SELECT name, durability FROM rods")), {"新手木竿": None, "海神之赐": 3000, "自定义竿": None})
        self.assertEqual(sorted(q("SELECT rod_id, current_durability FROM user_rods WHERE user_id = 'u'")), [(1, None), (5, None)])
        self.assertEqual(q("SELECT quantity FROM gacha_pool_items WHERE gacha_pool_id = 1")[0][0], 2000)
        # 管理员改过的数量不动
        self.assertEqual(q("SELECT quantity FROM gacha_pool_items WHERE gacha_pool_id = 2")[0][0], 15000)
        self.assertEqual(len(q("SELECT 1 FROM gacha_pool_items WHERE gacha_pool_id = 3")), 2)
        self.assertEqual(q("SELECT cooldown_modifier FROM accessories WHERE name = '海洋之心'")[0][0], 0.5)
        self.assertEqual(q("SELECT is_active FROM shops WHERE shop_id = 2")[0][0], 0)
        offer = q("SELECT item_id FROM shop_items WHERE shop_id = 1 AND name = ?", PASS_NAME)
        self.assertEqual(len(offer), 1)
        self.assertEqual(q("SELECT cost_amount FROM shop_item_costs WHERE item_id = ?", offer[0][0])[0][0], 2000)
        zones = {r[0]: r[1:] for r in q("SELECT id, required_rod_rarity, requires_pass, required_item_id, configs, fishing_cost FROM fishing_zones")}
        self.assertEqual(zones[2][0], 2)
        self.assertEqual(zones[2][4], 50)
        self.assertEqual(zones[3][:3], (3, 1, 5))
        self.assertIn("0.48", zones[3][3])
        self.assertEqual(zones[3][4], 120)
        # 没有新手木竿的玩家补发一根并装备
        given = q("SELECT rod_instance_id, current_durability, is_equipped FROM user_rods WHERE user_id = 'v'")
        self.assertEqual([(g[1], g[2]) for g in given], [(None, 1)])
        self.assertEqual(q("SELECT equipped_rod_instance_id FROM users WHERE user_id = 'v'")[0][0], given[0][0])
        self.assertEqual(q("SELECT COUNT(*) FROM db_meta WHERE key = 'daily_reset_at'")[0][0], 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
