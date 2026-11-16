"""银行与税收下线后，把仍留在银行里的金币退回玩家钱包。

退回的部分：
- 银行活期余额（含被取款预约锁定的部分）；
- 进行中的定期本金，已到期的定期连同预计利息一起退回。

欠税不再追缴，直接作废。退款后银行账户清零、定期标记为已结束、待处理的
取款预约标记为已取消，表本身保留，旧存档仍能正常读取。
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


def up(cursor: sqlite3.Cursor):
    if not _table_exists(cursor, "users"):
        return
    refunds = {}
    now = datetime.now()

    if _table_exists(cursor, "bank_accounts"):
        cursor.execute("SELECT user_id, balance FROM bank_accounts WHERE balance > 0")
        for user_id, balance in cursor.fetchall():
            refunds[user_id] = refunds.get(user_id, 0) + int(balance or 0)
        cursor.execute("UPDATE bank_accounts SET balance = 0, locked_balance = 0 WHERE balance != 0 OR locked_balance != 0")

    if _table_exists(cursor, "bank_fixed_deposits"):
        cursor.execute(
            "SELECT deposit_id, user_id, principal, expected_interest, matures_at "
            "FROM bank_fixed_deposits WHERE status = 'active'"
        )
        for deposit_id, user_id, principal, interest, matures_at in cursor.fetchall():
            matured = _parse_time(matures_at)
            amount = int(principal or 0)
            if matured is not None and matured <= now:
                amount += int(interest or 0)
            refunds[user_id] = refunds.get(user_id, 0) + amount
            cursor.execute(
                "UPDATE bank_fixed_deposits SET status = 'completed', completed_at = ? WHERE deposit_id = ?",
                (now.isoformat(sep=" "), deposit_id),
            )

    if _table_exists(cursor, "bank_withdraw_reservations"):
        cursor.execute("UPDATE bank_withdraw_reservations SET status = 'cancelled' WHERE status = 'pending'")

    for user_id, amount in refunds.items():
        if amount <= 0:
            continue
        cursor.execute(
            "UPDATE users SET coins = coins + ?, max_coins = MAX(COALESCE(max_coins, 0), coins + ?) WHERE user_id = ?",
            (amount, amount, user_id),
        )


def down(cursor: sqlite3.Cursor):
    """退款无法区分来源，不提供回滚。"""
