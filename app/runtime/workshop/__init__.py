"""Unified DeepAgent 领域层（架构定稿，2026-08）。

create_deep_agent 是唯一根图；FastPathMiddleware 在 before_agent 做一次性的
语义编译、继承、能力路由与有界执行（executed/rejected → jump_to=end 短路；
agent → 自然进入 model/tools/subagents 循环）；FinalizeMiddleware 在
after_agent 统一完成 guardrail、输出规范化、presentation 与持久化。

调用方只读取最终 state["response"]，不再为 FastPath 与 Agent 分别拼装响应。
"""
