"""经济调整：深海峡谷、传说之海少靠稀有大鱼撑收益，通行证按钓鱼的天数收费，新手木竿永久耐久并免费发放。

只改仍是上一版默认值的数据，管理员改过的保持不变。新库的游戏内容由 DataSetupService 写入，已经是新数值。
"""

import json
import sqlite3

ZONE_PASS_NAME = "前往神秘海域的通行证"
STARTER_ROD_NAME = "新手木竿"

ZONE3_NAME = "区域三：传说之海"
ZONE3_OLD_DESC = "5星鱼概率大幅提升，还有极小概率遇到6～8星的神话鱼。需要通行证。"
ZONE3_NEW_DESC = "4星鱼最多，也有机会钓到5星鱼和6～8星的神话鱼。需要装备3星及以上的鱼竿，并且每天消耗1张通行证。"
ZONE3_OLD_DIST = [0.3, 0.2, 0.2, 0.2, 0.095, 0.005]
ZONE3_NEW_DIST = [0.05, 0.15, 0.3, 0.48, 0.018, 0.002]
ZONE3_OLD_COST, ZONE3_NEW_COST = 110, 120

ZONE2_NAME = "区域二：深海峡谷"
ZONE2_OLD_DIST = [0.4, 0.3, 0.2, 0.09, 0.01]
ZONE2_NEW_DIST = [0.3, 0.3, 0.29, 0.105, 0.005, 0]
ZONE2_OLD_COST, ZONE2_NEW_COST = 60, 50

PASS_OLD_EFFECT = "进入传说之海时消耗 1 张，有效到下次每日刷新；刷新时仍在该海域会自动再消耗 1 张续期，没有通行证就回到新手港湾。"
PASS_NEW_DESC = "一张神秘的通行证，允许在传说之海钓鱼。"
PASS_NEW_EFFECT = "每天第一次在传说之海钓鱼时消耗 1 张，当天有效；没去钓鱼的日子不消耗。"
PASS_OLD_PRICE, PASS_NEW_PRICE = 20000, 2000
PASS_OFFER_OLD_DESC = "进入区域三「传说之海」需要的通行证，有效到下次每日刷新。"
PASS_OFFER_NEW_DESC = "在区域三「传说之海」钓鱼的门票：每天第一次钓鱼时消耗 1 张，当天有效。"


def _update_zone2(cursor: sqlite3.Cursor):
    # 少靠 5 星撑收益，多给 3、4 星，一次 20 竿亏本的概率从约 22% 降到约 7%
    row = cursor.execute("SELECT name, configs, fishing_cost FROM fishing_zones WHERE id = 2").fetchone()
    if not row or row[0] != ZONE2_NAME:
        return
    try:
        dist = json.loads(row[1] or "{}").get("rarity_distribution")
    except ValueError:
        dist = None
    if dist == ZONE2_OLD_DIST:
        cursor.execute(
            "UPDATE fishing_zones SET configs = ? WHERE id = 2",
            (json.dumps({"rarity_distribution": ZONE2_NEW_DIST}),),
        )
    if row[2] == ZONE2_OLD_COST:
        cursor.execute("UPDATE fishing_zones SET fishing_cost = ? WHERE id = 2", (ZONE2_NEW_COST,))


def _update_zone3(cursor: sqlite3.Cursor):
    row = cursor.execute("SELECT name, description, configs, fishing_cost FROM fishing_zones WHERE id = 3").fetchone()
    if not row or row[0] != ZONE3_NAME:
        return
    if row[1] == ZONE3_OLD_DESC:
        cursor.execute("UPDATE fishing_zones SET description = ? WHERE id = 3", (ZONE3_NEW_DESC,))
    try:
        dist = json.loads(row[2] or "{}").get("rarity_distribution")
    except ValueError:
        dist = None
    if dist == ZONE3_OLD_DIST:
        cursor.execute(
            "UPDATE fishing_zones SET configs = ? WHERE id = 3",
            (json.dumps({"rarity_distribution": ZONE3_NEW_DIST}),),
        )
    if row[3] == ZONE3_OLD_COST:
        cursor.execute("UPDATE fishing_zones SET fishing_cost = ? WHERE id = 3", (ZONE3_NEW_COST,))
    cursor.execute("UPDATE fishing_zones SET required_rod_rarity = 3 WHERE id = 3 AND required_rod_rarity = 0")


def _update_pass(cursor: sqlite3.Cursor):
    cursor.execute(
        "UPDATE items SET description = ?, effect_description = ?, rarity = 3 WHERE name = ? AND effect_description = ?",
        (PASS_NEW_DESC, PASS_NEW_EFFECT, ZONE_PASS_NAME, PASS_OLD_EFFECT),
    )
    for item_id, desc in cursor.execute(
        "SELECT item_id, description FROM shop_items WHERE name = ?", (ZONE_PASS_NAME,)
    ).fetchall():
        if desc == PASS_OFFER_OLD_DESC:
            cursor.execute("UPDATE shop_items SET description = ? WHERE item_id = ?", (PASS_OFFER_NEW_DESC, item_id))
        cursor.execute(
            "UPDATE shop_item_costs SET cost_amount = ? WHERE item_id = ? AND cost_type = 'coins' AND cost_amount = ?",
            (PASS_NEW_PRICE, item_id, PASS_OLD_PRICE),
        )


def _update_starter_rod(cursor: sqlite3.Cursor):
    row = cursor.execute("SELECT rod_id, durability FROM rods WHERE name = ?", (STARTER_ROD_NAME,)).fetchone()
    if not row:
        return
    rod_id = row[0]
    if row[1] == 200:
        cursor.execute(
            "UPDATE rods SET durability = NULL, description = '刚入门时的可靠伙伴，永不损坏' WHERE rod_id = ?",
            (rod_id,),
        )
        cursor.execute("UPDATE user_rods SET current_durability = NULL WHERE rod_id = ?", (rod_id,))
    # 还没有新手木竿的玩家补发一根；没装备鱼竿的顺便装上
    users = cursor.execute(
        "SELECT user_id, equipped_rod_instance_id FROM users WHERE user_id != 'MARKET' "
        "AND user_id NOT IN (SELECT user_id FROM user_rods WHERE rod_id = ?)",
        (rod_id,),
    ).fetchall()
    for user_id, equipped in users:
        cursor.execute(
            "INSERT INTO user_rods (user_id, rod_id, current_durability, obtained_at, refine_level, is_equipped, is_locked) "
            "VALUES (?, ?, NULL, CURRENT_TIMESTAMP, 1, ?, 0)",
            (user_id, rod_id, 0 if equipped else 1),
        )
        if not equipped:
            cursor.execute(
                "UPDATE users SET equipped_rod_instance_id = ? WHERE user_id = ?", (cursor.lastrowid, user_id)
            )


def up(cursor: sqlite3.Cursor):
    _update_zone2(cursor)
    _update_zone3(cursor)
    _update_pass(cursor)
    _update_starter_rod(cursor)
    # 上一版记录每日刷新时间点，现在通行证改为当天有效的标记，不再需要
    cursor.execute("DELETE FROM db_meta WHERE key = 'daily_reset_at'")
