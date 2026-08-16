"""验证 Fast Path 进入 LangSmith（独立 trace）。

运行：.venv/bin/python scripts/probe_fast_path_tracing.py
若打印「fast path trace 已上报」，去 LangSmith project=workshop-agent 应能看到
名为 run_fast_path / semantic_compiler.resolve_inheritance 的独立 run。
"""
import sys
import tempfile
from decimal import Decimal
from unittest.mock import patch

sys.path.insert(0, ".")

from app.config import get_settings  # noqa: E402
from app.services import agent_fast_path, analysis_result_store, finance_service  # noqa: E402

settings = get_settings()
if not (settings.langsmith_tracing and settings.langsmith_api_key):
    print("LangSmith 未启用（LANGSMITH_TRACING/API_KEY），跳过")
    sys.exit(0)

tmp = tempfile.mkdtemp()
settings.schedule_agent_data_dir = tmp
settings.agent_fast_path_enabled = True
settings.analysis_result_ttl_seconds = 3600
settings.analysis_result_max_per_session = 200


def fake_report(db, tenant_id, *, year=None, month=None, customer_id=None, keyword=None,
                date_from=None, date_to=None, loss_only=False):
    return {"orders": [
        {"customer_name": "客户 A", "revenue": Decimal("12350000")},
        {"customer_name": "客户 B", "revenue": Decimal("9800000")},
    ], "summary": {"revenue": Decimal("22150000")}, "year": year}


with patch.object(finance_service, "profit_report", fake_report), \
     patch.object(analysis_result_store, "get_settings", lambda: settings):
    out = agent_fast_path.run_fast_path(
        None, tenant_id=1, question="客户销售top2", conversation_id="probe_1",
        permission_codes=["menu.profit"],
    )
print("status:", out.status)
print("reply:", out.response["reply"] if out.response else None)
print("fast path trace 已上报（LangSmith project=workshop-agent 应能看到 run_fast_path）")
