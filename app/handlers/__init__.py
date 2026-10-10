from aiogram import Router

from app.handlers.barber import router as barber_router
from app.handlers.client import router as client_router
from app.handlers.common import router as common_router
from app.handlers.owner import router as owner_router
from app.handlers.payments import router as payments_router


def setup_routers() -> Router:
    main_router = Router()
    # Route in order of specificity
    main_router.include_router(payments_router)
    main_router.include_router(owner_router)
    main_router.include_router(barber_router)
    main_router.include_router(client_router)
    main_router.include_router(common_router)
    return main_router
