import sqlite3
import threading
from typing import Any, Optional, List, Dict
from datetime import date, datetime, timedelta, timezone
from astrbot.api import logger
# 导入抽象基类和领域模型
from .abstract_repository import AbstractLogRepository
from ..domain.models import FishingRecord, GachaRecord, UserFishStat

class SqliteLogRepository(AbstractLogRepository):
    """日志类数据仓储的SQLite实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        # 定义UTC+8时区
        self.UTC8 = timezone(timedelta(hours=8))
    def _get_connection(self) -> sqlite3.Connection:
        """获取一个线程安全的数据库连接。"""
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.connection = conn
        return conn

    # --- 私有映射辅助方法 ---
    def _row_to_fishing_record(self, row: sqlite3.Row) -> Optional[FishingRecord]:
        if not row:
            return None
        # 数据库中的 is_king_size 是 INTEGER，需要转为 bool
        data = dict(row)
        data["is_king_size"] = bool(data.get("is_king_size", 0))
        return FishingRecord(**data)

    def _row_to_user_fish_stat(self, row: sqlite3.Row) -> Optional[UserFishStat]:
        if not row:
            return None
        data = dict(row)
        return UserFishStat(**data)

    def _row_to_gacha_record(self, row: sqlite3.Row) -> Optional[GachaRecord]:
        if not row:
            return None
        return GachaRecord(**row)

    # --- Fishing Log Methods ---
    def add_fishing_record(self, record: FishingRecord) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1) 写入本次钓鱼记录
            cursor.execute(
                """
                INSERT INTO fishing_records (
                    user_id, fish_id, weight, value, rod_instance_id,
                    accessory_instance_id, bait_id, timestamp, is_king_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.user_id,
                    record.fish_id,
                    record.weight,
                    record.value,
                    record.rod_instance_id,
                    record.accessory_instance_id,
                    record.bait_id,
                    record.timestamp or datetime.now(self.UTC8),
                    1 if record.is_king_size else 0,
                ),
            )

            # 1.5) 更新用户鱼类聚合统计（UPSERT）
            now_ts = record.timestamp or datetime.now(self.UTC8)
            cursor.execute(
                """
                INSERT INTO user_fish_stats (
                    user_id, fish_id, first_caught_at, last_caught_at, max_weight, min_weight, total_caught, total_weight
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(user_id, fish_id) DO UPDATE SET
                    last_caught_at = excluded.last_caught_at,
                    max_weight = CASE WHEN excluded.max_weight > max_weight THEN excluded.max_weight ELSE max_weight END,
                    min_weight = CASE WHEN excluded.min_weight < min_weight THEN excluded.min_weight ELSE min_weight END,
                    total_caught = total_caught + 1,
                    total_weight = total_weight + excluded.total_weight
                """,
                (
                    record.user_id,
                    record.fish_id,
                    now_ts,
                    now_ts,
                    record.weight,
                    record.weight,
                    record.weight,
                ),
            )

            # 2) 仅保留当前用户最近10条记录（按时间倒序，时间相同按record_id倒序）
            cursor.execute(
                """
                DELETE FROM fishing_records
                WHERE user_id = ?
                  AND record_id NOT IN (
                    SELECT record_id FROM fishing_records
                    WHERE user_id = ?
                    ORDER BY timestamp DESC, record_id DESC
                    LIMIT 50
                  )
                """,
                (record.user_id, record.user_id),
            )

            # 3) 清理30天前的历史记录（全局）
            cutoff_time = datetime.now(self.UTC8) - timedelta(days=30)
            cursor.execute(
                """
                DELETE FROM fishing_records
                WHERE timestamp < ?
                """,
                (cutoff_time,),
            )

            conn.commit()
            return True


    def get_unlocked_fish_ids(self, user_id: str) -> Dict[int, datetime]:
        """
        获取指定用户所有钓到过的鱼类ID集合，以及对应的首次捕获时间。

        返回:
            Dict[int, datetime]: 键为鱼类ID，值为首次捕获时间
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT fish_id, MIN(timestamp) as first_caught_time
                FROM fishing_records
                WHERE user_id = ?
                GROUP BY fish_id
            """, (user_id,))
            rows = cursor.fetchall()
            return {row["fish_id"]: row["first_caught_time"] for row in rows}
            
    def get_fishing_records(self, user_id: str, limit: int) -> List[FishingRecord]:
        with self._get_connection() as conn:
            # 为了简化返回，这里不连接获取名称，表现层可以按需从ItemTemplateRepository获取
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM fishing_records
                WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
            """, (user_id, limit))
            return [self._row_to_fishing_record(row) for row in cursor.fetchall()]

    # --- Gacha Log Methods ---
    def add_gacha_record(self, record: GachaRecord) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1) 写入抽卡记录
            cursor.execute(
                """
                INSERT INTO gacha_records (
                    user_id, gacha_pool_id, item_type, item_id,
                    item_name, quantity, rarity, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.user_id,
                    record.gacha_pool_id,
                    record.item_type,
                    record.item_id,
                    record.item_name,
                    record.quantity,
                    record.rarity,
                    record.timestamp or datetime.now(self.UTC8),
                ),
            )

            # 2) 仅保留当前用户最近10条抽卡记录
            cursor.execute(
                """
                DELETE FROM gacha_records
                WHERE user_id = ?
                  AND record_id NOT IN (
                    SELECT record_id FROM gacha_records
                    WHERE user_id = ?
                    ORDER BY timestamp DESC, record_id DESC
                    LIMIT 50
                  )
                """,
                (record.user_id, record.user_id),
            )

            # 3) 清理30天前的抽卡记录（全局）
            cutoff_time = datetime.now(self.UTC8) - timedelta(days=30)
            cursor.execute(
                """
                DELETE FROM gacha_records
                WHERE timestamp < ?
                """,
                (cutoff_time,),
            )

            conn.commit()

    def get_gacha_records(self, user_id: str, limit: int) -> List[GachaRecord]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM gacha_records
                WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?
            """, (user_id, limit))
            return [self._row_to_gacha_record(row) for row in cursor.fetchall()]

    # --- Check-in Log Methods ---
    def add_check_in(self, user_id: str, check_in_date: date) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1) 写入签到记录
            cursor.execute(
                "INSERT INTO check_ins (user_id, check_in_date) VALUES (?, ?)",
                (user_id, check_in_date),
            )

            # 2) 仅保留当前用户最近10条签到记录（按日期倒序）
            cursor.execute(
                """
                DELETE FROM check_ins
                WHERE user_id = ?
                  AND check_in_date NOT IN (
                    SELECT check_in_date FROM check_ins
                    WHERE user_id = ?
                    ORDER BY check_in_date DESC
                    LIMIT 50
                  )
                """,
                (user_id, user_id),
            )

            # 3) 清理30天前的签到记录（全局）
            cutoff_date = (datetime.now(self.UTC8) - timedelta(days=30)).date()
            cursor.execute(
                """
                DELETE FROM check_ins
                WHERE check_in_date < ?
                """,
                (cutoff_date,),
            )

            conn.commit()

    def has_checked_in(self, user_id: str, check_in_date: date) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM check_ins WHERE user_id = ? AND check_in_date = ?",
                (user_id, check_in_date)
            )
            return cursor.fetchone() is not None

    def add_log(self, user_id: str, log_type: str, message: str) -> None:
        """记录一条通用事件日志（只写入 AstrBot 日志，不落库）。"""
        logger.info(f"[钓鱼][{log_type}] {user_id}: {message}")

    def get_gacha_records_count_today(
        self, user_id: str, gacha_pool_id: int
    ) -> int:
        # 获取 UTC+8 的今天的开始和结束时间点
        today_start_utc8 = datetime.now(self.UTC8).replace(hour=0, minute=0, second=0, microsecond=0)
        today_end_utc8 = today_start_utc8 + timedelta(days=1)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM gacha_records
                WHERE user_id = ? AND gacha_pool_id = ? AND timestamp >= ? AND timestamp < ?
                """,
                (user_id, gacha_pool_id, today_start_utc8, today_end_utc8),
            )
            result = cursor.fetchone()
            return result[0] if result else 0

    # --- 用户鱼类统计（用于图鉴与个人纪录） ---
    def get_user_fish_stats(self, user_id: str) -> List[UserFishStat]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_id, fish_id, first_caught_at, last_caught_at,
                       max_weight, min_weight, total_caught, total_weight
                FROM user_fish_stats
                WHERE user_id = ?
                ORDER BY last_caught_at DESC
                """,
                (user_id,),
            )
            return [self._row_to_user_fish_stat(row) for row in cursor.fetchall()]

    def get_user_fish_stat(self, user_id: str, fish_id: int) -> Optional[UserFishStat]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_id, fish_id, first_caught_at, last_caught_at,
                       max_weight, min_weight, total_caught, total_weight
                FROM user_fish_stats
                WHERE user_id = ? AND fish_id = ?
                LIMIT 1
                """,
                (user_id, fish_id),
            )
            row = cursor.fetchone()
            return self._row_to_user_fish_stat(row) if row else None
