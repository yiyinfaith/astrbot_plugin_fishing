import sqlite3
import threading
import time
from contextlib import contextmanager
from functools import wraps

from astrbot.api import logger


def atomic_game_operation(method):
    """Run a synchronous gameplay operation in the shared write transaction."""
    @wraps(method)
    def wrapped(service, *args, **kwargs):
        with service.inventory_repo.transaction():
            return method(service, *args, **kwargs)

    return wrapped


class DatabaseConnectionManager:
    """数据库连接管理器，提供线程安全的连接管理和重试机制"""
    
    def __init__(self, db_path: str, timeout: int = 30, max_retries: int = 3, retry_delay: float = 0.1):
        self.db_path = db_path
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._local = threading.local()
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取一个线程安全的数据库连接"""
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = self._create_connection()
            self._local.connection = conn
        return conn
    
    def _create_connection(self) -> sqlite3.Connection:
        """创建新的数据库连接"""
        conn = sqlite3.connect(
            self.db_path, 
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            timeout=self.timeout
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        # journal_mode 是数据库级设置，由初始化/迁移负责。连接建立时切换模式
        # 会与正在进行的写事务竞争锁，反而可能让重试尚未开始就失败。
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn
    
    @contextmanager
    def get_connection(self):
        """获取线程本地连接，并确保失败事务不会遗留数据库锁。"""
        conn = self._get_connection()
        if getattr(self._local, "transaction_depth", 0):
            yield conn
            return
        try:
            with conn:
                yield conn
        except sqlite3.OperationalError as e:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            if "database is locked" in str(e).lower():
                logger.warning(f"数据库锁定，操作无法在超时 ({self.timeout}s) 内完成: {e}")
            self.close_connection()
            raise
        except Exception as e:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            logger.error(f"数据库操作发生未知错误: {e}")
            raise
    
    @contextmanager
    def transaction(self, immediate: bool = True):
        """Share a write transaction across repositories and nested operations."""
        conn = self._get_connection()
        cursor = conn.cursor()
        depth = getattr(self._local, "transaction_depth", 0)
        savepoint = f"fishing_{depth}"
        cursor.execute(
            f"SAVEPOINT {savepoint}" if depth else ("BEGIN IMMEDIATE" if immediate else "BEGIN")
        )
        self._local.transaction_depth = depth + 1
        try:
            yield cursor
            if depth:
                cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                conn.commit()
        except BaseException:
            if depth:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                conn.rollback()
            raise
        finally:
            self._local.transaction_depth = depth
            cursor.close()

    def run_in_transaction(self, operation, immediate: bool = True):
        """执行 operation(cursor)，遇到数据库锁定时重放整个事务。

        事务失败会整体回滚，因此重放是安全的；operation 不应带有数据库之外
        的副作用。
        """
        if getattr(self._local, "transaction_depth", 0):
            with self.transaction(immediate=immediate) as cursor:
                return operation(cursor)
        for attempt in range(self.max_retries + 1):
            try:
                with self.transaction(immediate=immediate) as cursor:
                    return operation(cursor)
            except sqlite3.OperationalError as e:
                is_locked = "database is locked" in str(e).lower()
                self.close_connection()
                if not is_locked or attempt >= self.max_retries:
                    raise

                delay = self.retry_delay * (attempt + 1)
                logger.warning(
                    f"数据库锁定，事务第 {attempt + 1}/{self.max_retries} 次重试，"
                    f"等待 {delay:.2f}s: {e}"
                )
                time.sleep(delay)
            except Exception:
                self.close_connection()
                raise

    def close_connection(self):
        """关闭当前线程的数据库连接"""
        if hasattr(self._local, "connection"):
            try:
                conn = self._local.connection
                if conn.in_transaction:
                    conn.rollback()
                conn.close()
            except sqlite3.Error:
                pass
            finally:
                delattr(self._local, "connection")
    
    def execute_with_retry(self, query: str, params: tuple = (), fetch: str = "none"):
        """执行SQL查询，支持重试机制
        
        Args:
            query: SQL查询语句
            params: 查询参数
            fetch: 获取结果的方式 ("none", "one", "all")
        """
        if fetch not in {"none", "one", "all"}:
            raise ValueError(f"不支持的 fetch 类型: {fetch}")

        def execute(cursor):
            cursor.execute(query, params)
            if fetch == "one":
                return cursor.fetchone()
            if fetch == "all":
                return cursor.fetchall()
            return cursor.lastrowid or None

        return self.run_in_transaction(execute, immediate=False)
