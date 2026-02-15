# storage.py
# Простейшее in-memory хранилище для настроек каждого пользователя.
# Позже можно заменить на базу данных (SQLite/Redis/etc).

from config import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT

# Словарь: user_id -> данные
# Структура для одного пользователя:
# {
#   "model": str,
#   "system_prompt": str,
#   "history": list of {"role": "user"/"assistant", "content": "..."},
#   "waiting_for_prompt": bool
# }
user_data = {}


def get_user(user_id: int):
    """
    Возвращает объект настроек пользователя, создаёт по умолчанию при отсутствии.
    """
    if user_id not in user_data:
        # Инициализация значениями по умолчанию
        user_data[user_id] = {
            "model": DEFAULT_MODEL,
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
            "history": [],
            "waiting_for_prompt": False
        }
    return user_data[user_id]

