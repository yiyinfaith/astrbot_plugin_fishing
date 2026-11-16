"""清理已下线玩法遗留的模板数据。

擦弹玩法删除后，下面这些称号和道具再也无法通过游戏获得或使用。迁移只删除
没有任何玩家持有、也没有被卡池或商店引用的记录；已经有人拿到的保留原样，
避免动到玩家的存档。表结构（擦弹、命运之轮、骰宝、借贷、红包相关的列和表）
保持不变，旧存档仍能正常读取。
"""

import sqlite3

# 只由擦弹成就发放的称号
WIPE_BOMB_TITLE_IDS = (6, 20, 21, 22, 23, 24, 25)
# 只服务于擦弹的道具效果
WIPE_BOMB_EFFECT_TYPES = ("WIPE_BOMB_ATTEMPTS_BOOST", "FORECAST_WIPE_BOMB")


def _table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,))
    return cursor.fetchone() is not None


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _referenced(cursor: sqlite3.Cursor, checks) -> bool:
    for table, column, value, extra in checks:
        if not _table_exists(cursor, table) or not _column_exists(cursor, table, column):
            continue
        cursor.execute(f"SELECT 1 FROM {table} WHERE {column} = ? {extra} LIMIT 1", (value,))
        if cursor.fetchone():
            return True
    return False


def up(cursor: sqlite3.Cursor):
    if _table_exists(cursor, "titles"):
        for title_id in WIPE_BOMB_TITLE_IDS:
            if _referenced(cursor, (
                ("user_titles", "title_id", title_id, ""),
                ("users", "current_title_id", title_id, ""),
                ("gacha_pool_items", "item_id", title_id, "AND item_type = 'titles'"),
            )):
                continue
            cursor.execute("DELETE FROM titles WHERE title_id = ?", (title_id,))

    if _table_exists(cursor, "items") and _column_exists(cursor, "items", "effect_type"):
        placeholders = ",".join("?" * len(WIPE_BOMB_EFFECT_TYPES))
        cursor.execute(
            f"SELECT item_id FROM items WHERE effect_type IN ({placeholders})",
            WIPE_BOMB_EFFECT_TYPES,
        )
        for (item_id,) in cursor.fetchall():
            if _referenced(cursor, (
                ("user_items", "item_id", item_id, ""),
                ("gacha_pool_items", "item_id", item_id, "AND item_type = 'item'"),
                ("shop_item_rewards", "reward_item_id", item_id, "AND reward_type = 'item'"),
                ("shop_item_costs", "cost_item_id", item_id, "AND cost_type = 'item'"),
                ("market", "item_id", item_id, "AND item_type = 'item'"),
            )):
                continue
            cursor.execute("DELETE FROM items WHERE item_id = ?", (item_id,))
