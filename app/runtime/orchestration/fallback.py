"""显式 fallback 状态机（架构定稿 §6）。

禁止宽泛 ``except Exception: run_agent()``——权限错误、数据完整性错误和
基础设施异常必须分流到不同动作。本模块是唯一 fallback 决策点：输入
reason_code，输出动作。

```
NOT_APPLICABLE     → DeepAgent
LOW_CONFIDENCE     → DeepAgent
MISSING_SLOT       → Clarification
TRANSIENT_FAILURE  → Retry → DeepAgent（按能力配置）
PERMISSION_DENIED  → END / Reject
EVIDENCE_FAILED    → END / Fail Closed
SUCCESS            → Response
```
"""

from __future__ import annotations

from dataclasses import dataclass

from app.runtime.orchestration.state import FallbackAction


@dataclass(frozen=True)
class FallbackRule:
    reason_code: str
    action: FallbackAction
    description: str


# 稳定 reason_code → 动作映射（架构定稿 §6 表格）
FALLBACK_RULES: tuple[FallbackRule, ...] = (
    # 路由层
    FallbackRule("NOT_APPLICABLE", "to_deep_agent", "能力集合外 → 开放推理"),
    FallbackRule("LOW_CONFIDENCE", "to_deep_agent", "编译置信度不足 → 开放推理"),
    FallbackRule("MISSING_SLOT", "clarify", "缺必要信息 → 澄清"),
    FallbackRule("UNSUPPORTED_ANALYSIS_TYPE", "clarify", "能力未注册 → 澄清/拒绝"),
    # 执行层
    FallbackRule("PERMISSION_DENIED", "reject", "权限不足 → 拒绝，不降级"),
    FallbackRule("EVIDENCE_FAILED", "fail_closed", "证据不足 → 失败关闭"),
    FallbackRule("CONTRACT_VIOLATION", "fail_closed", "契约越界 → 失败关闭"),
    FallbackRule("TRANSIENT_FAILURE", "retry", "瞬时故障 → 重试（按能力配置）"),
    # 成功
    FallbackRule("SUCCESS", "respond", "成功 → 响应"),
)

# 已知 reason_code 查表；未知一律 fail_closed（宁可拒绝，不可猜）
_FALLBACK_MAP = {rule.reason_code: rule for rule in FALLBACK_RULES}
_DEFAULT_ACTION: FallbackAction = "fail_closed"


def fallback_action(reason_code: str) -> FallbackAction:
    """reason_code → 动作。未知 reason_code 默认 fail_closed。"""
    rule = _FALLBACK_MAP.get(reason_code)
    return rule.action if rule is not None else _DEFAULT_ACTION


def resolve_reason_code(status: str, *, extra: str | None = None) -> str:
    """把内部 status/异常类型归一为稳定 reason_code。

    - ``not_applicable``（FastPath 未命中）→ NOT_APPLICABLE → to_deep_agent
    - ``requires_clarification`` / ``unsupported`` → MISSING_SLOT /
      UNSUPPORTED_ANALYSIS_TYPE → clarify
    - ``rejected`` → PERMISSION_DENIED → reject
    - 其余（异常、校验失败）→ EVIDENCE_FAILED → fail_closed
    """
    if status == "not_applicable":
        return "NOT_APPLICABLE"
    if status == "requires_clarification":
        return "MISSING_SLOT"
    if status == "unsupported":
        return extra or "UNSUPPORTED_ANALYSIS_TYPE"
    if status == "rejected":
        return extra or "PERMISSION_DENIED"
    if status == "executed" or status == "success":
        return "SUCCESS"
    return "EVIDENCE_FAILED"
