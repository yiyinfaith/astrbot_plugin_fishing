import sqlite3
from datetime import datetime
from typing import Optional

from ..database.connection_manager import DatabaseConnectionManager
from ..domain.models import MarketListing
from ..utils import get_now
from .abstract_repository import AbstractMarketRepository


_LISTINGS_FROM = """
FROM market m
LEFT JOIN users u ON m.user_id = u.user_id
LEFT JOIN rods r ON m.item_type = 'rod' AND m.item_id = r.rod_id
LEFT JOIN accessories a ON m.item_type = 'accessory' AND m.item_id = a.accessory_id
LEFT JOIN items i ON m.item_type = 'item' AND m.item_id = i.item_id
LEFT JOIN fish f ON m.item_type = 'fish' AND m.item_id = f.fish_id
"""
_LISTINGS_SELECT = """
SELECT m.market_id, m.user_id, m.item_type, m.item_id, m.item_instance_id,
       m.quantity, m.price, m.refine_level, m.listed_at, m.expires_at,
       m.is_anonymous, m.quality_level,
       COALESCE(u.nickname, m.seller_nickname) AS seller_nickname,
       COALESCE(r.name, a.name, i.name, f.name, m.item_name) AS item_name,
       COALESCE(r.description, a.description, i.description, f.description, m.item_description) AS item_description
""" + _LISTINGS_FROM


class SqliteMarketRepository(AbstractMarketRepository):
    def __init__(self, db_path: str, connection_manager: DatabaseConnectionManager | None = None):
        self._connection_manager = connection_manager or DatabaseConnectionManager(db_path)

    @staticmethod
    def _row_to_market_listing(row: sqlite3.Row) -> MarketListing:
        data = dict(row)
        data["listed_at"] = datetime.fromisoformat(data["listed_at"].replace("Z", "+00:00"))
        if data["expires_at"]:
            data["expires_at"] = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        return MarketListing(**data)

    def get_listing_by_id(self, market_id: int) -> Optional[MarketListing]:
        with self._connection_manager.get_connection() as conn:
            row = conn.execute(_LISTINGS_SELECT + " WHERE m.market_id = ?", (market_id,)).fetchone()
            return self._row_to_market_listing(row) if row else None

    def get_all_listings(self, page: int = None, per_page: int = None,
                         item_type: str = None, min_price: int = None,
                         max_price: int = None, search: str = None) -> tuple:
        filters = []
        params = []
        for condition, value in (
            ("m.item_type = ?", item_type), ("m.price >= ?", min_price), ("m.price <= ?", max_price),
        ):
            if value is not None:
                filters.append(condition)
                params.append(value)
        if search:
            filters.append(
                "(COALESCE(r.name, a.name, i.name, f.name, m.item_name) LIKE ? "
                "OR COALESCE(u.nickname, m.seller_nickname) LIKE ?)"
            )
            params.extend([f"%{search}%"] * 2)

        where = " WHERE " + " AND ".join(filters) if filters else ""
        sql = _LISTINGS_SELECT + where + " ORDER BY m.listed_at DESC, m.market_id DESC"
        with self._connection_manager.get_connection() as conn:
            if page is None or per_page is None:
                rows = conn.execute(sql, params).fetchall()
                total_count = len(rows)
            else:
                total_count = conn.execute("SELECT COUNT(*) " + _LISTINGS_FROM + where, params).fetchone()[0]
                rows = conn.execute(sql + " LIMIT ? OFFSET ?", (*params, per_page, (page - 1) * per_page)).fetchall()
        return [self._row_to_market_listing(row) for row in rows], total_count

    def add_listing(self, listing: MarketListing) -> None:
        with self._connection_manager.get_connection() as conn:
            conn.execute("""
                INSERT INTO market (
                    user_id, seller_nickname, item_type, item_id, item_name, item_description,
                    quantity, price, listed_at, refine_level, is_anonymous, item_instance_id, quality_level, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                listing.user_id, listing.seller_nickname, listing.item_type, listing.item_id,
                listing.item_name, listing.item_description, listing.quantity, listing.price,
                listing.listed_at or get_now(), listing.refine_level, listing.is_anonymous,
                listing.item_instance_id, listing.quality_level, listing.expires_at,
            ))

    def remove_listing(self, market_id: int) -> None:
        with self._connection_manager.get_connection() as conn:
            conn.execute("DELETE FROM market WHERE market_id = ?", (market_id,))

    def update_listing(self, listing: MarketListing) -> None:
        with self._connection_manager.get_connection() as conn:
            conn.execute(
                "UPDATE market SET price = ?, refine_level = ? WHERE market_id = ?",
                (listing.price, listing.refine_level, listing.market_id),
            )
