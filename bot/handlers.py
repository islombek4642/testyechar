"""Telegram handlers: /start, mode selection, file processing, TXT/DOCX export."""
from __future__ import annotations

import asyncio
import html
import time
from uuid import uuid4
from dataclasses import dataclass
from typing import List, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.ai.docx_exporter import AIDocxExporter
from app.ai.exporter import AIExporter
from app.ai.merger import MergeResult
from app.ai.pipeline import AIResolverPipeline
from app.config import settings as core_settings
from app.core.pipeline import ParsingPipeline
from app.exporter import JSONExporter
from app.models.question import ParsedQuestion
from app.parser import FormatType
from app.utils.logger import get_logger

from bot.allowed_users import AllowedUsersStore
from bot.classic_txt import to_classic_txt
from bot.config import BotSettings
from bot.formatters import format_parser_summary, format_resolver_summary
from bot.states import Mode

log = get_logger(__name__)
router = Router()

BTN_PARSER = "📝 Parser"
BTN_RESOLVER = "🤖 AI Resolver"
BTN_CANCEL = "❌ Bekor qilish"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_MANAGE_USERS = "👥 Foydalanuvchilar"

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_PARSER), KeyboardButton(text=BTN_RESOLVER)],
        [KeyboardButton(text=BTN_SETTINGS)],
    ],
    resize_keyboard=True,
)

CANCEL_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
)

PARSER_EXTS = {"pdf", "docx", "doc", "xlsx", "txt"}
RESOLVER_EXTS = {"txt", "docx"}
MAX_FILE_BYTES = 20 * 1024 * 1024  # Telegram bot download limit

# AI Resolver uchun tanlash mumkin bo'lgan modellar (ko'rsatiladigan tartibda).
MODEL_OPTIONS = {
    "claude-opus-4-8": "Claude Opus 4.8",
    "claude-opus-4-7": "Claude Opus 4.7",
    "claude-sonnet-5": "Claude Sonnet 5",
}

_LABEL_TO_MODEL = {label: model_id for model_id, label in MODEL_OPTIONS.items()}


def settings_keyboard(selected_model: str, is_admin: bool) -> ReplyKeyboardMarkup:
    rows = []
    for model_id, label in MODEL_OPTIONS.items():
        text = f"✅ {label}" if model_id == selected_model else label
        rows.append([KeyboardButton(text=text)])
    if is_admin:
        rows.append([KeyboardButton(text=BTN_MANAGE_USERS)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@dataclass
class CachedResult:
    kind: str  # "parser" | "resolver"
    base_name: str  # original filename without extension
    questions: Optional[List[ParsedQuestion]] = None  # parser
    merge: Optional[MergeResult] = None  # resolver


_results: dict[int, CachedResult] = {}

# Har bir chat uchun tanlangan AI Resolver modeli (tanlanmagan bo'lsa
# bot_settings.model standart qiymat sifatida ishlatiladi).
_user_model: dict[int, str] = {}

# Sozlamalar xabarining message_id'si — model tanlanganda shu xabarni
# tahrirlab, tanlov tasdiqlanganini ko'rsatish uchun.
_settings_msg_id: dict[int, int] = {}

# Hozir Parser yoki Resolver jarayoni ishlab turgan chatlar — qiymat
# foydalanuvchiga ko'rsatiladigan jarayon nomi ("Parser" / "AI Resolver").
# Jarayon tugamaguncha o'sha chatda boshqa hech qanday amal qabul
# qilinmaydi (BusyGuardMiddleware orqali).
_busy_chats: dict[int, str] = {}


def is_chat_busy(chat_id: int) -> Optional[str]:
    return _busy_chats.get(chat_id)


def file_ext(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def export_keyboard(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="📄 TXT", callback_data=f"exp:{kind}:txt"),
            InlineKeyboardButton(text="📖 DOCX", callback_data=f"exp:{kind}:docx"),
        ]]
    )


def get_selected_model(chat_id: int, default: str) -> str:
    return _user_model.get(chat_id, default)


def settings_text(selected: str) -> str:
    label = MODEL_OPTIONS.get(selected, selected)
    return (
        "⚙️ <b>Sozlamalar</b>\n\n"
        f"AI Resolver uchun model — joriy: <b>{label}</b>\n"
        "Quyidagilardan birini tanlang:"
    )


def manage_users_text(ids: List[int]) -> str:
    if ids:
        body = "\n".join(f"🆔 <code>{uid}</code>" for uid in ids)
    else:
        body = "Hozircha qo'shimcha ruxsat etilgan foydalanuvchi yo'q."
    return (
        "👥 <b>Ruxsat etilgan foydalanuvchilar</b>\n\n"
        f"{body}\n\n"
        "(admin doim ruxsatli, ro'yxatga kiritilmaydi)"
    )


def manage_users_keyboard(ids: List[int]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"❌ {uid}", callback_data=f"deluser:{uid}")] for uid in ids
    ]
    rows.append([InlineKeyboardButton(text="➕ Yangi qo'shish", callback_data="adduser:prompt")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="users:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_status_and_restore_menu(message: Message, status_text: str) -> Message:
    """Restore MAIN_KB immediately, then send the freely-editable status message.

    Telegram never lets you edit a message that was sent with a
    ReplyKeyboardMarkup, so the keyboard-restoring message can't be the
    same one we keep editing for progress/results — it has to be a
    separate message. An earlier version tried to hide that extra
    message by deleting it immediately after sending, but deleting a
    message right after it sets a new reply keyboard is not reliable —
    on some clients the keyboard change itself gets lost. Send it
    without deleting: one extra short-lived-looking line in the chat,
    but the keyboard reliably comes back.
    """
    await message.answer("📥 Fayl qabul qilindi.", reply_markup=MAIN_KB)
    return await message.answer(status_text)


# ── /start and mode selection ───────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Assalomu alaykum! Rejimni tanlang:\n\n"
        f"{BTN_PARSER} — test faylini tahlil qilish (PDF, DOCX, DOC, XLSX, TXT)\n"
        f"{BTN_RESOLVER} — savollarga Claude AI yordamida javob topish (TXT, DOCX)",
        reply_markup=MAIN_KB,
    )


@router.message(F.text == BTN_PARSER)
async def choose_parser(message: Message, state: FSMContext) -> None:
    await state.set_state(Mode.parser_waiting)
    await message.answer(
        "📝 Parser rejimi.\nTest faylini yuboring (PDF, DOCX, DOC, XLSX yoki TXT, 20 MB gacha).",
        reply_markup=CANCEL_KB,
    )


@router.message(F.text == BTN_RESOLVER)
async def choose_resolver(message: Message, state: FSMContext) -> None:
    await state.set_state(Mode.resolver_waiting)
    await message.answer(
        "🤖 AI Resolver rejimi.\nSavollar faylini yuboring "
        "(TXT yoki DOCX, klassik `? = +` format, 20 MB gacha).",
        reply_markup=CANCEL_KB,
    )


@router.message(Mode.parser_waiting, F.text == BTN_CANCEL)
@router.message(Mode.resolver_waiting, F.text == BTN_CANCEL)
@router.message(Mode.adding_user, F.text == BTN_CANCEL)
async def cancel_waiting(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=MAIN_KB)


@router.message(F.text == BTN_SETTINGS)
async def show_settings(message: Message, state: FSMContext, bot_settings: BotSettings) -> None:
    await state.set_state(Mode.choosing_model)
    selected = get_selected_model(message.chat.id, bot_settings.model)
    is_admin = message.from_user.id == bot_settings.admin_id
    sent = await message.answer(
        settings_text(selected), reply_markup=settings_keyboard(selected, is_admin)
    )
    _settings_msg_id[message.chat.id] = sent.message_id


@router.message(Mode.choosing_model, F.text == BTN_MANAGE_USERS)
async def show_manage_users(
    message: Message,
    state: FSMContext,
    bot_settings: BotSettings,
    allowed_users: AllowedUsersStore,
) -> None:
    if message.from_user.id != bot_settings.admin_id:
        await state.clear()
        await message.answer("⛔ Bu bo'lim faqat admin uchun.", reply_markup=MAIN_KB)
        return
    await state.set_state(Mode.managing_users)
    ids = allowed_users.list_ids()
    await message.answer(manage_users_text(ids), reply_markup=manage_users_keyboard(ids))


@router.message(Mode.choosing_model)
async def handle_model_choice(message: Message, state: FSMContext, bot: Bot, bot_settings: BotSettings) -> None:
    text = (message.text or "").removeprefix("✅ ")
    model_id = _LABEL_TO_MODEL.get(text)
    if model_id is None:
        selected = get_selected_model(message.chat.id, bot_settings.model)
        is_admin = message.from_user.id == bot_settings.admin_id
        await message.answer(
            "Iltimos, quyidagi tugmalardan birini tanlang.",
            reply_markup=settings_keyboard(selected, is_admin),
        )
        return

    _user_model[message.chat.id] = model_id
    await state.clear()

    msg_id = _settings_msg_id.pop(message.chat.id, None)
    if msg_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text=f"✅ Model tanlandi: <b>{MODEL_OPTIONS[model_id]}</b>",
            )
        except TelegramBadRequest:
            pass  # eski xabar tahrirlanmadi — foydalanuvchiga baribir tasdiq ko'rinadi

    await message.answer("🏠 Bosh menyu", reply_markup=MAIN_KB)


# ── Foydalanuvchilarni boshqarish (faqat admin) ─────────────────────────────

@router.callback_query(F.data == "adduser:prompt")
async def prompt_add_user(cb: CallbackQuery, state: FSMContext, bot_settings: BotSettings) -> None:
    if cb.from_user.id != bot_settings.admin_id:
        await cb.answer("⛔ Ruxsat yo'q.", show_alert=True)
        return
    if cb.message is None:
        await cb.answer("Xabar eskirgan.", show_alert=True)
        return
    await state.set_state(Mode.adding_user)
    await cb.message.answer(
        "Yangi foydalanuvchining Telegram ID raqamini yuboring "
        "(masalan, @userinfobot orqali oling):",
        reply_markup=CANCEL_KB,
    )
    await cb.answer()


@router.message(Mode.adding_user)
async def handle_add_user_text(
    message: Message, state: FSMContext, allowed_users: AllowedUsersStore
) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(
            "❌ Iltimos, faqat raqamlardan iborat Telegram ID yuboring.", reply_markup=CANCEL_KB
        )
        return

    user_id = int(text)
    added = allowed_users.add(user_id)
    await state.clear()
    if added:
        await message.answer(
            f"✅ {user_id} ruxsat etilganlar ro'yxatiga qo'shildi.", reply_markup=MAIN_KB
        )
    else:
        await message.answer(
            f"ℹ️ {user_id} allaqachon ruxsat etilgan (yoki u admin).", reply_markup=MAIN_KB
        )


@router.callback_query(F.data.startswith("deluser:"))
async def handle_remove_user(
    cb: CallbackQuery, bot_settings: BotSettings, allowed_users: AllowedUsersStore
) -> None:
    if cb.from_user.id != bot_settings.admin_id:
        await cb.answer("⛔ Ruxsat yo'q.", show_alert=True)
        return
    if cb.message is None:
        await cb.answer("Xabar eskirgan.", show_alert=True)
        return
    try:
        user_id = int(cb.data.split(":", 1)[1])
    except ValueError:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    allowed_users.remove(user_id)
    ids = allowed_users.list_ids()
    try:
        await cb.message.edit_text(manage_users_text(ids), reply_markup=manage_users_keyboard(ids))
    except TelegramBadRequest:
        pass
    await cb.answer(f"✅ {user_id} o'chirildi")


@router.callback_query(F.data == "users:back")
async def handle_users_back(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if cb.message is not None:
        # Bu xabarni keyin tahrirlash shart emas, shuning uchun
        # send_status_and_restore_menu'dagi tashuvchi-xabar-yuborib-o'chirish
        # hiylasi kerak emas — to'g'ridan-to'g'ri MAIN_KB bilan yuboriladi
        # (ba'zi Telegram klientlarida xabarni zudlik bilan o'chirish
        # klaviatura o'zgarishini ba'zan bekor qilib qo'yishi mumkin edi).
        await cb.message.answer("🏠 Bosh menyu", reply_markup=MAIN_KB)
    await cb.answer()


# ── Parser flow ─────────────────────────────────────────────────────────────

@router.message(Mode.parser_waiting, F.document)
async def handle_parser_file(message: Message, state: FSMContext, bot: Bot) -> None:
    doc = message.document
    ext = file_ext(doc.file_name)
    if ext not in PARSER_EXTS:
        await message.answer(
            "❌ Bu fayl turi qo'llab-quvvatlanmaydi.\n"
            "Ruxsat etilgan: PDF, DOCX, DOC, XLSX, TXT."
        )
        return
    if doc.file_size and doc.file_size > MAX_FILE_BYTES:
        await message.answer("❌ Fayl juda katta (20 MB dan oshmasligi kerak).")
        return

    _busy_chats[message.chat.id] = "Parser"
    try:
        status = await send_status_and_restore_menu(message, "⏳ Tahlil qilinmoqda…")
        tmp_dir = core_settings.data_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        # doc.file_name tashqaridan keladi — yo'l sifatida ishlatilmaydi,
        # faqat tekshirilgan kengaytma + tasodifiy nom bilan saqlanadi.
        path = tmp_dir / f"{message.chat.id}_{uuid4().hex}.{ext}"
        try:
            await bot.download(doc, destination=path)
            result = await asyncio.to_thread(ParsingPipeline().run, path, FormatType.AUTO)
        except Exception as exc:  # yuklab olish/pipeline xatosi botni yiqitmasligi kerak
            log.exception("Parser pipeline xatosi")
            await status.edit_text(f"❌ Tahlilda xato: {html.escape(str(exc))}")
            return
        finally:
            path.unlink(missing_ok=True)

        if not result.questions:
            await status.edit_text(
                "❌ Faylda savollar topilmadi. Fayl formati to'g'riligini tekshiring."
            )
            return

        extra = []
        if ext == "doc":
            extra.append(".doc fayl zaxira usulda o'qildi — sifat pastroq bo'lishi mumkin.")

        base = doc.file_name.rsplit(".", 1)[0]
        _results[message.chat.id] = CachedResult("parser", base, questions=result.questions)
        await status.edit_text(
            format_parser_summary(doc.file_name, result, extra_warnings=extra),
            reply_markup=export_keyboard("parser"),
        )
    finally:
        _busy_chats.pop(message.chat.id, None)


# ── Resolver flow ───────────────────────────────────────────────────────────

@router.message(Mode.resolver_waiting, F.document)
async def handle_resolver_file(
    message: Message, state: FSMContext, bot: Bot, bot_settings: BotSettings
) -> None:
    doc = message.document
    ext = file_ext(doc.file_name)
    if ext not in RESOLVER_EXTS:
        await message.answer("❌ Faqat TXT yoki DOCX fayl yuboring.")
        return
    if doc.file_size and doc.file_size > MAX_FILE_BYTES:
        await message.answer("❌ Fayl juda katta (20 MB dan oshmasligi kerak).")
        return
    if not bot_settings.anthropic_api_key:
        await message.answer("❌ Serverda ANTHROPIC_API_KEY sozlanmagan.")
        return

    buf = await bot.download(doc)  # BytesIO when destination is omitted
    content = buf.read()

    _busy_chats[message.chat.id] = "AI Resolver"
    try:
        status = await send_status_and_restore_menu(message, "🤖 Savollar Batch API'ga yuborilmoqda…")
        throttle = {"text": "", "t": 0.0}
        started = time.monotonic()

        async def progress(msg_text: str, frac: float) -> None:
            # O'tgan vaqt qatori har pollda o'zgaradi — foydalanuvchi bot
            # tirikligini ko'radi (Batch API hisoblagichlari oxirigacha 0 bo'lib turadi).
            elapsed = int(time.monotonic() - started)
            text = (
                f"🤖 {msg_text} ({frac * 100:.0f}%)\n"
                f"⏱ O'tgan vaqt: {elapsed // 60:02d}:{elapsed % 60:02d} — "
                f"Batch odatda 15-30 daqiqada tugaydi, kuting…"
            )
            now = time.monotonic()
            if text == throttle["text"] or now - throttle["t"] < 8.0:
                return
            throttle["text"], throttle["t"] = text, now
            try:
                await status.edit_text(text)
            except Exception:
                # Progress xabarini yangilash shunchaki kosmetik amal — tarmoq
                # uzilishi yoki Telegram xatosi tufayli bu yerda muvaffaqiyatsiz
                # bo'lish asosiy Batch kutish jarayonini (poll_until_complete)
                # to'xtatib qo'ymasligi kerak. Keng Exception ushlanadi, chunki
                # aynan shu sabab (tarmoq uzilishi TelegramBadRequest bo'lmagani
                # uchun) ilgari butun resolver ishini bekor qilib qo'ygan edi.
                log.warning("Progress xabarini yangilab bo'lmadi, davom etilmoqda", exc_info=True)

        selected_model = get_selected_model(message.chat.id, bot_settings.model)
        pipeline = AIResolverPipeline(
            api_key=bot_settings.anthropic_api_key,
            model=selected_model,
            use_batch=True,
        )
        try:
            merge, stats = await pipeline.run(content, file_type=ext, progress_callback=progress)
        except Exception as exc:
            log.exception("Resolver pipeline xatosi")
            await status.edit_text(f"❌ AI yechishda xato: {html.escape(str(exc))}")
            return

        base = doc.file_name.rsplit(".", 1)[0]
        _results[message.chat.id] = CachedResult("resolver", base, merge=merge)
        await status.edit_text(
            format_resolver_summary(doc.file_name, merge, stats),
            reply_markup=export_keyboard("resolver"),
        )
    finally:
        _busy_chats.pop(message.chat.id, None)


# ── Export buttons ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("exp:"))
async def handle_export(cb: CallbackQuery) -> None:
    _, kind, fmt = cb.data.split(":")
    if cb.message is None:
        await cb.answer("Xabar eskirgan — yangi fayl yuboring.", show_alert=True)
        return
    cached = _results.get(cb.message.chat.id)
    if cached is None or cached.kind != kind:
        await cb.answer("Natija topilmadi — yangi fayl yuboring.", show_alert=True)
        return

    try:
        if kind == "parser":
            if fmt == "txt":
                data = to_classic_txt(cached.questions).encode("utf-8")
                name = f"{cached.base_name}_questions.txt"
            else:
                data = JSONExporter().to_docx_bytes(cached.questions)
                name = f"{cached.base_name}_questions.docx"
        else:
            if fmt == "txt":
                data = AIExporter().to_txt_string(cached.merge.questions).encode("utf-8")
                name = f"{cached.base_name}_resolved.txt"
            else:
                name = f"{cached.base_name}_resolved.docx"
                data = AIDocxExporter().export(cached.merge, name)

        await cb.message.answer_document(BufferedInputFile(data, filename=name))
    except Exception:
        log.exception("Eksport xatosi")
        await cb.answer("❌ Eksportda xato yuz berdi.", show_alert=True)
        return

    await cb.answer()


# ── Fallbacks ───────────────────────────────────────────────────────────────

@router.message(Mode.parser_waiting)
@router.message(Mode.resolver_waiting)
async def waiting_but_not_document(message: Message) -> None:
    await message.answer("📎 Iltimos, fayl (hujjat) sifatida yuboring.")


@router.message()
async def no_mode_selected(message: Message) -> None:
    await message.answer("Avval rejimni tanlang: 📝 Parser yoki 🤖 AI Resolver.", reply_markup=MAIN_KB)
