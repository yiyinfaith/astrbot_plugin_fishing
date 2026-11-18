"""1.0.0 数据库结构。

全新安装时一次建好所有表、索引和必要的初始数据（钓鱼区域、水族箱升级档位）。
鱼类、装备、道具、商店、卡池等游戏内容由 DataSetupService 写入。
"""

import sqlite3

SCHEMA_MARK = "fishing-1.0.0"

TABLES = [
    """
    CREATE TABLE IF NOT EXISTS db_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        nickname TEXT,
        coins INTEGER DEFAULT 200,
        total_fishing_count INTEGER DEFAULT 0,
        total_weight_caught INTEGER DEFAULT 0,
        total_coins_earned INTEGER DEFAULT 0,
        equipped_rod_instance_id INTEGER,
        equipped_accessory_instance_id INTEGER,
        current_bait_id INTEGER,
        bait_start_time DATETIME,
        auto_fishing_enabled INTEGER DEFAULT 0,
        last_fishing_time DATETIME,
        last_steal_time DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_login_time DATETIME,
        consecutive_login_days INTEGER DEFAULT 0,
        fish_pond_capacity INTEGER DEFAULT 480,
        last_stolen_at DATETIME,
        fishing_zone_id INTEGER DEFAULT 1,
        aquarium_capacity INTEGER DEFAULT 50,
        last_electric_fish_time DATETIME,
        max_coins INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fish (
        fish_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        rarity INTEGER NOT NULL CHECK (rarity >= 1),
        base_value INTEGER NOT NULL,
        min_weight INTEGER NOT NULL CHECK (min_weight >= 0),
        max_weight INTEGER NOT NULL CHECK (max_weight > min_weight),
        icon_url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS baits (
        bait_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        rarity INTEGER NOT NULL DEFAULT 1 CHECK (rarity >= 1),
        effect_description TEXT,
        duration_minutes INTEGER DEFAULT 0,
        cost INTEGER DEFAULT 0,
        required_rod_rarity INTEGER DEFAULT 0,
        success_rate_modifier REAL DEFAULT 0.0,
        rare_chance_modifier REAL DEFAULT 0.0,
        garbage_reduction_modifier REAL DEFAULT 0.0,
        value_modifier REAL DEFAULT 1.0,
        quantity_modifier REAL DEFAULT 1.0,
        is_consumable INTEGER DEFAULT 1,
        weight_modifier REAL DEFAULT 1.0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rods (
        rod_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        rarity INTEGER NOT NULL DEFAULT 1,
        source TEXT NOT NULL CHECK (source IN ('shop', 'gacha', 'event')),
        purchase_cost INTEGER,
        bonus_fish_quality_modifier REAL DEFAULT 1.0,
        bonus_fish_quantity_modifier REAL DEFAULT 1.0,
        bonus_rare_fish_chance REAL DEFAULT 0.0,
        durability INTEGER,
        icon_url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accessories (
        accessory_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        rarity INTEGER NOT NULL DEFAULT 1,
        slot_type TEXT DEFAULT 'general' NOT NULL,
        bonus_fish_quality_modifier REAL DEFAULT 1.0,
        bonus_fish_quantity_modifier REAL DEFAULT 1.0,
        bonus_rare_fish_chance REAL DEFAULT 0.0,
        bonus_coin_modifier REAL DEFAULT 1.0,
        other_bonus_description TEXT,
        icon_url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        rarity INTEGER NOT NULL DEFAULT 1,
        effect_description TEXT,
        cost INTEGER DEFAULT 0,
        is_consumable INTEGER DEFAULT 1,
        icon_url TEXT,
        effect_type TEXT,
        effect_payload TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fishing_zones (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        daily_rare_fish_quota INTEGER NOT NULL,
        rare_fish_caught_today INTEGER NOT NULL DEFAULT 0,
        configs TEXT,
        is_active INTEGER DEFAULT 1,
        available_from TEXT,
        available_until TEXT,
        required_item_id INTEGER,
        requires_pass BOOLEAN DEFAULT 0,
        fishing_cost INTEGER DEFAULT 10
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zone_fish_mapping (
        zone_id INTEGER,
        fish_id INTEGER,
        PRIMARY KEY (zone_id, fish_id),
        FOREIGN KEY (zone_id) REFERENCES fishing_zones(id) ON DELETE CASCADE,
        FOREIGN KEY (fish_id) REFERENCES fish(fish_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aquarium_upgrades (
        upgrade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        level INTEGER NOT NULL UNIQUE,
        capacity INTEGER NOT NULL,
        cost_coins INTEGER NOT NULL,
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_fish_inventory (
        user_id TEXT NOT NULL,
        fish_id INTEGER NOT NULL,
        quality_level INTEGER DEFAULT 0 CHECK (quality_level IN (0, 1)),
        quantity INTEGER DEFAULT 0 CHECK (quantity >= 0),
        no_sell_until DATETIME,
        PRIMARY KEY (user_id, fish_id, quality_level),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (fish_id) REFERENCES fish(fish_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_aquarium (
        user_id TEXT NOT NULL,
        fish_id INTEGER NOT NULL,
        quality_level INTEGER DEFAULT 0 CHECK (quality_level IN (0, 1)),
        quantity INTEGER DEFAULT 0 CHECK (quantity >= 0),
        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, fish_id, quality_level),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (fish_id) REFERENCES fish(fish_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_bait_inventory (
        user_id TEXT NOT NULL,
        bait_id INTEGER NOT NULL,
        quantity INTEGER DEFAULT 0 CHECK (quantity >= 0),
        PRIMARY KEY (user_id, bait_id),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (bait_id) REFERENCES baits(bait_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_rods (
        rod_instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        rod_id INTEGER NOT NULL,
        obtained_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        current_durability INTEGER,
        is_equipped INTEGER DEFAULT 0 CHECK (is_equipped IN (0, 1)),
        refine_level INTEGER DEFAULT 1,
        is_locked INTEGER DEFAULT 0 CHECK (is_locked IN (0, 1)),
        display_code TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (rod_id) REFERENCES rods(rod_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_accessories (
        accessory_instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        accessory_id INTEGER NOT NULL,
        obtained_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_equipped INTEGER DEFAULT 0 CHECK (is_equipped IN (0, 1)),
        refine_level INTEGER DEFAULT 1,
        is_locked INTEGER DEFAULT 0 CHECK (is_locked IN (0, 1)),
        display_code TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (accessory_id) REFERENCES accessories(accessory_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_items (
        user_id TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        quantity INTEGER DEFAULT 0 CHECK (quantity >= 0),
        PRIMARY KEY (user_id, item_id),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (item_id) REFERENCES items(item_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_buffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        buff_type TEXT NOT NULL,
        payload TEXT,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_fish_stats (
        user_id TEXT NOT NULL,
        fish_id INTEGER NOT NULL,
        first_caught_at DATETIME,
        last_caught_at DATETIME,
        max_weight INTEGER NOT NULL,
        min_weight INTEGER NOT NULL,
        total_caught INTEGER NOT NULL DEFAULT 0,
        total_weight INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, fish_id),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (fish_id) REFERENCES fish(fish_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS check_ins (
        user_id TEXT NOT NULL,
        check_in_date DATE NOT NULL,
        PRIMARY KEY (user_id, check_in_date),
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gacha_pools (
        gacha_pool_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        cost_coins INTEGER DEFAULT 0,
        is_limited_time INTEGER DEFAULT 0,
        open_until TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gacha_pool_items (
        gacha_pool_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        gacha_pool_id INTEGER NOT NULL,
        item_type TEXT NOT NULL CHECK (
            item_type IN ('rod', 'accessory', 'bait', 'fish', 'coins', 'item')
        ),
        item_id INTEGER NOT NULL,
        quantity INTEGER DEFAULT 1,
        weight INTEGER NOT NULL CHECK (weight > 0),
        FOREIGN KEY (gacha_pool_id) REFERENCES gacha_pools(gacha_pool_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gacha_records (
        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        gacha_pool_id INTEGER NOT NULL,
        item_type TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        item_name TEXT NOT NULL,
        quantity INTEGER DEFAULT 1,
        rarity INTEGER DEFAULT 1,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (gacha_pool_id) REFERENCES gacha_pools(gacha_pool_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market (
        market_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        item_type TEXT NOT NULL CHECK (item_type IN ('rod', 'accessory', 'item', 'fish')),
        item_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        price INTEGER NOT NULL,
        listed_at TEXT NOT NULL,
        expires_at TEXT,
        refine_level INTEGER DEFAULT 1,
        seller_nickname TEXT,
        item_name TEXT,
        item_description TEXT,
        item_instance_id INTEGER,
        is_anonymous INTEGER DEFAULT 0,
        quality_level INTEGER DEFAULT 0,
        UNIQUE (user_id, item_type, item_id, quality_level, item_instance_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shops (
        shop_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        shop_type TEXT NOT NULL DEFAULT 'normal' CHECK (shop_type IN ('normal', 'premium', 'limited')),
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        start_time DATETIME,
        end_time DATETIME,
        daily_start_time TIME,
        daily_end_time TIME,
        sort_order INTEGER DEFAULT 100 NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shop_items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        shop_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        category TEXT DEFAULT 'general' NOT NULL,
        stock_total INTEGER,
        stock_sold INTEGER DEFAULT 0 NOT NULL,
        per_user_limit INTEGER,
        per_user_daily_limit INTEGER,
        is_active BOOLEAN DEFAULT TRUE NOT NULL,
        start_time DATETIME,
        end_time DATETIME,
        sort_order INTEGER DEFAULT 100 NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME,
        FOREIGN KEY (shop_id) REFERENCES shops(shop_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shop_item_costs (
        cost_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        cost_type TEXT NOT NULL CHECK (cost_type IN ('coins', 'item', 'fish', 'rod', 'accessory')),
        cost_amount INTEGER NOT NULL CHECK (cost_amount > 0),
        cost_item_id INTEGER,
        cost_relation TEXT DEFAULT 'and' CHECK (cost_relation IN ('and', 'or')),
        group_id INTEGER,
        quality_level INTEGER DEFAULT 0,
        FOREIGN KEY (item_id) REFERENCES shop_items(item_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shop_item_rewards (
        reward_id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER NOT NULL,
        reward_type TEXT NOT NULL CHECK (reward_type IN ('rod', 'accessory', 'bait', 'item', 'fish', 'coins')),
        reward_item_id INTEGER,
        reward_quantity INTEGER NOT NULL DEFAULT 1 CHECK (reward_quantity > 0),
        reward_refine_level INTEGER,
        quality_level INTEGER DEFAULT 0,
        FOREIGN KEY (item_id) REFERENCES shop_items(item_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shop_purchase_records (
        record_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES shop_items(item_id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_users_coins ON users(coins)",
    "CREATE INDEX IF NOT EXISTS idx_users_last_login ON users(last_login_time)",
    "CREATE INDEX IF NOT EXISTS idx_user_bait_inventory_user ON user_bait_inventory(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_rods_user ON user_rods(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_rods_locked ON user_rods(user_id, is_locked)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_rods_display_code ON user_rods(display_code)",
    "CREATE INDEX IF NOT EXISTS idx_user_accessories_user ON user_accessories(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_accessories_locked ON user_accessories(user_id, is_locked)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_accessories_display_code ON user_accessories(display_code)",
    "CREATE INDEX IF NOT EXISTS idx_user_buffs_user_id ON user_buffs(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_buffs_expires_at ON user_buffs(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_user_fish_stats_user ON user_fish_stats(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_fish_stats_fish ON user_fish_stats(fish_id)",
    "CREATE INDEX IF NOT EXISTS idx_aquarium_upgrades_level ON aquarium_upgrades(level)",
    "CREATE INDEX IF NOT EXISTS idx_gacha_pool_items_pool_type ON gacha_pool_items(gacha_pool_id, item_type)",
    "CREATE INDEX IF NOT EXISTS idx_gacha_records_user_time ON gacha_records(user_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_market_user_item_quality ON market(user_id, item_type, item_id, quality_level)",
    "CREATE INDEX IF NOT EXISTS idx_market_item_quality ON market(item_type, item_id, quality_level)",
    "CREATE INDEX IF NOT EXISTS idx_shops_active_time ON shops(is_active, start_time, end_time)",
    "CREATE INDEX IF NOT EXISTS idx_shops_type ON shops(shop_type)",
    "CREATE INDEX IF NOT EXISTS idx_shops_daily_time ON shops(daily_start_time, daily_end_time)",
    "CREATE INDEX IF NOT EXISTS idx_shop_items_shop ON shop_items(shop_id)",
    "CREATE INDEX IF NOT EXISTS idx_shop_items_active_time ON shop_items(is_active, start_time, end_time)",
    "CREATE INDEX IF NOT EXISTS idx_shop_items_category ON shop_items(category)",
    "CREATE INDEX IF NOT EXISTS idx_shop_item_costs_item ON shop_item_costs(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_shop_item_costs_type ON shop_item_costs(cost_type)",
    "CREATE INDEX IF NOT EXISTS idx_shop_item_costs_relation ON shop_item_costs(cost_relation)",
    "CREATE INDEX IF NOT EXISTS idx_shop_item_costs_group ON shop_item_costs(group_id)",
    "CREATE INDEX IF NOT EXISTS idx_shop_item_costs_fish_quality ON shop_item_costs(cost_type, cost_item_id, quality_level) "
    "WHERE cost_type = 'fish'",
    "CREATE INDEX IF NOT EXISTS idx_shop_item_rewards_item ON shop_item_rewards(item_id)",
    "CREATE INDEX IF NOT EXISTS idx_shop_item_rewards_type ON shop_item_rewards(reward_type)",
    "CREATE INDEX IF NOT EXISTS idx_shop_purchase_user_item ON shop_purchase_records(user_id, item_id)",
    "CREATE INDEX IF NOT EXISTS idx_shop_purchase_time ON shop_purchase_records(timestamp)",
]

# (id, 名称, 描述, 每日稀有鱼配额, 稀有度分布, 钓鱼花费)
FISHING_ZONES = [
    (1, "区域一：新手港湾", "只能钓到0-4星鱼，4星鱼概率很低。", 50, "[0.6, 0.3, 0.08, 0.02, 0]", 10),
    (2, "区域二：深海峡谷", "4星鱼概率提升，有极小概率钓到5星鱼。", 2000, "[0.4, 0.3, 0.2, 0.09, 0.01]", 60),
    (3, "区域三：传说之海", "5星鱼概率大幅提升。", 500, "[0.3, 0.2, 0.2, 0.2, 0.1]", 110),
]

# (等级, 容量, 金币花费, 描述)
AQUARIUM_UPGRADES = [
    (1, 50, 0, "初始水族箱容量"),
    (2, 100, 10000, "升级到100容量"),
    (3, 150, 25000, "升级到150容量"),
    (4, 200, 50000, "升级到200容量"),
    (5, 300, 100000, "升级到300容量"),
    (6, 500, 200000, "升级到500容量"),
    (7, 750, 500000, "升级到750容量"),
    (8, 1000, 1000000, "升级到1000容量"),
    (9, 1500, 2000000, "升级到1500容量"),
    (10, 2000, 5000000, "升级到2000容量"),
]


def up(cursor: sqlite3.Cursor):
    for sql in TABLES:
        cursor.execute(sql)
    for sql in INDEXES:
        cursor.execute(sql)
    cursor.execute("INSERT OR REPLACE INTO db_meta (key, value) VALUES ('schema', ?)", (SCHEMA_MARK,))
    for zone_id, name, description, quota, distribution, cost in FISHING_ZONES:
        cursor.execute(
            "INSERT OR IGNORE INTO fishing_zones "
            "(id, name, description, daily_rare_fish_quota, configs, fishing_cost) VALUES (?, ?, ?, ?, ?, ?)",
            (zone_id, name, description, quota, '{"rarity_distribution": %s}' % distribution, cost),
        )
    for level, capacity, cost, description in AQUARIUM_UPGRADES:
        cursor.execute(
            "INSERT OR IGNORE INTO aquarium_upgrades (level, capacity, cost_coins, description) "
            "VALUES (?, ?, ?, ?)",
            (level, capacity, cost, description),
        )
