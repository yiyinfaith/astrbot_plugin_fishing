from typing import Dict, Any
import random

from .abstract_effect import AbstractItemEffect
from ...domain.models import User, Item


class AddCoinsEffect(AbstractItemEffect):
    effect_type = "ADD_COINS"

    def apply(
        self, user: User, item_template: Item, payload: Dict[str, Any], quantity: int = 1
    ) -> Dict[str, Any]:
        min_amount = payload.get("min_amount")
        max_amount = payload.get("max_amount")

        total_amount = 0
        if min_amount is not None and max_amount is not None:
            # 随机金额
            if (
                type(min_amount) is not int or type(max_amount) is not int
                or not 0 < min_amount <= max_amount
            ):
                return {"success": False, "message": "无效的随机金额范围"}
            if min_amount == max_amount:
                total_amount = min_amount * quantity
            else:
                total_amount = sum(random.randint(min_amount, max_amount) for _ in range(quantity))
        else:
            # 固定金额
            amount = payload.get("amount", 0)
            if type(amount) is not int or amount <= 0:
                return {"success": False, "message": "无效的金币道具"}
            total_amount = amount * quantity

        if total_amount <= 0:
            return {"success": False, "message": "无效的金币道具"}
            
        user.coins += total_amount
        self.user_repo.update(user)

        return {
            "success": True,
            "message": f"💰 打开 {item_template.name} x{quantity}，获得了 {total_amount} 金币！",
            "coins_gained": total_amount,
        }
