import sqlite3
from typing import Optional, List
from datetime import date, datetime, timedelta, timezone
from astrbot.api import logger
# 导入抽象基类和领域模型
from ..database.connection_manager import DatabaseConnectionManager
from .abstract_repository import AbstractLogRepository
from ..domain.models import UserFishStat

class SqliteLogRepository(AbstractLogRepository):
    """日志类数据仓储的SQLite实现"""

    def __init__(self, db_path: str, connection_manager: DatabaseConnectionManager | None = None):
        self.db_path = db_path
        self._connection_manager = connection_manager or DatabaseConnectionManager(db_path)
        self.UTC8 = timezone(timedelta(hours=8))

    def _row_to_user_fish_stat(self, row: sqlite3.Row) -> Optional[UserFishStat]:
        if not row:
            return None
        data = dict(row)
        return UserFishStat(**data)

    # --- Check-in Log Methods ---
    def add_check_in(self, user_id: str, check_in_date: date) -> None:
        with self._connection_manager.get_connection() as conn:
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


    def has_checked_in(self, user_id: str, check_in_date: date) -> bool:
        with self._connection_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM check_ins WHERE user_id = ? AND check_in_date = ?",
                (user_id, check_in_date)
            )
            return cursor.fetchone() is not None

    def add_log(self, user_id: str, log_type: str, message: str) -> None:
        """记录一条通用事件日志（只写入 AstrBot 日志，不落库）。"""
        logger.info(f"[钓鱼][{log_type}] {user_id}: {message}")

    # --- 用户鱼类统计（用于图鉴与个人纪录） ---
    def get_user_fish_stats(self, user_id: str) -> List[UserFishStat]:
        with self._connection_manager.get_connection() as conn:
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
        with self._connection_manager.get_connection() as conn:
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
