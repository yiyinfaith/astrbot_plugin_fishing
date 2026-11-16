import dataclasses
import sqlite3
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from astrbot.api import logger

from ..domain.models import User
from .abstract_repository import AbstractUserRepository

# 累计类字段按增量写回，和其他线程的原子更新（如自动钓鱼扣费）叠加，而不是互相覆盖
COUNTER_FIELDS = ("coins", "premium_currency", "total_fishing_count", "total_weight_caught", "total_coins_earned")
# 读取时的字段快照，update 时据此只写变化的字段
_SNAPSHOT_ATTR = "_db_snapshot"


def _snapshot(user: User) -> Dict[str, Any]:
    return {f.name: getattr(user, f.name) for f in dataclasses.fields(User)}


class SqliteUserRepository(AbstractUserRepository):
    """用户数据仓储的SQLite实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.connection = conn
        return conn

    def close_connection(self) -> None:
        """关闭当前线程的连接，退出后台任务时释放线程资源。"""
        conn = getattr(self._local, "connection", None)
        if conn is None:
            return
        try:
            if conn.in_transaction:
                conn.rollback()
            conn.close()
        finally:
            delattr(self._local, "connection")

    def _row_to_user(self, row: sqlite3.Row) -> Optional[User]:
        """
        [已修正] 将数据库行安全地转换为 User 对象。
        现在可以正确读取所有新旧字段。
        """
        if not row:
            return None
            
        def parse_datetime(dt_val):
            if isinstance(dt_val, datetime):
                return dt_val
            if isinstance(dt_val, str):
                try:
                    return datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        return datetime.strptime(dt_val, "%Y-%m-%d %H:%M:%S.%f")
                    except ValueError:
                        try:
                            return datetime.strptime(dt_val, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            return None
            return None
        
        # 使用 .keys() 检查字段是否存在，确保向后兼容性
        row_keys = row.keys()

        user = User(
            user_id=row["user_id"],
            nickname=row["nickname"],
            coins=row["coins"],
            premium_currency=row["premium_currency"],
            total_fishing_count=row["total_fishing_count"],
            total_weight_caught=row["total_weight_caught"],
            total_coins_earned=row["total_coins_earned"],
            max_coins=row["max_coins"] if "max_coins" in row_keys else 0,
            consecutive_login_days=row["consecutive_login_days"],
            fish_pond_capacity=row["fish_pond_capacity"],
            aquarium_capacity=row["aquarium_capacity"] if "aquarium_capacity" in row_keys else 50,
            created_at=parse_datetime(row["created_at"]),
            equipped_rod_instance_id=row["equipped_rod_instance_id"],
            equipped_accessory_instance_id=row["equipped_accessory_instance_id"],
            current_title_id=row["current_title_id"],
            current_bait_id=row["current_bait_id"],
            bait_start_time=parse_datetime(row["bait_start_time"]),


            auto_fishing_enabled=bool(row["auto_fishing_enabled"]),
            last_fishing_time=parse_datetime(row["last_fishing_time"]),
            last_steal_time=parse_datetime(row["last_steal_time"]),
            last_electric_fish_time=parse_datetime(row["last_electric_fish_time"]) if "last_electric_fish_time" in row_keys else None,
            last_login_time=parse_datetime(row["last_login_time"]),
            last_stolen_at=parse_datetime(row["last_stolen_at"]),
            fishing_zone_id=row["fishing_zone_id"],
        )
        setattr(user, _SNAPSHOT_ATTR, _snapshot(user))
        return user

    def get_by_id(self, user_id: str) -> Optional[User]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return self._row_to_user(row)

    def check_exists(self, user_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            return cursor.fetchone() is not None

    def add(self, user: User) -> None:
        # 使用与 update 相同的动态方法，确保 add 也是完整的
        fields = [f.name for f in dataclasses.fields(User)]
        columns_clause = ", ".join(fields)
        placeholders_clause = ", ".join(["?"] * len(fields))
        values = [getattr(user, field) for field in fields]

        sql = f"INSERT INTO users ({columns_clause}) VALUES ({placeholders_clause})"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(values))
            conn.commit()

    def update(self, user: User) -> None:
        """
        [已修正] 更新一个现有的用户记录。
        这个版本是动态的，可以处理 User 模型中的所有字段，未来扩展也无需修改。
        自动更新 max_coins 如果当前金币数超过历史最高。
        """
        snapshot = getattr(user, _SNAPSHOT_ATTR, None)
        if snapshot is not None:
            self._update_changed(user, snapshot)
            return

        # 自动更新历史最高金币数
        if user.coins > user.max_coins:
            user.max_coins = user.coins

        fields = [f.name for f in dataclasses.fields(User) if f.name != 'user_id']
        set_clause = ", ".join([f"{field} = ?" for field in fields])
        values = [getattr(user, field) for field in fields]
        values.append(user.user_id)
        
        sql = f"UPDATE users SET {set_clause} WHERE user_id = ?"

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, tuple(values))
                if cursor.rowcount == 0:
                    logger.warning(f"尝试更新不存在的用户 {user.user_id}，将转为添加操作。")
                    self.add(user) # 如果更新失败（比如用户不存在），则尝试添加
                else:
                    conn.commit()
        except sqlite3.Error as e:
            logger.error(f"更新用户 {user.user_id} 数据时发生数据库错误: {e}")
            raise

    def _update_changed(self, user: User, snapshot: Dict[str, Any]) -> None:
        """
        只写回读取后改动过的字段。金币等累计字段按增量写，
        这样读取之后其他线程做的原子更新（自动钓鱼扣费、出售入账等）不会被旧值覆盖。
        """
        sets, values = [], []
        for field in dataclasses.fields(User):
            name = field.name
            if name in ("user_id", "max_coins"):
                continue
            new, old = getattr(user, name), snapshot.get(name)
            if new == old:
                continue
            if name in COUNTER_FIELDS and isinstance(new, int) and isinstance(old, int):
                sets.append(f"{name} = MAX({name} + ?, 0)")
                values.append(new - old)
            else:
                sets.append(f"{name} = ?")
                values.append(new)
        if user.max_coins != snapshot.get("max_coins"):
            sets.append("max_coins = MAX(max_coins, ?)")
            values.append(user.max_coins)
        if not sets:
            return
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id = ?", (*values, user.user_id))
                if cursor.rowcount == 0:
                    logger.warning(f"尝试更新不存在的用户 {user.user_id}")
                    return
                # 历史最高金币按写入后的实际余额更新
                cursor.execute("UPDATE users SET max_coins = MAX(max_coins, coins) WHERE user_id = ?", (user.user_id,))
                row = cursor.execute(
                    f"SELECT {', '.join(COUNTER_FIELDS)}, max_coins FROM users WHERE user_id = ?", (user.user_id,)
                ).fetchone()
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"更新用户 {user.user_id} 数据时发生数据库错误: {e}")
            raise
        # 让对象与数据库保持一致，之后再次 update 只写新的改动
        for i, name in enumerate(COUNTER_FIELDS):
            setattr(user, name, row[i])
        user.max_coins = row[len(COUNTER_FIELDS)]
        setattr(user, _SNAPSHOT_ATTR, _snapshot(user))

    def toggle_auto_fishing(self, user_id: str) -> Optional[bool]:
        """原子切换自动钓鱼状态并返回新状态。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE users
                SET auto_fishing_enabled = CASE auto_fishing_enabled WHEN 0 THEN 1 ELSE 0 END
                WHERE user_id = ?
                RETURNING auto_fishing_enabled
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            conn.commit()
            return bool(row[0]) if row else None

    def set_auto_fishing_enabled(self, user_id: str, enabled: bool) -> bool:
        """原子设置自动钓鱼状态。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET auto_fishing_enabled = ? WHERE user_id = ?",
                (1 if enabled else 0, user_id),
            )
            updated = cursor.rowcount == 1
            conn.commit()
            return updated

    def record_failed_fishing(self, user_id: str, cost: int, timestamp: datetime) -> bool:
        """仅更新失败钓鱼所需字段，避免整行旧数据回写。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE users
                SET coins = coins - ?, last_fishing_time = ?
                WHERE user_id = ? AND coins >= ?
                """,
                (cost, timestamp, user_id, cost),
            )
            updated = cursor.rowcount == 1
            conn.commit()
            return updated

    def update_bait_state(
        self, user_id: str, bait_id: Optional[int], bait_start_time: Optional[datetime]
    ) -> bool:
        """只保存当前鱼饵状态。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET current_bait_id = ?, bait_start_time = ? WHERE user_id = ?",
                (bait_id, bait_start_time, user_id),
            )
            updated = cursor.rowcount == 1
            conn.commit()
            return updated

    def set_fishing_zone(self, user_id: str, zone_id: int) -> bool:
        """只更新用户所在钓鱼区域。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET fishing_zone_id = ? WHERE user_id = ?",
                (zone_id, user_id),
            )
            updated = cursor.rowcount == 1
            conn.commit()
            return updated

    def deduct_coins_up_to(self, user_id: str, amount: int) -> tuple[int, int]:
        """在一个事务内最多扣除指定金币，返回实际扣除额和余额。"""
        amount = max(int(amount), 0)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            try:
                cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                if row is None:
                    conn.rollback()
                    return 0, 0
                balance = int(row[0])
                deducted = min(amount, balance)
                new_balance = balance - deducted
                cursor.execute(
                    "UPDATE users SET coins = ? WHERE user_id = ?",
                    (new_balance, user_id),
                )
                conn.commit()
                return deducted, new_balance
            except Exception:
                conn.rollback()
                raise

    def get_all_user_ids(self, auto_fishing_only: bool = False) -> List[str]:
        query = "SELECT user_id FROM users"
        if auto_fishing_only:
            query += " WHERE auto_fishing_enabled = 1"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            return [row["user_id"] for row in cursor.fetchall()]

    def _get_top_users_base_query(self, order_by_column: str, limit: int) -> List[User]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if order_by_column not in ["total_fishing_count", "coins", "total_weight_caught", "max_coins"]:
                raise ValueError("Invalid order by column")
            
            query = f"SELECT * FROM users WHERE user_id != 'MARKET' ORDER BY {order_by_column} DESC LIMIT ?"
            cursor.execute(query, (limit,))
            return [self._row_to_user(row) for row in cursor.fetchall()]

    def get_top_users_by_fish_count(self, limit: int) -> List[User]:
        return self._get_top_users_base_query("total_fishing_count", limit)

    def get_top_users_by_coins(self, limit: int) -> List[User]:
        return self._get_top_users_base_query("coins", limit)

    def get_top_users_by_max_coins(self, limit: int) -> List[User]:
        """获取历史最高金币排行榜"""
        return self._get_top_users_base_query("max_coins", limit)

    def get_top_users_by_weight(self, limit: int) -> List[User]:
        return self._get_top_users_base_query("total_weight_caught", limit)

    def get_high_value_users(self, threshold: int) -> List[User]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE coins >= ?", (threshold,))
            return [self._row_to_user(row) for row in cursor.fetchall()]
    
    # 其他辅助方法保持不变...
    def get_all_users(self, limit: int = 100, offset: int = 0) -> List[User]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
            return [self._row_to_user(row) for row in cursor.fetchall()]

    def get_users_count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]

    def search_users(self, keyword: str, limit: int = 50, offset: int = 0) -> List[User]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM users 
                WHERE user_id LIKE ? OR nickname LIKE ? 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (f"%{keyword}%", f"%{keyword}%", limit, offset))
            return [self._row_to_user(row) for row in cursor.fetchall()]

    def get_search_users_count(self, keyword: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM users WHERE user_id LIKE ? OR nickname LIKE ?",
                (f"%{keyword}%", f"%{keyword}%")
            )
            return cursor.fetchone()[0]

    def delete_user(self, user_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
                conn.commit()
                return cursor.rowcount > 0
            except sqlite3.Error:
                conn.rollback()
                return False
