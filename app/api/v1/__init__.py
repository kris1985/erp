from fastapi import APIRouter

from app.api.v1 import (
    employees as _employees_module,
    auth,
    departments,
    employees,
    executions,
    fg,
    im_alerts,
    inventory_settings,
    masters,
    mcp_keys,
    ops,
    orders,
    own_products,
    org_settings,
    packing,
    production_lines,
    merge_batches,
    partners,
    rbac,
    reporting_settings,
    sales_orders,
    schedule,
    shop_floor_settings,
    stations,
    supplier_products,
    supply_chain,
    teams,
    trace,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(employees.router)
api_router.include_router(_employees_module._workers_router)
api_router.include_router(departments.router)
api_router.include_router(rbac.router)
api_router.include_router(masters.router)
api_router.include_router(partners.router)
api_router.include_router(production_lines.router)
api_router.include_router(orders.router)
api_router.include_router(sales_orders.router)
api_router.include_router(executions.router)
api_router.include_router(fg.router)
api_router.include_router(schedule.router)
api_router.include_router(stations.router)
api_router.include_router(supplier_products.router)
api_router.include_router(own_products.router)
api_router.include_router(org_settings.router)
api_router.include_router(ops.router)
api_router.include_router(trace.router)
api_router.include_router(supply_chain.router)
api_router.include_router(packing.router)
api_router.include_router(merge_batches.router)
api_router.include_router(teams.router)
api_router.include_router(inventory_settings.router)
api_router.include_router(reporting_settings.router)
api_router.include_router(shop_floor_settings.router)
api_router.include_router(im_alerts.router)
api_router.include_router(mcp_keys.router)
