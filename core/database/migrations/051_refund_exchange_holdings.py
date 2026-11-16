"""交易所下线后，把玩家手里和挂在市场上的大宗商品折成金币退回。

- 交易所持仓和市场里的大宗商品挂单，按该商品最后一次成交价折算后退给持有人；
  没有价格记录时，持仓按买入价折算，挂单不折算。
- 已经腐败的商品本来就一文不值，直接清除。

退款后清空持仓表并删除大宗商品挂单；价格历史等表保留，旧存档仍能正常读取。
"""

import sqlite3
from datetime import datetime


def _table_exists(cursor: sqlite3.Cursor, name: str) -> bool:
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,))
    return cursor.fetchone() is not None


def _parse_time(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _expired(value, now: datetime) -> bool:
    expires_at = _parse_time(value)
    return expires_at is not None and expires_at <= now


def _latest_prices(cursor: sqlite3.Cursor) -> dict:
    if not _table_exists(cursor, "exchange_prices"):
        return {}
    cursor.execute(
        "SELECT commodity_id, price FROM exchange_prices "
        "ORDER BY date, time, price_id"
    )
    prices = {}
    for commodity_id, price in cursor.fetchall():
        prices[commodity_id] = int(price or 0)
    return prices


def up(cursor: sqlite3.Cursor):
    if not _table_exists(cursor, "users"):
        return
    now = datetime.now()
    prices = _latest_prices(cursor)
    refunds = {}

    if _table_exists(cursor, "user_commodities"):
        cursor.execute("SELECT user_id, commodity_id, quantity, purchase_price, expires_at FROM user_commodities")
        for user_id, commodity_id, quantity, purchase_price, expires_at in cursor.fetchall():
            if _expired(expires_at, now):
                continue
            unit = prices.get(commodity_id, int(purchase_price or 0))
            refunds[user_id] = refunds.get(user_id, 0) + unit * int(quantity or 0)
        cursor.execute("DELETE FROM user_commodities")

    if _table_exists(cursor, "market"):
        cursor.execute("SELECT market_id, user_id, item_id, quantity, expires_at FROM market WHERE item_type = 'commodity'")
        for _market_id, user_id, commodity_id, quantity, expires_at in cursor.fetchall():
            if _expired(expires_at, now):
                continue
            unit = prices.get(commodity_id, 0)
            refunds[user_id] = refunds.get(user_id, 0) + unit * int(quantity or 0)
        cursor.execute("DELETE FROM market WHERE item_type = 'commodity'")

    for user_id, amount in refunds.items():
        if amount <= 0:
            continue
        cursor.execute(
            "UPDATE users SET coins = coins + ?, max_coins = MAX(COALESCE(max_coins, 0), coins + ?) WHERE user_id = ?",
            (amount, amount, user_id),
        )


def down(cursor: sqlite3.Cursor):
    """退款无法区分来源，不提供回滚。"""
