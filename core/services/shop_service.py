from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta, timezone
import copy
import math
import random

# 导入仓储接口
from ..database.connection_manager import atomic_game_operation
from ..repositories.abstract_repository import (
    AbstractItemTemplateRepository,
    AbstractInventoryRepository,
    AbstractUserRepository,
    AbstractShopRepository,
)
from ..utils import UTC8, get_now


# 一次购买最多生成的鱼竿和饰品数量
MAX_EQUIPMENT_PER_PURCHASE = 100


class ShopService:
    """封装与系统商店相关的业务逻辑（新设计：shops + shop_items）"""
    

    def __init__(
        self,
        item_template_repo: AbstractItemTemplateRepository,
        inventory_repo: AbstractInventoryRepository,
        user_repo: AbstractUserRepository,
        shop_repo: Optional[AbstractShopRepository] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.item_template_repo = item_template_repo
        self.inventory_repo = inventory_repo
        self.user_repo = user_repo
        self.shop_repo = shop_repo
        self.config = config or {}

    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """解析时间字符串为 datetime 对象"""
        if not dt_str or not isinstance(dt_str, str):
            return None
        try:
            parsed = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return parsed.astimezone(UTC8) if parsed.tzinfo else parsed.replace(tzinfo=UTC8)
        except Exception:
            return None

    def _check_shop_availability(self, shop: Dict[str, Any]) -> Optional[str]:
        """检查商店是否可用，返回错误消息或None"""
        if not shop.get("is_active", True):
            return "商店未启用"
        
        now = get_now()
        
        # 检查日期范围
        start_time = self._parse_datetime(shop.get("start_time"))
        end_time = self._parse_datetime(shop.get("end_time"))
        if start_time and now < start_time:
            return "商店尚未开放"
        if end_time and now > end_time:
            return "商店已关闭"
        
        # 检查每日时段
        daily_start = shop.get("daily_start_time")
        daily_end = shop.get("daily_end_time")
        if daily_start and daily_end:
            current_time = now.strftime("%H:%M")
            if daily_start <= daily_end:
                open_now = daily_start <= current_time <= daily_end
            else:
                open_now = current_time >= daily_start or current_time <= daily_end
            if not open_now:
                return f"商店营业时间：{daily_start}-{daily_end}"

        return None

    def _check_item_availability(self, item: Dict[str, Any]) -> Optional[str]:
        """检查商品是否可用，返回错误消息或None"""
        if not item.get("is_active", True):
            return "商品未启用"
        
        now = get_now()
        
        # 检查时间范围
        start_time = self._parse_datetime(item.get("start_time"))
        end_time = self._parse_datetime(item.get("end_time"))
        if start_time and now < start_time:
            return "商品尚未开售"
        if end_time and now > end_time:
            return "商品已过期"
        
        return None

    # ---- 商店管理 ----
    def get_shops(self) -> Dict[str, Any]:
        """获取所有活跃商店"""
        if not self.shop_repo:
            return {"success": True, "shops": []}
        
        shops = [shop for shop in self.shop_repo.get_all_shops() if not self._check_shop_availability(shop)]
        return {"success": True, "shops": shops}

    def get_shop_details(self, shop_id: int) -> Dict[str, Any]:
        """获取商店详情和商品列表"""
        if not self.shop_repo:
            return {"success": False, "message": "商店系统未初始化"}
        
        shop = self.shop_repo.get_shop_by_id(shop_id)
        if not shop:
            return {"success": False, "message": "商店不存在"}
        
        # 检查商店可用性
        availability_error = self._check_shop_availability(shop)
        if availability_error:
            return {"success": False, "message": availability_error}
        
        # 获取商店商品
        items = self.shop_repo.get_shop_items(shop_id)
        items_with_details = []
        
        for item in items:
            # 检查商品可用性
            item_error = self._check_item_availability(item)
            if item_error:
                continue  # 跳过不可用的商品
            
            # 获取成本和奖励
            costs = self.shop_repo.get_item_costs(item["item_id"])
            rewards = self.shop_repo.get_item_rewards(item["item_id"])
            
            items_with_details.append({
                "item": item,
                "costs": costs,
                "rewards": rewards,
            })
        
        return {
            "success": True,
            "shop": shop,
            "items": items_with_details
        }

    # ---- 商品购买 ----
    @atomic_game_operation
    def purchase_item(self, user_id: str, item_id: int, quantity: int = 1) -> Dict[str, Any]:
        """购买商店商品（已使用递归回溯算法优化OR逻辑）"""
        if not self.shop_repo:
            return {"success": False, "message": "商店系统未初始化"}
        
        if quantity <= 0:
            return {"success": False, "message": "数量必须大于0"}
        
        # 获取商品信息
        item = self.shop_repo.get_shop_item_by_id(item_id)
        if not item:
            return {"success": False, "message": "商品不存在"}
        
        # 检查商品可用性
        item_error = self._check_item_availability(item)
        if item_error:
            return {"success": False, "message": item_error}
        
        # 获取商店信息并检查可用性
        shop = self.shop_repo.get_shop_by_id(item["shop_id"])
        if not shop:
            return {"success": False, "message": "商店不存在"}
        
        shop_error = self._check_shop_availability(shop)
        if shop_error:
            return {"success": False, "message": shop_error}
        
        # 获取用户信息
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}
        
        # 一次购买生成的鱼竿、饰品数量有上限：每件都是单独的实例，太多会长时间占住数据库
        rewards = self.shop_repo.get_item_rewards(item_id)
        if not rewards:
            return {"success": False, "message": "商品未配置奖励"}
        equipment_per_item = sum(
            int(r.get("reward_quantity") or 1)
            for r in rewards
            if r.get("reward_type") in ("rod", "accessory")
        )
        if equipment_per_item and equipment_per_item * quantity > MAX_EQUIPMENT_PER_PURCHASE:
            most = max(1, MAX_EQUIPMENT_PER_PURCHASE // equipment_per_item)
            return {"success": False, "message": f"装备类商品一次最多购买 {most} 个，请分次购买"}

        # 库存检查
        if item.get("stock_total") is not None:
            available_stock = item["stock_total"] - item.get("stock_sold", 0)
            if available_stock < quantity:
                return {"success": False, "message": f"库存不足，剩余 {available_stock} 个"}
        
        # 限购检查
        if item.get("per_user_limit") is not None:
            purchased_total = self.shop_repo.get_user_purchased_count(user_id, item_id)
            if purchased_total + quantity > item["per_user_limit"]:
                remaining = item["per_user_limit"] - purchased_total
                if remaining <= 0:
                    return {"success": False, "message": f"该商品限购 {item['per_user_limit']} 个，您已购买完毕"}
                else:
                    return {"success": False, "message": f"超过个人限购，还可购买 {remaining} 个"}
        
        if item.get("per_user_daily_limit") is not None and item["per_user_daily_limit"] > 0:
            # 处理每日限购：数据库记录时间为UTC（SQLite CURRENT_TIMESTAMP），需将本地零点换算为UTC
            now_utc = datetime.now(timezone.utc)
            now_local = now_utc.astimezone(timezone(timedelta(hours=8)))
            local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            start_of_day_utc = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
            purchased_today = self.shop_repo.get_user_purchased_count(user_id, item_id, since=start_of_day_utc)
            if purchased_today + quantity > item["per_user_daily_limit"]:
                remaining = item["per_user_daily_limit"] - purchased_today
                if remaining <= 0:
                    return {"success": False, "message": f"该商品每日限购 {item['per_user_daily_limit']} 个，您今日已购买完毕"}
                else:
                    return {"success": False, "message": f"超过今日限购，今日还可购买 {remaining} 个"}
        
        # --- 核心购买逻辑重构 ---
        
        # 1. 解析成本结构
        costs_db = self.shop_repo.get_item_costs(item_id)
        cost_structure = self._get_cost_structure(costs_db, quantity)
        and_costs = cost_structure["and_costs"]
        or_choices = cost_structure["or_choices"]

        user_resources_copy = self._get_user_resources_copy(user)
        
        # 3. 检查并从快照中扣除必须的 AND 成本
        can_pay_and, resources_after_and = self._check_and_get_remaining_resources(user_resources_copy, and_costs)
        if not can_pay_and:
            return {"success": False, "message": self._insufficient_cost(user_resources_copy, and_costs)}

        fish_reward_count = sum(r["reward_quantity"] for r in rewards if r["reward_type"] == "fish") * quantity
        capacity_check = None
        if fish_reward_count:
            aquarium_count = self.inventory_repo.get_aquarium_total_count(user_id)
            slots_needed = aquarium_count + fish_reward_count - user.aquarium_capacity
            if slots_needed > 0:
                pond = {(f.fish_id, f.quality_level): f.quantity for f in self.inventory_repo.get_fish_inventory(user_id)}

                def capacity_check(remaining):
                    freed = sum(
                        max(0, held - remaining["fish"][key] - pond.get(key, 0))
                        for key, held in user_resources_copy["fish"].items()
                    )
                    return freed >= slots_needed

        or_solution = self._find_payable_combination(or_choices, resources_after_and, capacity_check)

        if or_solution is None:
            if capacity_check and self._find_payable_combination(or_choices, resources_after_and) is not None:
                return {"success": False, "message": "水族箱空间不足，无法接收这些鱼"}
            return {"success": False, "message": "支付条件不足，无法找到满足所有选项的物品组合"}

        # 5. 合并最终成本
        final_total_costs = and_costs
        for cost_part in or_solution:
            self._merge_costs(final_total_costs, cost_part)
        
        self._deduct_costs(user, final_total_costs)
        obtained_items = self._give_rewards(user_id, rewards, quantity)
        
        self.shop_repo.increase_item_sold(item_id, quantity)
        self.shop_repo.add_purchase_record(user_id, item_id, quantity)
        
        success_message = f"✅ 购买成功：{item['name']} x{quantity}"
        if obtained_items:
            unique_items = list(dict.fromkeys(obtained_items))
            success_message += f"\n📦 获得物品：\n" + "\n".join([f"  • {item}" for item in unique_items])
        
        return {"success": True, "message": success_message}

    def _merge_costs(self, base_costs: dict, extra_costs: dict) -> None:
        base_costs["coins"] = base_costs.get("coins", 0) + extra_costs.get("coins", 0)
        for category in ("items", "fish", "rods", "accessories"):
            for key, amount in extra_costs.get(category, {}).items():
                entries = base_costs.setdefault(category, {})
                entries[key] = entries.get(key, 0) + amount

    def _get_cost_structure(self, costs: List[Dict[str, Any]], quantity: int) -> Dict[str, Any]:
        and_costs = {}
        or_groups = {}
        cost_categories = {"fish": "fish", "item": "items", "rod": "rods", "accessory": "accessories"}
        for row in costs:
            cost_type = row["cost_type"]
            amount = row["cost_amount"] * quantity
            if cost_type == "coins":
                cost = {"coins": amount}
            else:
                key = row["cost_item_id"]
                if cost_type == "fish":
                    key = (key, row.get("quality_level") or 0)
                cost = {cost_categories[cost_type]: {key: amount}}

            group_id = row.get("group_id")
            if group_id is not None and row.get("cost_relation") == "or":
                or_groups.setdefault(group_id, []).append(cost)
            else:
                self._merge_costs(and_costs, cost)
        return {"and_costs": and_costs, "or_choices": [or_groups[key] for key in sorted(or_groups)]}

    def _get_user_resources_copy(self, user: Any) -> Dict[str, Any]:
        """获取用户当前可用资源的快照字典，支持鱼类品质"""
        resources = {
            "coins": user.coins,
            "items": self.inventory_repo.get_user_item_inventory(user.user_id),
            "fish": {}, # 结构: {fish_id: {quality_level: count}}
            "rods": {},
            "accessories": {}
        }
        
        # 合并鱼塘和水族箱的鱼，并按品质区分
        fish_inventory = self.inventory_repo.get_fish_inventory(user.user_id)
        aquarium_inventory = self.inventory_repo.get_aquarium_inventory(user.user_id)
        
        for fish_item in fish_inventory + aquarium_inventory:
            key = (fish_item.fish_id, fish_item.quality_level)
            resources["fish"][key] = resources["fish"].get(key, 0) + fish_item.quantity

        # 鱼竿和饰品只计入未锁定且未装备的
        for rod in self.inventory_repo.get_user_rod_instances(user.user_id):
            if not rod.is_locked and not rod.is_equipped:
                resources["rods"][rod.rod_id] = resources["rods"].get(rod.rod_id, 0) + 1
        for acc in self.inventory_repo.get_user_accessory_instances(user.user_id):
            if not acc.is_locked and not acc.is_equipped:
                resources["accessories"][acc.accessory_id] = resources["accessories"].get(acc.accessory_id, 0) + 1
        
        return resources

    def _check_and_get_remaining_resources(self, resources: Dict, cost: Dict) -> Tuple[bool, Optional[Dict]]:
        """在资源副本上检查并模拟扣除，返回是否成功和扣除后的新副本（支持鱼类品质）"""
        res_copy = copy.deepcopy(resources)
        
        if res_copy.get("coins", 0) < cost.get("coins", 0): return (False, None)
        res_copy["coins"] -= cost.get("coins", 0)

        for category in ("items", "fish", "rods", "accessories"):
            for key, needed in cost.get(category, {}).items():
                if res_copy[category].get(key, 0) < needed:
                    return (False, None)
                res_copy[category][key] -= needed

        return (True, res_copy)

    def _find_payable_combination(
        self, or_choices: List[List[Dict]], resources: Dict, accepts=None,
    ) -> Optional[List[Dict]]:
        """使用递归回溯寻找一个可行的支付组合"""
        if not or_choices:
            return [] if accepts is None or accepts(resources) else None

        first_group = or_choices[0]
        remaining_groups = or_choices[1:]

        for option_cost in first_group:
            can_pay, resources_after_pay = self._check_and_get_remaining_resources(resources, option_cost)
            if can_pay:
                result = self._find_payable_combination(remaining_groups, resources_after_pay, accepts)
                if result is not None:
                    return [option_cost] + result
        
        return None

    def _insufficient_cost(self, resources: dict, costs: dict) -> str:
        if resources["coins"] < costs.get("coins", 0):
            return f"金币不足，需要 {costs['coins']} 金币"

        for category, label, lookup in (
            ("items", "道具", self.item_template_repo.get_item_by_id),
            ("fish", "鱼类", self.item_template_repo.get_fish_by_id),
            ("rods", "可用鱼竿", self.item_template_repo.get_rod_by_id),
            ("accessories", "可用饰品", self.item_template_repo.get_accessory_by_id),
        ):
            for key, amount in costs.get(category, {}).items():
                available = resources[category].get(key, 0)
                if available >= amount:
                    continue
                template_id, quality = key if category == "fish" else (key, 0)
                template = lookup(template_id)
                name = template.name if template else f"#{template_id}"
                quality_label = "高品质" if quality else ""
                return f"{quality_label}{label}不足：{name} ×{amount}（现有 {available}）"
        return "资源不足"

    def _deduct_costs(self, user: Any, costs: Dict[str, Any]) -> None:
        """扣除用户资源"""
        # 扣除金币
        if costs.get("coins", 0) > 0:
            user.coins -= costs["coins"]
        
        # 更新用户
        self.user_repo.update(user)
        
        # 扣除道具
        if costs.get("items"):
            for item_id, need_qty in costs["items"].items():
                self.inventory_repo.decrease_item_quantity(user.user_id, item_id, need_qty)
        
        for (fish_id, quality), amount in costs.get("fish", {}).items():
            self.inventory_repo.deduct_fish_smart(user.user_id, fish_id, amount, quality)

        # 扣除鱼竿（排除上锁和装备中的）
        if costs.get("rods"):
            user_rods = self.inventory_repo.get_user_rod_instances(user.user_id)
            for rod_id_str, need_qty in costs["rods"].items():
                rod_id = int(rod_id_str) # 确保 rod_id 是整数
                remaining_qty = need_qty
                for rod in user_rods:
                    if remaining_qty <= 0:
                        break
                    if (rod.rod_id == rod_id and 
                        not rod.is_locked and 
                        not rod.is_equipped):
                        # 删除这个鱼竿实例
                        self.inventory_repo.delete_rod_instance(rod.rod_instance_id)
                        remaining_qty -= 1
        
        # 扣除饰品（排除上锁和装备中的）
        if costs.get("accessories"):
            user_accessories = self.inventory_repo.get_user_accessory_instances(user.user_id)
            for accessory_id_str, need_qty in costs["accessories"].items():
                accessory_id = int(accessory_id_str) # 确保 accessory_id 是整数
                remaining_qty = need_qty
                for accessory in user_accessories:
                    if remaining_qty <= 0:
                        break
                    if (accessory.accessory_id == accessory_id and 
                        not accessory.is_locked and 
                        not accessory.is_equipped):
                        # 删除这个饰品实例
                        self.inventory_repo.delete_accessory_instance(accessory.accessory_instance_id)
                        remaining_qty -= 1

    def _give_rewards(self, user_id: str, rewards: List[Dict[str, Any]], quantity: int) -> List[str]:
        obtained_items = []
        lookups = {
            "rod": self.item_template_repo.get_rod_by_id,
            "accessory": self.item_template_repo.get_accessory_by_id,
            "bait": self.item_template_repo.get_bait_by_id,
            "item": self.item_template_repo.get_item_by_id,
            "fish": self.item_template_repo.get_fish_by_id,
        }
        for reward in rewards:
            kind = reward["reward_type"]
            template_id = reward.get("reward_item_id")
            amount = reward["reward_quantity"] * quantity
            if amount <= 0:
                raise ValueError("奖励数量无效")
            if kind == "coins":
                user = self.user_repo.get_by_id(user_id)
                user.coins += amount
                self.user_repo.update(user)
                obtained_items.append(f"金币 ×{amount}")
                continue

            template = lookups[kind](template_id)
            if template is None:
                raise ValueError(f"商品引用的奖励已不存在：{kind} #{template_id}")

            refine_level = reward.get("reward_refine_level") or 1
            if kind == "rod":
                for _ in range(amount):
                    self.inventory_repo.add_rod_instance(user_id, template_id, template.durability, refine_level)
            elif kind == "accessory":
                for _ in range(amount):
                    self.inventory_repo.add_accessory_instance(user_id, template_id, refine_level)
            elif kind == "bait":
                self.inventory_repo.update_bait_quantity(user_id, template_id, amount)
            elif kind == "item":
                self.inventory_repo.update_item_quantity(user_id, template_id, amount)
            elif kind == "fish":
                quality = reward.get("quality_level", 0)
                self.inventory_repo.add_fish_to_aquarium(user_id, template_id, amount, quality)
            quality_text = "（高品质）" if kind == "fish" and reward.get("quality_level") else ""
            obtained_items.append(f"{template.name}{quality_text} ×{amount}")

        return obtained_items

    # ---- 兼容性方法（向后兼容旧系统） ----
    def get_shop_listings(self) -> Dict[str, Any]:
        """获取商店商品列表（兼容旧接口）"""
        result: Dict[str, Any] = {"success": True}
        if not self.shop_repo:
            result["offers"] = []
            return result
        
        offers = self.shop_repo.get_active_offers()
        offers_view: List[Dict[str, Any]] = []
        
        for offer in offers:
            costs = self.shop_repo.get_item_costs(offer["item_id"])
            rewards = self.shop_repo.get_item_rewards(offer["item_id"])
            offers_view.append({
                "offer": offer,
                "costs": costs,
                "rewards": rewards,
            })
        
        result["offers"] = offers_view
        return result

    def buy_item(self, user_id: str, item_type: str, item_template_id: int, quantity: int = 1) -> Dict[str, Any]:
        """旧商店购买接口（已废弃）"""
        return {"success": False, "message": "旧商店购买已废弃，请使用新的商店系统"}

    def purchase_offer(self, user_id: str, offer_id: int, quantity: int = 1) -> Dict[str, Any]:
        """购买商品（兼容旧接口）"""
        return self.purchase_item(user_id, offer_id, quantity)

    def purchase_in_shop(self, user_id: str, shop_id: int, offer_id: int, quantity: int = 1) -> Dict[str, Any]:
        """在指定商店购买商品（兼容旧接口）"""
        offer = self.shop_repo.get_shop_item_by_id(offer_id) if self.shop_repo else None
        if not offer or offer["shop_id"] != shop_id:
            return {"success": False, "message": "该商店没有此商品"}
        return self.purchase_item(user_id, offer_id, quantity)
