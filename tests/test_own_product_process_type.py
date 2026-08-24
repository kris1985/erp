from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.own_products import _ensure_process_by_name
from app.db import Base
from app.models import ProcessDefinition, ProcessType, Tenant
from app.schemas.api import OwnProductLaborIn


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_missing_process_type_preserves_existing_group_process():
    db = _session()
    try:
        tenant = Tenant(name="工序类型兼容测试")
        db.add(tenant)
        db.flush()
        process = ProcessDefinition(
            tenant_id=tenant.id,
            name="成型",
            code="FORMING",
            type=ProcessType.group,
        )
        db.add(process)
        db.commit()

        labor = OwnProductLaborIn(process_name="成型", unit_price=2.8)
        assert labor.process_type is None

        resolved = _ensure_process_by_name(
            db,
            tenant.id,
            labor.process_name,
            process_type=labor.process_type,
        )

        assert resolved.id == process.id
        assert resolved.type == ProcessType.group
    finally:
        db.close()


def test_new_process_without_process_type_defaults_to_personal():
    db = _session()
    try:
        tenant = Tenant(name="新工序默认类型测试")
        db.add(tenant)
        db.flush()

        process = _ensure_process_by_name(db, tenant.id, "包装")

        assert process.type == ProcessType.personal
    finally:
        db.close()
