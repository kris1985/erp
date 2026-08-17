"""pytest 域标记：按测试文件名把用例分为 agent / business 两域。

用法：
    pytest -m agent       # 车间军师 / Agent 域（workshop/runtime/planner/replay/analytics）
    pytest -m business    # 业务域（执行/采购/仓库/工资/排产/质检等）
    pytest                # 全量（默认，~24s，仍然安全兜底）

域清单集中在这里维护；新测试文件按文件名前缀自动归类。
"""

from __future__ import annotations

import pytest

_AGENT_PREFIXES = (
    "test_agent_",       # agent 编排/展示/可观测/策略
    "test_runtime_",     # 运行时可信链（contracts/facts/rules/renderer/…）
    "test_workshop_",    # 军师直查/中间件/持久化/指标
    "test_intent_",      # 意图路由（分层路由/golden 集）
    "test_analysis_plans",
    "test_analysis_result_store",
    "test_replay_",      # 回放快照（指标快照/排行）
    "test_lifecycle_agents",
    "test_analytics",    # 军师诊断 analytics.*
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "agent: 车间军师/Agent 域（workshop/runtime/planner/replay/analytics）")
    config.addinivalue_line("markers", "business: 业务域（执行/采购/仓库/工资/排产/质检等）")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        filename = item.nodeid.split("::", 1)[0].rsplit("/", 1)[-1]
        if filename.startswith(_AGENT_PREFIXES):
            item.add_marker(pytest.mark.agent)
        else:
            item.add_marker(pytest.mark.business)
