import json
import random
from datetime import timedelta
from typing import Dict, Any, Optional

# 导入仓储接口和领域模型
from ..database.connection_manager import atomic_game_operation
from ..repositories.abstract_repository import (
    AbstractInventoryRepository,
    AbstractUserRepository,
    AbstractItemTemplateRepository,
)
from .effect_manager import EffectManager
from ..utils import calculate_after_refine, ensure_aware, get_now
from .game_mechanics_service import GameMechanicsService
from ..game_settings import build_refine, refine_tables_for_rarity


class InventoryService:
    """封装与用户库存相关的业务逻辑"""

    def __init__(
        self,
        inventory_repo: AbstractInventoryRepository,
        user_repo: AbstractUserRepository,
        item_template_repo: AbstractItemTemplateRepository,
        effect_manager: EffectManager,
        game_mechanics_service: GameMechanicsService,
        config: Dict[str, Any],
    ):
        self.inventory_repo = inventory_repo
        self.user_repo = user_repo
        self.item_template_repo = item_template_repo
        self.effect_manager = effect_manager
        self.game_mechanics_service = game_mechanics_service
        self.config = config

    # === 短码解析 ===
    def _to_base36(self, n: int) -> str:
        if n < 0:
            raise ValueError("n must be non-negative")
        if n == 0:
            return "0"
        digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        out = []
        while n:
            n, rem = divmod(n, 36)
            out.append(digits[rem])
        return "".join(reversed(out))

    def _from_base36(self, s: str) -> int:
        s = (s or "").strip().upper()
        if not s:
            raise ValueError("empty")
        return int(s, 36)

    def resolve_rod_instance_id(self, user_id: str, token: str) -> Optional[int]:
        """将短码(Rxxxx)解析为 rod_instance_id。大小写不敏感。"""
        if token is None:
            return None
        tok = str(token).strip()
        code = tok.upper()
        if not code.startswith("R"):
            return None
        try:
            return self._from_base36(code[1:])
        except Exception:
            return None

    def resolve_accessory_instance_id(self, user_id: str, token: str) -> Optional[int]:
        """将短码(Axxxx)解析为 accessory_instance_id。大小写不敏感。"""
        if token is None:
            return None
        tok = str(token).strip()
        code = tok.upper()
        if not code.startswith("A"):
            return None
        try:
            return self._from_base36(code[1:])
        except Exception:
            return None

    def get_user_fish_pond(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的鱼塘信息（鱼类库存）。
        """
        inventory_items = self.inventory_repo.get_fish_inventory(user_id)
        total_value = self.inventory_repo.get_fish_inventory_value(user_id)

        # 为了丰富信息，可以从模板仓储获取鱼的详细信息
        enriched_items = []
        for item in inventory_items:
            fish_template = self.item_template_repo.get_fish_by_id(item.fish_id)
            if fish_template:
                # 计算实际价值（高品质鱼双倍价值）
                actual_value = fish_template.base_value * (1 + item.quality_level)
                enriched_items.append({
                    "fish_id": item.fish_id,  # 添加fish_id字段
                    "name": fish_template.name,
                    "rarity": fish_template.rarity,
                    "base_value": fish_template.base_value,
                    "quantity": item.quantity,
                    "quality_level": item.quality_level,  # 添加品质等级
                    "actual_value": actual_value,  # 添加实际价值
                    "quality_label": "✨高品质" if item.quality_level == 1 else "普通"  # 添加品质标签
                })

        return {
            "success": True,
            "fishes": enriched_items,
            "stats": {
                "total_count": sum(item["quantity"] for item in enriched_items),
                "total_value": total_value
            }
        }

    def get_user_rod_inventory(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的鱼竿库存。
        """
        rod_instances = self.inventory_repo.get_user_rod_instances(user_id)
        enriched_rods = []

        for rod_instance in rod_instances:
            rod_template = self.item_template_repo.get_rod_by_id(rod_instance.rod_id)
            if rod_template:
                # 计算精炼后的最大耐久度
                if rod_template.durability is not None:
                    # 每级精炼增加前一级50%的耐久上限
                    refine_bonus_multiplier = (1.5 ** (rod_instance.refine_level - 1))
                    refined_max_durability = int(rod_template.durability * refine_bonus_multiplier)
                else:
                    refined_max_durability = None
                
                enriched_rods.append({
                    "name": rod_template.name,
                    "rarity": rod_template.rarity,
                    "instance_id": rod_instance.rod_instance_id,
                    "display_code": getattr(rod_instance, 'display_code', f"R{self._to_base36(rod_instance.rod_instance_id)}"),
                    "description": rod_template.description,
                    "is_equipped": rod_instance.is_equipped,
                    "is_locked": rod_instance.is_locked,
                    "bonus_fish_quality_modifier": calculate_after_refine(rod_template.bonus_fish_quality_modifier, refine_level= rod_instance.refine_level, rarity=rod_template.rarity),
                    "bonus_fish_quantity_modifier": calculate_after_refine(rod_template.bonus_fish_quantity_modifier, refine_level= rod_instance.refine_level, rarity=rod_template.rarity),
                    "bonus_rare_fish_chance": calculate_after_refine(rod_template.bonus_rare_fish_chance, refine_level= rod_instance.refine_level, rarity=rod_template.rarity),
                    "refine_level": rod_instance.refine_level,
                    "current_durability": rod_instance.current_durability,
                    "max_durability": refined_max_durability,
                    "sell_price": self.game_mechanics_service.calculate_sell_price(
                        "rod", rod_template.rarity, rod_instance.refine_level, rod_template.purchase_cost,
                    ),
                })
        # 排序：装备的鱼竿优先显示，然后按稀有度降序，最后按精炼等级降序
        enriched_rods.sort(key=lambda x: (
            not x["is_equipped"],  # False (装备中) 排在前面
            -x["rarity"],          # 稀有度降序
            -x["refine_level"],    # 精炼等级降序
            x["instance_id"],
        ))
        
        return {
            "success": True,
            "rods": enriched_rods
        }

    def get_user_bait_inventory(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的鱼饵库存。
        """
        bait_inventory = self.inventory_repo.get_user_bait_inventory(user_id)
        enriched_baits = []

        for bait_id, quantity in bait_inventory.items():
            bait_template = self.item_template_repo.get_bait_by_id(bait_id)
            if bait_template:
                enriched_baits.append({
                    "bait_id": bait_id,
                    "name": bait_template.name,
                    "rarity": bait_template.rarity,
                    "quantity": quantity,
                    "duration_minutes": bait_template.duration_minutes,
                    "effect_description": bait_template.effect_description
                })

        return {
            "success": True,
            "baits": enriched_baits
        }

    def get_user_accessory_inventory(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的饰品库存。
        """
        accessory_instances = self.inventory_repo.get_user_accessory_instances(user_id)
        enriched_accessories = []

        for accessory_instance in accessory_instances:
            accessory_template = self.item_template_repo.get_accessory_by_id(accessory_instance.accessory_id)
            if accessory_template:
                enriched_accessories.append({
                    "name": accessory_template.name,
                    "rarity": accessory_template.rarity,
                    "instance_id": accessory_instance.accessory_instance_id,
                    "display_code": getattr(accessory_instance, 'display_code', f"A{self._to_base36(accessory_instance.accessory_instance_id)}"),
                    "description": accessory_template.description,
                    "is_equipped": accessory_instance.is_equipped,
                    "is_locked": accessory_instance.is_locked,
                    "bonus_fish_quality_modifier": calculate_after_refine(accessory_template.bonus_fish_quality_modifier, refine_level=accessory_instance.refine_level, rarity=accessory_template.rarity),
                    "bonus_fish_quantity_modifier": calculate_after_refine(accessory_template.bonus_fish_quantity_modifier, refine_level=accessory_instance.refine_level, rarity=accessory_template.rarity),
                    "bonus_rare_fish_chance": calculate_after_refine(accessory_template.bonus_rare_fish_chance, refine_level=accessory_instance.refine_level, rarity=accessory_template.rarity),
                    "bonus_coin_modifier": calculate_after_refine(accessory_template.bonus_coin_modifier, refine_level=accessory_instance.refine_level, rarity=accessory_template.rarity),
                    "refine_level": accessory_instance.refine_level,
                    "sell_price": self.game_mechanics_service.calculate_sell_price(
                        "accessory", accessory_template.rarity, accessory_instance.refine_level,
                    ),
                })

        # 排序：装备的饰品优先显示，然后按稀有度降序，最后按精炼等级降序
        enriched_accessories.sort(key=lambda x: (
            not x["is_equipped"],  # False (装备中) 排在前面
            -x["rarity"],          # 稀有度降序
            -x["refine_level"],    # 精炼等级降序
            x["instance_id"],
        ))
        
        return {
            "success": True,
            "accessories": enriched_accessories
        }

    def get_user_item_inventory(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户的道具库存。
        """
        item_inventory = self.inventory_repo.get_user_item_inventory(user_id)
        enriched_items = []

        for item_id, quantity in item_inventory.items():
            item_template = self.item_template_repo.get_item_by_id(item_id)
            if item_template:
                enriched_items.append({
                    "item_id": item_id,
                    "name": item_template.name,
                    "rarity": item_template.rarity,
                    "quantity": quantity,
                    "effect_description": item_template.effect_description,
                    "effect_type": item_template.effect_type,
                    "is_consumable": getattr(item_template, "is_consumable", False),
                })

        return {
            "success": True,
            "items": enriched_items
        }

    def sell_all_fish(self, user_id: str) -> Dict[str, Any]:
        """向系统卖出鱼塘中所有的鱼。"""
        if not self.user_repo.check_exists(user_id):
            return {"success": False, "message": "用户不存在"}

        sale = self.inventory_repo.sell_fish_atomic(user_id)
        sold_value = sale["total_value"]
        if sold_value <= 0:
            return {"success": False, "message": "❌ 你没有可以卖出的鱼"}

        sold_details = {"普通": 0, "✨高品质": 0}
        for detail in sale["details"]:
            key = "✨高品质" if detail["quality_level"] == 1 else "普通"
            sold_details[key] += int(detail["quantity"])

        # 构建详细消息
        message = f"💰 成功卖出鱼，获得 {sold_value} 金币"
        if sold_details["✨高品质"] > 0:
            message += f"\n📊 出售详情：普通鱼 {sold_details['普通']} 条，✨高品质鱼 {sold_details['✨高品质']} 条"

        return {"success": True, "message": message}

    def sell_fish_by_rarity(self, user_id: str, rarity: int) -> Dict[str, Any]:
        """
        向系统出售指定稀有度的鱼。

        Args:
            user_id: 用户ID
            rarity: 鱼的稀有度
        """
        if not self.user_repo.check_exists(user_id):
            return {"success": False, "message": "用户不存在"}

        sale = self.inventory_repo.sell_fish_atomic(user_id, rarities=[rarity])
        total_value = sale["total_value"]
        if total_value <= 0:
            return {"success": False, "message": "❌ 没有可卖出的鱼"}

        sold_details = {"普通": 0, "✨高品质": 0}
        for detail in sale["details"]:
            key = "✨高品质" if detail["quality_level"] == 1 else "普通"
            sold_details[key] += int(detail["quantity"])

        # 构建详细消息
        message = f"💰 成功卖出稀有度 {rarity} 的鱼，获得 {total_value} 金币"
        if sold_details["✨高品质"] > 0:
            message += f"\n📊 出售详情：普通鱼 {sold_details['普通']} 条，✨高品质鱼 {sold_details['✨高品质']} 条"

        return {"success": True, "message": message}

    def sell_fish_by_rarities(self, user_id: str, rarities: list[int]) -> Dict[str, Any]:
        """
        向系统出售指定稀有度列表的鱼。

        Args:
            user_id: 用户ID
            rarities: 鱼的稀有度列表, e.g., [3, 4, 5]
        """
        if not self.user_repo.check_exists(user_id):
            return {"success": False, "message": "用户不存在"}

        # 1. 验证并去重稀有度列表
        if not rarities:
            return {"success": False, "message": "❌ 请指定要出售的稀有度"}
        
        unique_rarities = set(r for r in rarities if 1 <= r <= 10)
        if not unique_rarities:
            return {"success": False, "message": "❌ 请提供有效的稀有度（1-10之间）"}

        sale = self.inventory_repo.sell_fish_atomic(
            user_id, rarities=list(unique_rarities)
        )
        total_value = sale["total_value"]
        sold_fish_details = {}
        for row in sale["details"]:
            rarity_value = int(row["rarity"])
            detail = sold_fish_details.setdefault(
                rarity_value,
                {"count": 0, "value": 0, "normal": 0, "high_quality": 0},
            )
            quantity = int(row["quantity"])
            detail["count"] += quantity
            detail["value"] += int(row["value"])
            if row["quality_level"] == 1:
                detail["high_quality"] += quantity
            else:
                detail["normal"] += quantity

        # 4. 如果没有符合条件的鱼，提前返回
        if total_value == 0:
            rarity_str = ", ".join(map(str, sorted(list(unique_rarities))))
            return {"success": False, "message": f"❌ 你没有任何稀有度为【{rarity_str}】的鱼可以出售"}

        # 5. 构建并返回成功的消息
        rarity_str_sold = ", ".join(map(str, sorted(sold_fish_details.keys())))
        message = f"💰 成功卖出稀有度为【{rarity_str_sold}】的鱼，共获得 {total_value} 金币。\n\n"
        message += "📊 出售详情：\n"
        for r in sorted(sold_fish_details.keys()):
            details = sold_fish_details[r]
            quality_info = ""
            if details['high_quality'] > 0:
                quality_info = f"（普通 {details['normal']} 条，✨高品质 {details['high_quality']} 条）"
            message += f" - 稀有度 {r}: {details['count']} 条{quality_info}，价值 {details['value']} 金币\n"

        return {"success": True, "message": message, "gained_coins": total_value}

    @atomic_game_operation
    def sell_everything_except_locked(self, user_id: str) -> Dict[str, Any]:
        """
        卖出所有未锁定且未装备的鱼竿、饰品和鱼塘中的鱼
        保留当前装备的鱼竿和饰品，以及所有锁定的装备
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        rod_prices = {}
        rod_instances = self.inventory_repo.get_user_rod_instances(user_id)
        for rod_instance in rod_instances:
            if not rod_instance.is_locked and not rod_instance.is_equipped:
                rod_template = self.item_template_repo.get_rod_by_id(rod_instance.rod_id)
                if rod_template:
                    rod_prices[rod_instance.rod_instance_id] = self.game_mechanics_service.calculate_sell_price(
                        item_type="rod",
                        rarity=rod_template.rarity,
                        refine_level=rod_instance.refine_level,
                        purchase_cost=rod_template.purchase_cost,
                    )

        accessory_prices = {}
        accessory_instances = self.inventory_repo.get_user_accessory_instances(user_id)
        for accessory_instance in accessory_instances:
            if not accessory_instance.is_locked and not accessory_instance.is_equipped:
                accessory_template = self.item_template_repo.get_accessory_by_id(accessory_instance.accessory_id)
                if accessory_template:
                    accessory_prices[accessory_instance.accessory_instance_id] = self.game_mechanics_service.calculate_sell_price(
                        item_type="accessory",
                        rarity=accessory_template.rarity,
                        refine_level=accessory_instance.refine_level,
                    )

        sold_items = self.inventory_repo.sell_everything_atomic(
            user_id, rod_prices, accessory_prices
        )
        total_value = sold_items["total_value"]

        if total_value == 0:
            return {"success": False, "message": "❌ 没有可出售的物品（可能全部被锁定或仓库为空）"}

        coins_from_bags = self.open_all_money_bags(user_id).get("total_gained", 0)

        # 构造详细的结果消息
        grand_total = total_value + coins_from_bags
        message = f"💰 卖出所有家产完成！总共获得 {grand_total} 金币\n\n"
        message += "📊 出售详情：\n"
        
        if sold_items["fish_count"] > 0:
            message += f"🐟 鱼类：{sold_items['fish_count']} 条 (💰 {sold_items['fish_value']} 金币)\n"
        
        if sold_items["rod_count"] > 0:
            message += f"🎣 鱼竿：{sold_items['rod_count']} 根 (💰 {sold_items['rod_value']} 金币)\n"
        
        if sold_items["accessory_count"] > 0:
            message += f"💍 饰品：{sold_items['accessory_count']} 件 (💰 {sold_items['accessory_value']} 金币)\n"

        if coins_from_bags > 0:
            message += f"👜 钱袋：自动开启获得 (💰 {coins_from_bags} 金币)\n"
        
        message += f"\n🔒 已锁定和装备中的装备已自动保留"
        
        return {"success": True, "message": message}

    @atomic_game_operation
    def sell_rod(self, user_id: str, rod_instance_id: int) -> Dict[str, Any]:
        """
        向系统出售指定的鱼竿。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 1. 验证鱼竿是否属于该用户
        user_rods = self.inventory_repo.get_user_rod_instances(user_id)
        rod_to_sell = next((r for r in user_rods if r.rod_instance_id == rod_instance_id), None)

        if not rod_to_sell:
            return {"success": False, "message": "鱼竿不存在或不属于你"}

        # 检查是否锁定
        if rod_to_sell.is_locked:
            return {"success": False, "message": "该鱼竿已锁定，无法出售"}

        # 2. 获取鱼竿模板以计算售价
        rod_template = self.item_template_repo.get_rod_by_id(rod_to_sell.rod_id)
        if not rod_template:
             return {"success": False, "message": "找不到鱼竿的基础信息"}

        # 3. 计算售价
        sell_price = self.game_mechanics_service.calculate_sell_price(
            item_type="rod",
            rarity=rod_template.rarity,
            refine_level=rod_to_sell.refine_level,
            purchase_cost=rod_template.purchase_cost,
        )

        # 4. 执行操作
        # 如果卖出的是当前装备的鱼竿，需要先卸下
        if rod_to_sell.is_equipped:
            user.equipped_rod_instance_id = None

        self.inventory_repo.delete_rod_instance(rod_instance_id)
        user.coins += sell_price
        self.user_repo.update(user)

        return {"success": True, "message": f"成功出售鱼竿【{rod_template.name}】，获得 {sell_price} 金币"}

    @atomic_game_operation
    def sell_all_rods(self, user_id: str) -> Dict[str, Any]:
        """
        向系统卖出所有可出售的鱼竿。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 获取用户的鱼竿库存
        user_rods = self.inventory_repo.get_user_rod_instances(user_id)
        if not user_rods:
            return {"success": False, "message": "❌ 你没有可以卖出的鱼竿"}

        total_value = 0
        rods_to_sell = []
        
        # 只计算可以卖出的鱼竿（未锁定、未装备且小于5星）
        for rod_instance in user_rods:
            if rod_instance.is_equipped or rod_instance.is_locked:
                continue
            rod_template = self.item_template_repo.get_rod_by_id(rod_instance.rod_id)
            if rod_template and rod_template.rarity < 5:  # 只计算小于5星的鱼竿
                sell_price = self.game_mechanics_service.calculate_sell_price(
                    item_type="rod",
                    rarity=rod_template.rarity,
                    refine_level=rod_instance.refine_level,
                    purchase_cost=rod_template.purchase_cost,
                )
                total_value += sell_price
                rods_to_sell.append(rod_instance)
        
        if total_value == 0:
            return {"success": False, "message": "❌ 没有可以卖出的鱼竿（已自动保留锁定、已装备或5星以上的鱼竿）"}
        
        # 逐个删除可以卖出的鱼竿
        for rod_instance in rods_to_sell:
            self.inventory_repo.delete_rod_instance(rod_instance.rod_instance_id)
        
        # 更新用户金币
        user.coins += total_value
        self.user_repo.update(user)
        return {"success": True, "message": f"💰 成功卖出 {len(rods_to_sell)} 根鱼竿，获得 {total_value} 金币"}

    @atomic_game_operation
    def sell_accessory(self, user_id: str, accessory_instance_id: int) -> Dict[str, Any]:
        """
        向系统出售指定的饰品。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 1. 验证饰品是否属于该用户
        user_accessories = self.inventory_repo.get_user_accessory_instances(user_id)
        accessory_to_sell = next((a for a in user_accessories if a.accessory_instance_id == accessory_instance_id), None)

        if not accessory_to_sell:
            return {"success": False, "message": "饰品不存在或不属于你"}

        # 检查是否锁定
        if accessory_to_sell.is_locked:
            return {"success": False, "message": "该饰品已锁定，无法出售"}

        # 2. 获取饰品模板以计算售价
        accessory_template = self.item_template_repo.get_accessory_by_id(accessory_to_sell.accessory_id)
        if not accessory_template:
            return {"success": False, "message": "找不到饰品的基础信息"}

        # 3. 计算售价
        sell_price = self.game_mechanics_service.calculate_sell_price(
            item_type="accessory",
            rarity=accessory_template.rarity,
            refine_level=accessory_to_sell.refine_level,
        )

        # 4. 执行操作
        # 如果卖出的是当前装备的饰品，需要先卸下
        if accessory_to_sell.is_equipped:
            user.equipped_accessory_instance_id = None
        self.inventory_repo.delete_accessory_instance(accessory_instance_id)
        user.coins += sell_price
        self.user_repo.update(user)
        return {"success": True, "message": f"成功出售饰品【{accessory_template.name}】，获得 {sell_price} 金币"}

    @atomic_game_operation
    def sell_all_accessories(self, user_id: str) -> Dict[str, Any]:
        """
        向系统卖出所有可出售的饰品。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 获取用户的饰品库存
        user_accessories = self.inventory_repo.get_user_accessory_instances(user_id)
        if not user_accessories:
            return {"success": False, "message": "❌ 你没有可以卖出的饰品"}

        total_value = 0
        accessories_to_sell = []
        
        # 只计算可以卖出的饰品（未锁定、未装备且小于5星）
        for accessory_instance in user_accessories:
            if accessory_instance.is_equipped or accessory_instance.is_locked:
                continue
            accessory_template = self.item_template_repo.get_accessory_by_id(accessory_instance.accessory_id)
            if accessory_template and accessory_template.rarity < 5:  # 只计算小于5星的饰品
                sell_price = self.game_mechanics_service.calculate_sell_price(
                    item_type="accessory",
                    rarity=accessory_template.rarity,
                    refine_level=accessory_instance.refine_level,
                )
                total_value += sell_price
                accessories_to_sell.append(accessory_instance)

        if total_value == 0:
            return {"success": False, "message": "❌ 没有可以卖出的饰品（已自动保留锁定、已装备或5星以上的饰品）"}

        # 逐个删除可以卖出的饰品
        for accessory_instance in accessories_to_sell:
            self.inventory_repo.delete_accessory_instance(accessory_instance.accessory_instance_id)
        
        # 更新用户金币
        user.coins += total_value
        self.user_repo.update(user)

        return {"success": True, "message": f"💰 成功卖出 {len(accessories_to_sell)} 件饰品，获得 {total_value} 金币"}

    def sell_equipment(self, user_id: str, instance_id: int, item_type: str) -> Dict[str, Any]:
        """
        统一出售装备方法 - 根据类型自动调用对应的出售方法
        
        Args:
            user_id: 用户ID
            instance_id: 物品实例ID
            item_type: 物品类型，"rod"或"accessory"
        """
        if item_type == "rod":
            return self.sell_rod(user_id, instance_id)
        elif item_type == "accessory":
            return self.sell_accessory(user_id, instance_id)
        else:
            return {"success": False, "message": "❌ 不支持的装备类型"}

    @atomic_game_operation
    def equip_item(self, user_id: str, instance_id: int, item_type: str) -> Dict[str, Any]:
        """
        装备一个物品（鱼竿或饰品）。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}
        equip_item_name = ""
        equip_item_id = None
        # 验证物品归属
        if item_type == "rod":
            # 获取目标实例并校验归属
            target_instance = self.inventory_repo.get_user_rod_instance_by_id(user_id, instance_id)
            if not target_instance:
                return {"success": False, "message": "❌ 鱼竿不存在或不属于你"}
            equip_item_id = target_instance.rod_id

            # 阻止装备 0 耐久（非无限）鱼竿
            if target_instance.current_durability is not None and target_instance.current_durability <= 0:
                return {
                    "success": False,
                    "message": "❌ 该鱼竿已损坏（耐久为 0），无法装备。请精炼成功以恢复耐久或更换鱼竿。"
                }

            user.equipped_rod_instance_id = instance_id
            equip_item_name = self.item_template_repo.get_rod_by_id(equip_item_id).name

        elif item_type == "accessory":
            instances = self.inventory_repo.get_user_accessory_instances(user_id)
            for instance in instances:
                if instance.accessory_instance_id == instance_id:
                    equip_item_id = instance.accessory_id
                    break
            if instance_id not in [i.accessory_instance_id for i in instances]:
                return {"success": False, "message": "❌ 饰品不存在或不属于你"}
            user.equipped_accessory_instance_id = instance_id
            equip_item_name = self.item_template_repo.get_accessory_by_id(equip_item_id).name
        else:
            return {"success": False, "message": "❌ 不支持的装备类型"}

        # 统一由一个仓储方法处理装备状态的事务性
        self.inventory_repo.set_equipment_status(
            user_id,
            rod_instance_id=user.equipped_rod_instance_id,
            accessory_instance_id=user.equipped_accessory_instance_id
        )
        # 更新用户表
        self.user_repo.update(user)

        return {"success": True, "message": f"💫 装备 【{equip_item_name}】 成功！"}

    @atomic_game_operation
    def use_bait(self, user_id: str, bait_id: int) -> Dict[str, Any]:
        """
        使用一个鱼饵。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 检查是否有此鱼饵
        bait_inventory = self.inventory_repo.get_user_bait_inventory(user_id)
        if bait_inventory.get(bait_id, 0) <= 0:
            return {"success": False, "message": "你没有这个鱼饵"}

        bait_template = self.item_template_repo.get_bait_by_id(bait_id)
        if not bait_template:
            return {"success": False, "message": "鱼饵信息不存在"}

        required_rod_rarity = getattr(bait_template, "required_rod_rarity", 0) or 0
        if required_rod_rarity > 0:
            equipped_rod = self.inventory_repo.get_user_equipped_rod(user_id)
            if not equipped_rod:
                return {
                    "success": False,
                    "message": f"使用【{bait_template.name}】需要装备 {required_rod_rarity} 星及以上鱼竿"
                }

            rod_template = self.item_template_repo.get_rod_by_id(equipped_rod.rod_id)
            if not rod_template or rod_template.rarity < required_rod_rarity:
                current_rarity = rod_template.rarity if rod_template else 0
                return {
                    "success": False,
                    "message": f"使用【{bait_template.name}】需要 {required_rod_rarity} 星及以上鱼竿，当前鱼竿为 {current_rarity} 星"
                }

        # Time-based bait occupies one stock unit until it expires or is replaced.
        now = get_now()
        previous_bait = self.item_template_repo.get_bait_by_id(user.current_bait_id) if user.current_bait_id else None
        previous_start = ensure_aware(user.bait_start_time)
        if previous_bait and previous_bait.duration_minutes > 0 and previous_start:
            if previous_bait.bait_id == bait_id and now < previous_start + timedelta(minutes=previous_bait.duration_minutes):
                return {"success": True, "message": f"正在使用鱼饵【{bait_template.name}】"}
            self.inventory_repo.update_bait_quantity(user_id, previous_bait.bait_id, -1)
            if previous_bait.bait_id == bait_id and bait_inventory[bait_id] == 1:
                self.user_repo.update_bait_state(user_id, None, None)
                return {"success": False, "message": "上一份鱼饵已到期，背包里没有剩余鱼饵"}

        start = now if bait_template.duration_minutes > 0 else None
        self.user_repo.update_bait_state(user_id, bait_id, start)

        return {"success": True, "message": f"💫 成功使用鱼饵【{bait_template.name}】"}

    def get_user_fish_pond_capacity(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户鱼塘容量以及当前容量。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}
        fish_inventory = self.inventory_repo.get_fish_inventory(user_id)
        next_upgrade = self._next_pond_upgrade(user.fish_pond_capacity)
        return {
            "success": True,
            "fish_pond_capacity": user.fish_pond_capacity,
            "current_fish_count": sum(item.quantity for item in fish_inventory),
            "total_value": self.inventory_repo.get_fish_inventory_value(user_id),
            "next_capacity": next_upgrade["to"] if next_upgrade else None,
            "next_cost": next_upgrade["cost"] if next_upgrade else None,
        }

    def _next_pond_upgrade(self, capacity: int):
        """下一档鱼塘升级。容量不在档位上（如管理员改过）时取第一个更大的档位。"""
        for upgrade in self.config.get("pond_upgrades", []):
            if upgrade["to"] > capacity:
                return upgrade
        return None

    @atomic_game_operation
    def upgrade_fish_pond(self, user_id: str) -> Dict[str, Any]:
        """
        升级鱼塘容量。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        next_upgrade = self._next_pond_upgrade(user.fish_pond_capacity)

        if not next_upgrade:
            return {"success": False, "message": "鱼塘容量已达到最大，无法再升级"}

        cost = next_upgrade["cost"]
        if not user.can_afford(cost):
            return {"success": False, "message": f"金币不足，升级需要 {cost} 金币"}

        # 执行升级
        user.coins -= cost
        user.fish_pond_capacity = next_upgrade["to"]
        self.user_repo.update(user)

        return {
            "success": True,
            "message": f"鱼塘升级成功！新容量为 {user.fish_pond_capacity}。",
            "new_capacity": user.fish_pond_capacity,
            "cost": cost
        }
    @atomic_game_operation
    def refine(self, user_id, instance_id: int, item_type: str):
        """
        精炼鱼竿或饰品，提升其属性。

        Args:
            user_id: 用户ID
            instance_id: 物品实例ID
            item_type: 物品类型，"rod"或"accessory"
        """
        # 检查用户是否存在
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 根据物品类型设置相关配置
        if item_type not in ["rod", "accessory"]:
            return {"success": False, "message": "❌ 不支持的精炼类型"}

        config = self._get_item_config(item_type, instance_id, user_id)
        if not config["success"]:
            return config

        # 解包配置
        instance = config["instance"]
        template = config["template"]
        item_name = config["item_name"]
        id_field = config["id_field"]

        # 检查精炼等级
        if instance.refine_level >= 10:
            return {"success": False, "message": "已达到最高精炼等级"}

        # 获取装备稀有度
        rarity = template.rarity if hasattr(template, 'rarity') else 5

        # 根据稀有度调整精炼费用和成功率
        refine_costs, success_rates = self._get_refine_config_by_rarity(rarity)

        # 获取同类型物品列表
        same_items = config["same_items"]
        if len(same_items) < 2:
            return {"success": False, "message": f"需要至少两个同类型{item_name}进行精炼。当前拥有：{len(same_items)}个"}

        # 查找合适的消耗品进行精炼
        return self._find_refinement_candidate(
            user, instance, template, same_items, refine_costs, id_field, item_type, success_rates
        )

    def _get_refine_config_by_rarity(self, rarity: int) -> tuple:
        """按装备星级取精炼费用表和成功率表（来自配置 refine，未配置时用默认值）。"""
        refine = self.config.get("refine") or build_refine({})
        return refine_tables_for_rarity(refine, rarity)

    def _determine_failure_type(self, instance, template) -> str:
        """
        确定精炼失败的类型：普通失败、降级失败、毁坏失败
        
        Args:
            instance: 装备实例
            template: 装备模板
            
        Returns:
            str: "normal", "downgrade", "destruction"
        """
        import random
        
        # 获取装备稀有度和精炼等级
        rarity = template.rarity if template and hasattr(template, 'rarity') else 5
        refine_level = instance.refine_level
        
        # 基础概率设置
        downgrade_chance = 0.10  # 固定10%概率降级
        destruction_chance = 0.0
            
        # 根据稀有度调整毁坏概率
        if refine_level >= 5:
            if rarity <= 2:
                destruction_chance = 0.30  # 10% + 20% = 30%
            elif rarity <= 4:
                destruction_chance = 0.35  # 15% + 20% = 35%
            elif rarity <= 6:
                destruction_chance = 0.40  # 20% + 20% = 40%
            else:
                destruction_chance = 0.50  # 30% + 20% = 50%
                
        # 随机决定失败类型
        rand = random.random()
        
        if rand < destruction_chance:
            return "destruction"
        elif rand < destruction_chance + downgrade_chance:
            return "downgrade"
        else:
            return "normal"

    def _get_item_config(self, item_type, instance_id, user_id) -> Dict[str, Any]:
        """获取物品配置信息"""        
        if item_type == "rod":
            instances = self.inventory_repo.get_user_rod_instances(user_id)
            instance = next((i for i in instances if i.rod_instance_id == instance_id), None)
            if not instance:
                return {"success": False, "message": "鱼竿不存在或不属于你"}

            # 锁定装备可以作为主装备精炼，但不能作为材料

            template = self.item_template_repo.get_rod_by_id(instance.rod_id)
            same_items = self.inventory_repo.get_same_rod_instances(user_id, instance.rod_id)

            return {
                "success": True,
                "instance": instance,
                "template": template,
                "same_items": same_items,
                "item_name": "鱼竿",
                "id_field": "rod_instance_id"
            }

        else:  # accessory
            instances = self.inventory_repo.get_user_accessory_instances(user_id)
            instance = next((i for i in instances if i.accessory_instance_id == instance_id), None)
            if not instance:
                return {"success": False, "message": "饰品不存在或不属于你"}

            # 锁定装备可以作为主装备精炼，但不能作为材料

            template = self.item_template_repo.get_accessory_by_id(instance.accessory_id)
            same_items = self.inventory_repo.get_same_accessory_instances(user_id, instance.accessory_id)

            return {
                "success": True,
                "instance": instance,
                "template": template,
                "same_items": same_items,
                "item_name": "饰品",
                "id_field": "accessory_instance_id"
            }

    def _find_refinement_candidate(self, user, instance, template, same_items, refine_costs, id_field, item_type, success_rates):
        candidate = min(
            (item for item in same_items
             if getattr(item, id_field) != getattr(instance, id_field) and not item.is_equipped and not item.is_locked),
            key=lambda item: (item.refine_level, getattr(item, id_field)),
            default=None,
        )
        if candidate is None:
            return {"success": False, "message": "没有可消耗的同款装备，请确认材料没有装备或锁定"}

        cost = refine_costs.get(instance.refine_level, 0)
        if not user.can_afford(cost):
            return {"success": False, "message": f"至少需要 {cost} 金币才能精炼，当前金币不足"}

        target_level = instance.refine_level + 1
        rate = success_rates.get(target_level, 1.0)
        if random.random() >= rate:
            user.coins -= cost
            self.user_repo.update(user)
            if item_type == "rod":
                self.inventory_repo.delete_rod_instance(candidate.rod_instance_id)
            else:
                self.inventory_repo.delete_accessory_instance(candidate.accessory_instance_id)
            return self._refinement_failure(user.user_id, instance, template, item_type, target_level, rate)

        first_infinite = self._perform_refinement(user, instance, candidate, target_level, cost, item_type)
        message = f"成功精炼{template.name}，新精炼等级为 {instance.refine_level}。"
        if first_infinite:
            message += " 🎉 装备已获得无限耐久！"
        elif item_type == "rod" and instance.current_durability is not None:
            message += f" 耐久度已恢复至 {instance.current_durability}！"
        return {"success": True, "message": message, "new_refine_level": instance.refine_level}

    def _refinement_failure(self, user_id, instance, template, item_type, target_level, rate):
        outcome = self._determine_failure_type(instance, template)
        result = {"success": False, "failed": True, "destroyed": False, "target_level": target_level, "success_rate": rate}
        shield_name = None
        shield_mode = None
        if outcome in ("downgrade", "destruction"):
            owned = self.inventory_repo.get_user_item_inventory(user_id)
            shields = []
            for item in self.item_template_repo.get_all_items():
                if item.effect_type != "REFINE_DESTRUCTION_SHIELD" or not owned.get(item.item_id):
                    continue
                try:
                    payload = json.loads(item.effect_payload or "{}")
                    if not isinstance(payload, dict):
                        continue
                    mode = payload.get("mode", "keep")
                    limit = payload.get("max_rarity")
                    if limit is not None:
                        limit = int(limit)
                except (ValueError, TypeError):
                    continue
                if mode not in ("keep", "downgrade") or (limit is not None and limit < template.rarity):
                    continue
                if outcome == "downgrade" and (mode != "keep" or limit is not None):
                    continue
                priority = (mode == "keep", limit is None, limit or 0)
                shields.append((priority, item, mode))
            if shields:
                _, shield, shield_mode = max(shields, key=lambda candidate: candidate[0])
                self.inventory_repo.decrease_item_quantity(user_id, shield.item_id, 1)
                shield_name = shield.name
            elif outcome == "destruction":
                repo = self.game_mechanics_service.buff_repo
                buff = repo.get_active_by_user_and_type(user_id, "REFINE_DESTRUCTION_SHIELD")
                if buff and buff.payload:
                    try:
                        payload = json.loads(buff.payload)
                        if isinstance(payload, dict) and int(payload.get("charges", 0)) > 0:
                            charges = int(payload["charges"]) - 1
                            shield_mode = payload.get("mode", "keep")
                            shield_name = "精炼护符"
                            if charges > 0:
                                payload["charges"] = charges
                                buff.payload = json.dumps(payload)
                                repo.update(buff)
                            else:
                                repo.delete(buff.id)
                    except (ValueError, TypeError):
                        pass

        if shield_name and shield_mode != "downgrade":
            result["message"] = f"🛡 {shield_name}生效，{template.name}保留原精炼等级。"
        elif outcome == "downgrade" or shield_name:
            instance.refine_level = max(1, instance.refine_level - 1)
            if item_type == "rod":
                if template.durability is not None:
                    cap = int(template.durability * 1.5 ** (instance.refine_level - 1))
                    current = instance.current_durability
                    instance.current_durability = cap if current is None else min(cap, current)
                self.inventory_repo.update_rod_instance(instance)
            else:
                self.inventory_repo.update_accessory_instance(instance)
            prefix = f"🛡 {shield_name}生效，" if shield_name else "📉 精炼失败，"
            result.update(
                message=f"{prefix}{template.name}降至 {instance.refine_level} 级。",
                level_reduced=True, new_refine_level=instance.refine_level,
            )
        elif outcome == "destruction":
            if item_type == "rod":
                self.inventory_repo.delete_rod_instance(instance.rod_instance_id)
            else:
                self.inventory_repo.delete_accessory_instance(instance.accessory_instance_id)
            result.update(message=f"💥 精炼失败，{template.name}已毁坏。", destroyed=True)
        else:
            result["message"] = f"💔 精炼失败，未能提升到 {target_level} 级（已消耗材料与金币，成功率 {rate:.0%}）。"
        return result

    def _perform_refinement(
        self, user, instance, candidate, new_refine_level, cost, item_type
    ):
        """执行精炼操作，返回是否首次获得无限耐久"""
        # 扣除金币
        user.coins -= cost

        # 获取原始最大耐久度（用于计算精炼加成）
        if item_type == "rod":
            template = self.item_template_repo.get_rod_by_id(instance.rod_id)
        else:
            template = self.item_template_repo.get_accessory_by_id(instance.accessory_id)
        
        # 检查模板是否存在durability属性（配饰可能没有耐久度）
        original_max_durability = None
        if template and hasattr(template, 'durability') and template.durability is not None:
            original_max_durability = template.durability

        # 提升精炼等级
        instance.refine_level = new_refine_level

        # 检查精炼前是否已经是无限耐久（配饰可能没有耐久度属性）
        was_infinite_before = (hasattr(instance, 'current_durability') and 
                              instance.current_durability is None)

        # 处理耐久度恢复和上限提升
        is_first_infinite = False
        
        # 获取装备稀有度（对于所有装备类型）
        rarity = template.rarity if template and hasattr(template, 'rarity') else 1
        
        # 检查是否符合无限耐久条件（5星以上10级）
        if new_refine_level >= 10 and rarity >= 5:
            # 只有装备实例支持耐久度时才设置无限耐久
            if hasattr(instance, 'current_durability'):
                instance.current_durability = None  # 无限耐久
                # 标记是否首次获得无限耐久
                is_first_infinite = not was_infinite_before
            # 更新最大耐久度为None（如果装备实例有这个字段）
            if hasattr(instance, 'max_durability'):
                instance.max_durability = None
        elif original_max_durability is not None:
            # 普通精炼：计算新的最大耐久度（仅适用于有耐久度的装备）
            # 公式：新上限 = 原始上限 * (1.5)^精炼等级
            refine_bonus_multiplier = (1.5 ** (new_refine_level - 1))
            new_max_durability = int(original_max_durability * refine_bonus_multiplier)
            
            # 精炼成功时恢复全部耐久度到新的最大值（仅对支持耐久度的装备）
            if hasattr(instance, 'current_durability'):
                instance.current_durability = new_max_durability
            
            # 更新最大耐久度（如果装备实例有这个字段）
            if hasattr(instance, 'max_durability'):
                instance.max_durability = new_max_durability

        # 根据物品类型执行相应操作
        if item_type == "rod":
            self.inventory_repo.update_rod_instance(instance)
            self.inventory_repo.delete_rod_instance(candidate.rod_instance_id)
        else:  # accessory
            self.inventory_repo.update_accessory_instance(instance)
            self.inventory_repo.delete_accessory_instance(candidate.accessory_instance_id)

        # 更新用户信息
        self.user_repo.update(user)
        
        return is_first_infinite

    @atomic_game_operation
    def use_item(self, user_id: str, item_id: int, quantity: int = 1) -> Dict[str, Any]:
        """
        使用一个或多个道具，并将效果处理委托给 EffectManager。
        """
        if quantity <= 0:
            return {"success": False, "message": "数量必须大于0"}

        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        item_inventory = self.inventory_repo.get_user_item_inventory(user_id)
        available_quantity = item_inventory.get(item_id, 0)
        if available_quantity < quantity:
            return {"success": False, "message": f"你只有 {available_quantity} 个该道具，数量不足"}

        item_template = self.item_template_repo.get_item_by_id(item_id)
        if not item_template:
            return {"success": False, "message": "道具信息不存在"}

        if not getattr(item_template, "is_consumable", False):
            return {"success": False, "message": f"【{item_template.name}】无法直接使用。"}

        effect_type = item_template.effect_type
        if effect_type:
            handler = self.effect_manager.get_effect(effect_type)
            if handler is None:
                return {"success": False, "message": f"找不到 {effect_type} 效果的处理器，请检查配置。"}
            try:
                payload = json.loads(item_template.effect_payload or "{}")
            except (ValueError, TypeError):
                return {"success": False, "message": "道具效果配置格式无效"}
            if not isinstance(payload, dict):
                return {"success": False, "message": "道具效果必须是 JSON 对象"}
            result = handler.apply(user, item_template, payload, quantity=quantity)
            if not result.get("success"):
                return {"success": False, "message": f"❌ 使用道具失败：{result.get('message', '')}"}
        else:
            result = {"success": True}

        consumed = result.get("quantity_used", quantity)
        self.inventory_repo.decrease_item_quantity(user_id, item_id, consumed)
        outcome = result.get("message", "")
        result["message"] = f"成功使用了 {consumed} 个【{item_template.name}】！{outcome}"
        return result

    @atomic_game_operation
    def open_all_money_bags(self, user_id: str) -> Dict[str, Any]:
        """Open every valid money-bag stack and report the combined proceeds."""
        if not self.user_repo.check_exists(user_id):
            return {"success": False, "message": "用户不存在"}
        inventory = self.inventory_repo.get_user_item_inventory(user_id)
        total_gained = opened_bags = 0
        details = []
        failed = []
        for template in self.item_template_repo.get_all_items():
            quantity = inventory.get(template.item_id, 0)
            if not quantity or template.effect_type != "ADD_COINS" or not template.is_consumable:
                continue
            result = self.use_item(user_id, template.item_id, quantity)
            if not result["success"]:
                failed.append(template.name)
                continue
            coins = result["coins_gained"]
            opened_bags += quantity
            total_gained += coins
            details.append(f"  {template.name} ×{quantity} → {coins} 金币")

        message = "🎒 您当前没有可开启的钱袋"
        if details:
            message = f"🎒 成功开启了 {opened_bags} 个钱袋，共获得 {total_gained} 金币！\n" + "\n".join(details)
        if failed:
            notice = "以下钱袋的效果配置无效，已保留：" + "、".join(failed)
            message = f"{message}\n{notice}" if details else notice
        return {
            "success": bool(details) or not failed,
            "message": message,
            "total_gained": total_gained,
            "opened_bags": opened_bags,
        }

    @atomic_game_operation
    def sell_item(self, user_id: str, item_id: int, quantity: int = 1) -> Dict[str, Any]:
        """出售指定数量的道具，按照模板 cost 的一半计价（至少 1）。"""
        if quantity <= 0:
            return {"success": False, "message": "数量必须大于0"}

        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        inv = self.inventory_repo.get_user_item_inventory(user_id)
        owned_qty = inv.get(item_id, 0)
        if owned_qty <= 0:
            return {"success": False, "message": "❌ 你没有这个道具"}
        if quantity > owned_qty:
            return {"success": False, "message": f"❌ 数量不足，当前仅有 {owned_qty} 个"}

        tpl = self.item_template_repo.get_item_by_id(item_id)
        if not tpl:
            return {"success": False, "message": "道具信息不存在"}

        # 定价：模板 cost 的 50%，至少 1
        single_price = max(1, int((tpl.cost or 0) * 0.5))
        total = single_price * quantity

        # 扣减库存，增加金币
        self.inventory_repo.decrease_item_quantity(user_id, item_id, quantity)
        user.coins += total
        self.user_repo.update(user)

        return {
            "success": True,
            "message": f"💰 成功卖出【{tpl.name}】x{quantity}，获得 {total} 金币",
            "gained": total,
            "remaining": owned_qty - quantity
        }

    @atomic_game_operation
    def lock_rod(self, user_id: str, rod_instance_id: int) -> Dict[str, Any]:
        """
        锁定指定的鱼竿，防止被当作精炼材料、卖出、上架
        注意：锁定的鱼竿仍可作为主装备进行精炼，精炼失败时仍会被碎掉
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 验证鱼竿是否属于该用户
        user_rods = self.inventory_repo.get_user_rod_instances(user_id)
        rod_to_lock = next((r for r in user_rods if r.rod_instance_id == rod_instance_id), None)
        
        if not rod_to_lock:
            return {"success": False, "message": "鱼竿不存在或不属于您"}

        if rod_to_lock.is_locked:
            return {"success": False, "message": "该鱼竿已经锁定"}

        # 锁定鱼竿
        rod_to_lock.is_locked = True
        self.inventory_repo.update_rod_instance(rod_to_lock)

        # 获取鱼竿模板信息用于显示
        rod_template = self.item_template_repo.get_rod_by_id(rod_to_lock.rod_id)
        rod_name = rod_template.name if rod_template else f"鱼竿#{rod_instance_id}"

        return {
            "success": True,
            "message": f"🔒 成功锁定【{rod_name}】，该鱼竿现在受到保护"
        }

    @atomic_game_operation
    def unlock_rod(self, user_id: str, rod_instance_id: int) -> Dict[str, Any]:
        """
        解锁指定的鱼竿
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 验证鱼竿是否属于该用户
        user_rods = self.inventory_repo.get_user_rod_instances(user_id)
        rod_to_unlock = next((r for r in user_rods if r.rod_instance_id == rod_instance_id), None)
        
        if not rod_to_unlock:
            return {"success": False, "message": "鱼竿不存在或不属于您"}

        if not rod_to_unlock.is_locked:
            return {"success": False, "message": "该鱼竿未锁定"}

        # 解锁鱼竿
        rod_to_unlock.is_locked = False
        self.inventory_repo.update_rod_instance(rod_to_unlock)

        # 获取鱼竿模板信息用于显示
        rod_template = self.item_template_repo.get_rod_by_id(rod_to_unlock.rod_id)
        rod_name = rod_template.name if rod_template else f"鱼竿#{rod_instance_id}"

        return {
            "success": True,
            "message": f"🔓 成功解锁【{rod_name}】，该鱼竿现在可以正常操作"
        }

    @atomic_game_operation
    def lock_accessory(self, user_id: str, accessory_instance_id: int) -> Dict[str, Any]:
        """
        锁定指定的饰品，防止被当作精炼材料、卖出、上架
        注意：锁定的饰品仍可作为主装备进行精炼，精炼失败时仍会被碎掉
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 验证饰品是否属于该用户
        user_accessories = self.inventory_repo.get_user_accessory_instances(user_id)
        accessory_to_lock = next((a for a in user_accessories if a.accessory_instance_id == accessory_instance_id), None)
        
        if not accessory_to_lock:
            return {"success": False, "message": "饰品不存在或不属于您"}

        if accessory_to_lock.is_locked:
            return {"success": False, "message": "该饰品已经锁定"}

        # 锁定饰品
        accessory_to_lock.is_locked = True
        self.inventory_repo.update_accessory_instance(accessory_to_lock)

        # 获取饰品模板信息用于显示
        accessory_template = self.item_template_repo.get_accessory_by_id(accessory_to_lock.accessory_id)
        accessory_name = accessory_template.name if accessory_template else f"饰品#{accessory_instance_id}"

        return {
            "success": True,
            "message": f"🔒 成功锁定【{accessory_name}】，该饰品现在受到保护"
        }

    @atomic_game_operation
    def unlock_accessory(self, user_id: str, accessory_instance_id: int) -> Dict[str, Any]:
        """
        解锁指定的饰品
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 验证饰品是否属于该用户
        user_accessories = self.inventory_repo.get_user_accessory_instances(user_id)
        accessory_to_unlock = next((a for a in user_accessories if a.accessory_instance_id == accessory_instance_id), None)
        
        if not accessory_to_unlock:
            return {"success": False, "message": "饰品不存在或不属于您"}

        if not accessory_to_unlock.is_locked:
            return {"success": False, "message": "该饰品未锁定"}

        # 解锁饰品
        accessory_to_unlock.is_locked = False
        self.inventory_repo.update_accessory_instance(accessory_to_unlock)

        # 获取饰品模板信息用于显示
        accessory_template = self.item_template_repo.get_accessory_by_id(accessory_to_unlock.accessory_id)
        accessory_name = accessory_template.name if accessory_template else f"饰品#{accessory_instance_id}"

        return {
            "success": True,
            "message": f"🔓 成功解锁【{accessory_name}】，该饰品现在可以正常操作"
        }
