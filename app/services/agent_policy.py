"""Versioned, validated policy artifacts for the workshop agent.

The agent may read these policies, but it never treats a prompt as the source of
authority.  Invalid policy files fail application startup instead of silently
changing query or action behaviour.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisTypePolicy(_StrictModel):
    required_slots: list[str] = Field(default_factory=list)
    allowed_metrics: list[str] = Field(default_factory=list)
    result_shape: str
    defaults: dict[str, Any] = Field(default_factory=dict)
    match_rules: dict[str, Any] = Field(default_factory=dict)


class AnalysisRegistryPolicy(_StrictModel):
    version: str
    analysis_types: dict[str, AnalysisTypePolicy]


class MetricPolicy(_StrictModel):
    metric_id: str
    supported_analysis_types: list[str]


class MetricCatalogPolicy(_StrictModel):
    version: str
    metrics: dict[str, MetricPolicy]


class GlobalPolicy(_StrictModel):
    version: str
    numeric: dict[str, Any]
    evidence: dict[str, Any]
    permissions: dict[str, Any]
    hitl: dict[str, Any]


class ActionPolicy(_StrictModel):
    version: str
    actions: dict[str, Literal["read_only", "draft", "approval_required", "prohibited"]]


class UiContractEntry(_StrictModel):
    typed_result: str
    presentation: str


class UiContractPolicy(_StrictModel):
    version: str
    analysis_types: dict[str, UiContractEntry]


class PolicyBundle(_StrictModel):
    global_policy: GlobalPolicy
    analysis_registry: AnalysisRegistryPolicy
    metric_catalog: MetricCatalogPolicy
    action_policy: ActionPolicy
    ui_contract: UiContractPolicy

    @property
    def versions(self) -> dict[str, str]:
        return {
            "global_policy": self.global_policy.version,
            "analysis_registry": self.analysis_registry.version,
            "metric_catalog": self.metric_catalog.version,
            "action_policy": self.action_policy.version,
            "ui_contract": self.ui_contract.version,
        }


_POLICY_DIR = Path(__file__).resolve().parents[1] / "agent_policy"


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"agent_policy_file_unreadable:{path.name}") from exc
    except yaml.YAMLError as exc:
        raise RuntimeError(f"agent_policy_yaml_invalid:{path.name}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"agent_policy_root_invalid:{path.name}")
    return data


def load_policy_bundle(policy_dir: Path | None = None) -> PolicyBundle:
    """Load every policy file and validate cross-file references."""
    root = policy_dir or _POLICY_DIR
    try:
        bundle = PolicyBundle(
            global_policy=_load_yaml(root / "global-policy.yaml"),
            analysis_registry=_load_yaml(root / "analysis-registry.yaml"),
            metric_catalog=_load_yaml(root / "metric-catalog.yaml"),
            action_policy=_load_yaml(root / "action-policy.yaml"),
            ui_contract=_load_yaml(root / "ui-contract.yaml"),
        )
    except ValidationError as exc:
        raise RuntimeError("agent_policy_schema_invalid") from exc

    registry = bundle.analysis_registry.analysis_types
    catalog = bundle.metric_catalog.metrics
    ui_types = bundle.ui_contract.analysis_types
    if set(registry) != set(ui_types):
        raise RuntimeError("agent_policy_ui_contract_mismatch")
    for analysis_type, spec in registry.items():
        if spec.result_shape != ui_types[analysis_type].typed_result:
            raise RuntimeError(f"agent_policy_result_shape_mismatch:{analysis_type}")
        for metric in spec.allowed_metrics:
            if metric not in catalog:
                raise RuntimeError(f"agent_policy_unknown_metric:{analysis_type}:{metric}")
            if analysis_type not in catalog[metric].supported_analysis_types:
                raise RuntimeError(f"agent_policy_metric_analysis_mismatch:{analysis_type}:{metric}")
    return bundle


@lru_cache
def get_policy_bundle() -> PolicyBundle:
    return load_policy_bundle()
