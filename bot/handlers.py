"""Telegram handlers: /start, mode selection, file processing, DOCX export."""
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
from app.ai.docx_parser import AIRawQuestion
from app.ai.merger import MergeResult
from app.ai.pipeline import AIResolverPipeline
from app.config import settings as core_settings
from app.core.pipeline import ParsingPipeline
from app.exporter import JSONExporter
from app.models.question import ParsedQuestion, RawOption, RawQuestion
from app.parser import FormatType
from app.utils.logger import get_logger

from bot.allowed_users import AllowedUsersStore
from bot.config import BotSettings
from bot.formatters import format_parser_summary, format_resolver_summary
from bot.states import Mode

log = get_logger(__name__)
router = Router()

BTN_TEST = "📝 Test yuborish"
BTN_CANCEL = "❌ Bekor qilish"
BTN_SETTINGS = "⚙️ Sozlamalar"
BTN_MANAGE_USERS = "👥 Foydalanuvchilar"
BTN_ADD_USER = "➕ Yangi qo'shish"
BTN_BACK = "⬅️ Orqaga"

MAIN_KB_USER = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_TEST)]],
    resize_keyboard=True,
)

MAIN_KB_ADMIN = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_TEST)],
        [KeyboardButton(text=BTN_SETTINGS)],
    ],
    resize_keyboard=True,
)


def main_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    """⚙️ Sozlamalar faqat adminga ko'rinadi — u model tanlovini barcha
    foydalanuvchilar uchun global qilib belgilaydi."""
    return MAIN_KB_ADMIN if is_admin else MAIN_KB_USER


CANCEL_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
)

PARSER_EXTS = {"pdf", "docx", "doc", "xlsx", "txt"}
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

# Admin tanlagan AI Resolver modeli — GLOBAL, barcha foydalanuvchilar
# uchun bir xil (tanlanmagan bo'lsa bot_settings.model standart qiymat
# sifatida ishlatiladi).
_active_model: Optional[str] = None

# Sozlamalar xabarining message_id'si — model tanlanganda shu xabarni
# tahrirlab, tanlov tasdiqlanganini ko'rsatish uchun.
_settings_msg_id: dict[int, int] = {}

# Hozir tahlil yoki AI Resolver jarayoni ishlab turgan chatlar — qiymat
# foydalanuvchiga ko'rsatiladigan jarayon nomi ("Tahlil" / "AI Resolver").
# Jarayon tugamaguncha o'sha chatda boshqa hech qanday amal qabul
# qilinmaydi (BusyGuardMiddleware orqali).
_busy_chats: dict[int, str] = {}


def is_chat_busy(chat_id: int) -> Optional[str]:
    return _busy_chats.get(chat_id)


def file_ext(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def build_ai_raw_questions(questions: List[ParsedQuestion]) -> List[AIRawQuestion]:
    """Bridge Parser's ParsedQuestion list into AIResolverPipeline's own
    AIRawQuestion format for resolve_raw_questions() — unlike routing
    through to_classic_txt() (text-only), this reads each question's first
    extracted image straight off disk so it survives into the AI request.
    An already-marked correct option (q.c != -1) becomes is_correct=True,
    so the resolver's own resolved/unresolved split still skips it.
    """
    raw_ai_qs: List[AIRawQuestion] = []
    for q in questions:
        options = [
            RawOption(text=opt, is_correct=(idx == q.c)) for idx, opt in enumerate(q.o)
        ]
        raw_question = RawQuestion(question_text=q.q, options=options)
        image_bytes = None
        if q.img:
            img_path = core_settings.output_dir / q.img[0]
            if img_path.exists():
                image_bytes = img_path.read_bytes()
        raw_ai_qs.append(AIRawQuestion(question=raw_question, image=image_bytes))
    return raw_ai_qs


def export_keyboard(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📖 DOCX", callback_data=f"exp:{kind}")]]
    )


def parser_result_keyboard(has_unresolved: bool) -> InlineKeyboardMarkup:
    """Tahlil natijasi tugmalari: DOCX yuklash har doim bepul va mavjud;
    AI bilan yechish tugmasi faqat javobsiz savol bo'lsa ko'rinadi (pullik)."""
    rows = [[InlineKeyboardButton(text="📖 DOCX", callback_data="exp:parser")]]
    if has_unresolved:
        rows.append(
            [InlineKeyboardButton(text="🤖 To'g'ri javobni aniqlash", callback_data="resolve:ai")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_active_model(default: str) -> str:
    return _active_model or default


def set_active_model(model_id: str) -> None:
    global _active_model
    _active_model = model_id


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


def manage_users_keyboard(ids: List[int]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=f"❌ {uid}")] for uid in ids]
    rows.append([KeyboardButton(text=BTN_ADD_USER)])
    rows.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


async def send_status_and_restore_menu(
    message: Message, status_text: str, menu_kb: ReplyKeyboardMarkup
) -> Message:
    """Restore the main menu immediately, then send the freely-editable status message.

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
    await message.answer("📥 Fayl qabul qilindi.", reply_markup=menu_kb)
    return await message.answer(status_text)


# ── /start and mode selection ───────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot_settings: BotSettings) -> None:
    await state.clear()
    is_admin = message.from_user.id == bot_settings.admin_id
    await message.answer(
        "Assalomu alaykum!\n\n"
        f"{BTN_TEST} — test faylini yuboring (PDF, DOCX, DOC, XLSX, TXT). "
        "Fayl tahlil qilinadi va tartibli DOCX shaklida yuklab olasiz. "
        "Agar javobi belgilanmagan savollar bo'lsa, ularni Claude AI "
        "yordamida yechish tugmasi ham chiqadi.",
        reply_markup=main_keyboard(is_admin),
    )


@router.message(F.text == BTN_TEST)
async def choose_test(message: Message, state: FSMContext) -> None:
    await state.set_state(Mode.test_waiting)
    await message.answer(
        "📝 Test faylini yuboring (PDF, DOCX, DOC, XLSX yoki TXT, 20 MB gacha).",
        reply_markup=CANCEL_KB,
    )


@router.message(Mode.test_waiting, F.text == BTN_CANCEL)
@router.message(Mode.adding_user, F.text == BTN_CANCEL)
async def cancel_waiting(message: Message, state: FSMContext, bot_settings: BotSettings) -> None:
    await state.clear()
    is_admin = message.from_user.id == bot_settings.admin_id
    await message.answer("❌ Bekor qilindi.", reply_markup=main_keyboard(is_admin))


@router.message(F.text == BTN_SETTINGS)
async def show_settings(message: Message, state: FSMContext, bot_settings: BotSettings) -> None:
    if message.from_user.id != bot_settings.admin_id:
        # Tugma oddiy foydalanuvchiga ko'rinmaydi, lekin matnni qo'lda
        # yozib yuborishi mumkin — shuning uchun bu yerda ham tekshiramiz.
        await message.answer("⛔ Bu bo'lim faqat admin uchun.", reply_markup=main_keyboard(False))
        return
    await state.set_state(Mode.choosing_model)
    selected = get_active_model(bot_settings.model)
    sent = await message.answer(
        settings_text(selected), reply_markup=settings_keyboard(selected, is_admin=True)
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
        await message.answer("⛔ Bu bo'lim faqat admin uchun.", reply_markup=main_keyboard(False))
        return
    await state.set_state(Mode.managing_users)
    ids = allowed_users.list_ids()
    await message.answer(manage_users_text(ids), reply_markup=manage_users_keyboard(ids))


@router.message(Mode.choosing_model)
async def handle_model_choice(message: Message, state: FSMContext, bot: Bot, bot_settings: BotSettings) -> None:
    text = (message.text or "").removeprefix("✅ ")
    model_id = _LABEL_TO_MODEL.get(text)
    if model_id is None:
        selected = get_active_model(bot_settings.model)
        await message.answer(
            "Iltimos, quyidagi tugmalardan birini tanlang.",
            reply_markup=settings_keyboard(selected, is_admin=True),
        )
        return

    set_active_model(model_id)
    await state.clear()

    msg_id = _settings_msg_id.pop(message.chat.id, None)
    if msg_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=msg_id,
                text=(
                    f"✅ Model tanlandi: <b>{MODEL_OPTIONS[model_id]}</b>\n"
                    "(barcha foydalanuvchilar uchun amal qiladi)"
                ),
            )
        except TelegramBadRequest:
            pass  # eski xabar tahrirlanmadi — foydalanuvchiga baribir tasdiq ko'rinadi

    await message.answer("🏠 Bosh menyu", reply_markup=main_keyboard(True))


# ── Foydalanuvchilarni boshqarish (faqat admin) ─────────────────────────────
# Mode.managing_users faqat show_manage_users orqali kirish mumkin, u allaqachon
# admin-only tekshiruvdan o'tkazadi — shuning uchun quyidagi handlerlar buni
# qayta tekshirmaydi (handle_model_choice bilan bir xil naqsh).

@router.message(Mode.managing_users, F.text == BTN_ADD_USER)
async def prompt_add_user(message: Message, state: FSMContext) -> None:
    await state.set_state(Mode.adding_user)
    await message.answer(
        "Yangi foydalanuvchining Telegram ID raqamini yuboring "
        "(masalan, @userinfobot orqali oling):",
        reply_markup=CANCEL_KB,
    )


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
    # Bu holatga faqat admin (prompt_add_user orqali) kirishi mumkin.
    if added:
        await message.answer(
            f"✅ {user_id} ruxsat etilganlar ro'yxatiga qo'shildi.", reply_markup=main_keyboard(True)
        )
    else:
        await message.answer(
            f"ℹ️ {user_id} allaqachon ruxsat etilgan (yoki u admin).", reply_markup=main_keyboard(True)
        )


@router.message(Mode.managing_users, F.text.startswith("❌ "))
async def handle_remove_user(message: Message, allowed_users: AllowedUsersStore) -> None:
    text = message.text.removeprefix("❌ ").strip()
    if not text.isdigit():
        return
    user_id = int(text)
    allowed_users.remove(user_id)
    ids = allowed_users.list_ids()
    await message.answer(
        f"✅ {user_id} o'chirildi.\n\n{manage_users_text(ids)}",
        reply_markup=manage_users_keyboard(ids),
    )


@router.message(Mode.managing_users, F.text == BTN_BACK)
async def handle_users_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🏠 Bosh menyu", reply_markup=main_keyboard(True))


@router.message(Mode.managing_users)
async def managing_users_fallback(message: Message, allowed_users: AllowedUsersStore) -> None:
    ids = allowed_users.list_ids()
    await message.answer(
        "Iltimos, quyidagi tugmalardan birini tanlang.",
        reply_markup=manage_users_keyboard(ids),
    )


# ── Test flow: parse, then optionally AI-resolve on the same result ────────

@router.message(Mode.test_waiting, F.document)
async def handle_test_file(
    message: Message, state: FSMContext, bot: Bot, bot_settings: BotSettings
) -> None:
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

    is_admin = message.from_user.id == bot_settings.admin_id
    _busy_chats[message.chat.id] = "Tahlil"
    try:
        status = await send_status_and_restore_menu(
            message, "⏳ Tahlil qilinmoqda…", main_keyboard(is_admin)
        )
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

        base = doc.file_name.rsplit(".", 1)[0]
        _results[message.chat.id] = CachedResult("parser", base, questions=result.questions)
        has_unresolved = any(q.c == -1 for q in result.questions)
        await status.edit_text(
            format_parser_summary(doc.file_name, result),
            reply_markup=parser_result_keyboard(has_unresolved),
        )
    finally:
        _busy_chats.pop(message.chat.id, None)


# ── AI-resolve: triggered by the "🤖 To'g'ri javobni aniqlash" button on an ──
# ── already-parsed result, using the cached questions — no re-upload needed ──

@router.callback_query(F.data == "resolve:ai")
async def handle_resolve_ai(cb: CallbackQuery, bot_settings: BotSettings) -> None:
    if cb.message is None:
        await cb.answer("Xabar eskirgan — yangi fayl yuboring.", show_alert=True)
        return
    chat_id = cb.message.chat.id
    cached = _results.get(chat_id)
    if cached is None or cached.kind != "parser" or not cached.questions:
        await cb.answer("Natija topilmadi — yangi fayl yuboring.", show_alert=True)
        return
    if not bot_settings.anthropic_api_key:
        await cb.answer("❌ Serverda ANTHROPIC_API_KEY sozlanmagan.", show_alert=True)
        return

    await cb.answer()
    is_admin = cb.from_user.id == bot_settings.admin_id
    # Parser natijasidagi savollarni AI Resolver'ning o'z AIRawQuestion
    # formatiga aylantiramiz (to_classic_txt orqali emas — u faqat matn,
    # rasmni saqlamaydi). Allaqachon javobi belgilangan savollar
    # is_correct=True bilan chiqadi va Resolver ularni qayta yubormaydi
    # (faqat `c == -1` bo'lganlar, ya'ni belgilanmaganlar, AI ga yuboriladi).
    raw_ai_qs = build_ai_raw_questions(cached.questions)
    base = cached.base_name

    _busy_chats[chat_id] = "AI Resolver"
    try:
        waiting_text = "⏳ Javoblar aniqlanmoqda, iltimos kuting…\nBu bir necha daqiqadan yarim soatgacha davom etishi mumkin."
        status = await send_status_and_restore_menu(
            cb.message, waiting_text, main_keyboard(is_admin)
        )
        throttle = {"t": 0.0}
        started = time.monotonic()

        async def progress(msg_text: str, frac: float) -> None:
            # Foydalanuvchiga faqat o'tgan vaqt ko'rsatiladi — Batch/holat
            # tafsilotlari (msg_text, frac) unga kerak emas, faqat bot
            # tirikligini bilishi kifoya.
            now = time.monotonic()
            if now - throttle["t"] < 8.0:
                return
            throttle["t"] = now
            elapsed = int(now - started)
            text = f"{waiting_text}\n⏱ O'tgan vaqt: {elapsed // 60:02d}:{elapsed % 60:02d}"
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

        selected_model = get_active_model(bot_settings.model)
        pipeline = AIResolverPipeline(
            api_key=bot_settings.anthropic_api_key,
            model=selected_model,
            use_batch=True,
        )
        try:
            merge, stats = await pipeline.resolve_raw_questions(raw_ai_qs, progress_callback=progress)
        except Exception as exc:
            log.exception("Resolver pipeline xatosi")
            await status.edit_text(f"❌ AI yechishda xato: {html.escape(str(exc))}")
            return

        _results[chat_id] = CachedResult("resolver", base, merge=merge)
        await status.edit_text(
            format_resolver_summary(base, merge, stats),
            reply_markup=export_keyboard("resolver"),
        )
    finally:
        _busy_chats.pop(chat_id, None)


# ── Export buttons ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("exp:"))
async def handle_export(cb: CallbackQuery) -> None:
    _, kind = cb.data.split(":")
    if cb.message is None:
        await cb.answer("Xabar eskirgan — yangi fayl yuboring.", show_alert=True)
        return
    cached = _results.get(cb.message.chat.id)
    if cached is None or cached.kind != kind:
        await cb.answer("Natija topilmadi — yangi fayl yuboring.", show_alert=True)
        return

    try:
        if kind == "parser":
            data = JSONExporter().to_docx_bytes(cached.questions)
            name = f"{cached.base_name}_questions.docx"
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

@router.message(Mode.test_waiting)
async def waiting_but_not_document(message: Message) -> None:
    await message.answer("📎 Iltimos, fayl (hujjat) sifatida yuboring.")


@router.message()
async def no_mode_selected(message: Message, bot_settings: BotSettings) -> None:
    is_admin = message.from_user.id == bot_settings.admin_id
    await message.answer(
        f"Avval {BTN_TEST} tugmasini bosing.", reply_markup=main_keyboard(is_admin)
    )
