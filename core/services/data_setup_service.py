from ..repositories.abstract_repository import (
    AbstractItemTemplateRepository,
    AbstractGachaRepository,
    AbstractShopRepository,
)
from ..initial_data import (
    FISH_DATA,
    BAIT_DATA,
    ROD_DATA,
    ACCESSORY_DATA,
    GACHA_POOL,
    GACHA_POOL_ITEMS,
    ITEM_DATA,
    SHOP_DATA,
    ZONE_PASS_NAME,
    ZONE_PASS_PRICE,
)
from ..domain.models import Item
from astrbot.api import logger


class DataSetupService:
    """负责在首次启动时初始化游戏基础数据。"""

    def __init__(
        self,
        item_template_repo: AbstractItemTemplateRepository,
        gacha_repo: AbstractGachaRepository,
        shop_repo: AbstractShopRepository,
        user_repo=None,
        inventory_repo=None,
    ):
        """
        初始化数据设置服务。

        Args:
            item_template_repo: 物品模板仓储的实例，用于与数据库交互。
            gacha_repo: 抽卡仓储的实例。
            shop_repo: 商店仓储的实例。
            user_repo: 用户仓储实例。
            inventory_repo: 库存仓储实例，用于把通行证关联到钓鱼区域。
        """
        self.gacha_repo = gacha_repo
        self.item_template_repo = item_template_repo
        self.shop_repo = shop_repo
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo

    def setup_initial_data(self):
        """
        检查核心数据表是否为空，如果为空则进行数据填充。
        这是一个幂等操作（idempotent），可以安全地多次调用而不会重复插入数据。
        """
        try:
            existing_fish = self.item_template_repo.get_all_fish()
            if existing_fish:
                logger.info("数据库核心数据已存在，跳过初始化。")
                return
        except Exception as e:
            # 如果表不存在等数据库错误，也需要继续执行创建和插入
            logger.error(f"检查数据时发生错误 (可能是表不存在，将继续初始化): {e}")

        logger.info("检测到数据库为空或核心数据不完整，正在初始化游戏数据...")

        # 填充鱼类数据
        for fish in FISH_DATA:
            self.item_template_repo.add_fish_template({
                "name": fish[0],
                "description": fish[1],
                "rarity": fish[2],
                "base_value": fish[3],
                "min_weight": fish[4],
                "max_weight": fish[5],
                "icon_url": fish[6]
            })

        # 填充鱼饵数据
        for bait in BAIT_DATA:
            self.item_template_repo.add_bait_template({
                "name": bait[0],
                "description": bait[1],
                "rarity": bait[2],
                "effect_description": bait[3],
                "duration_minutes": bait[4],
                "cost": bait[5],
                "required_rod_rarity": bait[6],
                "success_rate_modifier": bait[7],
                "rare_chance_modifier": bait[8],
                "garbage_reduction_modifier": bait[9],
                "value_modifier": bait[10],
                "quantity_modifier": bait[11],
                "weight_modifier": bait[12],
                "is_consumable": bait[13],
            })

        # 填充鱼竿数据
        for rod in ROD_DATA:
            self.item_template_repo.add_rod_template({
                "name": rod[0],
                "description": rod[1],
                "rarity": rod[2],
                "source": rod[3],
                "purchase_cost": rod[4],
                "bonus_fish_quality_modifier": rod[5],
                "bonus_fish_quantity_modifier": rod[6],
                "bonus_rare_fish_chance": rod[7],
                "durability": rod[8],
                "icon_url": rod[9]
            })

        # 填充饰品数据
        for acc in ACCESSORY_DATA:
            self.item_template_repo.add_accessory_template({
                "name": acc[0],
                "description": acc[1],
                "rarity": acc[2],
                "slot_type": acc[3],
                "bonus_fish_quality_modifier": acc[4],
                "bonus_fish_quantity_modifier": acc[5],
                "bonus_rare_fish_chance": acc[6],
                "bonus_coin_modifier": acc[7],
                "other_bonus_description": acc[8],
                "icon_url": acc[9],
                "cooldown_modifier": acc[10],
            })


        for pool in GACHA_POOL:
            self.gacha_repo.add_pool_template(
                {
                    "pool_id": pool[0],
                    "name": pool[1],
                    "description": pool[2],
                    "cost_coins": pool[3],
                }
            )

        # 填充道具数据
        self.create_initial_items()

        # --- 填充抽卡池具体物品 ---
        self._fill_gacha_pools()

        # 区域三需要通行证才能进入
        self._link_zone_pass()

        # --- 填充初始商店 ---
        if not self.shop_repo.get_all_shops():
            logger.info("正在初始化商店...")
            for shop_data in SHOP_DATA:
                self.shop_repo.create_shop({
                    "name": shop_data[1],
                    "description": shop_data[2],
                    "shop_type": shop_data[3],
                    "is_active": shop_data[4],
                    "start_time": shop_data[5],
                    "end_time": shop_data[6],
                    "sort_order": shop_data[7],
                })
            
            # 使用统一的方法填充商店1商品
            self._ensure_shop1_default_items()
            logger.info("初始商店与商品填充完成。")

        logger.info("核心游戏数据初始化完成。")

    def _template_id(self, kind: str, name: str):
        """按名称查找模板 ID，找不到时返回 None。"""
        getters = {
            "rod": (self.item_template_repo.get_all_rods, "rod_id"),
            "accessory": (self.item_template_repo.get_all_accessories, "accessory_id"),
            "bait": (self.item_template_repo.get_all_baits, "bait_id"),
            "item": (self.item_template_repo.get_all_items, "item_id"),
        }
        getter, id_field = getters[kind]
        for template in getter():
            if template.name == name:
                return getattr(template, id_field)
        return None

    def _fill_gacha_pools(self):
        """给还没有内容的内置卡池放入默认物品，已有内容的卡池不动。"""
        filled = {}
        for pool_id, kind, name, quantity, weight in GACHA_POOL_ITEMS:
            if pool_id not in filled:
                filled[pool_id] = bool(self.gacha_repo.get_pool_items(pool_id))
            if filled[pool_id]:
                continue
            item_id = 0 if kind == "coins" else self._template_id(kind, name)
            if item_id is None:
                logger.warning(f"卡池 {pool_id} 的默认物品 {name} 不存在，已跳过")
                continue
            self.gacha_repo.add_item_to_pool(
                pool_id, {"item_full_id": f"{kind}-{item_id}", "quantity": quantity, "weight": weight}
            )

    def _link_zone_pass(self):
        """新库里给区域三设置通行证要求。"""
        if not self.inventory_repo:
            return
        pass_id = self._template_id("item", ZONE_PASS_NAME)
        if pass_id is not None:
            self.inventory_repo.set_zone_pass_requirement(3, pass_id)

    def sync_shops_from_initial_data(self):
        """
        手动从 initial_data.py 同步商店和基础商品到数据库。
        这是一个幂等操作，可以安全地多次调用。
        """
        logger.info("正在从 initial_data.py 同步商店...")
        
        # 先确保基础数据已初始化
        self.setup_initial_data()
        
        # --- 填充初始商店 ---
        all_shops = self.shop_repo.get_all_shops()
        existing_shop_names = {s['name'] for s in all_shops}
        
        for shop_data in SHOP_DATA:
            if shop_data[1] not in existing_shop_names:
                self.shop_repo.create_shop({
                    "name": shop_data[1],
                    "description": shop_data[2],
                    "shop_type": shop_data[3],
                    "is_active": shop_data[4],
                    "start_time": shop_data[5],
                    "end_time": shop_data[6],
                    "sort_order": shop_data[7],
                })
                logger.info(f"创建新商店: {shop_data[1]}")

        # --- 为海鸥港杂货铺添加初始商品 ---
        self._ensure_shop1_default_items()

        logger.info("商店数据同步完成。")

    def _ensure_shop1_default_items(self):
        """确保商店1有默认商品（新设计：直接创建shop_items）"""
        logger.info("正在确保商店1有默认商品...")
        
        # 获取商店1的现有商品
        shop1_items = self.shop_repo.get_shop_items(1)
        existing_item_names = {item["name"] for item in shop1_items}

        # 添加所有3星以下的鱼竿到商店1
        rod_items = []
        for rod_data in ROD_DATA:
            if rod_data[2] <= 3 and rod_data[3] == "shop" and rod_data[4] and rod_data[4] > 0:  # rarity <= 3, source=shop, has cost
                rod_items.append(rod_data)
        
        for rod_data in rod_items:
            rod_name = rod_data[0]
            rod_id = ROD_DATA.index(rod_data) + 1
            
            # 检查是否已存在同名商品
            if rod_name in existing_item_names:
                logger.info(f"鱼竿商品已存在: {rod_name}")
                continue
            
            # 创建新商品
            rod_description = rod_data[1] if len(rod_data) > 1 else ""
            logger.info(f"创建鱼竿商品: {rod_name}, 描述: {rod_description}")
            
            # 创建商品
            item_data = {
                "name": rod_name,
                "description": rod_description,
                "category": "basic",
                "is_active": True,
                "sort_order": rod_data[2] * 10,  # 按稀有度排序
            }
            created_item = self.shop_repo.create_shop_item(1, item_data)
            item_id = created_item["item_id"]
            
            # 添加成本
            self.shop_repo.add_item_cost(item_id, {
                "cost_type": "coins",
                "cost_amount": rod_data[4],
                "cost_relation": "and",
            })
            
            # 添加奖励
            self.shop_repo.add_item_reward(item_id, {
                "reward_type": "rod",
                "reward_item_id": rod_id,
                "reward_quantity": 1,
                "reward_refine_level": 1,
            })
            
            logger.info(f"已上架鱼竿: {rod_name}")

        # 添加所有有成本的鱼饵到商店1
        bait_items = []
        for bait_data in BAIT_DATA:
            if bait_data[5] > 0:  # has cost > 0
                bait_items.append(bait_data)
        
        for bait_data in bait_items:
            bait_name = bait_data[0]
            bait_id = BAIT_DATA.index(bait_data) + 1
            
            # 检查是否已存在同名商品
            if bait_name in existing_item_names:
                logger.info(f"鱼饵商品已存在: {bait_name}")
                continue
            
            # 创建新商品
            bait_description = bait_data[1] if len(bait_data) > 1 else ""
            logger.info(f"创建鱼饵商品: {bait_name}, 描述: {bait_description}")
            
            # 创建商品
            item_data = {
                "name": bait_name,
                "description": bait_description,
                "category": "basic",
                "is_active": True,
                "sort_order": bait_data[2] * 10 + 100,  # 鱼饵排在鱼竿后面
            }
            created_item = self.shop_repo.create_shop_item(1, item_data)
            item_id = created_item["item_id"]
            
            # 添加成本
            self.shop_repo.add_item_cost(item_id, {
                "cost_type": "coins",
                "cost_amount": bait_data[5],
                "cost_relation": "and",
            })
            
            # 添加奖励
            self.shop_repo.add_item_reward(item_id, {
                "reward_type": "bait",
                "reward_item_id": bait_id,
                "reward_quantity": 1,
                "reward_refine_level": 1,
            })
            
            logger.info(f"已上架鱼饵: {bait_name}")

        # 区域三的通行证
        pass_id = self._template_id("item", ZONE_PASS_NAME)
        if pass_id is not None and ZONE_PASS_NAME not in existing_item_names:
            created_item = self.shop_repo.create_shop_item(1, {
                "name": ZONE_PASS_NAME,
                "description": "在区域三「传说之海」钓鱼的门票：每天第一次钓鱼时消耗 1 张，当天有效。",
                "category": "basic",
                "is_active": True,
                "sort_order": 200,
            })
            item_id = created_item["item_id"]
            self.shop_repo.add_item_cost(item_id, {
                "cost_type": "coins",
                "cost_amount": ZONE_PASS_PRICE,
                "cost_relation": "and",
            })
            self.shop_repo.add_item_reward(item_id, {
                "reward_type": "item",
                "reward_item_id": pass_id,
                "reward_quantity": 1,
                "reward_refine_level": 1,
            })
            logger.info(f"已上架通行证: {ZONE_PASS_NAME}")

    def sync_all_initial_data(self):
        """
        手动从 initial_data.py 同步所有设计为可同步的数据（如道具、商店）。
        """
        logger.info("--- 开始同步所有初始设定 ---")
        self.create_initial_items()
        self.sync_shops_from_initial_data()
        logger.info("--- 所有初始设定同步完成 ---")

    def create_initial_items(self):
        """创建初始的道具"""
        existing_items = self.item_template_repo.get_all()
        existing_item_names = {item.name for item in existing_items}

        items_to_create = []
        for item_data in ITEM_DATA:
            if item_data[1] not in existing_item_names:
                items_to_create.append(
                    Item(
                        item_id=0,  # ID is auto-incrementing
                        name=item_data[1],
                        description=item_data[2],
                        rarity=item_data[3],
                        effect_description=item_data[4],
                        cost=item_data[5],
                        is_consumable=item_data[6],
                        icon_url=item_data[7],
                        effect_type=item_data[8],
                        effect_payload=item_data[9],
                    )
                )

        if items_to_create:
            logger.info(f"发现 {len(items_to_create)} 个新的道具，正在添加到数据库...")
            for item in items_to_create:
                self.item_template_repo.add(item)
            logger.info("新道具添加完成。")
        else:
            logger.info("没有发现新的道具需要添加。")
