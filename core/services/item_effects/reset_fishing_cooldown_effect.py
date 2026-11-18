from typing import Dict, Any, Optional
from collections import defaultdict

from .abstract_effect import AbstractItemEffect
from ...domain.models import User, Item


class ResetFishingCooldownEffect(AbstractItemEffect):
    effect_type = "RESET_FISHING_COOLDOWN"

    def __init__(
        self,
        user_repo: Optional[Any] = None,
        buff_repo: Optional[Any] = None,
        fishing_service=None,
        **kwargs,
    ):
        """
        构造函数，用于依赖注入。
        """
        super().__init__(user_repo, buff_repo, **kwargs)
        self.fishing_service = fishing_service
        if not self.fishing_service:
            raise ValueError("ResetFishingCooldownEffect requires fishing_service dependency")

    def apply(
        self, user: User, item_template: Item, payload: Dict[str, Any], quantity: int = 1
    ) -> Dict[str, Any]:
        # 检查最大使用量限制
        if quantity > 99:
            return {
                "success": False,
                "message": f"【{item_template.name}】一次最多只能使用 99 个。"
            }
        
        results = []
        stop_reason = ""
        for _ in range(quantity):
            result = self.fishing_service.go_fish(user.user_id)
            if "fishing_cost" not in result:
                stop_reason = result["message"]
                break
            results.append(result)

        if not results:
            return {"success": False, "message": stop_reason}

        fish_stats = defaultdict(int)
        notices = []
        for result in results:
            if result["success"]:
                fish = result["fish"]
                fish_stats[(fish["name"], fish["quality_level"])] += fish["quantity"]
            notices.extend(result.get("notices", ()))
            notices.extend(result.get("equipment_broken_messages", ()))

        caught = sum(fish_stats.values())
        coins = sum(result["fishing_cost"] for result in results)
        lines = [f"抛竿 {len(results)} 次，钓到 {caught} 条鱼，花费 {coins} 金币。"]
        for (fish_name, quality), count in sorted(fish_stats.items()):
            quality_text = "（高品质）" if quality else ""
            lines.append(f"{fish_name}{quality_text} ×{count}")
        lines.extend(dict.fromkeys(notices))
        if stop_reason:
            lines.append(stop_reason)
        return {"success": True, "message": "\n".join(lines), "quantity_used": len(results)}
