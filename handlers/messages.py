# handlers/messages.py
# Обработчики сообщений — Reply-клавиатура + меню выбора моделей (inline),
# пагинация, смена system prompt, очистка истории, основной чат со стримингом.
from aiogram import F
from aiogram.types import ContentType

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
import urllib.parse
import math
import logging
import asyncio

from storage import get_user
from services.ollama_client import generate_stream, get_models

router = Router()

# Постоянная клавиатура внизу
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Модель"), KeyboardButton(text="🎛 Prompt")],
        [KeyboardButton(text="🧹 Очистить")],
    ],
    resize_keyboard=True,
)

PAGE_SIZE = 8  # сколько моделей на страницу


# /start
@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"Приветствую, ваше благородие! Я - Хьюберт бот, содержaщий в себе кучу нейросетей основаных на общении. Если вы чувтвуете себя одиноким, то моя цель скрасить ваше одиночество!",
        reply_markup=main_keyboard,
    )


# Reply-кнопка "📋 Модель"
@router.message(lambda m: m.text == "📋 Модель")
async def on_choose_model(message: types.Message):
    models = await get_models()
    if not models:
        await message.answer("⚠️ Не удалось получить список моделей. Проверь Ollama.")
        return

    keyboard = build_models_keyboard(models, page=0)
    await message.answer("Выбери модель:", reply_markup=keyboard)


# Конструктор inline-клавиатуры для страниц
def build_models_keyboard(models, page: int) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(len(models) / PAGE_SIZE))
    print(f"total_pages: {total_pages}")
    page = max(0, min(page, total_pages - 1))
    print(f"page: {page}")

    start = page * PAGE_SIZE
    print(f"start: {start}")
    end = start + PAGE_SIZE
    print(f"end: {end}")
    slice_models = models[start:end]
    print(f"slice_models: {slice_models}")

    rows = []
    for name in slice_models:
        encoded = urllib.parse.quote_plus(name)
        rows.append(
            [InlineKeyboardButton(text=name, callback_data=f"setmodel:{encoded}")]
        )

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=f"models_page:{page - 1}"
            )
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                text="Вперед ➡️", callback_data=f"models_page:{page + 1}"
            )
        )
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="Закрыть ❌", callback_data="models_close")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# Переход по страницам
@router.callback_query(lambda c: c.data and c.data.startswith("models_page:"))
async def on_models_page(callback: types.CallbackQuery):
    await callback.answer()
    try:
        page = int(callback.data.split(":", 1)[1])
    except Exception:
        page = 0

    models = await get_models()
    if not models:
        try:
            await callback.message.edit_text("⚠️ Не удалось получить список моделей.")
        except Exception:
            await callback.message.answer("⚠️ Не удалось получить список моделей.")
        return

    keyboard = build_models_keyboard(models, page=page)
    try:
        await callback.message.edit_text("Выбери модель:", reply_markup=keyboard)
    except Exception:
        await callback.message.answer("Выбери модель:", reply_markup=keyboard)


# Выбор модели
@router.callback_query(lambda c: c.data and c.data.startswith("setmodel:"))
async def on_set_model(callback: types.CallbackQuery):
    await callback.answer()
    try:
        encoded = callback.data.split(":", 1)[1]
        model_name = urllib.parse.unquote_plus(encoded)
    except Exception:
        try:
            await callback.message.edit_text("❌ Неправильное имя модели.")
        except Exception:
            await callback.message.answer("❌ Неправильное имя модели.")
        return

    user = get_user(callback.from_user.id)
    user["model"] = model_name

    try:
        await callback.message.edit_text(f"✅ Модель изменена на: {model_name}")
    except Exception:
        await callback.message.answer(f"✅ Модель изменена на: {model_name}")


# Закрыть меню моделей
@router.callback_query(lambda c: c.data == "models_close")
async def on_models_close(callback: types.CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        try:
            await callback.message.edit_text("Меню закрыто.")
        except Exception:
            pass


# Reply-кнопка "🎛 Prompt"
@router.message(lambda m: m.text == "🎛 Prompt")
async def on_change_prompt(message: types.Message):
    user = get_user(message.from_user.id)
    user["waiting_for_prompt"] = True
    await message.answer("✍️ Отправь новый system prompt одним сообщением.")


# Reply-кнопка "🧹 Очистить"
@router.message(lambda m: m.text == "🧹 Очистить")
async def on_clear_history(message: types.Message):
    user = get_user(message.from_user.id)
    user["history"] = []
    await message.answer("🧹 История очищена.")


@router.message(F.content_type == ContentType.VOICE)
async def handle_voice(message: types.Message):
    user = get_user(message.from_user.id)

    # Если ждём prompt — игнорируем голосовые (или можно адаптировать)
    if user.get("waiting_for_prompt"):
        await message.answer("⚠️ Ожидаю текстовый system prompt.")
        return

    placeholder = await message.answer("🎤 Распознаю голосовое сообщение...")

    try:
        # Скачиваем файл
        file_id = message.voice.file_id
        file = await message.bot.get_file(file_id)
        downloaded_file = await message.bot.download_file(file.file_path)

        # Сохраняем временно (или можно в память с BytesIO)
        temp_filename = f"temp_voice_{message.message_id}.ogg"
        with open(temp_filename, "wb") as f:
            f.write(downloaded_file.read())

        # Транскрипция (пример с faster-whisper)
        from faster_whisper import WhisperModel

        model = WhisperModel(
            "small"
        )  # или "base", "medium" — в зависимости от ресурсов; "small" хорошо для русского
        segments, info = model.transcribe(
            temp_filename, language="ru"
        )  # явно указываем русский
        transcribed_text = " ".join(seg.text for seg in segments).strip()

        # Удаляем временный файл
        import os

        os.remove(temp_filename)

        if not transcribed_text:
            await placeholder.edit_text(
                "⚠️ Не удалось распознать речь. Попробуйте говорить чётче."
            )
            return

        await placeholder.edit_text(
            f"🎤 Распознано: {transcribed_text}\n\n⏳ Генерирую ответ..."
        )

        # Теперь используем тот же код генерации, что и для текста
        # Лучше вынести в отдельную функцию, но для примера дублируем логику
        full_text = ""
        buffer_text = ""

        async def on_chunk(chunk: str):
            nonlocal full_text, buffer_text
            buffer_text += chunk
            if len(buffer_text) > 20:
                full_text += buffer_text
                try:
                    await placeholder.edit_text(full_text[:4000])
                except Exception:
                    pass
                buffer_text = ""
                await asyncio.sleep(0.1)

        await generate_stream(
            model=user["model"],
            system_prompt=user["system_prompt"],
            history=user["history"],
            user_prompt=transcribed_text,
            on_chunk=on_chunk,
        )

        full_text += buffer_text
        await placeholder.edit_text(full_text[:4000])

        # Сохраняем в историю (голосовое как текст пользователя)
        user["history"].append(
            {"role": "user", "content": f"[Голосовое] {transcribed_text}"}
        )
        user["history"].append({"role": "assistant", "content": full_text})

    except Exception as e:
        logging.exception("Ошибка при обработке голосового")
        await placeholder.edit_text(f"❌ Ошибка: {e}")


# Основной чат
@router.message()
async def on_chat(message: types.Message):
    user = get_user(message.from_user.id)

    # Если ждем новый system prompt
    if user.get("waiting_for_prompt"):
        user["system_prompt"] = message.text
        user["waiting_for_prompt"] = False
        await message.answer("✅ System prompt обновлён.")
        return

    placeholder = await message.answer("⏳ Генерирую...")

    full_text = ""
    buffer_text = ""

    # Буферизированная функция on_chunk
    async def on_chunk(chunk: str):
        nonlocal full_text, buffer_text
        buffer_text += chunk
        if len(buffer_text) > 20:
            full_text += buffer_text
            try:
                await placeholder.edit_text(full_text[:4000])
            except Exception:
                logging.exception("Не удалось обновить сообщение")
            buffer_text = ""
            # даём Telegram немного “отдыха”
            await asyncio.sleep(0.1)

    try:
        await generate_stream(
            model=user["model"],
            system_prompt=user["system_prompt"],
            history=user["history"],
            user_prompt=message.text,
            on_chunk=on_chunk,
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при генерации: {e}")
        return

    # Отправляем оставшийся буфер
    full_text += buffer_text
    try:
        await placeholder.edit_text(full_text[:4000])
    except Exception:
        pass

    # Сохраняем историю
    user["history"].append({"role": "user", "content": message.text})
    user["history"].append({"role": "assistant", "content": full_text})
