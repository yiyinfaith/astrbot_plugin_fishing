import json
import math
import random
import threading
import time
from typing import Dict, Any, Optional
from datetime import timedelta
from astrbot.api import logger

# 导入仓储接口和领域模型
from ..repositories.abstract_repository import (
    AbstractUserRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractLogRepository,
    AbstractUserBuffRepository,
)
from ..domain.models import FishingZone, UserBuff
from ..services.fishing_zone_service import FishingZoneService
from .fish_weight_service import FishWeightService
from ..utils import get_now, get_last_reset_time, calculate_after_refine

# 抽中「6 星及以上」后各星级的默认相对权重（可在配置中修改），星级越高越难出；没列出的星级权重为 1
HIGH_RARITY_WEIGHTS = {6: 15, 7: 4, 8: 1}
# 通行证当天有效的标记（user_buffs.buff_type 前缀，后接区域 ID）
ZONE_PASS_BUFF = "ZONE_PASS"


class FishingService:
    """封装核心的钓鱼动作及后台任务"""

    def __init__(
        self,
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        log_repo: AbstractLogRepository,
        buff_repo: AbstractUserBuffRepository,
        fishing_zone_service: FishingZoneService,
        fish_weight_service: FishWeightService,
        config: Dict[str, Any],
    ):
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.log_repo = log_repo
        self.buff_repo = buff_repo
        self.fish_weight_service = fish_weight_service
        self.fishing_zone_service = fishing_zone_service
        self.config = config
        # 获取每日刷新时间配置
        self.daily_reset_hour = self.config.get("daily_reset_hour", 0)
        # 自动钓鱼线程相关属性
        self.auto_fishing_thread: Optional[threading.Thread] = None
        self.auto_fishing_running = False
        self._auto_fishing_stop_event = threading.Event()
        # 可选的消息通知回调：签名 (target: str, message: str) -> None，用于消息通知
        self._notifier = None
        # 通知目标可配置，默认群聊。可由 config['notifications']['relocation_target'] 覆盖
        notifications_cfg = self.config.get("notifications", {}) if isinstance(self.config, dict) else {}
        self._notification_target = notifications_cfg.get("relocation_target", "group")
        

    def register_notifier(self, notifier, default_target: Optional[str] = None):
        """
        注册一个用于发送系统消息的回调（如群聊推送）。
        回调应为同步函数，签名为 (target: str, message: str) -> None。
        默认目标可通过参数或配置指定。
        """
        self._notifier = notifier
        if default_target:
            self._notification_target = default_target

    def _get_bait_rod_requirement_error(self, user_id: str, bait_template) -> Optional[str]:
        required_rod_rarity = getattr(bait_template, "required_rod_rarity", 0) or 0
        if required_rod_rarity <= 0:
            return None

        equipped_rod = self.inventory_repo.get_user_equipped_rod(user_id)
        if not equipped_rod:
            return f"使用【{bait_template.name}】需要装备 {required_rod_rarity} 星及以上鱼竿"

        rod_template = self.item_template_repo.get_rod_by_id(equipped_rod.rod_id)
        if not rod_template or rod_template.rarity < required_rod_rarity:
            current_rarity = rod_template.rarity if rod_template else 0
            return f"使用【{bait_template.name}】需要 {required_rod_rarity} 星及以上鱼竿，当前鱼竿为 {current_rarity} 星"

        return None

    def _get_random_usable_bait_id(self, user_id: str) -> Optional[int]:
        bait_inventory = self.inventory_repo.get_user_bait_inventory(user_id)
        usable_bait_ids = []

        for bait_id, quantity in bait_inventory.items():
            if quantity <= 0:
                continue

            bait_template = self.item_template_repo.get_bait_by_id(bait_id)
            if not bait_template:
                continue

            if self._get_bait_rod_requirement_error(user_id, bait_template) is None:
                usable_bait_ids.append(bait_id)

        return random.choice(usable_bait_ids) if usable_bait_ids else None

    def toggle_auto_fishing(self, user_id: str) -> Dict[str, Any]:
        """
        切换用户的自动钓鱼状态。

        Args:
            user_id: 用户ID。

        Returns:
            一个包含操作结果的字典。
        """
        enabled = self.user_repo.toggle_auto_fishing(user_id)
        if enabled is None:
            return {"success": False, "message": "❌您还没有注册，请先使用 /钓鱼注册 命令注册。"}

        if enabled:
            return {"success": True, "message": "🎣 自动钓鱼已开启！"}
        else:
            return {"success": True, "message": "🚫 自动钓鱼已关闭！"}

    def go_fish(self, user_id: str) -> Dict[str, Any]:
        """
        执行一次完整的钓鱼动作。

        Args:
            user_id: 尝试钓鱼的用户ID。

        Returns:
            一个包含结果的字典。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在，无法钓鱼。"}

        # 1. 检查成本（从区域配置中读取）
        zone = self.inventory_repo.get_zone_by_id(user.fishing_zone_id)
        if not zone:
            return {"success": False, "message": "钓鱼区域不存在"}
        
        # 检查区域是否激活
        if not zone.is_active:
            return {"success": False, "message": "该钓鱼区域被浓雾隐匿了，暂时无法进入"}
        
        # 检查时间限制
        now = get_now()
        if zone.available_from and now < zone.available_from:
            return {"success": False, "message": f"该钓鱼区域将在 {zone.available_from.strftime('%Y-%m-%d %H:%M')} 开放"}
        
        if zone.available_until and now > zone.available_until:
            # 区域已关闭，自动传送回初始区域
            user.fishing_zone_id = 1
            self.user_repo.set_fishing_zone(user_id, 1)
            # 获取初始区域的名字
            first_zone = self.inventory_repo.get_zone_by_id(1)
            first_zone_name = first_zone.name if first_zone else "初始区域"
            return {"success": False, "message": f"该钓鱼区域已于 {zone.available_until.strftime('%Y-%m-%d %H:%M')} 关闭，已自动传送回{first_zone_name}"}

        rod_error = self._get_zone_rod_requirement_error(user_id, zone)
        if rod_error:
            return {"success": False, "message": rod_error, "zone_requirement_failed": True}

        if user.current_bait_id is not None:
            bait_template = self.item_template_repo.get_bait_by_id(user.current_bait_id)
            if bait_template:
                requirement_error = self._get_bait_rod_requirement_error(user_id, bait_template)
                if requirement_error:
                    user.current_bait_id = None
                    user.bait_start_time = None
                    self.user_repo.update_bait_state(user_id, None, None)
                    return {"success": False, "message": requirement_error}
        
        fishing_cost = zone.fishing_cost
        if not user.can_afford(fishing_cost):
            return {"success": False, "message": f"金币不足，需要 {fishing_cost} 金币。"}

        # 需要通行证的区域：当天第一次钓鱼时消耗 1 张
        pass_error, pass_notice = self._use_zone_pass_if_needed(user_id, zone)
        if pass_error:
            return {"success": False, "message": pass_error, "zone_requirement_failed": True}
        notices = [pass_notice] if pass_notice else []

        # 2. 计算各种加成和修正值
        base_success_rate = self.config.get("fishing", {}).get("base_success_rate", 0.7)  # 基础成功率
        quality_modifier = 1.0 # 品质加成
        quantity_modifier = 1.0 # 数量加成
        rare_chance = 0.0 # 稀有鱼出现几率
        coins_chance = 0.0 # 增加同稀有度高金币出现几率
        weight_modifier = 1.0 # 最大重量潜力加成

        # --- 新增：应用 Buff 效果 ---
        active_buffs = self.buff_repo.get_all_active_by_user(user_id)
        for buff in active_buffs:
            if buff.buff_type == "RARE_FISH_BOOST":
                try:
                    payload = json.loads(buff.payload) if buff.payload else {}
                    multiplier = payload.get("multiplier", 1.0)
                    # 这里的实现是直接增加到 rare_chance
                    # 注意：如果基础值是0，乘法无意义，所以用加法或更复杂的逻辑
                    # 假设 payload 的 multiplier 是一个额外的概率加成
                    rare_chance += multiplier
                    logger.info(
                        f"用户 {user_id} 的 RARE_FISH_BOOST 生效，稀有几率增加 {multiplier}"
                    )
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"解析 buff payload 失败: {buff.payload}")
        # --- Buff 应用结束 ---

        logger.debug(
            f"当前钓鱼概率： base_success_rate={base_success_rate}, quality_modifier={quality_modifier}, quantity_modifier={quantity_modifier}, rare_chance={rare_chance}, coins_chance={coins_chance}"
        )
        # 获取装备鱼竿并应用加成
        equipped_rod_instance = self.inventory_repo.get_user_equipped_rod(user.user_id)
        if equipped_rod_instance:
            rod_template = self.item_template_repo.get_rod_by_id(equipped_rod_instance.rod_id)
            if rod_template:
                quality_modifier *= calculate_after_refine(rod_template.bonus_fish_quality_modifier, refine_level= equipped_rod_instance.refine_level, rarity=rod_template.rarity)
                quantity_modifier *= calculate_after_refine(rod_template.bonus_fish_quantity_modifier, refine_level= equipped_rod_instance.refine_level, rarity=rod_template.rarity)
                rare_chance += calculate_after_refine(rod_template.bonus_rare_fish_chance, refine_level= equipped_rod_instance.refine_level, rarity=rod_template.rarity)
        logger.debug(f"装备鱼竿加成后： quality_modifier={quality_modifier}, quantity_modifier={quantity_modifier}, rare_chance={rare_chance}")
        # 获取装备饰品并应用加成
        equipped_accessory_instance = self.inventory_repo.get_user_equipped_accessory(user.user_id)
        if equipped_accessory_instance:
            acc_template = self.item_template_repo.get_accessory_by_id(equipped_accessory_instance.accessory_id)
            if acc_template:
                quality_modifier *= calculate_after_refine(acc_template.bonus_fish_quality_modifier, refine_level= equipped_accessory_instance.refine_level, rarity=acc_template.rarity)
                quantity_modifier *= calculate_after_refine(acc_template.bonus_fish_quantity_modifier, refine_level= equipped_accessory_instance.refine_level, rarity=acc_template.rarity)
                rare_chance += calculate_after_refine(acc_template.bonus_rare_fish_chance, refine_level= equipped_accessory_instance.refine_level, rarity=acc_template.rarity)
                coins_chance += calculate_after_refine(acc_template.bonus_coin_modifier, refine_level= equipped_accessory_instance.refine_level, rarity=acc_template.rarity) - 1
        logger.debug(f"装备饰品加成后： quality_modifier={quality_modifier}, quantity_modifier={quantity_modifier}, rare_chance={rare_chance}, coins_chance={coins_chance}")
        # 获取鱼饵并应用加成
        cur_bait_id = user.current_bait_id
        garbage_reduction_modifier = None

        # 判断鱼饵是否过期
        if user.current_bait_id is not None:
            bait_template = self.item_template_repo.get_bait_by_id(cur_bait_id)
            if bait_template:
                requirement_error = self._get_bait_rod_requirement_error(user_id, bait_template)
                if requirement_error:
                    user.current_bait_id = None
                    user.bait_start_time = None
                    self.user_repo.update_bait_state(user_id, None, None)
                    return {"success": False, "message": requirement_error}

            if bait_template and bait_template.duration_minutes > 0:
                # 检查鱼饵是否过期
                bait_expiry_time = user.bait_start_time
                if bait_expiry_time:
                    now = get_now()
                    expiry_time = bait_expiry_time + timedelta(minutes=bait_template.duration_minutes)
                    # 移除两个时间的时区信息
                    if now.tzinfo is not None:
                        now = now.replace(tzinfo=None)
                    if expiry_time.tzinfo is not None:
                        expiry_time = expiry_time.replace(tzinfo=None)
                    if now > expiry_time:
                        # 鱼饵已过期，清除当前鱼饵
                        user.current_bait_id = None
                        user.bait_start_time = None
                        self.inventory_repo.update_bait_quantity(user_id, cur_bait_id, -1)
                        self.user_repo.update_bait_state(user_id, None, None)
                        logger.warning(f"用户 {user_id} 的当前鱼饵{bait_template}已过期，已被清除。")
            else:
                if bait_template:
                    # 如果鱼饵没有设置持续时间, 是一次性鱼饵，消耗一个鱼饵
                    user_bait_inventory = self.inventory_repo.get_user_bait_inventory(user_id)
                    if user_bait_inventory is not None and user_bait_inventory.get(user.current_bait_id, 0) > 0:
                        self.inventory_repo.update_bait_quantity(user_id, user.current_bait_id, -1)
                    else:
                        # 如果用户没有库存鱼饵，清除当前鱼饵
                        user.current_bait_id = None
                        user.bait_start_time = None
                        self.user_repo.update_bait_state(user_id, None, None)
                        logger.warning(f"用户 {user_id} 的当前鱼饵{bait_template.bait_id}已被清除，因为库存不足。")
                else:
                    # 如果鱼饵模板不存在，清除当前鱼饵
                    user.current_bait_id = None
                    user.bait_start_time = None
                    self.user_repo.update_bait_state(user_id, None, None)
                    logger.warning(f"用户 {user_id} 的当前鱼饵已被清除，因为鱼饵模板不存在。")

        if user.current_bait_id is None:
            is_renewed = False
            # 1. 优先尝试续上刚才使用的同款鱼饵
            if cur_bait_id is not None:
                user_bait_inventory = self.inventory_repo.get_user_bait_inventory(user_id)
                # 如果同款鱼饵还有库存，则自动续上同款
                if user_bait_inventory is not None and user_bait_inventory.get(cur_bait_id, 0) > 0:
                    bait_template = self.item_template_repo.get_bait_by_id(cur_bait_id)
                    if bait_template and self._get_bait_rod_requirement_error(user_id, bait_template) is None:
                        user.current_bait_id = cur_bait_id

                        # 如果是限时型鱼饵，自动续期时需要重置它的生效开始时间
                        if bait_template.duration_minutes > 0:
                            user.bait_start_time = get_now()

                        self.user_repo.update_bait_state(
                            user_id, user.current_bait_id, user.bait_start_time
                        )
                        logger.info(f"用户 {user_id} 自动续装了同款鱼饵: {cur_bait_id}")
                        is_renewed = True
            
            # 2. 如果同款已经彻底用光了（未成功续杯），则随机抓取背包里的其他鱼饵
            if not is_renewed:
                random_bait_id = self._get_random_usable_bait_id(user.user_id)
                if random_bait_id:
                    user.current_bait_id = random_bait_id
                    
                    # 为新随机到的鱼饵初始化时间（如果抽到的是限时鱼饵）
                    new_bait_template = self.item_template_repo.get_bait_by_id(random_bait_id)
                    if new_bait_template and new_bait_template.duration_minutes > 0:
                        user.bait_start_time = get_now()
                    
                    self.user_repo.update_bait_state(
                        user_id, user.current_bait_id, user.bait_start_time
                    )
                    logger.info(f"用户 {user_id} 同款耗尽，自动随机切换至新鱼饵: {random_bait_id}")

        if user.current_bait_id is not None:
            bait_template = self.item_template_repo.get_bait_by_id(user.current_bait_id)
            # logger.info(f"鱼饵信息: {bait_template}")
            if bait_template:
                quantity_modifier *= bait_template.quantity_modifier
                rare_chance += bait_template.rare_chance_modifier
                base_success_rate += bait_template.success_rate_modifier
                garbage_reduction_modifier = bait_template.garbage_reduction_modifier
                coins_chance += bait_template.value_modifier - 1
                weight_modifier *= getattr(bait_template, "weight_modifier", 1.0) or 1.0
        logger.debug(f"使用鱼饵加成后： base_success_rate={base_success_rate}, quality_modifier={quality_modifier}, quantity_modifier={quantity_modifier}, rare_chance={rare_chance}, coins_chance={coins_chance}, weight_modifier={weight_modifier}")
        # 3. 判断是否成功钓到
        if random.random() >= base_success_rate:
            # 失败逻辑
            if not self.user_repo.record_failed_fishing(user_id, fishing_cost, get_now()):
                return {"success": False, "message": f"金币不足，需要 {fishing_cost} 金币。"}
            return {"success": False, "message": "💨 什么都没钓到...", "notices": notices}

        # 4. 成功，生成渔获
        # 使用区域策略获取基础稀有度分布
        strategy = self.fishing_zone_service.get_strategy(user.fishing_zone_id)
        # 复制一份，避免改动策略里缓存的分布
        rarity_distribution = list(strategy.get_fish_rarity_distribution(user))

        # 应用稀有度加成（rare_chance）调整分布权重
        # 如果玩家有装备/Buff/鱼饵提供的稀有度加成，会提升 4-5 星鱼的概率
        # 6+ 星鱼的概率不受影响，保持其作为"运气时刻"的设计
        if rare_chance > 0:
            adjusted_distribution = self._apply_rare_chance_to_distribution(
                rarity_distribution, rare_chance
            )
        else:
            adjusted_distribution = rarity_distribution
        
        # 根据调整后的分布加权随机抽取稀有度
        rarity_index = random.choices(range(len(adjusted_distribution)), weights=adjusted_distribution, k=1)[0]
        
        if rarity_index == 5:  # 抽中6+星组合
            # 从6星及以上的鱼中随机选择，兼容区域限定鱼
            rarity = self._get_random_high_rarity(zone)
        else:
            # 1-5星直接对应
            rarity = rarity_index + 1
            
        fish_template = self._get_fish_template(rarity, zone, coins_chance)

        if not fish_template:
             return {"success": False, "message": "错误：当前条件下没有可钓的鱼！"}

        # 如果有垃圾鱼减少修正，则应用，价值 < 5则被视为垃圾鱼
        if garbage_reduction_modifier is not None and fish_template.base_value < 5:
            # 根据垃圾鱼减少修正值决定是否重新选择一次
            if random.random() < garbage_reduction_modifier:
                # 重新选择一条鱼
                new_rarity = random.choices(range(1, len(rarity_distribution) + 1), weights=rarity_distribution, k=1)[0]
                new_fish_template = self._get_fish_template(new_rarity, zone, coins_chance)

                if new_fish_template:
                    fish_template = new_fish_template

        # 计算最终属性
        effective_max_weight = max(
            fish_template.min_weight,
            int(fish_template.max_weight * weight_modifier)
        )
        weight = random.randint(fish_template.min_weight, effective_max_weight)
        value = fish_template.base_value

        # 4.2 按品质加成给予额外品质（重量/价值）奖励
        # 品质加成来自：鱼竿 × 饰品 × 鱼饵（乘法累积）
        # 使用对数压缩避免概率过高，保持高品质鱼的稀有性
        quality_bonus = False
        quality_level = 0  # 默认普通品质
        if quality_modifier > 1.0:
            # 对数压缩公式：处理乘法累积的品质加成
            # log2(x) 特性：log2(1)=0, log2(2)=1, log2(4)=2
            # 天然适合处理乘法累积：log2(a×b) = log2(a) + log2(b)
            log_value = math.log2(quality_modifier)
            
            # 从配置获取高品质鱼最大触发概率，默认35%
            max_quality_chance = self.config.get("quality_bonus_max_chance", 0.35)
            
            # 缩放到配置的上限，让 quality_modifier=4.0 时达到上限
            # 缩放系数 = max_chance / 2（因为 log2(4) = 2）
            scale_factor = max_quality_chance / 2.0
            adjusted_chance = log_value * scale_factor
            
            # 确保不超过配置的上限，避免高品质鱼过于常见
            final_chance = min(adjusted_chance, max_quality_chance)
            
            quality_bonus = random.random() <= final_chance
        if quality_bonus:
            extra_weight = random.randint(fish_template.min_weight, effective_max_weight)
            weight += extra_weight
            # 标记为高品质鱼，价值在出售时按2倍计算
            quality_level = 1

        # 4.3 按数量加成决定额外渔获数量
        total_catches = 1
        if quantity_modifier > 1.0:
            # 整数部分-1 为保证的额外数量；小数部分为额外+1的概率
            guaranteed_extra = max(0, int(quantity_modifier) - 1)
            total_catches += guaranteed_extra
            fractional = quantity_modifier - int(quantity_modifier)
            if fractional > 0 and random.random() < fractional:
                total_catches += 1

        # 5. 计算装备变化，最终与库存、统计和日志一起原子提交。
        equipment_broken_messages = []
        rod_instance_id = None
        rod_durability = None
        rod_broken = False
        if user.equipped_rod_instance_id:
            rod_instance = self.inventory_repo.get_user_rod_instance_by_id(user.user_id, user.equipped_rod_instance_id)
            if rod_instance:
                rod_instance_id = rod_instance.rod_instance_id
                if rod_instance.current_durability is not None and rod_instance.current_durability > 0:
                    rod_durability = rod_instance.current_durability - 1
                else:
                    rod_durability = rod_instance.current_durability
                if rod_durability is not None and rod_durability <= 0:
                    rod_broken = True
                    rod_template = self.item_template_repo.get_rod_by_id(rod_instance.rod_id)
                    rod_name = rod_template.name if rod_template else "鱼竿"
                    equipment_broken_messages.append(f"⚠️ 您的{rod_name}已损坏，自动卸下！")

        accessory_instance_id = None
        if user.equipped_accessory_instance_id:
            accessory_instance = self.inventory_repo.get_user_accessory_instance_by_id(user.user_id, user.equipped_accessory_instance_id)
            if accessory_instance:
                accessory_instance_id = accessory_instance.accessory_instance_id

        settled_at = get_now()
        settled = self.inventory_repo.settle_fishing_catch(
            user_id=user.user_id,
            fish_id=fish_template.fish_id,
            total_catches=total_catches,
            quality_level=quality_level,
            weight=weight,
            base_value=value,
            earned_value=fish_template.base_value * total_catches * (1 + quality_level),
            fishing_cost=fishing_cost,
            fish_pond_capacity=user.fish_pond_capacity,
            timestamp=settled_at,
            rod_instance_id=rod_instance_id,
            rod_durability=rod_durability,
            rod_broken=rod_broken,
            accessory_instance_id=accessory_instance_id,
            bait_id=user.current_bait_id,
        )
        if not settled:
            return {"success": False, "message": f"金币不足，需要 {fishing_cost} 金币。"}

        # 7. 构建成功返回结果
        result = {
            "success": True,
            "fish": {
                "name": fish_template.name,
                "rarity": fish_template.rarity,
                "weight": weight,
                "value": value * 2 if quality_level == 1 else value,  # 高品质鱼双倍价值
                "quality_level": quality_level,  # 添加品质等级
                "quality_label": "✨高品质" if quality_level == 1 else "普通"  # 添加品质标签
            }
        }
        
        # 添加装备损坏消息
        if equipment_broken_messages:
            result["equipment_broken_messages"] = equipment_broken_messages
        if notices:
            result["notices"] = notices

        return result

    def get_user_pokedex(self, user_id: str) -> Dict[str, Any]:
        """获取用户的图鉴信息。"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}
        # 使用聚合统计作为图鉴数据来源
        stats = self.log_repo.get_user_fish_stats(user_id)
        if not stats:
            return {"success": True, "pokedex": []}
        all_fish_count = len(self.item_template_repo.get_all_fish())
        unlock_fish_count = len(stats)
        pokedex = []
        for stat in stats:
            fish_template = self.item_template_repo.get_fish_by_id(stat.fish_id)
            if fish_template:
                pokedex.append({
                    "fish_id": stat.fish_id,
                    "name": fish_template.name,
                    "rarity": fish_template.rarity,
                    "description": fish_template.description,
                    "value": fish_template.base_value,
                    "icon_url": fish_template.icon_url,
                    "first_caught_time": stat.first_caught_at,
                    "last_caught_time": stat.last_caught_at,
                    "max_weight": stat.max_weight,
                    "min_weight": stat.min_weight,
                    "total_caught": stat.total_caught,
                    "total_weight": stat.total_weight,
                })
        # 将图鉴按稀有度从大到小排序
        pokedex.sort(key=lambda x: x["rarity"], reverse=True)
        return {
            "success": True,
            "pokedex": pokedex,
            "total_fish_count": all_fish_count,
            "unlocked_fish_count": unlock_fish_count,
            "unlocked_percentage": (unlock_fish_count / all_fish_count) if all_fish_count > 0 else 0
    }

    def get_user_fish_log(self, user_id: str, limit: int = 10) -> Dict[str, Any]:
        """
        获取用户的钓鱼记录。

        Args:
            user_id: 用户ID。
            limit: 返回记录的数量限制。

        Returns:
            包含钓鱼记录的字典。
        """
        records = self.log_repo.get_fishing_records(user_id, limit)
        # 根据records中的 fish_id 获取鱼类名称 rod_instance_id 和 accessory_instance_id 以及 bait_id 获取鱼竿、饰品、鱼饵信息
        fish_details = []
        for record in records:
            fish_template = self.item_template_repo.get_fish_by_id(record.fish_id)
            bait_template = self.item_template_repo.get_bait_by_id(record.bait_id) if record.bait_id else None

            user_rod = self.inventory_repo.get_user_rod_instance_by_id(user_id, record.rod_instance_id) if record.rod_instance_id else None
            rod_instance = self.item_template_repo.get_rod_by_id(user_rod.rod_id) if user_rod else None
            user_accessory = self.inventory_repo.get_user_accessory_instance_by_id(user_id, record.accessory_instance_id) if record.accessory_instance_id else None
            accessory_instance = self.item_template_repo.get_accessory_by_id(user_accessory.accessory_id) if user_accessory else None

            fish_details.append({
                "fish_name": fish_template.name if fish_template else "未知鱼类",
                "fish_rarity": fish_template.rarity if fish_template else "未知稀有度",
                "fish_weight": record.weight,
                "fish_value": record.value,
                "timestamp": record.timestamp,
                "rod": rod_instance.name if rod_instance else "未装备鱼竿",
                "accessory": accessory_instance.name if accessory_instance else "未装备饰品",
                "bait": bait_template.name if bait_template else "未使用鱼饵",
            })
        return {
            "success": True,
            "records": fish_details
        }

    def get_user_fishing_zones(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的钓鱼区域信息。

        Args:
            user_id: 用户ID。

        Returns:
            包含钓鱼区域信息的字典。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        fishing_zones = self.inventory_repo.get_all_zones()
        zones_info = []
        
        for zone in fishing_zones:
            # 获取通行证道具名称
            required_item_name = None
            if zone.requires_pass and zone.required_item_id:
                item_template = self.item_template_repo.get_item_by_id(zone.required_item_id)
                required_item_name = item_template.name if item_template else f"道具ID{zone.required_item_id}"
            
            zones_info.append({
                "zone_id": zone.id,
                "name": zone.name,
                "description": zone.description,
                "required_rod_rarity": zone.required_rod_rarity or 0,
                "whether_in_use": zone.id == user.fishing_zone_id,
                "is_active": zone.is_active,
                "requires_pass": zone.requires_pass,
                "required_item_id": zone.required_item_id,
                "required_item_name": required_item_name,
                "fishing_cost": zone.fishing_cost,
                "available_from": zone.available_from,
                "available_until": zone.available_until,
            })

        return {
            "success": True,
            "zones": zones_info
        }

    def _apply_rare_chance_to_distribution(self, distribution: list, rare_chance: float) -> list:
        """
        应用稀有度加成，调整鱼类稀有度分布权重。
        
        设计理念：
        - 装备/Buff/鱼饵的稀有度加成影响 4-5 星鱼（稀有鱼）的概率
        - 6+ 星鱼（超稀有/传说鱼）保持纯运气机制，不受装备影响
        - 通过从低星转移权重到中高星，确保概率总和始终为 1
        
        实现原理：
        1. 从 1-3 星的总权重中，按 rare_chance 比例转移部分权重
        2. 将转移的权重分配给 4-5 星，按其原始比例分配
        3. 6+ 星的概率保持不变，保证超稀有鱼的珍贵性
        
        示例效果（rare_chance = 0.46）：
        - 原始: 1-3星 60%, 4-5星 38%, 6+星 2%
        - 调整后: 1-3星 32%, 4-5星 66%, 6+星 2%（不变）
        
        Args:
            distribution: 原始稀有度分布列表 [1星, 2星, 3星, 4星, 5星, 6+星]
            rare_chance: 稀有度加成值，通常在 0.0-0.8 之间
        
        Returns:
            调整后的稀有度分布列表，概率总和为 1
        """
        if len(distribution) < 6:
            # 安全检查：如果分布数组长度不足，直接返回副本
            return distribution.copy()
        
        # 转换系数：1.0 表示 rare_chance 直接作为权重转移比例
        # 例如 rare_chance=0.46 → 从低星转移 46% 的权重到中高星
        TRANSFER_FACTOR = 1.0
        
        actual_boost = rare_chance * TRANSFER_FACTOR
        
        # 限制上限为 0.8，防止低星概率被转移到接近 0 导致游戏体验失衡
        actual_boost = min(actual_boost, 0.8)
        
        new_distribution = distribution.copy()
        
        # 分组计算：
        # - 低星（1-3星，索引 0-2）：普通鱼，作为权重来源
        # - 中高星（4-5星，索引 3-4）：稀有鱼，接收权重转移
        # - 超稀有（6+星，索引 5）：传说鱼，不参与计算以保持稀有性
        low_star_total = sum(new_distribution[:3])
        mid_high_star_total = sum(new_distribution[3:5])
        
        # 边界情况：如果某一组概率为 0，则无法进行权重转移
        if mid_high_star_total <= 0 or low_star_total <= 0:
            return new_distribution
        
        # 计算转移量：从低星总权重中按比例转移
        # 例如：低星总权重 60%，rare_chance 46% → 转移 27.6% 的绝对权重
        transfer_amount = low_star_total * actual_boost
        
        # 步骤 1：从低星（1-3星）按原始比例扣减权重
        # 保持各低星之间的相对比例不变，整体权重减少
        for i in range(3):
            if low_star_total > 0:
                ratio = new_distribution[i] / low_star_total
                new_distribution[i] = max(0, new_distribution[i] - transfer_amount * ratio)
        
        # 步骤 2：向中高星（4-5星）按原始比例分配转移的权重
        # 保持 4星和 5星之间的相对比例不变，整体权重增加
        for i in range(3, 5):
            if mid_high_star_total > 0:
                ratio = new_distribution[i] / mid_high_star_total
                new_distribution[i] = new_distribution[i] + transfer_amount * ratio
        
        # 步骤 3：6+星（索引 5）完全不参与上述计算，保持原值
        # 这确保了超稀有鱼的概率不受装备影响，维持其珍贵性和神秘感
        
        # 归一化处理：确保所有概率之和精确为 1.0
        # 这是必要的，因为浮点运算可能产生微小误差
        new_distribution = [x / sum(new_distribution) for x in new_distribution]
        
        return new_distribution

    def _get_fish_template(self, rarity: int, zone: FishingZone, coins_chance: float):
        """根据稀有度和区域配置获取鱼类模板"""
        
        # 检查 FishingZone 对象是否有 'specific_fish_ids' 属性
        specific_fish_ids = getattr(zone, 'specific_fish_ids', [])

        if specific_fish_ids:
            # 如果是区域限定鱼，那么就在限定的鱼里面抽
            fish_list = [self.item_template_repo.get_fish_by_id(fish_id) for fish_id in specific_fish_ids]
            fish_list = [fish for fish in fish_list if fish and fish.rarity == rarity]
        else:
            # 否则就在全局鱼里面抽
            fish_list = self.item_template_repo.get_fishes_by_rarity(rarity)

        if not fish_list:
            # 如果限定鱼或全局鱼列表为空，则从所有鱼中随机抽取一条
            return self.item_template_repo.get_random_fish(rarity)

        return self.fish_weight_service.choose_fish(fish_list, coins_chance) # <--- 改为使用注入的服务

    def _get_random_high_rarity(self, zone: FishingZone = None) -> int:
        """从6星及以上鱼类中随机选择一个稀有度，兼容区域限定鱼"""
        # 检查是否有区域限定鱼
        specific_fish_ids = getattr(zone, 'specific_fish_ids', []) if zone else []
        
        if specific_fish_ids:
            # 如果是区域限定鱼，只在限定鱼中查找高星级
            fish_list = [self.item_template_repo.get_fish_by_id(fish_id) for fish_id in specific_fish_ids]
            fish_list = [fish for fish in fish_list if fish]
        else:
            # 否则在全局鱼池中查找
            fish_list = self.item_template_repo.get_all_fish()
        
        # 找出所有6星及以上的稀有度
        high_rarities = sorted({fish.rarity for fish in fish_list if fish.rarity >= 6})

        if not high_rarities:
            # 如果没有6星及以上的鱼，返回5星
            return 5

        # 星级越高越难出
        configured = self.config.get("fishing", {}).get("mythic_weights") or HIGH_RARITY_WEIGHTS
        weights = [configured.get(r, 1) for r in high_rarities]
        if sum(weights) <= 0:
            weights = [1] * len(high_rarities)
        return random.choices(high_rarities, weights=weights, k=1)[0]

    def _get_zone_rod_requirement_error(self, user_id: str, zone: FishingZone) -> Optional[str]:
        """检查玩家装备的鱼竿是否达到区域要求的星级。"""
        required = getattr(zone, "required_rod_rarity", 0) or 0
        if required <= 0:
            return None
        equipped_rod = self.inventory_repo.get_user_equipped_rod(user_id)
        rod_template = self.item_template_repo.get_rod_by_id(equipped_rod.rod_id) if equipped_rod else None
        if not rod_template:
            return f"❌ 在{zone.name}钓鱼需要装备 {required} 星及以上的鱼竿，你当前没有装备鱼竿"
        if rod_template.rarity < required:
            return f"❌ 在{zone.name}钓鱼需要装备 {required} 星及以上的鱼竿，当前鱼竿【{rod_template.name}】是 {rod_template.rarity} 星"
        return None

    def get_cooldown_seconds(self, user_id: str, auto: bool = False) -> float:
        """玩家的钓鱼冷却时间。饰品的冷却倍率会生效；自动钓鱼再按效率放慢。"""
        fishing_config = self.config.get("fishing", {})
        cooldown = float(fishing_config.get("cooldown_seconds", 180))
        equipped_accessory = self.inventory_repo.get_user_equipped_accessory(user_id)
        if equipped_accessory:
            template = self.item_template_repo.get_accessory_by_id(equipped_accessory.accessory_id)
            modifier = getattr(template, "cooldown_modifier", 1.0) if template else 1.0
            if modifier is not None and modifier > 0:
                cooldown *= modifier
        if auto:
            efficiency = fishing_config.get("auto_fishing_efficiency", 0.5)
            efficiency = min(1.0, max(0.05, float(efficiency or 0.5)))
            cooldown /= efficiency
        return cooldown

    def set_user_fishing_zone(self, user_id: str, zone_id: int) -> Dict[str, Any]:
        """
        设置用户的钓鱼区域。

        Args:
            user_id: 用户ID。
            zone_id: 要设置的钓鱼区域ID。

        Returns:
            包含操作结果的字典。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        zone = self.inventory_repo.get_zone_by_id(zone_id)
        if not zone:
            return {"success": False, "message": "钓鱼区域不存在"}

        # 检查区域是否激活
        if not zone.is_active:
            return {"success": False, "message": "该钓鱼区域暂未开放"}

        # 检查时间限制
        now = get_now()
        if zone.available_from and now < zone.available_from:
            return {"success": False, "message": f"该钓鱼区域将在 {zone.available_from.strftime('%Y-%m-%d %H:%M')} 开放"}
        
        if zone.available_until and now > zone.available_until:
            return {"success": False, "message": f"该钓鱼区域已于 {zone.available_until.strftime('%Y-%m-%d %H:%M')} 关闭"}

        if zone.id == user.fishing_zone_id:
            return {"success": False, "message": f"你已经在 {zone.name} 了"}

        rod_error = self._get_zone_rod_requirement_error(user_id, zone)
        if rod_error:
            return {"success": False, "message": rod_error}

        # 需要通行证的区域：进入时只检查，当天第一次钓鱼时才消耗
        pass_hint = ""
        if zone.requires_pass and zone.required_item_id:
            item_name = self._item_name(zone.required_item_id)
            if not self._has_zone_pass_today(user_id, zone.id):
                current_quantity = self.inventory_repo.get_user_item_inventory(user_id).get(zone.required_item_id, 0)
                if current_quantity < 1:
                    return {
                        "success": False,
                        "message": f"❌ 进入{zone.name}需要 {item_name}，你当前没有。海鸥港杂货铺有售"
                    }
                pass_hint = f"\n🔑 今天第一次在这里钓鱼时会消耗 1 个 {item_name}，当天有效（你有 {current_quantity} 个）"
            else:
                pass_hint = f"\n🔑 今天的 {item_name} 已生效"

        user.fishing_zone_id = zone.id
        self.user_repo.set_fishing_zone(user_id, zone.id)
        return {"success": True, "message": f"✅已将钓鱼区域设置为 {zone.name}{pass_hint}"}

    def _item_name(self, item_id: int) -> str:
        item_template = self.item_template_repo.get_item_by_id(item_id)
        return item_template.name if item_template else f"道具ID{item_id}"

    def _has_zone_pass_today(self, user_id: str, zone_id: int) -> bool:
        return self.buff_repo.get_active_by_user_and_type(user_id, f"{ZONE_PASS_BUFF}:{zone_id}") is not None

    def _use_zone_pass_if_needed(self, user_id: str, zone: FishingZone):
        """
        需要通行证的区域，当天第一次钓鱼时消耗 1 张通行证，有效到下次每日刷新。
        没在这里钓鱼的日子不消耗。

        Returns:
            (错误消息, 提示消息)，都可能为 None
        """
        if not zone.requires_pass or not zone.required_item_id:
            return None, None
        if self._has_zone_pass_today(user_id, zone.id):
            return None, None
        item_name = self._item_name(zone.required_item_id)
        current_quantity = self.inventory_repo.get_user_item_inventory(user_id).get(zone.required_item_id, 0)
        if current_quantity < 1:
            return (
                f"❌ 今天在{zone.name}钓鱼需要 1 个 {item_name}，你的背包里没有。"
                f"可在海鸥港杂货铺购买，或用「钓鱼区域 1」回到新手港湾"
            ), None
        self.inventory_repo.decrease_item_quantity(user_id, zone.required_item_id, 1)
        now = get_now().replace(tzinfo=None)
        expires_at = get_last_reset_time(self.daily_reset_hour).replace(tzinfo=None) + timedelta(days=1)
        self.buff_repo.add(UserBuff(
            id=None, user_id=user_id, buff_type=f"{ZONE_PASS_BUFF}:{zone.id}",
            payload=None, started_at=now, expires_at=expires_at,
        ))
        self.log_repo.add_log(user_id, "zone_pass", f"使用 1 个 {item_name}，今天可在 {zone.name} 钓鱼")
        return None, f"🔑 已使用 1 个 {item_name}，今天可以在{zone.name}钓鱼（剩余 {current_quantity - 1} 个）"

    def start_auto_fishing_task(self):
        """启动自动钓鱼的后台线程。"""
        if self.auto_fishing_thread and self.auto_fishing_thread.is_alive():
            logger.info("自动钓鱼线程已在运行中")
            return

        self.auto_fishing_running = True
        self._auto_fishing_stop_event.clear()
        self.auto_fishing_thread = threading.Thread(target=self._auto_fishing_loop, daemon=True)
        self.auto_fishing_thread.start()
        logger.info("自动钓鱼线程已启动")

    def stop_auto_fishing_task(self):
        """停止自动钓鱼的后台线程。"""
        self.auto_fishing_running = False
        self._auto_fishing_stop_event.set()
        if self.auto_fishing_thread:
            self.auto_fishing_thread.join(timeout=5.0)
            if self.auto_fishing_thread.is_alive():
                logger.warning("自动钓鱼线程未能在 5 秒内停止")
            else:
                logger.info("自动钓鱼线程已停止")

    def _close_thread_connections(self) -> None:
        """关闭当前后台线程在常用仓储中创建的线程本地连接。"""
        for name in ("user_repo", "inventory_repo", "log_repo", "buff_repo"):
            repo = getattr(self, name, None)
            close = getattr(repo, "close_connection", None)
            if callable(close):
                try:
                    close()
                except Exception as e:
                    logger.warning(f"关闭后台线程数据库连接失败: {e}")

    def _notify(self, user_id: str, message: str) -> None:
        if not self._notifier:
            return
        try:
            self._notifier(user_id, message)
        except Exception:
            pass

    def _process_auto_fishing_user(self, user_id: str) -> None:
        """处理单个自动钓鱼用户，异常由循环按用户隔离。"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return

        # 自动钓鱼按效率放慢出竿间隔，收益低于手动
        cooldown = self.get_cooldown_seconds(user_id, auto=True)
        now_ts = get_now().timestamp()
        last_ts = 0
        if user.last_fishing_time and user.last_fishing_time.year > 1:
            last_ts = user.last_fishing_time.timestamp()
        if now_ts - last_ts < cooldown:
            return

        zone = self.inventory_repo.get_zone_by_id(user.fishing_zone_id)
        if not zone:
            return
        fishing_cost = zone.fishing_cost
        if not user.can_afford(fishing_cost):
            self.user_repo.set_auto_fishing_enabled(user_id, False)
            logger.warning(
                f"用户 {user_id} 金币不足（需要 {fishing_cost} 金币），已关闭自动钓鱼"
            )
            return

        result = self.go_fish(user_id)
        if not result:
            return
        if not result.get("success") and "已自动传送回" in result.get("message", ""):
            self._notify(user_id, f"🌅 {result['message']}")
        if result.get("zone_requirement_failed"):
            # 鱼竿坏了或通行证用完：回到新手港湾继续自动钓鱼
            self.user_repo.set_fishing_zone(user_id, 1)
            first_zone = self.inventory_repo.get_zone_by_id(1)
            self._notify(user_id, f"{result['message']}\n🏠 已回到{first_zone.name if first_zone else '1 号区域'}继续自动钓鱼")
            return

        for msg in result.get("equipment_broken_messages") or []:
            self._notify(user_id, msg)

    def _auto_fishing_loop(self):
        """自动钓鱼循环任务，由后台线程执行。"""
        while self.auto_fishing_running:
            try:
                # 获取所有开启自动钓鱼的用户
                auto_users_ids = self.user_repo.get_all_user_ids(auto_fishing_only=True)

                for user_id in auto_users_ids:
                    try:
                        self._process_auto_fishing_user(user_id)
                    except Exception as e:
                        logger.error(f"用户 {user_id} 自动钓鱼任务出错: {e}", exc_info=True)

                # 每轮检查间隔
                stop_event = getattr(self, "_auto_fishing_stop_event", None)
                if stop_event is not None:
                    if stop_event.wait(40):
                        break
                else:
                    time.sleep(40)

            except Exception as e:
                logger.error(f"自动钓鱼任务出错: {e}")
                # 打印堆栈信息
                import traceback
                logger.error(traceback.format_exc())
                stop_event = getattr(self, "_auto_fishing_stop_event", None)
                if stop_event is not None:
                    if stop_event.wait(60):
                        break
                else:
                    time.sleep(60)

        self._close_thread_connections()
