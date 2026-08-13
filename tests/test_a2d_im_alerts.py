"""A2d：IM 预警推送 + 进度日报（v1 stub，只推不改）。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Order, OrderStatus, OwnProduct, Tenant
from app.services import im_alerts_service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_tenant(db, *, name: str = "预警测试厂") -> Tenant:
    tenant = Tenant(name=name)
    db.add(tenant)
    db.commit()
    return tenant


def _seed_at_risk_order(db, tenant: Tenant) -> Order:
    """交期今天、无工序（进度 0%）→ workshop_display 判定 at_risk=true。"""
    product = OwnProduct(tenant_id=tenant.id, product_code="A2D-001", quote_price=100)
    db.add(product)
    db.flush()
    order = Order(
        tenant_id=tenant.id,
        order_no="A2D-ORDER-01",
        customer_name="风险测试客户",
        own_product_id=product.id,
        total_qty=100,
        delivery_date=date.today(),
        status=OrderStatus.confirmed,
        is_rush=True,
    )
    db.add(order)
    db.commit()
    return order


class _FakeResponse:
    """伪造 `urlopen` 返回的响应对象，支持 `with` 语法。"""

    def __init__(self, status: int, body: bytes = b"{}"):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self._body


# ---------------------------------------------------------------------------
# 设置：默认值 / 合并 / 持久化
# ---------------------------------------------------------------------------


def test_default_im_alerts_disabled_with_all_events():
    cfg = im_alerts_service.default_im_alerts()
    assert cfg["enabled"] is False
    assert cfg["webhook_url"] is None
    assert set(cfg["events"]) == set(im_alerts_service.EVENT_TYPES)


def test_merge_im_alerts_filters_unknown_events():
    merged = im_alerts_service.merge_im_alerts(
        {"im_alerts": {"webhook_url": "  https://example.com/hook  ", "enabled": True, "events": ["shortage", "bogus"]}}
    )
    assert merged["webhook_url"] == "https://example.com/hook"
    assert merged["enabled"] is True
    assert merged["events"] == ["shortage"]


def test_merge_im_alerts_blank_webhook_becomes_none():
    merged = im_alerts_service.merge_im_alerts({"webhook_url": "   ", "enabled": True})
    assert merged["webhook_url"] is None


def test_save_and_get_im_alerts_patch_roundtrip(db):
    tenant = _seed_tenant(db)
    saved = im_alerts_service.save_im_alerts_patch(
        db,
        tenant.id,
        {"webhook_url": "https://qyapi.example.com/hook?key=abc", "enabled": True, "events": ["shortage", "digest"]},
    )
    assert saved["webhook_url"] == "https://qyapi.example.com/hook?key=abc"
    assert saved["enabled"] is True
    assert saved["events"] == ["shortage", "digest"]

    reloaded = im_alerts_service.get_im_alerts_by_tenant_id(db, tenant.id)
    assert reloaded == saved


def test_save_im_alerts_patch_unknown_tenant_raises(db):
    with pytest.raises(ValueError):
        im_alerts_service.save_im_alerts_patch(db, 999999, {"enabled": True})


# ---------------------------------------------------------------------------
# payload 组装（干跑，不发送）
# ---------------------------------------------------------------------------


def test_build_alert_payload_empty_is_all_clear(db):
    tenant = _seed_tenant(db)
    payload = im_alerts_service.build_alert_payload(db, tenant.id)
    assert payload["kind"] == "alert"
    assert payload["event_count"] == 0
    assert payload["message"]["msgtype"] == "markdown"
    assert "一切正常" in payload["message"]["markdown"]["content"]


def test_build_alert_payload_includes_delivery_risk_order(db):
    tenant = _seed_tenant(db)
    order = _seed_at_risk_order(db, tenant)
    payload = im_alerts_service.build_alert_payload(db, tenant.id)
    assert payload["event_count"] >= 1
    codes = [e["type"] for e in payload["events"]]
    assert "delivery_risk" in codes
    content = payload["message"]["markdown"]["content"]
    assert order.order_no in content
    assert "**交期风险**" in content


def test_build_alert_payload_event_types_filter_out_delivery_risk(db):
    tenant = _seed_tenant(db)
    _seed_at_risk_order(db, tenant)
    payload = im_alerts_service.build_alert_payload(db, tenant.id, event_types=["shortage"])
    assert payload["event_count"] == 0


def test_build_alert_payload_shortage_event_from_material_blocks(db, monkeypatch):
    tenant = _seed_tenant(db)

    fake_display = {
        "summary": {},
        "focus_orders": [],
        "material_blocks": [
            {"order_no": "SHORT-01", "label": "齐套不足（缺 2 项）", "is_rush": True},
        ],
    }
    monkeypatch.setattr(im_alerts_service, "workshop_display", lambda db_, tenant_id_: fake_display)

    payload = im_alerts_service.build_alert_payload(db, tenant.id)
    assert payload["event_count"] == 1
    assert payload["events"][0]["type"] == "shortage"
    content = payload["message"]["markdown"]["content"]
    assert "SHORT-01" in content
    assert "急单" in content
    assert "**缺料**" in content
    assert 'color="warning"' in content


def test_build_daily_digest_contains_summary_and_focus(db, monkeypatch):
    tenant = _seed_tenant(db)
    fake_display = {
        "summary": {
            "yesterday_qualified": 120,
            "yesterday_defect": 3,
            "yesterday_defect_rate": 2.4,
            "rush_orders": 2,
            "material_blocked_orders": 1,
        },
        "focus_orders": [
            {
                "order_no": "DIGEST-01",
                "customer_name": "日报客户",
                "delivery_label": "D-2",
                "overall_percent": 55.0,
            }
        ],
        "material_blocks": [],
    }
    monkeypatch.setattr(im_alerts_service, "workshop_display", lambda db_, tenant_id_: fake_display)

    digest = im_alerts_service.build_daily_digest(db, tenant.id)
    assert digest["kind"] == "digest"
    assert digest["message"]["msgtype"] == "markdown_v2"
    content = digest["message"]["markdown_v2"]["content"]
    assert "## 产量 KPI" in content
    assert "| 昨日合格 | 120 |" in content
    assert "## Top5 重点订单" in content
    assert "DIGEST-01" in content
    assert "日报客户" in content
    assert "55.0%" in content
    assert digest["summary"]["rush_orders"] == 2


def test_build_daily_digest_empty_focus_orders(db, monkeypatch):
    tenant = _seed_tenant(db)
    fake_display = {
        "summary": {
            "yesterday_qualified": 0,
            "yesterday_defect": 0,
            "yesterday_defect_rate": 0,
            "rush_orders": 0,
            "material_blocked_orders": 0,
        },
        "focus_orders": [],
        "material_blocks": [],
    }
    monkeypatch.setattr(im_alerts_service, "workshop_display", lambda db_, tenant_id_: fake_display)

    digest = im_alerts_service.build_daily_digest(db, tenant.id)
    content = digest["message"]["markdown_v2"]["content"]
    assert "| 昨日合格 | 0 |" in content
    assert "暂无重点跟进订单" in content


# ---------------------------------------------------------------------------
# post_json（mock urlopen）
# ---------------------------------------------------------------------------


def test_post_json_success(monkeypatch):
    monkeypatch.setattr(
        im_alerts_service.urllib.request,
        "urlopen",
        lambda req, timeout=5: _FakeResponse(200, b'{"errcode":0}'),
    )
    result = im_alerts_service.post_json("https://example.com/hook", {"msgtype": "text"})
    assert result["ok"] is True
    assert result["status"] == 200
    assert result["error"] is None


def test_post_json_http_error(monkeypatch):
    import io
    import urllib.error

    def _raise(req, timeout=5):
        raise urllib.error.HTTPError(
            "https://example.com/hook", 404, "Not Found", hdrs=None, fp=io.BytesIO(b"no route")
        )

    monkeypatch.setattr(im_alerts_service.urllib.request, "urlopen", _raise)
    result = im_alerts_service.post_json("https://example.com/hook", {"msgtype": "text"})
    assert result["ok"] is False
    assert result["status"] == 404


def test_post_json_network_error_never_raises(monkeypatch):
    def _raise(req, timeout=5):
        raise OSError("network unreachable")

    monkeypatch.setattr(im_alerts_service.urllib.request, "urlopen", _raise)
    result = im_alerts_service.post_json("https://example.com/hook", {"msgtype": "text"})
    assert result["ok"] is False
    assert "network unreachable" in result["error"]


# ---------------------------------------------------------------------------
# send_test：试发（忽略 enabled，但必须有 webhook_url）
# ---------------------------------------------------------------------------


def test_send_test_requires_webhook_url(db):
    tenant = _seed_tenant(db)
    with pytest.raises(ValueError):
        im_alerts_service.send_test(db, tenant.id, kind="alert")


def test_send_test_posts_to_configured_webhook(db, monkeypatch):
    tenant = _seed_tenant(db)
    im_alerts_service.save_im_alerts_patch(
        db, tenant.id, {"webhook_url": "https://example.com/hook", "enabled": False}
    )

    captured = {}

    def _fake_post_json(url, payload, **kwargs):
        captured["url"] = url
        captured["payload"] = payload
        return {"ok": True, "status": 200, "body": "", "error": None}

    monkeypatch.setattr(im_alerts_service, "post_json", _fake_post_json)

    result = im_alerts_service.send_test(db, tenant.id, kind="alert")
    assert result["result"]["ok"] is True
    assert captured["url"] == "https://example.com/hook"
    assert captured["payload"]["msgtype"] == "markdown"


def test_send_test_webhook_override_does_not_require_saved_config(db, monkeypatch):
    tenant = _seed_tenant(db)
    captured = {}
    monkeypatch.setattr(
        im_alerts_service,
        "post_json",
        lambda url, payload, **kw: captured.update(url=url) or {"ok": True, "status": 200, "body": "", "error": None},
    )
    result = im_alerts_service.send_test(
        db, tenant.id, kind="digest", webhook_url_override="https://temp.example.com/hook"
    )
    assert captured["url"] == "https://temp.example.com/hook"
    assert result["kind"] == "digest"


# ---------------------------------------------------------------------------
# send_*_if_enabled：预留给未来调度器，enabled=false 时不应发送
# ---------------------------------------------------------------------------


def test_send_alert_if_enabled_skips_when_disabled(db, monkeypatch):
    tenant = _seed_tenant(db)
    im_alerts_service.save_im_alerts_patch(
        db, tenant.id, {"webhook_url": "https://example.com/hook", "enabled": False}
    )
    called = []
    monkeypatch.setattr(im_alerts_service, "post_json", lambda *a, **k: called.append(1))
    assert im_alerts_service.send_alert_if_enabled(db, tenant.id) is None
    assert not called


def test_send_alert_if_enabled_sends_when_configured(db, monkeypatch):
    tenant = _seed_tenant(db)
    _seed_at_risk_order(db, tenant)
    im_alerts_service.save_im_alerts_patch(
        db,
        tenant.id,
        {"webhook_url": "https://example.com/hook", "enabled": True, "events": ["delivery_risk"]},
    )
    called = []
    monkeypatch.setattr(
        im_alerts_service,
        "post_json",
        lambda url, payload, **kw: called.append((url, payload)) or {"ok": True, "status": 200, "body": "", "error": None},
    )
    result = im_alerts_service.send_alert_if_enabled(db, tenant.id)
    assert result is not None
    assert called and called[0][0] == "https://example.com/hook"
