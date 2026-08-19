"""工序段服务：默认段 seed（per-tenant 惰性）与段查询。

工序段重构 2.11/C2：默认段按租户**惰性 ensure**（首次用到时补），
不依赖全局启动 seed（多租户场景无租户上下文）；新租户正式入口为
初始化向导 /org/setup（18A），存量租户由迁移脚本回填（34.1）。
"""

from sqlalchemy import select

from app.db import Session
from app.models import ProcessSegment

# 默认工序段：(code, name, sort_order, is_optional)。铲皮为可选段（28.2 开关）。
DEFAULT_SEGMENTS: list[tuple[str, str, int, bool]] = [
    ("cut", "截断", 10, False),
    ("stitch", "针车", 20, False),
    ("forming", "成型", 30, False),
    ("packing", "包装", 40, False),
    ("skiving", "铲皮", 50, True),
]

# 部门名 → 段 code（34.3 名称映射用；未匹配留空）
DEPARTMENT_SEGMENT_MAP: dict[str, str] = {
    "截断": "cut",
    "裁断": "cut",
    "冲裁": "cut",
    "针车": "stitch",
    "车缝": "stitch",
    "成型": "forming",
    "包装": "packing",
    "铲皮": "skiving",
}

# 工序名 → 段 code（34.2 名称映射用；未匹配留 null，按 D18 未分段处理）
PROCESS_SEGMENT_MAP: dict[str, str] = {
    "裁断": "cut",
    "划料": "cut",
    "冲裁": "cut",
    "针车": "stitch",
    "车缝": "stitch",
    "合后跟": "stitch",
    "成型": "forming",
    "脱楦": "forming",
    "包装": "packing",
    "装箱": "packing",
    "铲皮": "skiving",
}


def ensure_default_segments(db: Session, tenant_id: int) -> int:
    """确保租户存在默认工序段（按 code 幂等，不覆盖已有）。返回新建条数。"""
    existing = {
        s.code
        for s in db.scalars(
            select(ProcessSegment).where(ProcessSegment.tenant_id == tenant_id)
        ).all()
    }
    created = 0
    for code, name, sort_order, is_optional in DEFAULT_SEGMENTS:
        if code in existing:
            continue
        db.add(
            ProcessSegment(
                tenant_id=tenant_id,
                name=name,
                code=code,
                sort_order=sort_order,
                is_active=True,
                is_optional=is_optional,
            )
        )
        created += 1
    if created:
        db.flush()
    return created


def list_segments(
    db: Session, tenant_id: int, *, include_inactive: bool = False
) -> list[ProcessSegment]:
    """租户工序段列表（按 sort_order 升序）。"""
    q = select(ProcessSegment).where(ProcessSegment.tenant_id == tenant_id)
    if not include_inactive:
        q = q.where(ProcessSegment.is_active.is_(True))
    return list(db.scalars(q.order_by(ProcessSegment.sort_order, ProcessSegment.id)).all())


def get_segment(db: Session, tenant_id: int, segment_id: int) -> ProcessSegment | None:
    seg = db.get(ProcessSegment, segment_id)
    if seg and seg.tenant_id == tenant_id:
        return seg
    return None


def segment_code_of_name(name: str) -> str | None:
    """部门/工序名 → 段 code（名称映射；未匹配返回 None）。"""
    if not name:
        return None
    return PROCESS_SEGMENT_MAP.get(name)
