"""规则调整：取消稀有鱼每日配额，区域加鱼竿星级门槛，饰品冷却倍率改为属性。

新库的游戏内容由 DataSetupService 按 initial_data.py 写入，已经是新数值，这里只改结构和区域。
已有的库同时把内置内容改成新数值；只改仍是内置默认值的数据，管理员改过的保持不变。
"""

import json
import sqlite3

ZONE_PASS_NAME = "前往神秘海域的通行证"
ZONE_PASS_PRICE = 20000

# (区域ID, 原名称, 原描述, 新描述, 原分布, 新分布, 鱼竿星级要求)
ZONES = [
    (2, "区域二：深海峡谷", "4星鱼概率提升，有极小概率钓到5星鱼。",
     "4星鱼概率提升，有极小概率钓到5星鱼。需要装备2星及以上的鱼竿。",
     None, None, 2),
    (3, "区域三：传说之海", "5星鱼概率大幅提升。",
     "5星鱼概率大幅提升，还有极小概率遇到6～8星的神话鱼。需要通行证。",
     [0.3, 0.2, 0.2, 0.2, 0.1], [0.3, 0.2, 0.2, 0.2, 0.095, 0.005], 0),
]

# 原来无限耐久的内置鱼竿：(名称, 耐久)
ROD_DURABILITY = [("新手木竿", 200), ("竹制鱼竿", 500), ("星辰钓者", 2000), ("海神之赐", 3000)]

# 卡池金币奖励：(卡池ID, 原数量, 新数量)
GACHA_COINS = [(1, 10000, 2000), (2, 20000, 4000)]

# 每日补给池内容：(类型, 名称, 数量, 权重)
DAILY_POOL = [
    ("bait", "普通蚯蚓", 10, 30),
    ("bait", "红虫", 5, 25),
    ("bait", "活虾", 3, 15),
    ("bait", "万能饵", 2, 15),
    ("item", "幸运药水", 1, 10),
    ("item", "便携式声呐", 1, 5),
]

TEMPLATE_TABLES = {
    "rod": ("rods", "rod_id"),
    "accessory": ("accessories", "accessory_id"),
    "bait": ("baits", "bait_id"),
    "item": ("items", "item_id"),
}


def _id_by_name(cursor: sqlite3.Cursor, kind: str, name: str):
    table, id_field = TEMPLATE_TABLES[kind]
    row = cursor.execute(f"SELECT {id_field} FROM {table} WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def _update_zones(cursor: sqlite3.Cursor):
    for zone_id, name, old_desc, new_desc, old_dist, new_dist, rod_rarity in ZONES:
        row = cursor.execute(
            "SELECT name, description, configs FROM fishing_zones WHERE id = ?", (zone_id,)
        ).fetchone()
        if not row or row[0] != name:
            continue
        if row[1] == old_desc:
            cursor.execute("UPDATE fishing_zones SET description = ? WHERE id = ?", (new_desc, zone_id))
        if rod_rarity:
            cursor.execute("UPDATE fishing_zones SET required_rod_rarity = ? WHERE id = ?", (rod_rarity, zone_id))
        if old_dist is not None:
            try:
                dist = json.loads(row[2] or "{}").get("rarity_distribution")
            except ValueError:
                dist = None
            if dist == old_dist:
                cursor.execute(
                    "UPDATE fishing_zones SET configs = ? WHERE id = ?",
                    (json.dumps({"rarity_distribution": new_dist}), zone_id),
                )
    # 区域三需要通行证；新库这时还没有道具，由 DataSetupService 设置
    pass_id = _id_by_name(cursor, "item", ZONE_PASS_NAME)
    if pass_id is not None:
        cursor.execute(
            "UPDATE fishing_zones SET requires_pass = 1, required_item_id = ? "
            "WHERE id = 3 AND name = ? AND (requires_pass = 0 OR requires_pass IS NULL)",
            (pass_id, ZONES[1][1]),
        )


def _update_rods(cursor: sqlite3.Cursor):
    for name, durability in ROD_DURABILITY:
        row = cursor.execute("SELECT rod_id, rarity, durability FROM rods WHERE name = ?", (name,)).fetchone()
        if not row or row[2] is not None:
            continue
        rod_id, rarity = row[0], row[1]
        cursor.execute("UPDATE rods SET durability = ? WHERE rod_id = ?", (durability, rod_id))
        # 玩家手里的这类鱼竿按精炼等级给满耐久；5 星精炼到 10 级本来就是无限耐久
        for instance_id, refine_level in cursor.execute(
            "SELECT rod_instance_id, refine_level FROM user_rods WHERE rod_id = ? AND current_durability IS NULL",
            (rod_id,),
        ).fetchall():
            level = max(refine_level or 1, 1)
            if rarity >= 5 and level >= 10:
                continue
            cursor.execute(
                "UPDATE user_rods SET current_durability = ? WHERE rod_instance_id = ?",
                (int(durability * (1.5 ** (level - 1))), instance_id),
            )


def _update_gacha(cursor: sqlite3.Cursor):
    for pool_id, old_quantity, new_quantity in GACHA_COINS:
        cursor.execute(
            "UPDATE gacha_pool_items SET quantity = ? "
            "WHERE gacha_pool_id = ? AND item_type = 'coins' AND quantity = ?",
            (new_quantity, pool_id, old_quantity),
        )
    pool = cursor.execute(
        "SELECT gacha_pool_id FROM gacha_pools WHERE gacha_pool_id = 3 AND cost_coins = 0 "
    ).fetchone()
    has_items = cursor.execute("SELECT 1 FROM gacha_pool_items WHERE gacha_pool_id = 3").fetchone()
    if pool and not has_items:
        for kind, name, quantity, weight in DAILY_POOL:
            item_id = _id_by_name(cursor, kind, name)
            if item_id is None:
                continue
            cursor.execute(
                "INSERT INTO gacha_pool_items (gacha_pool_id, item_type, item_id, quantity, weight) VALUES (3, ?, ?, ?, ?)",
                (kind, item_id, quantity, weight),
            )


def _update_shops(cursor: sqlite3.Cursor):
    # 没有商品的内置商店先关闭
    for name in ("七海珍宝阁", "幽灵船黑市"):
        cursor.execute(
            "UPDATE shops SET is_active = 0 WHERE name = ? "
            "AND NOT EXISTS (SELECT 1 FROM shop_items WHERE shop_items.shop_id = shops.shop_id)",
            (name,),
        )
    # 海鸥港杂货铺上架通行证
    shop = cursor.execute("SELECT shop_id FROM shops WHERE name = '海鸥港杂货铺'").fetchone()
    pass_id = _id_by_name(cursor, "item", ZONE_PASS_NAME)
    if not shop or pass_id is None:
        return
    exists = cursor.execute(
        "SELECT 1 FROM shop_items WHERE shop_id = ? AND name = ?", (shop[0], ZONE_PASS_NAME)
    ).fetchone()
    if exists:
        return
    cursor.execute(
        "INSERT INTO shop_items (shop_id, name, description, category, is_active, sort_order) "
        "VALUES (?, ?, ?, 'basic', 1, 200)",
        (shop[0], ZONE_PASS_NAME, "进入区域三「传说之海」需要的通行证，有效到下次每日刷新。"),
    )
    shop_item_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO shop_item_costs (item_id, cost_type, cost_amount, cost_relation) VALUES (?, 'coins', ?, 'and')",
        (shop_item_id, ZONE_PASS_PRICE),
    )
    cursor.execute(
        "INSERT INTO shop_item_rewards (item_id, reward_type, reward_item_id, reward_quantity, reward_refine_level) "
        "VALUES (?, 'item', ?, 1, 1)",
        (shop_item_id, pass_id),
    )


def _update_items(cursor: sqlite3.Cursor):
    cursor.execute(
        "UPDATE accessories SET cooldown_modifier = 0.5, other_bonus_description = '钓鱼冷却时间减半' "
        "WHERE name = '海洋之心'"
    )
    cursor.execute(
        "UPDATE items SET description = ?, effect_description = ? WHERE name = ? AND effect_description = ?",
        (
            "一张神秘的通行证，允许进入传说之海。",
            "进入传说之海时消耗 1 张，有效到下次每日刷新；刷新时仍在该海域会自动再消耗 1 张续期，没有通行证就回到新手港湾。",
            ZONE_PASS_NAME,
            "进入特定钓鱼区域时自动消耗。",
        ),
    )


def up(cursor: sqlite3.Cursor):
    cursor.execute("ALTER TABLE fishing_zones DROP COLUMN daily_rare_fish_quota")
    cursor.execute("ALTER TABLE fishing_zones DROP COLUMN rare_fish_caught_today")
    cursor.execute("ALTER TABLE fishing_zones ADD COLUMN required_rod_rarity INTEGER NOT NULL DEFAULT 0")
    cursor.execute("ALTER TABLE accessories ADD COLUMN cooldown_modifier REAL NOT NULL DEFAULT 1.0")
    _update_zones(cursor)
    _update_rods(cursor)
    _update_gacha(cursor)
    _update_shops(cursor)
    _update_items(cursor)
