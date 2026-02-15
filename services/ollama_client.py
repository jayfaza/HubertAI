# services/ollama_client.py
# Модуль для общения с Ollama API: получение списка моделей и стриминг-чат.
# Здесь добавлены таймауты и защита от ошибок, чтобы бот не "вис" при проблемах сети.

import aiohttp
import asyncio
import json
from typing import List, Callable, Awaitable

from config import OLLAMA_URL, HTTP_TIMEOUT_SECONDS

# Конфигурация таймаута для aiohttp
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=60)


async def get_models() -> List[str]:
    """
    Возвращает список имён моделей, доступных в Ollama.
    В случае ошибки возвращает пустой список (без выбрасывания исключения).
    """
    url = f"{OLLAMA_URL}/api/tags"
    try:
        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
            async with session.get(url) as resp:
                # Если сервис вернул не 200 — считаем, что список недоступен
                if resp.status != 200:
                    return []
                print(f"                                 -----------DATA-----------")
                data = await resp.json()
                print(data)
                # Поддерживаем несколько возможных структур ответа
                models = []
                # Ollama может вернуть {"models": [{"name": "..."} , ...]} или похожую структуру
                if isinstance(data, dict):
                    print(f"Data is dict...")
                    for k in ("models", "tags", "data"):
                        print("for key in keys...")
                        items = data.get(k)
                        print(f"                         -----------ITEMS BY KEY----------------")
                        print(items)
                        if items and isinstance(items, list):
                            print(f"items exists and items is list")
                            for it in items:
                                print("for item in items list")
                                # если элемент — словарь с ключом "name"
                                if isinstance(it, dict):
                                    print(f"item is dict")
                                    name = it.get("name") or it.get("model") or it.get("id")
                                    print(f"name: {name}")
                                    if name:
                                        print(f"appending to models: {name}")
                                        models.append(str(name))
                                # если элемент уже строка
                                elif isinstance(it, str):
                                    print(f"item - str, not dict, appending")
                                    models.append(it)
                            if models:
                                print(f"models is list")
                                return models
                # если ничего не подошло — пробуем обработать как список строк
                if isinstance(data, list):
                    for it in data:
                        if isinstance(it, str):
                            models.append(it)
                        elif isinstance(it, dict):
                            nm = it.get("name") or it.get("model") or it.get("id")
                            if nm:
                                models.append(str(nm))
                return models
    except asyncio.TimeoutError:
        return []
    except Exception:
        return []


async def generate_stream(
    model: str,
    system_prompt: str,
    history: list,
    user_prompt: str,
    on_chunk: Callable[[str], Awaitable[None]]
):
    """
    Запускает стрим-чат через Ollama API (POST /api/chat) и вызывает on_chunk(chunk)
    при получении каждой части ответа. В случае ошибки on_chunk вызывается с текстом ошибки.
    Параметры:
    - model: имя модели
    - system_prompt: системный промпт (строка)
    - history: список сообщений [{'role': 'user'|'assistant', 'content': '...'}, ...]
    - user_prompt: текущий запрос пользователя
    - on_chunk: async-функция, которая принимает строку (кусочек) и возвращает awaitable
    """
    url = f"{OLLAMA_URL}/api/chat"
    print("MESSAGE GENERATING...")
    print("model: {model}\nsystem_prompt: {system_prompt}\nhistory: {history}\nuser prompt: {user_prompt}")

    # Формируем messages (system + history + user)
    messages = [{"role": "system", "content": system_prompt}]
    # history ожидается как список словарей с полями role/content
    if history:
        messages.extend(history)
        print(f"messages: {messages}")
    messages.append({"role": "user", "content": user_prompt})
    print(f"messages: {messages}")

    payload = {
        "model": model,
        "messages": messages,
        "stream": True
    }

    try:
        async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
            print(f"opened server transportation.")
            async with session.post(url, json=payload) as resp:
                print(f"network with ollama is established")
                # если сервер дал ошибку — попробуем вернуть тело ошибки пользователю
                if resp.status != 200:
                    try:
                        text = await resp.text()
                    except Exception:
                        text = f"HTTP {resp.status}"
                    await on_chunk(f"\n\n[Ошибка Ollama: {text}]")
                    return

                # Читаем поток байтов; каждый кусок может быть JSON-строкой
                async for raw in resp.content:
                    print(f"reading content...\n")
                    print(f"raw: {raw}\n")
                    if not raw:
                        print(f"no content")
                        continue
                    try:
                        decoded = raw.decode(errors="ignore").strip()
                        if not decoded:
                            continue
                        print(f"decoded message is {type(decoded)}: {decoded}\n")
                        # Попытка распарсить JSON в ожидаемом формате
                        data = json.loads(decoded)
                        print(f"data is: {type(data)}: {data}\n")
                        # Ожидаем структуру {"message": {"content": "..."}} или похожую
                        if isinstance(data, dict):
                            # случай, когда сервер шлёт событие с полем "message"
                            if "message" in data and isinstance(data["message"], dict):
                                print(f"data have 'message', data['message'] content, data is dict")
                                content = data["message"].get("content")
                                print(f"\nSCREENED CONTENT: {content}\n")
                                if content:
                                    await on_chunk(str(content))
                            # либо сервер может отправлять { "content": "..." }
                            elif "content" in data:
                                await on_chunk(str(data["content"]))
                            else:
                                # если структура другая — отправим repr
                                await on_chunk(str(data))
                        else:
                            # если это не dict — отправим как текст
                            await on_chunk(str(data))
                    except json.JSONDecodeError:
                        # Если не JSON — пробуем отправить сырый текст
                        try:
                            txt = raw.decode(errors="ignore")
                            await on_chunk(txt)
                        except Exception:
                            # молча пропускаем кусочек, который нельзя обработать
                            pass
                    except asyncio.CancelledError:
                        # прерывание — пробрасываем дальше
                        raise
                    except Exception as e:
                        # любая другая единичная ошибка — информируем частичным сообщением
                        try:
                            await on_chunk(f"\n\n[Ошибка при обработке стрима: {e}]")
                        except Exception:
                            pass
    except asyncio.TimeoutError:
        await on_chunk("\n\n[Ошибка: соединение с Ollama превысило таймаут.]")
    except Exception as e:
        await on_chunk(f"\n\n[Внутренняя ошибка при подключении к Ollama: {e}]")

