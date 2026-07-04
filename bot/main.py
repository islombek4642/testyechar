"""Bot entry point: wiring, middleware, polling."""
from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ErrorEvent

from app.config import settings as core_settings
from app.utils.logger import get_logger

from bot.allowed_users import AllowedUsersStore
from bot.config import load_settings
from bot.handlers import router
from bot.middleware import AccessMiddleware

log = get_logger(__name__)


async def main() -> None:
    settings = load_settings()
    allowed_users = AllowedUsersStore(
        admin_id=settings.admin_id,
        path=core_settings.data_dir / "allowed_users.json",
        seed=settings.allowed_users,
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.set_my_commands(
        [BotCommand(command="start", description="Botni ishga tushirish / bosh menyu")]
    )
    dp = Dispatcher(bot_settings=settings, allowed_users=allowed_users)

    dp.message.outer_middleware(AccessMiddleware(allowed_users))
    dp.callback_query.outer_middleware(AccessMiddleware(allowed_users))
    dp.include_router(router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("Handler xatosi: %s", event.exception)
        return True  # mark as handled so polling continues

    log.info("Bot polling boshlandi (model: %s)", settings.model)
    await dp.start_polling(bot)
