from fastapi import APIRouter

from app.api.v1 import auth, masters, ops, orders, styles

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(masters.router)
api_router.include_router(styles.router)
api_router.include_router(orders.router)
api_router.include_router(ops.router)
