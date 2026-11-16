"""把插件配置里的数值规则整理成服务使用的格式。

列表类配置在配置页里写成逗号分隔的数字。写错时记一条警告并使用默认值，插件照常启动。
"""

from typing import Any, Dict, List, Optional

from astrbot.api import logger

DEFAULT_BASE_SUCCESS_RATE = 0.7
DEFAULT_MYTHIC_WEIGHTS = "15,4,1"
DEFAULT_ELECTRIC_MAX_CATCH = 50
DEFAULT_SIGNIN_MIN, DEFAULT_SIGNIN_MAX = 100, 300
DEFAULT_POND_CAPACITIES = "480,1000,2000,5000,10000"
DEFAULT_POND_COSTS = "20000,100000,500000,2000000"
# 从 1 级精炼到 2 级、2 级到 3 级……9 级到 10 级的基础费用（共 9 个值）
DEFAULT_REFINE_BASE_COSTS = "10000,30000,50000,100000,200000,500000,1000000,2000000,5000000"
# 1 星、2 星、3 星、4 星、5 星、6 星、7 星及以上
DEFAULT_REFINE_COST_MULTIPLIERS = "0.1,0.15,0.2,0.25,0.5,0.7,1.0"
# 精炼到 2 级、3 级……10 级的成功率（共 9 个值）
DEFAULT_REFINE_SUCCESS_RATES = {
    "low": "0.95,0.90,0.90,0.85,0.80,0.75,0.70,0.60,0.50",   # 1-2 星
    "r3": "0.90,0.85,0.85,0.80,0.75,0.65,0.55,0.45,0.35",
    "r4": "0.85,0.80,0.80,0.75,0.70,0.60,0.50,0.40,0.30",
    "r5": "0.85,0.80,0.75,0.65,0.50,0.40,0.35,0.30,0.25",
    "r6": "0.80,0.75,0.70,0.60,0.45,0.35,0.30,0.25,0.20",
    "high": "0.8,0.8,0.8,0.7,0.6,0.5,0.4,0.3,0.2",          # 7 星及以上
}
REFINE_RATE_KEYS = {
    "low": "success_rates_1_2", "r3": "success_rates_3", "r4": "success_rates_4",
    "r5": "success_rates_5", "r6": "success_rates_6", "high": "success_rates_7_plus",
}


def parse_numbers(value: Any, default: str, label: str, *, count: Optional[int] = None,
                  minimum: Optional[float] = None, maximum: Optional[float] = None,
                  integer: bool = False) -> List[float]:
    """解析逗号分隔的数字列表，格式不对时返回默认值。"""
    fallback = [int(x) if integer else float(x) for x in default.split(",")]
    if value is None or value == "":
        return fallback
    try:
        text = str(value).replace("，", ",")
        items = [x.strip() for x in text.split(",") if x.strip()]
        numbers = [int(float(x)) if integer else float(x) for x in items]
        if count is not None and len(numbers) != count:
            raise ValueError(f"需要 {count} 个数，实际 {len(numbers)} 个")
        if minimum is not None and any(n < minimum for n in numbers):
            raise ValueError(f"不能小于 {minimum}")
        if maximum is not None and any(n > maximum for n in numbers):
            raise ValueError(f"不能大于 {maximum}")
        return numbers
    except (TypeError, ValueError) as e:
        logger.warning(f"[钓鱼] 配置「{label}」格式不对（{e}），已使用默认值 {default}")
        return fallback


def _number(value: Any, default: float, label: str, minimum: float, maximum: Optional[float] = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < minimum or (maximum is not None and number > maximum):
        logger.warning(f"[钓鱼] 配置「{label}」超出范围，已使用默认值 {default}")
        return default
    return number


def build_fishing_rules(fishing_config: Dict[str, Any]) -> Dict[str, Any]:
    weights = parse_numbers(fishing_config.get("mythic_weights"), DEFAULT_MYTHIC_WEIGHTS,
                            "6/7/8 星神话鱼比例", count=3, minimum=0)
    if sum(weights) <= 0:
        weights = parse_numbers(None, DEFAULT_MYTHIC_WEIGHTS, "")
    return {
        "base_success_rate": _number(fishing_config.get("base_success_rate", DEFAULT_BASE_SUCCESS_RATE),
                                     DEFAULT_BASE_SUCCESS_RATE, "基础钓鱼成功率", 0.05, 1.0),
        "mythic_weights": {6: weights[0], 7: weights[1], 8: weights[2]},
    }


def build_signin(signin_config: Dict[str, Any]) -> Dict[str, int]:
    low = int(_number(signin_config.get("min_reward", DEFAULT_SIGNIN_MIN), DEFAULT_SIGNIN_MIN, "签到最少金币", 0))
    high = int(_number(signin_config.get("max_reward", DEFAULT_SIGNIN_MAX), DEFAULT_SIGNIN_MAX, "签到最多金币", 0))
    if high < low:
        logger.warning("[钓鱼] 签到最多金币小于最少金币，已互换")
        low, high = high, low
    return {"min_reward": low, "max_reward": high}


def build_pond_upgrades(pond_config: Dict[str, Any]) -> List[Dict[str, int]]:
    capacities = parse_numbers(pond_config.get("capacities"), DEFAULT_POND_CAPACITIES, "鱼塘容量档位",
                               minimum=1, integer=True)
    costs = parse_numbers(pond_config.get("upgrade_costs"), DEFAULT_POND_COSTS, "鱼塘升级价格",
                          minimum=0, integer=True)
    if len(costs) != len(capacities) - 1 or any(b <= a for a, b in zip(capacities, capacities[1:])):
        logger.warning("[钓鱼] 鱼塘容量档位需要从小到大，且升级价格比档位少 1 个，已使用默认值")
        capacities = parse_numbers(None, DEFAULT_POND_CAPACITIES, "", integer=True)
        costs = parse_numbers(None, DEFAULT_POND_COSTS, "", integer=True)
    return [{"from": a, "to": b, "cost": c} for a, b, c in zip(capacities, capacities[1:], costs)]


def build_refine(refine_config: Dict[str, Any]) -> Dict[str, Any]:
    base = parse_numbers(refine_config.get("base_costs"), DEFAULT_REFINE_BASE_COSTS, "精炼基础费用",
                         count=9, minimum=0, integer=True)
    multipliers = parse_numbers(refine_config.get("cost_multipliers"), DEFAULT_REFINE_COST_MULTIPLIERS,
                                "精炼费用倍率", count=7, minimum=0)
    rates = {}
    for group, key in REFINE_RATE_KEYS.items():
        values = parse_numbers(refine_config.get(key), DEFAULT_REFINE_SUCCESS_RATES[group],
                               f"精炼成功率 {key}", count=9, minimum=0, maximum=1)
        rates[group] = {level + 2: v for level, v in enumerate(values)}
    return {
        "base_costs": {level + 1: c for level, c in enumerate(base)},
        "cost_multipliers": multipliers,
        "success_rates": rates,
    }


def refine_tables_for_rarity(refine: Dict[str, Any], rarity: int):
    """按装备星级返回 (费用表, 成功率表)。费用表键为当前等级 1～9，成功率表键为目标等级 2～10。"""
    index = min(max(rarity, 1), 7) - 1
    multiplier = refine["cost_multipliers"][index]
    costs = {level: int(cost * multiplier) for level, cost in refine["base_costs"].items()}
    if rarity <= 2:
        group = "low"
    elif rarity <= 6:
        group = f"r{rarity}"
    else:
        group = "high"
    return costs, dict(refine["success_rates"][group])
