"""手机员工管理权限进入默认角色。"""

from app.permissions import all_permission_codes, default_permissions_for_role
from app.services.employee_feature_service import FEATURE_PERMISSION_CODES


def test_mobile_workers_permission_defaults():
    codes = set(all_permission_codes())
    assert "mobile.workers" in codes
    assert "mobile.workers.write" in codes
    assert FEATURE_PERMISSION_CODES["workers"] == "mobile.workers"
    assert FEATURE_PERMISSION_CODES["workers_write"] == "mobile.workers.write"

    manager = set(default_permissions_for_role("manager"))
    workshop = set(default_permissions_for_role("workshop"))
    finance = set(default_permissions_for_role("finance"))
    worker = set(default_permissions_for_role("worker"))
    assert {"mobile.workers", "mobile.workers.write"} <= manager
    assert {"mobile.workers", "mobile.workers.write"} <= workshop
    assert "mobile.workers" in finance
    assert "mobile.workers.write" not in finance
    assert "mobile.workers" not in worker
