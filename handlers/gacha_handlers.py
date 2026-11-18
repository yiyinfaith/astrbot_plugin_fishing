from collections import Counter

from astrbot.api.event import AstrMessageEvent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import FishingPlugin


def _get_field(obj, key, default=None):
    """统一读取字段，兼容 dataclass 模型实现了 __getitem__ 但没有 dict.get 的情况。"""
    try:
        # 优先尝试下标访问（GachaPool 实现了 __getitem__）
        return obj[key]
    except Exception:
        # 若是 dict 支持 get；否则回退 getattr
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)


def _format_pool_details(pool, probabilities):
    message = "【🎰 卡池详情】\n\n"
    message += f"ID: {pool['gacha_pool_id']} - {pool['name']}\n"
    message += f"描述: {pool['description']}\n"
    # 限时开放信息展示（安全检查字段）
    is_limited_time = bool(_get_field(pool, "is_limited_time"))
    open_until = _get_field(pool, "open_until")
    if is_limited_time and open_until:
        display_time = str(open_until).replace("T", " ").replace("-", "/")
        if len(display_time) > 16:
            display_time = display_time[:16]
        message += f"限时开放 至: {display_time}\n"
    message += f"花费: {pool['cost_coins']} 金币 / 次\n\n"
    message += "【📋 物品概率】\n"
    if probabilities:
        for item in probabilities:
            message += (
                f" - {'⭐' * item.get('item_rarity', 0)} {item['item_name']} "
                f"(概率: {item['probability']:.2%})\n"
            )
    return message


async def gacha(self: "FishingPlugin", event: AstrMessageEvent):
    """抽卡"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split()
    if len(args) < 2:
        # 展示所有的抽奖池信息并显示帮助
        pools = self.gacha_service.get_all_pools()
        if not pools["success"] or not pools["pools"]:
            yield event.plain_result("❌ 当前没有可用的抽奖池。")
            return
        message = "【🎰 抽奖池列表】\n\n"
        for pool in pools.get("pools", []):
            cost_text = f"💰 金币 {pool['cost_coins']} / 次"
            message += f"ID: {pool['gacha_pool_id']} - {pool['name']} - {pool['description']}\n {cost_text}\n\n"
        # 添加卡池详细信息
        message += "【📋 卡池详情】使用「查看卡池 ID」命令查看详细物品概率\n"
        message += "【🎲 抽卡命令】使用「抽卡 ID」命令选择抽卡池进行单次抽卡\n"
        message += "【🎯 十连命令】使用「十连 ID [次数]」命令进行十连抽卡\n"
        message += "   - 单次十连：/十连 1\n"
        message += "   - 多次十连：/十连 1 5 (进行5次十连，合并统计)"
        yield event.plain_result(message)
        return
    pool_id = args[1]
    if not pool_id.isdecimal():
        yield event.plain_result("❌ 抽奖池 ID 必须是数字，请检查后重试。")
        return
    pool_id = int(pool_id)
    if result := self.gacha_service.perform_draw(user_id, pool_id, num_draws=1):
        if result["success"]:
            items = result.get("results", [])
            message = f"🎉 抽卡成功！您抽到了 {len(items)} 件物品：\n"
            for item in items:
                # 构造输出信息
                if item.get("type") == "coins":
                    # 金币类型的物品
                    message += f"⭐ {item['quantity']} 金币！\n"
                else:
                    message += f"{'⭐' * item.get('rarity', 1)} {item['name']} ×{item['quantity']}\n"
            yield event.plain_result(message)
        else:
            yield event.plain_result(f"❌ 抽卡失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def ten_gacha(self: "FishingPlugin", event: AstrMessageEvent):
    """十连抽卡"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split()
    if len(args) < 2:
        yield event.plain_result("❌ 请指定要进行十连抽卡的抽奖池 ID，例如：/十连 1")
        return
    
    # 检查是否有次数参数
    times = 1
    if len(args) >= 3:
        if args[2].isdecimal():
            times = int(args[2])
            if times <= 0:
                yield event.plain_result("❌ 抽卡次数必须大于0")
                return
            if times > 100:
                yield event.plain_result("❌ 单次最多只能进行100次十连抽卡")
                return
        else:
            yield event.plain_result("❌ 抽卡次数必须是数字")
            return
    
    pool_id = args[1]
    if not pool_id.isdecimal():
        yield event.plain_result("❌ 抽奖池 ID 必须是数字，请检查后重试。")
        return
    pool_id = int(pool_id)
    
    # 如果是多次十连，使用合并统计功能
    if times > 1:
        async for result in multi_ten_gacha(self, event, pool_id, times):
            yield result
        return
    
    # 单次十连抽卡
    if result := self.gacha_service.perform_draw(user_id, pool_id, num_draws=10):
        if result["success"]:
            items = result.get("results", [])
            message = f"🎉 十连抽卡成功！您抽到了 {len(items)} 件物品：\n"
            for item in items:
                # 构造输出信息
                if item.get("type") == "coins":
                    # 金币类型的物品
                    message += f"⭐ {item['quantity']} 金币！\n"
                else:
                    message += f"{'⭐' * item.get('rarity', 1)} {item['name']} ×{item['quantity']}\n"
            yield event.plain_result(message)
        else:
            yield event.plain_result(f"❌ 抽卡失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def multi_ten_gacha(self: "FishingPlugin", event: AstrMessageEvent, pool_id: int, times: int):
    """Run a batch of ten-draws and report its consolidated rewards."""
    user_id = self._get_effective_user_id(event)
    result = self.gacha_service.perform_draw(user_id, pool_id, num_draws=times * 10)
    if not result["success"]:
        yield event.plain_result(f"❌ 抽卡失败：{result['message']}")
        return

    items = Counter()
    rarities = Counter()
    coins = 0
    for reward in result["results"]:
        if reward["type"] == "coins":
            coins += reward["quantity"]
        else:
            items[reward["name"]] += reward["quantity"]
            rarities[min(reward["rarity"], 10)] += reward["quantity"]

    lines = [f"🎉 完成 {times} 次十连，消耗 {result['cost_coins']:,} 金币。"]
    lines.extend(f"{'⭐' * rarity} {count} 件" for rarity, count in sorted(rarities.items(), reverse=True))
    if coins:
        lines.append(f"💰 获得金币 {coins:,}")
    lines.extend(f"{name} ×{count}" for name, count in sorted(items.items()))
    yield event.plain_result("\n".join(lines))


async def view_gacha_pool(self: "FishingPlugin", event: AstrMessageEvent):
    """查看当前卡池"""
    args = event.message_str.split()
    if len(args) < 2:
        yield event.plain_result("❌ 请指定要查看的卡池 ID，例如：/查看卡池 1")
        return
    pool_id = args[1]
    if not pool_id.isdecimal():
        yield event.plain_result("❌ 卡池 ID 必须是数字，请检查后重试。")
        return
    pool_id = int(pool_id)
    if result := self.gacha_service.get_pool_details(pool_id):
        if result["success"]:
            pool = result.get("pool", {})
            probabilities = result.get("probabilities", [])
            yield event.plain_result(_format_pool_details(pool, probabilities))
        else:
            yield event.plain_result(f"❌ 查看卡池失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")
