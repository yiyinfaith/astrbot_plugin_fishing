import os

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

# ==========================================================
# 导入仓储和服务
# ==========================================================
from .core.repositories.sqlite_user_repo import SqliteUserRepository
from .core.repositories.sqlite_item_template_repo import SqliteItemTemplateRepository
from .core.repositories.sqlite_inventory_repo import SqliteInventoryRepository
from .core.repositories.sqlite_gacha_repo import SqliteGachaRepository
from .core.repositories.sqlite_market_repo import SqliteMarketRepository
from .core.repositories.sqlite_shop_repo import SqliteShopRepository
from .core.repositories.sqlite_log_repo import SqliteLogRepository
from .core.repositories.sqlite_user_buff_repo import SqliteUserBuffRepository

from .core.services.data_setup_service import DataSetupService
from .core.services.item_template_service import ItemTemplateService
from .core.services.user_service import UserService
from .core.services.fishing_service import FishingService
from .core.services.inventory_service import InventoryService
from .core.services.shop_service import ShopService
from .core.services.market_service import MarketService
from .core.services.gacha_service import GachaService
from .core.services.game_mechanics_service import GameMechanicsService
from .core.services.effect_manager import EffectManager
from .core.services.fishing_zone_service import FishingZoneService
from .core.services.fish_weight_service import FishWeightService

from .core.database.connection_manager import DatabaseConnectionManager
from .core.database.migration import run_migrations
from .core.game_settings import build_fishing_rules, build_pond_upgrades, build_refine, build_signin

# ==========================================================
# 导入所有指令函数
# ==========================================================
from .handlers import (
    common_handlers,
    inventory_handlers,
    market_handlers,
    social_handlers,
    gacha_handlers,
    aquarium_handlers,
)
from .handlers.fishing_handlers import FishingHandlers
from .webui import FishingAdminAPI

PLUGIN_NAME = "astrbot_plugin_fishing"


class FishingPlugin(Star):

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        # --- 1. 加载配置 ---

        # 插件数据统一放在 AstrBot 的 data/plugin_data/<插件名> 下
        self.plugin_id = PLUGIN_NAME
        self.data_dir = str(StarTools.get_data_dir(PLUGIN_NAME))

        self.tmp_dir = os.path.join(self.data_dir, "tmp")
        os.makedirs(self.tmp_dir, exist_ok=True)

        db_path = os.path.join(self.data_dir, "fish.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # --- 1.2. 配置数据完整性检查注释 ---
        # 以下配置项必须在此处从 AstrBotConfig 中提取并放入 game_config，
        # 以确保所有服务在接收 game_config 时能够正确读取配置值
        # 
        # 配置数据流：_conf_schema.json → AstrBotConfig (config) → game_config → 各个服务
        # 
        # 从框架读取嵌套配置
        # 注意：框架会自动解析 _conf_schema.json 中的嵌套对象
        fishing_config = config.get("fishing", {})
        steal_config = config.get("steal", {})
        electric_fish_config = config.get("electric_fish", {})
        game_global_config = config.get("game", {})
        user_config = config.get("user", {})
        market_config = config.get("market", {})
        sell_prices_config = config.get("sell_prices", {})
        fishing_rules = build_fishing_rules(fishing_config)
        
        self.game_config = {
            "fishing": {
                "cooldown_seconds": fishing_config.get("cooldown_seconds", 180),
                "auto_fishing_efficiency": fishing_config.get("auto_fishing_efficiency", 0.5),
                "base_success_rate": fishing_rules["base_success_rate"],
                "mythic_weights": fishing_rules["mythic_weights"],
            },
            "signin": build_signin(config.get("signin", {})),
            "refine": build_refine(config.get("refine", {})),
            "quality_bonus_max_chance": fishing_config.get("quality_bonus_max_chance", 0.35),
            "steal": {
                "cooldown_seconds": steal_config.get("cooldown_seconds", 14400)
            },
            "electric_fish": {
                "enabled": electric_fish_config.get("enabled", True),
                "cooldown_seconds": electric_fish_config.get("cooldown_seconds", 7200),
                "base_success_rate": electric_fish_config.get("base_success_rate", 0.6),
                "failure_penalty_max_rate": electric_fish_config.get("failure_penalty_max_rate", 0.5),
                "failure_penalty_cap": electric_fish_config.get("failure_penalty_cap", 5000),
                "max_catch": max(1, int(electric_fish_config.get("max_catch", 50) or 50)),
            },
            "daily_reset_hour": game_global_config.get("daily_reset_hour", 0),
            "user": {
                "initial_coins": user_config.get("initial_coins", 200),
                "transfer_fee_rate": user_config.get("transfer_fee_rate", 0.05),
            },
            "market": {
                "listing_tax_rate": market_config.get("listing_tax_rate", 0.05)
            },
            "pond_upgrades": build_pond_upgrades(config.get("pond", {})),
            "sell_prices": {
                "rod": { 
                    "1": sell_prices_config.get("by_rarity_1", 100),
                    "2": sell_prices_config.get("by_rarity_2", 500),
                    "3": sell_prices_config.get("by_rarity_3", 2000),
                    "4": sell_prices_config.get("by_rarity_4", 5000),
                    "5": sell_prices_config.get("by_rarity_5", 10000),
                    "6": sell_prices_config.get("by_rarity_6", 20000),
                    "7": sell_prices_config.get("by_rarity_7", 50000),
                    "8": sell_prices_config.get("by_rarity_8", 100000),
                    "9": sell_prices_config.get("by_rarity_9", 200000),
                    "10": sell_prices_config.get("by_rarity_10", 500000)
                },
                "accessory": { 
                    "1": sell_prices_config.get("by_rarity_1", 100),
                    "2": sell_prices_config.get("by_rarity_2", 500),
                    "3": sell_prices_config.get("by_rarity_3", 2000),
                    "4": sell_prices_config.get("by_rarity_4", 5000),
                    "5": sell_prices_config.get("by_rarity_5", 10000),
                    "6": sell_prices_config.get("by_rarity_6", 20000),
                    "7": sell_prices_config.get("by_rarity_7", 50000),
                    "8": sell_prices_config.get("by_rarity_8", 100000),
                    "9": sell_prices_config.get("by_rarity_9", 200000),
                    "10": sell_prices_config.get("by_rarity_10", 500000)
                },
                "refine_multiplier": {
                    "1": 1.0, "2": 1.6, "3": 3.0, "4": 6.0, "5": 12.0,
                    "6": 25.0, "7": 55.0, "8": 125.0, "9": 280.0, "10": 660.0
                }
            },
        }
        
        # 初始化数据库模式
        plugin_root_dir = os.path.dirname(__file__)
        migrations_path = os.path.join(plugin_root_dir, "core", "database", "migrations")
        run_migrations(db_path, migrations_path)

        # --- 2. 组合根：实例化所有仓储层 ---
        self.database = DatabaseConnectionManager(db_path)
        self.user_repo = SqliteUserRepository(db_path, self.database)
        self.item_template_repo = SqliteItemTemplateRepository(db_path, self.database)
        self.inventory_repo = SqliteInventoryRepository(db_path, self.database)
        self.gacha_repo = SqliteGachaRepository(db_path, self.database)
        self.market_repo = SqliteMarketRepository(db_path, self.database)
        self.shop_repo = SqliteShopRepository(db_path, self.database)
        self.log_repo = SqliteLogRepository(db_path, self.database)
        self.buff_repo = SqliteUserBuffRepository(db_path, self.database)

        # --- 3. 组合根：实例化所有服务层，并注入依赖 ---
        # 3.1 核心服务必须在效果管理器之前实例化，以解决依赖问题
        self.fishing_zone_service = FishingZoneService(self.item_template_repo, self.inventory_repo, self.game_config)
        self.game_mechanics_service = GameMechanicsService(self.user_repo, self.log_repo, self.inventory_repo,
                                                          self.item_template_repo, self.buff_repo, self.game_config)

        # 3.3 实例化其他核心服务
        self.gacha_service = GachaService(self.gacha_repo, self.user_repo, self.inventory_repo, self.item_template_repo)
        # UserService 依赖 GachaService，因此在 GachaService 之后实例化
        self.user_service = UserService(self.user_repo, self.log_repo, self.inventory_repo, self.item_template_repo, self.gacha_service, self.game_config)
        self.inventory_service = InventoryService(
            self.inventory_repo,
            self.user_repo,
            self.item_template_repo,
            None,  # 先设为None，稍后设置
            self.game_mechanics_service,
            self.game_config,
        )
        self.shop_service = ShopService(self.item_template_repo, self.inventory_repo, self.user_repo, self.shop_repo, self.game_config)
        self.market_service = MarketService(self.market_repo, self.inventory_repo, self.user_repo, self.log_repo,
                                           self.item_template_repo, self.game_config)
        self.fish_weight_service = FishWeightService()
        self.fishing_service = FishingService(
            self.user_repo,
            self.inventory_repo,
            self.item_template_repo,
            self.log_repo,
            self.buff_repo,
            self.fishing_zone_service,
            self.fish_weight_service,
            self.game_config,
        )
        
        # 导入并初始化水族箱服务
        from .core.services.aquarium_service import AquariumService
        self.aquarium_service = AquariumService(
            self.inventory_repo,
            self.user_repo,
            self.item_template_repo
        )
        
        #初始化钓鱼处理器
        self.fishing_handlers = FishingHandlers(self)


        # 3.2 实例化效果管理器并自动注册所有效果（需要在fishing_service之后）
        self.effect_manager = EffectManager()
        self.effect_manager.discover_and_register(
            effects_package_path=f"{__package__}.core.services.item_effects",
            dependencies={
                "user_repo": self.user_repo, 
                "buff_repo": self.buff_repo,
                "game_mechanics_service": self.game_mechanics_service,
                "fishing_service": self.fishing_service,
                "log_repo": self.log_repo,
                "game_config": self.game_config,
            },
        )
        
        # 设置inventory_service的effect_manager
        self.inventory_service.effect_manager = self.effect_manager

        self.item_template_service = ItemTemplateService(self.item_template_repo, self.gacha_repo)

        # --- 4. 初始化核心游戏数据 ---
        data_setup_service = DataSetupService(
            self.item_template_repo, self.gacha_repo, self.shop_repo, self.user_repo,
            inventory_repo=self.inventory_repo,
        )
        with self.database.transaction():
            data_setup_service.setup_initial_data()

        # --- 5. 保留数据服务实例，供面板「同步初始设定」使用 ---
        self.data_setup_service = data_setup_service

        # --- AstrBot 面板内嵌管理页的后端接口 ---
        self.admin_api = FishingAdminAPI(self)
        # AstrBot 热重载时会保留已注册接口，先清理本插件的旧路由。
        route_prefix = f"/{self.plugin_id}/"
        context.registered_web_apis[:] = [
            api for api in context.registered_web_apis if not api[0].startswith(route_prefix)
        ]
        self.admin_api.register(self.context, PLUGIN_NAME)
        self.fishing_service.start_auto_fishing_task()

    async def _guard(self, event: AstrMessageEvent, results):
        """执行一条指令；出错时记录完整日志，并给玩家一个明确的回复，而不是没有反应。"""
        try:
            async for r in results:
                yield r
        except OverflowError:
            yield event.plain_result("❌ 输入的数字太大了，请检查后重试")
        except Exception as e:
            logger.error(f"[钓鱼] 处理指令「{event.message_str}」出错: {e}", exc_info=True)
            yield event.plain_result("❌ 处理指令时出错了，请检查参数后重试")

    def _get_effective_user_id(self, event: AstrMessageEvent):
        """执行指令的玩家 ID，即消息发送者。"""
        return event.get_sender_id()

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        logger.info("""
    _____ _     _     _
    |  ___(_)___| |__ (_)_ __   __ _
    | |_  | / __| '_ \\| | '_ \\ / _` |
    |  _| | \\__ \\ | | | | | | | (_| |
    |_|   |_|___/_| |_|_|_| |_|\\__, |
                               |___/
                               """)
    # =========== 基础与核心 ==========

    @filter.command("钓鱼注册")
    async def register_user(self, event: AstrMessageEvent):
        """注册成为钓鱼游戏玩家，开始你的钓鱼之旅"""
        async for r in self._guard(event, common_handlers.register_user(self, event)):
            yield r

    @filter.command("钓鱼")
    async def fish(self, event: AstrMessageEvent):
        """进行一次钓鱼，消耗金币并获得鱼类或物品"""
        async for r in self._guard(event, self.fishing_handlers.fish(event)):
            yield r

    @filter.command("钓鱼签到")
    async def sign_in(self, event: AstrMessageEvent):
        """每日签到领取金币和每日补给"""
        async for r in self._guard(event, common_handlers.sign_in(self, event)):
            yield r

    @filter.command("自动钓鱼")
    async def auto_fish(self, event: AstrMessageEvent):
        """开启或关闭自动钓鱼，自动钓鱼的出竿频率低于手动"""
        async for r in self._guard(event, self.fishing_handlers.auto_fish(event)):
            yield r

    @filter.command("钓鱼状态", alias={"我的状态"})
    async def state(self, event: AstrMessageEvent):
        """查看当前装备、钓鱼区域、鱼塘容量及扩容价格"""
        async for r in self._guard(event, common_handlers.state(self, event)):
            yield r

    @filter.command("钓鱼帮助", alias={"钓鱼菜单"})
    async def fishing_help(self, event: AstrMessageEvent):
        """查看钓鱼游戏的帮助信息和所有可用命令"""
        async for r in self._guard(event, common_handlers.fishing_help(self, event)):
            yield r

    # =========== 背包与资产 ==========

    @filter.command("钓鱼背包")
    async def user_backpack(self, event: AstrMessageEvent):
        """一次查看全部鱼竿、饰品、鱼饵和道具"""
        async for r in self._guard(event, inventory_handlers.user_backpack(self, event)):
            yield r

    @filter.command("鱼塘")
    async def pond(self, event: AstrMessageEvent):
        """查看你的鱼塘，查看所有已钓到的鱼"""
        async for r in self._guard(event, inventory_handlers.pond(self, event)):
            yield r

    @filter.command("偷看鱼塘", alias={"查看鱼塘", "偷看"})
    async def peek_pond(self, event: AstrMessageEvent):
        """偷看别人的鱼塘，查看其他玩家的鱼。用法：偷看鱼塘 @用户"""
        async for r in self._guard(event, inventory_handlers.peek_pond(self, event)):
            yield r

    @filter.command("升级鱼塘", alias={"鱼塘升级"})
    async def upgrade_pond(self, event: AstrMessageEvent):
        """升级鱼塘容量，可以存放更多的鱼"""
        async for r in self._guard(event, inventory_handlers.upgrade_pond(self, event)):
            yield r

    # 水族箱相关命令
    @filter.command("水族箱")
    async def aquarium(self, event: AstrMessageEvent):
        """查看你的水族箱，欣赏展示的珍贵鱼类"""
        async for r in self._guard(event, aquarium_handlers.aquarium(self, event)):
            yield r

    @filter.command("放入水族箱", alias={"移入水族箱"})
    async def add_to_aquarium(self, event: AstrMessageEvent):
        """将鱼从鱼塘放入水族箱展示。用法：放入水族箱 鱼的编号"""
        async for r in self._guard(event, aquarium_handlers.add_to_aquarium(self, event)):
            yield r

    @filter.command("移出水族箱", alias={"移回鱼塘"})
    async def remove_from_aquarium(self, event: AstrMessageEvent):
        """将鱼从水族箱移回鱼塘。用法：移出水族箱 鱼的编号"""
        async for r in self._guard(event, aquarium_handlers.remove_from_aquarium(self, event)):
            yield r

    @filter.command("升级水族箱", alias={"水族箱升级"})
    async def upgrade_aquarium(self, event: AstrMessageEvent):
        """升级水族箱容量，可以展示更多珍贵鱼类"""
        async for r in self._guard(event, aquarium_handlers.upgrade_aquarium(self, event)):
            yield r

    @filter.command("精炼", alias={"强化"})
    async def refine_equipment(self, event: AstrMessageEvent):
        """精炼装备提升属性。用法：精炼 装备编号"""
        async for r in self._guard(event, inventory_handlers.refine_equipment(self, event)):
            yield r

    @filter.command("出售", alias={"卖出"})
    async def sell_equipment(self, event: AstrMessageEvent):
        """出售装备换取金币。用法：出售 装备编号"""
        async for r in self._guard(event, inventory_handlers.sell_equipment(self, event)):
            yield r

    @filter.command("开启全部钱袋", alias={"打开全部钱袋", "打开所有钱袋"})
    async def open_all_money_bags(self, event: AstrMessageEvent):
        """一次性打开所有钱袋，获得金币"""
        async for r in self._guard(event, inventory_handlers.open_all_money_bags(self, event)):
            yield r

    @filter.command("锁定装备", alias={"上锁"})
    async def lock_equipment(self, event: AstrMessageEvent):
        """锁定装备防止误操作。用法：锁定装备 装备编号"""
        async for r in self._guard(event, inventory_handlers.lock_equipment(self, event)):
            yield r

    @filter.command("解锁装备", alias={"开锁"})
    async def unlock_equipment(self, event: AstrMessageEvent):
        """解锁已锁定的装备。用法：解锁装备 装备编号"""
        async for r in self._guard(event, inventory_handlers.unlock_equipment(self, event)):
            yield r

    @filter.command("使用", alias={"装备"})
    async def use_equipment(self, event: AstrMessageEvent):
        """使用或装备物品。用法：使用 物品编号"""
        async for r in self._guard(event, inventory_handlers.use_equipment(self, event)):
            yield r

    @filter.command("金币", alias={"钱包", "余额"})
    async def coins(self, event: AstrMessageEvent):
        """查看你当前拥有的金币数量"""
        async for r in self._guard(event, inventory_handlers.coins(self, event)):
            yield r

    @filter.command("转账", alias={"赠送"})
    async def transfer_coins(self, event: AstrMessageEvent):
        """转账金币给其他玩家。用法：转账 @用户 金额"""
        async for r in self._guard(event, common_handlers.transfer_coins(self, event)):
            yield r

    @filter.command("更新昵称", alias={"修改昵称", "改昵称", "昵称"})
    async def update_nickname(self, event: AstrMessageEvent):
        """更新你的游戏昵称。用法：更新昵称 新昵称"""
        async for r in self._guard(event, common_handlers.update_nickname(self, event)):
            yield r

    # =========== 钓鱼与图鉴 ==========

    @filter.command("钓鱼区域", alias={"区域"})
    async def fishing_area(self, event: AstrMessageEvent):
        """查看所有钓鱼区域和切换钓鱼区域。用法：钓鱼区域 [区域编号]"""
        async for r in self._guard(event, self.fishing_handlers.fishing_area(event)):
            yield r

    @filter.command("鱼类图鉴", alias={"图鉴"})
    async def fish_pokedex(self, event: AstrMessageEvent):
        """查看鱼类图鉴，了解所有可钓到的鱼"""
        async for r in self._guard(event, self.fishing_handlers.fish_pokedex(event)):
            yield r

    # =========== 市场与商店 ==========

    @filter.command("卖出所有鱼")
    async def sell_all(self, event: AstrMessageEvent):
        """卖出鱼塘中所有的鱼，换取金币"""
        async for r in self._guard(event, market_handlers.sell_all(self, event)):
            yield r

    @filter.command("卖出所有家产")
    async def sell_everything(self, event: AstrMessageEvent):
        """卖掉所有可以出售的物品，包括鱼、装备等"""
        async for r in self._guard(event, market_handlers.sell_everything(self, event)):
            yield r

    @filter.command("卖出稀有度鱼")
    async def sell_by_rarity(self, event: AstrMessageEvent):
        """按稀有度卖鱼。用法：卖出稀有度鱼 星级 [更多星级]"""
        async for r in self._guard(event, market_handlers.sell_by_rarity(self, event)):
            yield r

    @filter.command("卖出所有鱼竿")
    async def sell_all_rods(self, event: AstrMessageEvent):
        """出售所有未装备且未锁定的鱼竿"""
        async for r in self._guard(event, market_handlers.sell_all_rods(self, event)):
            yield r

    @filter.command("卖出所有饰品")
    async def sell_all_accessories(self, event: AstrMessageEvent):
        """出售所有未装备且未锁定的饰品"""
        async for r in self._guard(event, market_handlers.sell_all_accessories(self, event)):
            yield r

    @filter.command("商店")
    async def shop(self, event: AstrMessageEvent):
        """查看所有可用的商店"""
        async for r in self._guard(event, market_handlers.shop(self, event)):
            yield r

    @filter.command("商店购买", alias={"购买商店商品", "购买商店"})
    async def buy_in_shop(self, event: AstrMessageEvent):
        """从商店购买商品。用法：商店购买 商品编号 [数量]"""
        async for r in self._guard(event, market_handlers.buy_in_shop(self, event)):
            yield r

    @filter.command("市场")
    async def market(self, event: AstrMessageEvent):
        """查看玩家市场中的所有上架商品"""
        async for r in self._guard(event, market_handlers.market(self, event)):
            yield r

    @filter.command("上架")
    async def list_any(self, event: AstrMessageEvent):
        """将物品上架到市场出售。用法：上架 物品编号 价格"""
        async for r in self._guard(event, market_handlers.list_any(self, event)):
            yield r

    @filter.command("购买")
    async def buy_item(self, event: AstrMessageEvent):
        """从市场购买玩家上架的商品。用法：购买 订单编号"""
        async for r in self._guard(event, market_handlers.buy_item(self, event)):
            yield r

    @filter.command("我的上架", alias={"上架列表", "我的商品", "我的挂单"})
    async def my_listings(self, event: AstrMessageEvent):
        """查看你在市场上架的所有商品"""
        async for r in self._guard(event, market_handlers.my_listings(self, event)):
            yield r

    @filter.command("下架")
    async def delist_item(self, event: AstrMessageEvent):
        """从市场下架你上架的商品。用法：下架 订单编号"""
        async for r in self._guard(event, market_handlers.delist_item(self, event)):
            yield r

    # =========== 抽卡 ==========

    @filter.command("抽卡", alias={"抽奖"})
    async def gacha(self, event: AstrMessageEvent):
        """进行一次抽卡，有机会获得稀有装备和道具"""
        async for r in self._guard(event, gacha_handlers.gacha(self, event)):
            yield r

    @filter.command("十连")
    async def ten_gacha(self, event: AstrMessageEvent):
        """进行十次连续抽卡"""
        async for r in self._guard(event, gacha_handlers.ten_gacha(self, event)):
            yield r

    @filter.command("查看卡池", alias={"卡池"})
    async def view_gacha_pool(self, event: AstrMessageEvent):
        """查看当前卡池中的所有物品及其概率"""
        async for r in self._guard(event, gacha_handlers.view_gacha_pool(self, event)):
            yield r

    # =========== 社交 ==========

    @filter.command("排行榜", alias={"phb"})
    async def ranking(self, event: AstrMessageEvent):
        """查看金币、鱼类等各种排行榜"""
        async for r in self._guard(event, social_handlers.ranking(self, event)):
            yield r

    @filter.command("偷鱼")
    async def steal_fish(self, event: AstrMessageEvent):
        """偷取其他玩家的鱼，但有失败风险。用法：偷鱼 @用户"""
        async for r in self._guard(event, social_handlers.steal_fish(self, event)):
            yield r

    @filter.command("电鱼")
    async def electric_fish(self, event: AstrMessageEvent):
        """对其他玩家使用电鱼，成功可获得金币。用法：电鱼 @用户"""
        async for r in self._guard(event, social_handlers.electric_fish(self, event)):
            yield r

    @filter.command("驱灵")
    async def dispel_protection(self, event: AstrMessageEvent):
        """驱散目标玩家的保护效果。用法：驱灵 @用户"""
        async for r in self._guard(event, social_handlers.dispel_protection(self, event)):
            yield r

    async def terminate(self):
        """插件被卸载/停用时调用"""
        logger.info("钓鱼插件正在终止...")
        self.fishing_service.stop_auto_fishing_task()
        
        self.database.close_connection()
        logger.info("钓鱼插件已成功终止。")
