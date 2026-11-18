import random
from typing import Dict, Any, Optional
from datetime import datetime

from astrbot.api import logger
# 导入仓储接口和领域模型
from ..database.connection_manager import atomic_game_operation
from ..repositories.abstract_repository import (
    AbstractGachaRepository,
    AbstractUserRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
)
from ..domain.models import GachaPool, GachaPoolItem
from ..utils import UTC8, get_now, get_today


def _perform_single_weighted_draw(pool: GachaPool) -> GachaPoolItem:
    """执行一次加权随机抽奖。"""
    total_weight = sum(item.weight for item in pool.items)
    rand_val = random.randrange(total_weight)

    current_weight = 0
    for item in pool.items:
        current_weight += item.weight
        if rand_val < current_weight:
            return item
    raise ValueError("卡池权重无效")


class GachaService:
    """封装与抽卡系统相关的业务逻辑"""

    def __init__(
        self,
        gacha_repo: AbstractGachaRepository,
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
    ):
        self.gacha_repo = gacha_repo
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo

    def get_all_pools(self) -> Dict[str, Any]:
        """提供查看所有卡池信息的功能。"""
        try:
            pools = self.gacha_repo.get_all_pools()
            logger.info(f"获取到 {len(pools)} 个卡池信息")
            return {"success": True, "pools": pools}
        except Exception as e:
            return {"success": False, "message": f"获取卡池信息失败: {str(e)}"}

    def get_daily_free_pool(self) -> Optional[GachaPool]:
        """获取每日免费池 (第一个成本为0的池)"""
        free_pools = self.gacha_repo.get_free_pools()
        return free_pools[0] if free_pools else None

    def get_pool_details(self, pool_id: int) -> Dict[str, Any]:
        """获取单个卡池的详细信息，包括奖品列表和概率。"""
        pool = self.gacha_repo.get_pool_by_id(pool_id)
        if not pool:
            return {"success": False, "message": "该卡池不存在"}

        total_weight = sum(item.weight for item in pool.items)
        if total_weight == 0:
            return {"success": True, "pool": pool, "probabilities": []}

        probabilities = []
        for item in pool.items:
            probability = float(item.weight / total_weight)
            template = self._reward_template(item)
            item_name = f"{item.quantity} 金币" if item.item_type == "coins" else template.name if template else "未知物品"
            item_rarity = template.rarity if template else 1

            probabilities.append({
                "item_type": item.item_type,
                "item_id": item.item_id,
                "item_name": item_name,
                "item_rarity": item_rarity,
                "weight": item.weight,
                "probability": probability,
            })
        return {"success": True, "pool": pool, "probabilities": probabilities}

    @atomic_game_operation
    def perform_draw(self, user_id: str, pool_id: int, num_draws: int = 1) -> Dict[str, Any]:
        """
        实现单抽和十连抽的核心逻辑。

        Args:
            user_id: 抽卡的用户ID
            pool_id: 卡池ID
            num_draws: 抽卡次数

        Returns:
            一个包含成功状态和抽卡结果的字典。
        """
        if not 1 <= num_draws <= 1000:
            return {"success": False, "message": "一次最多支持 1～1000 抽"}

        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        pool = self.gacha_repo.get_pool_by_id(pool_id)
        if not pool or not pool.items:
            return {"success": False, "message": "卡池不存在或卡池为空"}

        # 每日免费池限制检查
        is_daily_supply = pool.cost_coins == 0
        if is_daily_supply and num_draws > 1:
            return {"success": False, "message": "每日免费补给一次只能抽一张哦！"}

        # 限时卡池过期校验
        if pool.is_limited_time:
            try:
                close_time = datetime.fromisoformat((pool.open_until or "").replace("Z", "+00:00"))
                close_time = close_time.astimezone(UTC8) if close_time.tzinfo else close_time.replace(tzinfo=UTC8)
            except ValueError:
                return {"success": False, "message": "限时卡池的截止时间配置无效"}
            if get_now() >= close_time:
                return {"success": False, "message": f"该卡池已结束开放（截止 {close_time:%Y/%m/%d %H:%M}）"}

        total_coin_cost = (pool.cost_coins or 0) * num_draws
        if not user.can_afford(total_coin_cost):
            return {"success": False, "message": f"金币不足，需要 {total_coin_cost} 金币"}

        draw_results = [_perform_single_weighted_draw(pool) for _ in range(num_draws)]
        equipment_count = sum(item.quantity for item in draw_results if item.item_type in ("rod", "accessory"))
        if equipment_count > 1000:
            return {"success": False, "message": "本批奖励超过 1000 件装备，请分批抽取"}

        # 2. 领取每日补给或扣除金币
        claim_date = get_today() if is_daily_supply else None
        if claim_date is not None:
            if not self.gacha_repo.claim_daily_supply(user_id, pool_id, claim_date):
                return {"success": False, "message": "今天的免费补给已经领过啦，明天再来吧！"}
        elif total_coin_cost:
            user.coins -= total_coin_cost
            self.user_repo.update(user)

        granted_rewards = [self._grant_reward(user_id, item) for item in draw_results]
        return {"success": True, "results": granted_rewards, "cost_coins": total_coin_cost}

    def _reward_template(self, item: GachaPoolItem):
        lookup = {
            "rod": self.item_template_repo.get_rod_by_id,
            "accessory": self.item_template_repo.get_accessory_by_id,
            "bait": self.item_template_repo.get_bait_by_id,
            "item": self.item_template_repo.get_item_by_id,
        }.get(item.item_type)
        return lookup(item.item_id) if lookup else None

    def _grant_reward(self, user_id: str, item: GachaPoolItem):
        """Grant a draw reward and return its display data."""
        quantity = item.quantity
        if quantity <= 0:
            raise ValueError("卡池奖励数量必须大于零")

        if item.item_type == "coins":
            user = self.user_repo.get_by_id(user_id)
            user.coins += quantity
            self.user_repo.update(user)
            return {"type": "coins", "quantity": quantity}

        template = self._reward_template(item)
        if template is None:
            raise ValueError(f"卡池奖励不存在：{item.item_type} #{item.item_id}")

        if item.item_type == "rod":
            for _ in range(quantity):
                self.inventory_repo.add_rod_instance(user_id, item.item_id, template.durability)
        elif item.item_type == "accessory":
            for _ in range(quantity):
                self.inventory_repo.add_accessory_instance(user_id, item.item_id)
        elif item.item_type == "bait":
            self.inventory_repo.update_bait_quantity(user_id, item.item_id, quantity)
        else:
            self.inventory_repo.update_item_quantity(user_id, item.item_id, quantity)

        return {
            "type": item.item_type, "id": item.item_id, "name": template.name,
            "rarity": template.rarity, "quantity": quantity,
        }
