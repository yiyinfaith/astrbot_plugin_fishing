import random
import json
from typing import Dict, Any, Optional, TYPE_CHECKING
from astrbot.api import logger

# 导入仓储接口和领域模型
from ..repositories.abstract_repository import (
    AbstractUserRepository,
    AbstractLogRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractUserBuffRepository,
)
from ..domain.models import User
from ...core.utils import get_now, get_today

if TYPE_CHECKING:
    from ..repositories.sqlite_user_repo import SqliteUserRepository

# 一次电鱼最多电走的鱼数
ELECTRIC_FISH_MAX_CATCH = 50


class GameMechanicsService:
    """封装偷鱼、电鱼、驱灵与装备售价等独立的游戏机制"""


    def __init__(
        self,
        user_repo: AbstractUserRepository,
        log_repo: AbstractLogRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        buff_repo: AbstractUserBuffRepository,
        config: Dict[str, Any]
    ):
        self.user_repo = user_repo
        self.log_repo = log_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.buff_repo = buff_repo
        self.config = config

    def steal_fish(self, thief_id: str, victim_id: str) -> Dict[str, Any]:
        """
        处理"偷鱼"的逻辑。
        """
        if thief_id == victim_id:
            return {"success": False, "message": "不能偷自己的鱼！"}

        thief = self.user_repo.get_by_id(thief_id)
        if not thief:
            return {"success": False, "message": "偷窃者用户不存在"}

        victim = self.user_repo.get_by_id(victim_id)
        if not victim:
            return {"success": False, "message": "目标用户不存在"}

        # 0. 首先检查偷窃CD
        cooldown_seconds = self.config.get("steal", {}).get("cooldown_seconds", 14400) # 默认4小时
        now = get_now()

        # 修复时区问题
        last_steal_time = thief.last_steal_time
        if last_steal_time and last_steal_time.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif last_steal_time and last_steal_time.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=last_steal_time.tzinfo)

        if last_steal_time and (now - last_steal_time).total_seconds() < cooldown_seconds:
            remaining = int(cooldown_seconds - (now - last_steal_time).total_seconds())
            return {"success": False, "message": f"偷鱼冷却中，请等待 {remaining // 60} 分钟后再试"}

        # 1. 检查受害者是否受保护，以及偷窃者是否有反制能力
        protection_buff = self.buff_repo.get_active_by_user_and_type(
            victim_id, "STEAL_PROTECTION_BUFF"
        )
        
        penetration_buff = self.buff_repo.get_active_by_user_and_type(
            thief_id, "STEAL_PENETRATION_BUFF"
        )
        shadow_cloak_buff = self.buff_repo.get_active_by_user_and_type(
            thief_id, "SHADOW_CLOAK_BUFF"
        )
        
        if protection_buff:
            if not penetration_buff and not shadow_cloak_buff:
                return {"success": False, "message": f"❌ 无法偷窃，【{victim.nickname}】的鱼塘似乎被神秘力量守护着！"}
            else:
                if shadow_cloak_buff:
                    self.buff_repo.delete(shadow_cloak_buff.id)

        # 2. 检查受害者是否有鱼可偷
        victim_inventory = self.inventory_repo.get_fish_inventory(victim_id)
        if not victim_inventory:
            return {"success": False, "message": f"目标用户【{victim.nickname}】的鱼塘是空的！"}

        # 3. 随机选择一条鱼偷取
        stolen_fish_item = random.choice(victim_inventory)
        stolen_fish_template = self.item_template_repo.get_fish_by_id(stolen_fish_item.fish_id)

        if not stolen_fish_template:
            return {"success": False, "message": "发生内部错误，无法识别被偷的鱼"}

        # 4. 执行偷窃事务（保持品质属性）
        self.inventory_repo.update_fish_quantity(victim_id, stolen_fish_item.fish_id, delta=-1, quality_level=stolen_fish_item.quality_level)
        self.inventory_repo.add_fish_to_inventory(thief_id, stolen_fish_item.fish_id, quantity=1, quality_level=stolen_fish_item.quality_level)

        # 5. 更新偷窃者的CD时间
        thief.last_steal_time = now
        self.user_repo.update(thief)

        # 6. 生成成功消息
        counter_message = ""
        if protection_buff:
            if penetration_buff:
                counter_message = "⚡ 破灵符的力量穿透了海灵守护！"
            elif shadow_cloak_buff:
                counter_message = "🌑 暗影斗篷让你在阴影中行动！"

        # 构建品质信息
        quality_info = ""
        actual_value = stolen_fish_template.base_value
        if stolen_fish_item.quality_level == 1:
            quality_info = "（✨高品质）"
            actual_value = stolen_fish_template.base_value * 2
        
        return {
            "success": True,
            "message": f"{counter_message}✅ 成功从【{victim.nickname}】的鱼塘里偷到了一条{stolen_fish_template.rarity}★【{stolen_fish_template.name}】{quality_info}！价值 {actual_value} 金币",
        }

    # ============================================================
    # ==================== 新增功能：电鱼 开始 ====================
    # ============================================================
    def electric_fish(self, thief_id: str, victim_id: str) -> Dict[str, Any]:
        """
        处理"电鱼"的逻辑。
        - 基础成功率，受多种因素影响
        - 失败会扣除金币作为设备损坏费
        - 成功有三个档次：大成功、普通成功、小成功
        - 对鱼塘内鱼数>=100的目标随机偷取
        - 其中最多只能包含一条5星及以上的鱼
        """
        if thief_id == victim_id:
            return {"success": False, "message": "不能电自己的鱼！"}
    
        thief = self.user_repo.get_by_id(thief_id)
        if not thief:
            return {"success": False, "message": "使用者用户不存在"}
    
        victim = self.user_repo.get_by_id(victim_id)
        if not victim:
            return {"success": False, "message": "目标用户不存在"}
    
        # 0. 检查电鱼CD
        cooldown_seconds = self.config.get("electric_fish", {}).get("cooldown_seconds", 10800) # 默认3小时
        now = get_now()
    
        last_electric_fish_time = thief.last_electric_fish_time
        if last_electric_fish_time and last_electric_fish_time.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif last_electric_fish_time and last_electric_fish_time.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=last_electric_fish_time.tzinfo)
    
        if last_electric_fish_time and (now - last_electric_fish_time).total_seconds() < cooldown_seconds:
            remaining = int(cooldown_seconds - (now - last_electric_fish_time).total_seconds())
            return {"success": False, "message": f"电鱼冷却中，请等待 {remaining // 60} 分钟后再试"}
    
        # 1. 检查受害者是否受保护，逻辑同偷鱼
        protection_buff = self.buff_repo.get_active_by_user_and_type(
            victim_id, "STEAL_PROTECTION_BUFF"
        )
        
        penetration_buff = self.buff_repo.get_active_by_user_and_type(
            thief_id, "STEAL_PENETRATION_BUFF"
        )
        shadow_cloak_buff = self.buff_repo.get_active_by_user_and_type(
            thief_id, "SHADOW_CLOAK_BUFF"
        )
        
        if protection_buff:
            if not penetration_buff and not shadow_cloak_buff:
                return {"success": False, "message": f"❌ 无法电鱼，【{victim.nickname}】的鱼塘似乎被神秘力量守护着！"}
            else:
                if shadow_cloak_buff:
                    self.buff_repo.delete(shadow_cloak_buff.id)
    
        # 2. 检查受害者鱼塘数量是否达标
        victim_inventory = self.inventory_repo.get_fish_inventory(victim_id)
        if not victim_inventory:
            return {"success": False, "message": f"目标用户【{victim.nickname}】的鱼塘是空的！"}
        
        total_fish_count = sum(item.quantity for item in victim_inventory)
        if total_fish_count < 100:
            return {"success": False, "message": f"目标用户【{victim.nickname}】的鱼塘里鱼太少了（{total_fish_count}/100），电不到什么好东西，还是放过他吧。"}
        
        # 3. 计算成功率并进行判定
        # 所有目标用户的成功率相同，只使用基础成功率
        final_success_rate = self.config.get("electric_fish", {}).get("base_success_rate", 0.6)
        
        # 进行随机判定
        roll = random.random()
        
        # 失败处理
        if roll > final_success_rate:
            # 使用正态分布计算天罚百分比（0-max_rate之间）
            max_penalty_rate = self.config.get("electric_fish", {}).get("failure_penalty_max_rate", 0.5)
            
            # 正态分布，均值在中间（max_rate/2），标准差使得95%的值在0到max_rate之间
            mean = max_penalty_rate / 2
            std_dev = max_penalty_rate / 4  # 约95%的值在[0, max_rate]之间
            
            # 使用random.gauss生成正态分布的惩罚比例，并限制在[0, max_rate]范围内
            penalty_rate = random.gauss(mean, std_dev)
            penalty_rate = max(0.0, min(max_penalty_rate, penalty_rate))
            
            # 计算实际扣除的金币，并按配置封顶
            penalty_coins = int(thief.coins * penalty_rate)
            penalty_cap = self.config.get("electric_fish", {}).get("failure_penalty_cap", 5000)
            if penalty_cap and penalty_cap > 0:
                penalty_coins = min(penalty_coins, int(penalty_cap))

            thief.coins -= penalty_coins
            thief.last_electric_fish_time = now  # 失败也要更新CD
            self.user_repo.update(thief)
            
            # 根据惩罚程度显示不同的消息（动态基于配置的最大天罚）
            # 轻微: 0-20%的max, 中度: 20-50%的max, 严重: 50-80%的max, 毁灭性: 80-100%的max
            relative_penalty = penalty_rate / max_penalty_rate if max_penalty_rate > 0 else 0
            if relative_penalty < 0.2:
                severity = "⚡ 轻微天罚"
            elif relative_penalty < 0.5:
                severity = "⚡⚡ 中度天罚"
            elif relative_penalty < 0.8:
                severity = "⚡⚡⚡ 严重天罚"
            else:
                severity = "⚡⚡⚡⚡ 毁灭性天罚"
            
            return {
                "success": False,
                "message": f"❌ 电鱼失败！{severity}降临，雷电击中了你，损失了 {penalty_coins} 金币！\n💡 本次成功率为 {final_success_rate*100:.1f}%"
            }

        # 4. 成功了！根据成功度（roll值）决定收益档次
        # roll越接近0表示越幸运，获得的收益越高
        success_quality = roll / final_success_rate  # 归一化到0-1之间
        
        # 分段式收益（鱼塘超过 400 条时按比例，否则按固定条数）：
        # - 大成功（0-0.3）：8%-10% 的鱼 / 10-15 条
        # - 普通成功（0.3-0.7）：5%-8% 的鱼 / 5-10 条
        # - 小成功（0.7-1.0）：2%-5% 的鱼 / 3-5 条
        # 单次最多电走 ELECTRIC_FISH_MAX_CATCH 条
        success_type = ""
        multiplier_range = (0, 0)

        if success_quality <= 0.3:
            success_type = "⭐大成功"
            multiplier_range = (0.08, 0.10)
        elif success_quality <= 0.7:
            success_type = "✅普通成功"
            multiplier_range = (0.05, 0.08)
        else:
            success_type = "🔹小成功"
            multiplier_range = (0.02, 0.05)
        
        # 5. 准备数据：获取鱼模板并将鱼塘扁平化
        fish_templates = {
            item.fish_id: self.item_template_repo.get_fish_by_id(item.fish_id)
            for item in victim_inventory
        }
        all_fish_in_pond = []
        for item in victim_inventory:
            all_fish_in_pond.extend([item.fish_id] * item.quantity)

        # 6. 决定偷取数量并进行初次完全随机抽样
        num_to_steal = 0
        if total_fish_count > 400:
            # 如果鱼数大于400，按成功档次的百分比计算
            lower_bound = max(1, int(total_fish_count * multiplier_range[0]))
            upper_bound = max(lower_bound, int(total_fish_count * multiplier_range[1]))
            num_to_steal = random.randint(lower_bound, upper_bound)
        else:
            # 鱼数较少时，使用固定数量区间
            if success_quality <= 0.3:
                num_to_steal = random.randint(10, 15)  # 大成功
            elif success_quality <= 0.7:
                num_to_steal = random.randint(5, 10)   # 普通成功
            else:
                num_to_steal = random.randint(3, 5)    # 小成功

        num_to_steal = min(num_to_steal, ELECTRIC_FISH_MAX_CATCH)
        actual_num_to_steal = min(num_to_steal, len(all_fish_in_pond))
        initial_catch = random.sample(all_fish_in_pond, actual_num_to_steal)

        # 7. 检查并修正高星鱼数量
        high_rarity_caught = []
        low_rarity_caught = []
        for fish_id in initial_catch:
            template = fish_templates.get(fish_id)
            if template and template.rarity >= 5:
                high_rarity_caught.append(fish_id)
            else:
                low_rarity_caught.append(fish_id)
        
        final_stolen_fish_ids = []
        if len(high_rarity_caught) <= 1:
            final_stolen_fish_ids = initial_catch
        else:
            random.shuffle(high_rarity_caught)
            final_stolen_fish_ids.append(high_rarity_caught.pop(0))
            final_stolen_fish_ids.extend(low_rarity_caught)
            
            num_to_replace = len(high_rarity_caught)

            from collections import Counter
            pond_counts = Counter(all_fish_in_pond)
            initial_catch_counts = Counter(initial_catch)
            pond_counts.subtract(initial_catch_counts)

            replacement_pool = []
            for fish_id, count in pond_counts.items():
                if count > 0:
                    template = fish_templates.get(fish_id)
                    if template and template.rarity < 5:
                        replacement_pool.extend([fish_id] * count)
            
            if replacement_pool:
                num_can_replace = min(num_to_replace, len(replacement_pool))
                replacements = random.sample(replacement_pool, num_can_replace)
                final_stolen_fish_ids.extend(replacements)

        # 8. 统计最终偷到的鱼
        stolen_fish_counts = {}
        for fish_id in final_stolen_fish_ids:
            stolen_fish_counts[fish_id] = stolen_fish_counts.get(fish_id, 0) + 1
    
        # 9. 执行电鱼事务并计算总价值
        stolen_summary = []
        total_value_stolen = 0
    
        for fish_id, count in stolen_fish_counts.items():
            self.inventory_repo.update_fish_quantity(victim_id, fish_id, delta=-count, quality_level=0)
            self.inventory_repo.add_fish_to_inventory(thief_id, fish_id, quantity=count, quality_level=0)
            
            template = fish_templates.get(fish_id)
            if template:
                stolen_summary.append(f"【{template.name}】x{count}")
                total_value_stolen += template.base_value * count
    
        # 10. 更新电鱼的CD时间并保存
        thief.last_electric_fish_time = now
        self.user_repo.update(thief)
    
        # 11. 生成成功消息
        counter_message = ""
        if protection_buff:
            if penetration_buff:
                counter_message = "⚡ 破灵符的力量穿透了海灵守护！\n"
            elif shadow_cloak_buff:
                counter_message = "🌑 暗影斗篷让你在阴影中行动！\n"
    
        stolen_details = "、".join(stolen_summary)
        actual_stolen_count = len(final_stolen_fish_ids)
        
        # 计算收益占比
        steal_percentage = (actual_stolen_count / total_fish_count) * 100
        
        return {
            "success": True,
            "message": f"{counter_message}{success_type}！成功对【{victim.nickname}】的鱼塘进行了电击，捕获了{actual_stolen_count}条鱼（占其总数的{steal_percentage:.1f}%），总价值 {total_value_stolen} 金币！\n分别是：{stolen_details}。\n💡 本次成功率为 {final_success_rate*100:.1f}%",
        }
    # ============================================================
    # ===================== 新增功能：电鱼 结束 =====================
    # ============================================================

    def dispel_steal_protection(self, target_id: str) -> Dict[str, Any]:
        """
        驱散目标的海灵守护效果
        """
        target = self.user_repo.get_by_id(target_id)
        if not target:
            return {"success": False, "message": "目标用户不存在"}

        protection_buff = self.buff_repo.get_active_by_user_and_type(
            target_id, "STEAL_PROTECTION_BUFF"
        )
        
        if not protection_buff:
            return {"success": False, "message": f"【{target.nickname}】没有海灵守护效果"}
        
        self.buff_repo.delete(protection_buff.id)
        
        return {
            "success": True, 
            "message": f"成功驱散了【{target.nickname}】的海灵守护效果"
        }

    def check_steal_protection(self, target_id: str) -> Dict[str, Any]:
        """
        检查目标是否有海灵守护效果
        """
        target = self.user_repo.get_by_id(target_id)
        if not target:
            return {"has_protection": False, "target_name": "未知用户", "message": "目标用户不存在"}

        protection_buff = self.buff_repo.get_active_by_user_and_type(
            target_id, "STEAL_PROTECTION_BUFF"
        )
        
        return {
            "has_protection": protection_buff is not None,
            "target_name": target.nickname,
            "message": f"【{target.nickname}】{'有' if protection_buff else '没有'}海灵守护效果"
        }

    def calculate_sell_price(self, item_type: str, rarity: int, refine_level: int, purchase_cost: Optional[int] = None) -> int:
        """
        计算物品的系统售价。

        Args:
            item_type: 物品类型 ('rod', 'accessory')
            rarity: 物品稀有度
            refine_level: 物品精炼等级
            purchase_cost: 商店售价。有售价时基础回收价不超过售价的一半，避免买了直接卖掉赚钱

        Returns:
            计算出的售价。
        """
        sell_price_config = self.config.get("sell_prices", {})
        
        base_prices = sell_price_config.get(item_type, {})
        base_price = base_prices.get(str(rarity), 0)

        # 如果配置中没有该稀有度的基础价格，使用基于稀有度的公式计算默认值
        # 公式：基础价 = 100 * (2.5 ^ (rarity - 1))，确保高稀有度物品有合理的价格
        if base_price <= 0:
            # 使用指数增长公式：1星=100, 2星≈250, 3星≈625, 4星≈1562, 5星≈3906, 6星≈9765, 7星≈24414, 8星≈61035, 9星≈152587, 10星≈381469
            base_price = int(100 * (2.5 ** (rarity - 1)))
            # 确保最低价格为 100
            base_price = max(100, base_price)

        if purchase_cost and purchase_cost > 0:
            base_price = min(base_price, max(1, purchase_cost // 2))

        refine_multipliers= sell_price_config.get("refine_multiplier", {})
        refine_multiplier = refine_multipliers.get(str(refine_level), 1.0)

        final_price = int(base_price * refine_multiplier)

        # 确保最终价格至少为 30 金币（防止计算错误导致负值或零值）
        if final_price <= 0:
            return 30  # 默认最低价格

        return final_price
