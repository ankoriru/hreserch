# HH Vacancy Monitor — Web App

Веб-приложение для автоматического мониторинга вакансий ИТ-руководителей на hh.ru с уведомлениями в Telegram.

## 🚀 Быстрый старт (локально)

```bash
# 1. Клонируйте/скопируйте проект
cd hh-vacancy-web

# 2. Создайте виртуальное окружение
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# 3. Установите зависимости
pip install -r requirements.txt

# 4. Запустите
python app.py
```

Приложение будет доступно на `http://localhost:8000`

**Логин по умолчанию:** `admin` / `admin`

## 🐳 Развёртывание на Amvera

### 1. Подготовка

Убедитесь, что в проекте есть:
- `Dockerfile`
- `requirements.txt`
- `app.py`

### 2. Переменные окружения (Amvera)

В настройках проекта на Amvera добавьте:

| Переменная | Значение | Описание |
|------------|----------|----------|
| `SECRET_KEY` | `your-random-secret-key` | Секретный ключ Flask (обязательно сменить!) |
| `ADMIN_USER` | `admin` | Логин администратора |
| `ADMIN_PASS_HASH` | `pbkdf2:sha256...` | Хеш пароля (генерируется через Werkzeug) |
| `PORT` | `8000` | Порт приложения |

**Как получить хеш пароля:**

```python
from werkzeug.security import generate_password_hash
print(generate_password_hash("your_password"))
```

Или локально:
```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"
```

### 3. Деплой через Git

```bash
git init
git add .
git commit -m "Initial"
git remote add amvera https://git.amvera.ru/YOUR_USERNAME/YOUR_PROJECT.git
git push amvera master
```

Или загрузите ZIP-архив через веб-интерфейс Amvera.

### 4. После деплоя

- Откройте URL вашего приложения на Amvera
- Войдите с логином/паролем из переменных окружения
- Перейдите в **Настройки** и укажите:
  - Telegram Bot Token
  - Chat ID
  - Время запуска (по умолчанию 09:00)
  - Поисковые запросы
- Включите мониторинг

## 📁 Структура проекта

```
hh-vacancy-web/
├── app.py              # Flask backend + авторизация
├── scheduler.py        # Фоновый планировщик (APScheduler)
├── config.py           # Управление конфигурацией
├── requirements.txt    # Зависимости
├── Dockerfile          # Контейнер для Amvera
├── templates/          # HTML шаблоны
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   └── settings.html
├── static/
│   ├── css/style.css
│   └── js/app.js
└── reports/            # Сгенерированные отчёты (HTML + TXT)
```

## ⚙️ Функционал

- **Авторизация** — защищённая панель управления
- **Настройки через UI** — без редактирования файлов
- **Расписание** — ежедневный запуск в заданное время
- **Только будни** — пропуск выходных
- **Telegram** — мгновенные уведомления о новых вакансиях
- **История** — не повторяет уже отправленные вакансии
- **Ручной запуск** — кнопка «Запустить сейчас»
- **Отчёты** — HTML и TXT файлы с результатами

## 🔒 Безопасность

- **Обязательно смените** `SECRET_KEY` и `ADMIN_PASS_HASH` в переменных окружения
- Не храните реальные токены в коде — используйте переменные окружения
- В production отключите `debug=True`

## 📝 Лицензия

MIT — свободное использование.
