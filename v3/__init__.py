"""
v3 — V3 L1 意图路由层 (独立于 V2 src/)
=======================================

V3 核心变化:
  - 单阶段: 仅 L1 意图路由, 无 L0/L2/L3
  - 调用格式: ###call(L1-L2) 替换 28 个具名 API
  - 澄清: L1 意图竞争澄清 + L2 SOP 驱动澄清
  - 不收集槽位, 不做风险评估

用法:
    from v3.entrance import entrance
    result = entrance(messages, debug=True)
"""
