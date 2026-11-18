import importlib.util
import os
import re
import sqlite3

from astrbot.api import logger

# 与 migrations/001_initial_schema.py 中的 SCHEMA_MARK 保持一致
SCHEMA_MARK = "fishing-1.0.1"


def get_current_version(cursor: sqlite3.Cursor) -> int:
    """获取当前数据库的版本号。"""
    try:
        cursor.execute("SELECT version FROM schema_version")
        result = cursor.fetchone()
        return result[0] if result else 0
    except sqlite3.OperationalError:
        return 0


def set_version(cursor: sqlite3.Cursor, version: int):
    """设置数据库的版本号。"""
    cursor.execute("UPDATE schema_version SET version = ?", (version,))


def _check_schema(conn: sqlite3.Connection) -> None:
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if not tables - {"schema_version"}:
        return
    marker = conn.execute("SELECT value FROM db_meta WHERE key = 'schema'").fetchone() if "db_meta" in tables else None
    if not marker or marker[0] != SCHEMA_MARK:
        raise RuntimeError("钓鱼数据库结构与当前插件不兼容，请使用新数据库。")


def run_migrations(db_path: str, migrations_dir: str):
    """
    运行所有待处理的数据库迁移脚本。
    """
    # 确保版本表存在
    with sqlite3.connect(db_path) as conn:
        _check_schema(conn)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL PRIMARY KEY)")
        cursor.execute("SELECT COUNT(*) FROM schema_version")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO schema_version (version) VALUES (0)")
            logger.info("schema_version 表已初始化。")
        conn.commit()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        current_version = get_current_version(cursor)
        logger.info(f"当前数据库版本: {current_version}")

    try:
        migration_files = sorted(
            [f for f in os.listdir(migrations_dir) if f.endswith(".py") and re.match(r"^\d{3}_", f)],
            key=lambda f: int(f.split("_")[0])
        )
    except FileNotFoundError:
        logger.warning(f"迁移目录 '{migrations_dir}' 不存在，跳过迁移。")
        return

    for filename in migration_files:
        version = int(filename.split("_")[0])
        if version > current_version:
            logger.info(f"正在应用迁移脚本: {filename}...")
            module_name = f"fishing_migration_{version}_{filename[:-3]}"
            migration_path = os.path.join(migrations_dir, filename)
            try:
                spec = importlib.util.spec_from_file_location(module_name, migration_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"无法从路径加载迁移脚本: {migration_path}")
                migration_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration_module)

                with sqlite3.connect(db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()

                    try:
                        cursor.execute("BEGIN TRANSACTION")
                        migration_module.up(cursor)
                        # 在同一个事务中更新版本号
                        set_version(cursor, version)
                        conn.commit()
                        logger.info(f"成功应用迁移: {filename}")
                    except Exception as e:
                        conn.rollback()
                        logger.error(f"应用迁移失败: {filename}。错误: {e}")
                        raise
            except Exception as e:
                logger.error(f"加载迁移脚本失败: {migration_path}。错误: {e}")
                raise
