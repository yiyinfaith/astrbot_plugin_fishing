from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.message.components import At
from ..draw.utils import image_result
from ..utils import format_rarity_display, parse_amount
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import FishingPlugin


async def user_backpack(plugin: "FishingPlugin", event: AstrMessageEvent):
    """分页查看鱼竿、饰品、鱼饵和道具。"""
    user_id = plugin._get_effective_user_id(event)
    user = plugin.user_repo.get_by_id(user_id)
    if not user:
        yield event.plain_result("❌ 您还没有注册，请先发送「钓鱼注册」。")
        return

    args = event.message_str.split()
    try:
        page = int(args[1]) if len(args) == 2 else 1
    except ValueError:
        page = 0
    if len(args) > 2 or page < 1:
        yield event.plain_result("❌ 用法：钓鱼背包 [页码]，页码为正整数。")
        return

    from ..draw.backpack import draw_backpack_image, get_user_backpack_data

    backpack = get_user_backpack_data(plugin.inventory_service, user_id, page)
    if page > backpack["page_count"]:
        yield event.plain_result(f"❌ 背包只有 {backpack['page_count']} 页。")
        return
    backpack["nickname"] = user.nickname or user_id
    try:
        image = await draw_backpack_image(backpack, plugin.data_dir)
        yield image_result(event, image)
    except Exception:
        logger.exception("生成钓鱼背包图片失败")
        lines = [f"【钓鱼背包】第 {page} / {backpack['page_count']} 页"]
        for category, label in (("rods", "鱼竿"), ("accessories", "饰品"), ("baits", "鱼饵"), ("items", "道具")):
            lines.append(f"\n{label}")
            for item in backpack[category]:
                if category == "baits":
                    code = f"B{item['bait_id']}"
                elif category == "items":
                    code = f"D{item['item_id']}"
                else:
                    code = item["display_code"]
                quantity = f" ×{item['quantity']}" if "quantity" in item else ""
                equipped = "（装备中）" if item.get("is_equipped") or item.get("is_current") else ""
                lines.append(f"{code} {item['name']}{quantity}{equipped}")
            if not backpack[category]:
                lines.append("本页无物品")
        yield event.plain_result("\n".join(lines))


async def pond(plugin: "FishingPlugin", event: AstrMessageEvent):
    """查看用户鱼塘内的鱼"""
    user_id = plugin._get_effective_user_id(event)
    if pond_fish := plugin.inventory_service.get_user_fish_pond(user_id):
        fishes = pond_fish["fishes"]
        # 把fishes按稀有度分组
        fished_by_rarity = {}
        for fish in fishes:
            rarity = fish.get("rarity", "未知")
            if rarity not in fished_by_rarity:
                fished_by_rarity[rarity] = []
            fished_by_rarity[rarity].append(fish)
        # 构造输出信息
        message = "【🐠 鱼塘】：\n"

        for rarity in sorted(fished_by_rarity.keys(), reverse=True):
            fish_list = fished_by_rarity[rarity]
            if fish_list:
                message += f"\n {format_rarity_display(rarity)}：\n"
                for fish in fish_list:
                    fish_id = int(fish.get("fish_id", 0) or 0)
                    quality_level = fish.get('quality_level', 0)
                    # 生成带品质标识的FID
                    if quality_level == 1:
                        fcode = f"F{fish_id}H" if fish_id else "F0H"  # H代表✨高品质
                    else:
                        fcode = f"F{fish_id}" if fish_id else "F0"   # 普通品质
                    # 显示品质信息
                    quality_display = ""
                    if quality_level == 1:
                        quality_display = " ✨高品质"
                    message += f"  - {fish['name']}{quality_display} x  {fish['quantity']} （{fish['actual_value']}金币 / 个） ID: {fcode}\n"
        message += f"\n🐟 总鱼数：{pond_fish['stats']['total_count']} 条\n"
        message += f"💰 总价值：{pond_fish['stats']['total_value']} 金币\n"
        yield event.plain_result(message)
    else:
        yield event.plain_result("🐟 您的鱼塘是空的，快去钓鱼吧！")


async def peek_pond(plugin: "FishingPlugin", event: AstrMessageEvent):
    """偷看他人鱼塘内的鱼"""
    user_id = plugin._get_effective_user_id(event)
    message_obj = event.message_obj
    target_user_id = None

    # 首先尝试从@中获取用户ID
    if hasattr(message_obj, "message"):
        # 检查消息中是否有At对象
        for comp in message_obj.message:
            if isinstance(comp, At):
                # 排除机器人本身的id
                if comp.qq != message_obj.self_id:
                    target_user_id = str(comp.qq)
                    break

    # 如果没有@，尝试从消息文本中解析
    if target_user_id is None:
        message_text = event.message_str.strip()
        if len(message_text.split()) > 1:
            # 支持 "偷看鱼塘 用户ID" 格式
            parts = message_text.split()
            if len(parts) >= 2:
                target_user_id = parts[1].strip()

    if not target_user_id:
        yield event.plain_result(
            "❌ 请指定要查看的用户！\n用法：/偷看鱼塘 @用户 或 /偷看鱼塘 用户ID"
        )
        return

    # 检查目标用户是否存在
    target_user = plugin.user_repo.get_by_id(target_user_id)
    if not target_user:
        yield event.plain_result(f"❌ 用户 {target_user_id} 不存在！")
        return

    # 获取目标用户的鱼塘信息
    if pond_fish := plugin.inventory_service.get_user_fish_pond(target_user_id):
        fishes = pond_fish["fishes"]
        # 把fishes按稀有度分组
        fished_by_rarity = {}
        for fish in fishes:
            rarity = fish.get("rarity", "未知")
            if rarity not in fished_by_rarity:
                fished_by_rarity[rarity] = []
            fished_by_rarity[rarity].append(fish)

        # 构造输出信息
        message = f"【🔍 偷看 {target_user.nickname} 的鱼塘】：\n"

        for rarity in sorted(fished_by_rarity.keys(), reverse=True):
            fish_list = fished_by_rarity[rarity]
            if fish_list:
                message += f"\n {format_rarity_display(rarity)} 稀有度 {rarity}：\n"
                for fish in fish_list:
                    fish_id = int(fish.get("fish_id", 0) or 0)
                    quality_level = fish.get('quality_level', 0)
                    # 生成带品质标识的FID
                    if quality_level == 1:
                        fcode = f"F{fish_id}H" if fish_id else "F0H"  # H代表✨高品质
                    else:
                        fcode = f"F{fish_id}" if fish_id else "F0"   # 普通品质
                    # 显示品质信息
                    quality_display = ""
                    if quality_level == 1:
                        quality_display = " ✨高品质"
                    actual_value = fish.get('actual_value', fish.get('base_value', 0))
                    message += f"  - {fish['name']}{quality_display} x  {fish['quantity']} （{actual_value}金币 / 个） ID: {fcode}\n"
        message += f"\n🐟 总鱼数：{pond_fish['stats']['total_count']} 条\n"
        message += f"💰 总价值：{pond_fish['stats']['total_value']} 金币\n"
        yield event.plain_result(message)
    else:
        yield event.plain_result(f"🐟 {target_user.nickname} 的鱼塘是空的！")


async def upgrade_pond(plugin: "FishingPlugin", event: AstrMessageEvent):
    """升级鱼塘容量"""
    user_id = plugin._get_effective_user_id(event)
    result = plugin.inventory_service.upgrade_fish_pond(user_id)
    if result["success"]:
        yield event.plain_result(
            f"🐠 鱼塘升级成功！新容量为 {result['new_capacity']} 条鱼。"
        )
    else:
        yield event.plain_result(f"❌ 升级失败：{result['message']}")


async def open_all_money_bags(plugin: "FishingPlugin", event: AstrMessageEvent):
    """开启全部钱袋：/开启全部钱袋"""
    user_id = plugin._get_effective_user_id(event)

    result = plugin.inventory_service.open_all_money_bags(user_id)

    if result and result.get("success"):
        yield event.plain_result(f"✅ {result['message']}")
    else:
        error_message = result.get("message", "未知错误") if result else "未知错误"
        yield event.plain_result(f"❌ 开启钱袋失败：{error_message}")


async def refine_help(plugin: "FishingPlugin", event: AstrMessageEvent):
    """精炼系统帮助（当前版本）"""
    help_message = """🔨 精炼系统指南（当前版本）

═══════════════════════════════════
📖 核心规则
═══════════════════════════════════

• 精炼对象：鱼竿、饰品（同模板之间精炼）
• 等级范围：1级 → 10级（目前的满级）
• 消耗条件：同模板材料 + 金币
• 每次只升1级：精N → 精N+1
• 材料选择：优先使用"未装备、精炼等级最低"的同模板实例；永不使用正在装备的作为材料

成功：
• 目标等级+1，消耗1件材料与对应金币

失败（三种）：
• 普通失败：装备本体不变，但会消耗1件材料与对应金币
• 降级失败：装备等级-1，消耗1件材料与对应金币（10%概率）
• 毁坏失败（高等级概率触发）：消耗1件材料与对应金币，并摧毁本体装备

═══════════════════════════════════
✨ 稀有度与费用/成功率
═══════════════════════════════════

🎲 成功率（关键档位）：
• 1-4星：前期成功率高，后期逐步下降（更易满精）
• 5星：6→10级约为 50%、40%、35%、30%、25%
• 6星：6→10级约为 45%、35%、30%、25%、20%
• 7星及以上：挑战性高，6→10级约为 60%、50%、40%、30%、20%

提示：成功率按"目标新等级"计算（例如精2→精3，用精3的成功率）。

═══════════════════════════════════
⚡ 属性成长与加成
═══════════════════════════════════

• 1-3星：≈+15%/级
• 4星：≈+12%/级
• 5星：≈+8%/级
• 6星：≈+5%/级
• 7星+：≈+3%/级

═══════════════════════════════════
💰 精炼收益（系统回收价）
═══════════════════════════════════

• 售价 = 基础价(按稀有度) × 精炼等级乘数
• 基础价（示例）：1★=100，2★=500，3★=2000，4★=5000，5★=10000
• 精炼乘数（示例）：1→10级：1.0, 1.6, 3.0, 6.0, 12.0, 25.0, 55.0, 125.0, 280.0, 660.0
• 设计目标：收益随等级近指数增长，高精炼装备可覆盖成本并获得显著利润
• 出售所有会逐件按该规则计价，跳过正在装备的物品
• 玩家市场价格由卖家自定，不受该公式限制

═══════════════════════════════════
🏆 耐久度（仅鱼竿）
═══════════════════════════════════

• 每次钓鱼：鱼竿耐久 -1，降至0自动卸下
• 精炼成功：耐久恢复至当前最大值
• 每升1级：最大耐久度 ×1.5（累计）
• 神器奖励：5星及以上鱼竿精炼到10级 → 获得"无限耐久"（∞）
• 饰品无耐久度，不受上述规则影响

═══════════════════════════════════
📉 失败类型与概率
═══════════════════════════════════

🎲 降级概率（固定）：
• 所有等级：10%概率降级

💥 毁坏概率（5级及以上）：
• 1-2星：30%概率毁坏
• 3-4星：35%概率毁坏
• 5-6星：40%概率毁坏
• 7星+：50%概率毁坏

💔 普通失败：剩余概率（装备保持不变）

═══════════════════════════════════
📝 命令用法
═══════════════════════════════════

• /精炼鱼竿 [鱼竿ID]
• /精炼饰品 [饰品ID]
• 需要至少两件同模板装备（目标 + 材料）
• 查看装备编号：钓鱼背包 [页码]

"""

    yield event.plain_result(help_message)


async def use_equipment(plugin: "FishingPlugin", event: AstrMessageEvent, equipment_type: str = None):
    """统一使用命令 - 根据短码前缀自动判断类型"""
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.split(" ")
    if len(args) < 2:
        yield event.plain_result(
            "❌ 请指定要使用的物品ID，例如：/使用 R1A2B（鱼竿）、/使用 A3C4D（饰品）、/使用 D1（道具）、/使用 B2（鱼饵）\n💡 道具支持数量参数：/使用 D1 10（使用10个道具）"
        )
        return

    token = args[1].strip().upper()

    # 检查是否为数字ID（旧格式）
    if token.isdigit():
        yield event.plain_result(
            "❌ 请使用正确的物品ID！\n\n📝 短码格式：\n• R开头：鱼竿（如 R2N9C）\n• A开头：饰品（如 A7K3Q）\n• D开头：道具（如 D1）\n• B开头：鱼饵（如 B2）\n\n💡 提示：使用 /钓鱼背包 查看您的物品短码"
        )
        return

    # 根据前缀自动判断物品类型
    if token.startswith("R"):
        target_type = "rod"
        type_name = "鱼竿"
    elif token.startswith("A"):
        target_type = "accessory"
        type_name = "饰品"
    elif token.startswith("D"):
        target_type = "item"
        type_name = "道具"
    elif token.startswith("B"):
        target_type = "bait"
        type_name = "鱼饵"
    else:
        # 如果没有前缀，使用传入的类型参数
        if equipment_type:
            target_type = equipment_type
            type_name = "鱼竿" if equipment_type == "rod" else "饰品"
        else:
            yield event.plain_result(
                "❌ 请使用正确的物品ID：R开头为鱼竿，A开头为饰品，D开头为道具，B开头为鱼饵"
            )
            return

    # 处理不同类型的物品
    if target_type in ["rod", "accessory"]:
        # 装备类物品
        equipment_info = (
            plugin.inventory_service.get_user_rod_inventory(user_id)
            if target_type == "rod"
            else plugin.inventory_service.get_user_accessory_inventory(user_id)
        )

        if not equipment_info or not equipment_info.get(
            "rods" if target_type == "rod" else "accessories"
        ):
            yield event.plain_result(f"❌ 您还没有{type_name}，请先购买或抽奖获得。")
            return

        # 解析实例ID
        if target_type == "rod":
            instance_id = plugin.inventory_service.resolve_rod_instance_id(user_id, token)
        else:
            instance_id = plugin.inventory_service.resolve_accessory_instance_id(
                user_id, token
            )

        if instance_id is None:
            yield event.plain_result(f"❌ 无效的{type_name}ID，请检查后重试。")
            return

        # 装备物品
        if result := plugin.inventory_service.equip_item(
            user_id, int(instance_id), target_type
        ):
            if result["success"]:
                yield event.plain_result(result["message"])
            else:
                yield event.plain_result(f"❌ 使用{type_name}失败：{result['message']}")
        else:
            yield event.plain_result("❌ 出错啦！请稍后再试。")

    elif target_type == "item":
        # 道具类物品（简单数字ID）
        try:
            item_id = int(token[1:])
        except Exception:
            yield event.plain_result("❌ 无效的道具ID，请检查后重试。")
            return

        # 处理数量参数
        quantity = 1
        if len(args) > 2 and args[2].isdigit():
            quantity = int(args[2])
            if quantity <= 0:
                yield event.plain_result("❌ 数量必须是正整数。")
                return

        # 使用道具
        if result := plugin.inventory_service.use_item(user_id, int(item_id), quantity):
            if result["success"]:
                yield event.plain_result(result["message"])
            else:
                yield event.plain_result(f"❌ 使用道具失败：{result['message']}")
        else:
            yield event.plain_result("❌ 出错啦！请稍后再试。")

    elif target_type == "bait":
        # 鱼饵类物品（简单数字ID）
        try:
            bait_id = int(token[1:])
        except Exception:
            yield event.plain_result("❌ 无效的鱼饵ID，请检查后重试。")
            return

        # 使用鱼饵
        if result := plugin.inventory_service.use_bait(user_id, int(bait_id)):
            if result["success"]:
                yield event.plain_result(result["message"])
            else:
                yield event.plain_result(f"❌ 使用鱼饵失败：{result['message']}")
        else:
            yield event.plain_result("❌ 出错啦！请稍后再试。")


async def refine_equipment(plugin: "FishingPlugin", event: AstrMessageEvent, equipment_type: str = None):
    """统一精炼装备命令 - 根据短码前缀自动判断类型"""
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.split(" ")
    if len(args) < 2:
        # 如果没有参数，返回精炼帮助
        async for r in refine_help(plugin, event):
            yield r
        return

    token = args[1].strip().upper()

    # 检查是否为数字ID（旧格式）
    if token.isdigit():
        yield event.plain_result(
            "❌ 请使用正确的物品ID！\n\n📝 短码格式：\n• R开头：鱼竿（如 R2N9C）\n• A开头：饰品（如 A7K3Q）\n\n💡 提示：使用 /钓鱼背包 查看您的物品短码"
        )
        return

    # 根据前缀自动判断装备类型
    if token.startswith("R"):
        target_type = "rod"
        type_name = "鱼竿"
    elif token.startswith("A"):
        target_type = "accessory"
        type_name = "饰品"
    else:
        # 如果没有前缀，使用传入的类型参数
        if equipment_type:
            target_type = equipment_type
            type_name = "鱼竿" if equipment_type == "rod" else "饰品"
        else:
            yield event.plain_result("❌ 请使用正确的装备ID：R开头为鱼竿，A开头为饰品")
            return

    # 解析实例ID
    if target_type == "rod":
        instance_id = plugin.inventory_service.resolve_rod_instance_id(user_id, token)
    else:
        instance_id = plugin.inventory_service.resolve_accessory_instance_id(
            user_id, token
        )

    if instance_id is None:
        yield event.plain_result(f"❌ 无效的{type_name}ID，请检查后重试。")
        return

    # 精炼物品
    if result := plugin.inventory_service.refine(user_id, int(instance_id), target_type):
        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(f"❌ 精炼失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def sell_equipment(plugin: "FishingPlugin", event: AstrMessageEvent, equipment_type: str = None):
    """统一出售物品命令 - 根据短码前缀自动判断类型"""
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.split(" ")
    if len(args) < 2:
        yield event.plain_result(
            "❌ 请指定要出售的物品ID，例如：/出售 R1A2B（鱼竿）、/出售 A3C4D（饰品）、/出售 D1（道具）\n💡 道具支持数量参数：/出售 D1 10（出售10个道具）或 /出售 D1 一千（支持中文数字）"
        )
        return

    token = args[1].strip().upper()

    # 检查是否为数字ID（旧格式）
    if token.isdigit():
        yield event.plain_result(
            "❌ 请使用正确的物品ID！\n\n📝 短码格式：\n• R开头：鱼竿（如 R2N9C）\n• A开头：饰品（如 A7K3Q）\n• D开头：道具（如 D1）\n\n💡 提示：使用 /钓鱼背包 查看您的物品短码"
        )
        return

    # 根据前缀自动判断物品类型
    if token.startswith("R"):
        target_type = "rod"
        type_name = "鱼竿"
    elif token.startswith("A"):
        target_type = "accessory"
        type_name = "饰品"
    elif token.startswith("D"):
        target_type = "item"
        type_name = "道具"
    else:
        # 如果没有前缀，使用传入的类型参数
        if equipment_type:
            target_type = equipment_type
            type_name = "鱼竿" if equipment_type == "rod" else "饰品"
        else:
            yield event.plain_result(
                "❌ 请使用正确的物品ID：R开头为鱼竿，A开头为饰品，D开头为道具"
            )
            return

    # 处理道具的特殊情况（需要解析数量参数）
    if target_type == "item":
        # 解析道具ID
        try:
            item_id = int(token[1:])
        except ValueError:
            yield event.plain_result("❌ 无效的道具ID，请检查后重试。")
            return

        # 解析数量参数
        quantity = 1
        if len(args) >= 3:
            try:
                quantity = parse_amount(args[2])
                if quantity <= 0:
                    yield event.plain_result("❌ 数量必须是正整数")
                    return
            except Exception as e:
                yield event.plain_result(f"❌ 无法解析数量：{str(e)}。示例：1 或 五 或 一千")
                return

        # 出售道具
        if result := plugin.inventory_service.sell_item(user_id, item_id, quantity):
            if result["success"]:
                yield event.plain_result(result["message"])
            else:
                yield event.plain_result(f"❌ 出售失败：{result['message']}")
        else:
            yield event.plain_result("❌ 出错啦！请稍后再试。")
        return

    # 处理装备（鱼竿和饰品）
    # 解析实例ID
    if target_type == "rod":
        instance_id = plugin.inventory_service.resolve_rod_instance_id(user_id, token)
    else:
        instance_id = plugin.inventory_service.resolve_accessory_instance_id(
            user_id, token
        )

    if instance_id is None:
        yield event.plain_result(f"❌ 无效的{type_name}ID，请检查后重试。")
        return

    # 出售物品
    if result := plugin.inventory_service.sell_equipment(
        user_id, int(instance_id), target_type
    ):
        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(f"❌ 出售失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def lock_equipment(plugin: "FishingPlugin", event: AstrMessageEvent, equipment_type: str = None):
    """统一锁定装备命令 - 根据短码前缀自动判断类型"""
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.split(" ")
    if len(args) < 2:
        yield event.plain_result(
            "❌ 请指定要锁定的装备ID，例如：/锁定装备 R1A2B 或 /锁定装备 A3C4D"
        )
        return

    token = args[1].strip().upper()

    # 检查是否为数字ID（旧格式）
    if token.isdigit():
        yield event.plain_result(
            "❌ 请使用正确的物品ID！\n\n📝 短码格式：\n• R开头：鱼竿（如 R2N9C）\n• A开头：饰品（如 A7K3Q）\n\n💡 提示：使用 /钓鱼背包 查看您的物品短码"
        )
        return

    # 根据前缀自动判断装备类型
    if token.startswith("R"):
        target_type = "rod"
        type_name = "鱼竿"
    elif token.startswith("A"):
        target_type = "accessory"
        type_name = "饰品"
    else:
        # 如果没有前缀，使用传入的类型参数
        if equipment_type:
            target_type = equipment_type
            type_name = "鱼竿" if equipment_type == "rod" else "饰品"
        else:
            yield event.plain_result("❌ 请使用正确的装备ID：R开头为鱼竿，A开头为饰品")
            return

    # 解析实例ID
    if target_type == "rod":
        instance_id = plugin.inventory_service.resolve_rod_instance_id(user_id, token)
    else:
        instance_id = plugin.inventory_service.resolve_accessory_instance_id(
            user_id, token
        )

    if instance_id is None:
        yield event.plain_result(f"❌ 无效的{type_name}ID，请检查后重试。")
        return

    # 锁定物品
    if target_type == "rod":
        result = plugin.inventory_service.lock_rod(user_id, int(instance_id))
    else:
        result = plugin.inventory_service.lock_accessory(user_id, int(instance_id))

    if result["success"]:
        yield event.plain_result(result["message"])
    else:
        yield event.plain_result(f"❌ 锁定失败：{result['message']}")


async def unlock_equipment(plugin: "FishingPlugin", event: AstrMessageEvent, equipment_type: str = None):
    """统一解锁装备命令 - 根据短码前缀自动判断类型"""
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.split(" ")
    if len(args) < 2:
        yield event.plain_result(
            "❌ 请指定要解锁的装备ID，例如：/解锁装备 R1A2B 或 /解锁装备 A3C4D"
        )
        return

    token = args[1].strip().upper()

    # 检查是否为数字ID（旧格式）
    if token.isdigit():
        yield event.plain_result(
            "❌ 请使用正确的物品ID！\n\n📝 短码格式：\n• R开头：鱼竿（如 R2N9C）\n• A开头：饰品（如 A7K3Q）\n\n💡 提示：使用 /钓鱼背包 查看您的物品短码"
        )
        return

    # 根据前缀自动判断装备类型
    if token.startswith("R"):
        target_type = "rod"
        type_name = "鱼竿"
    elif token.startswith("A"):
        target_type = "accessory"
        type_name = "饰品"
    else:
        # 如果没有前缀，使用传入的类型参数
        if equipment_type:
            target_type = equipment_type
            type_name = "鱼竿" if equipment_type == "rod" else "饰品"
        else:
            yield event.plain_result("❌ 请使用正确的装备ID：R开头为鱼竿，A开头为饰品")
            return

    # 解析实例ID
    if target_type == "rod":
        instance_id = plugin.inventory_service.resolve_rod_instance_id(user_id, token)
    else:
        instance_id = plugin.inventory_service.resolve_accessory_instance_id(
            user_id, token
        )

    if instance_id is None:
        yield event.plain_result(f"❌ 无效的{type_name}ID，请检查后重试。")
        return

    # 解锁物品
    if target_type == "rod":
        result = plugin.inventory_service.unlock_rod(user_id, int(instance_id))
    else:
        result = plugin.inventory_service.unlock_accessory(user_id, int(instance_id))

    if result["success"]:
        yield event.plain_result(result["message"])
    else:
        yield event.plain_result(f"❌ 解锁失败：{result['message']}")


async def coins(plugin: "FishingPlugin", event: AstrMessageEvent):
    """查看用户金币信息"""
    user_id = plugin._get_effective_user_id(event)
    if user := plugin.user_repo.get_by_id(user_id):
        yield event.plain_result(f"💰 您的金币余额：{user.coins:,} 金币")
    else:
        yield event.plain_result("❌ 您还没有注册，请先使用 /钓鱼注册 命令注册。")
