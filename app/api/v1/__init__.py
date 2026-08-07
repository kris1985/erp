from fastapi import APIRouter

from app.api.v1 import (
    auth,
    inventory_settings,
    masters,
    ops,
    orders,
    own_products,
    partners,
    rbac,
    reporting_settings,
    sales_orders,
    schedule,
    stations,
    supplier_products,
    supply_chain,
    teams,
    trace,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(rbac.router)
api_router.include_router(masters.router)
api_router.include_router(partners.router)
api_router.include_router(orders.router)
api_router.include_router(sales_orders.router)
api_router.include_router(schedule.router)
api_router.include_router(stations.router)
api_router.include_router(supplier_products.router)
api_router.include_router(own_products.router)
api_router.include_router(ops.router)
api_router.include_router(trace.router)
api_router.include_router(supply_chain.router)
api_router.include_router(teams.router)
api_router.include_router(inventory_settings.router)
api_router.include_router(reporting_settings.router)
