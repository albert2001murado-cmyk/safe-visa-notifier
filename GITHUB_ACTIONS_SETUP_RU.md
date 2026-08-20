# Подробная инструкция: бесплатный запуск через GitHub Actions

## 0. Что это за вариант

Это не полноценный постоянно включённый Telegram-бот с кнопками. Это бесплатный вариант без VPS:

- GitHub сам запускает проверку по расписанию.
- Скрипт проверяет публичную страницу ожиданий виз США.
- Если есть нужное изменение, он отправляет сообщение в Telegram.
- Компьютер можно выключить.

Команды `/start` и кнопки при выключенном компьютере работать не будут, потому что для этого нужен постоянно работающий сервер/VPS.

---

## 1. Что должно быть в проекте

В репозитории должны быть файлы:

```text
.github/workflows/visa-check.yml
action_checker.py
action_state.json
requirements-action.txt
.gitignore
```

Папку `.github` обязательно загружать целиком.

---

## 2. Загрузи файлы на GitHub

Открой VS Code в папке проекта и в терминале выполни:

```powershell
git add .
```

```powershell
git commit -m "Add free GitHub Actions visa checker"
```

```powershell
git push
```

После этого открой свой репозиторий на GitHub и проверь, что появилась папка `.github`.

---

## 3. Включи права на сохранение состояния

Скрипт сохраняет последние значения в `action_state.json`, чтобы понимать, стало лучше или нет.

На GitHub открой репозиторий и нажми:

```text
Settings → Actions → General
```

Найди блок:

```text
Workflow permissions
```

Выбери:

```text
Read and write permissions
```

Нажми:

```text
Save
```

---

## 4. Добавь Telegram-токен в Secrets

Открой:

```text
Settings → Secrets and variables → Actions
```

Открой вкладку:

```text
Secrets
```

Нажми:

```text
New repository secret
```

Добавь:

```text
Name: TELEGRAM_BOT_TOKEN
Secret: токен от BotFather
```

Токен нельзя хранить в коде, `.env` или README.

---

## 5. Узнай свой TELEGRAM_CHAT_ID

1. Останови локального бота в VS Code, если он сейчас запущен: `Ctrl + C`.
2. Напиши своему Telegram-боту любое сообщение, например `/start`.
3. В браузере открой ссылку такого вида:

```text
https://api.telegram.org/botТВОЙ_ТОКЕН/getUpdates
```

4. Найди в ответе:

```json
"chat": { "id": 123456789 }
```

Число `123456789` — это твой `TELEGRAM_CHAT_ID`.

Если в ответе пусто, отправь боту ещё одно сообщение и обнови страницу.

---

## 6. Добавь TELEGRAM_CHAT_ID в Secrets

GitHub:

```text
Settings → Secrets and variables → Actions → Secrets → New repository secret
```

Добавь:

```text
Name: TELEGRAM_CHAT_ID
Secret: твой числовой chat_id
```

---

## 7. Добавь настройки в Variables

На той же странице открой вкладку:

```text
Variables
```

Нажми:

```text
New repository variable
```

Добавь переменные:

```text
Name: VISA_CITIES
Value: Almaty,Astana,Warsaw,Krakow,Yerevan
```

```text
Name: VISA_TYPE
Value: B1B2
```

```text
Name: TARGET_MONTHS
Value: 2
```

```text
Name: SEARCH_HORIZON_MONTHS
Value: 36
```

Что это значит:

- `VISA_CITIES` — какие города проверять.
- `VISA_TYPE` — тип визы.
- `TARGET_MONTHS` — срочный порог. Например, если поставить `2`, бот уведомит, когда ожидание станет 2 месяца или меньше.
- `SEARCH_HORIZON_MONTHS` — общий горизонт поиска. Максимум `36`, то есть 3 года.

Допустимые типы виз:

```text
B1B2      туризм / бизнес
FMJ       учёба / обмен
PETITION  рабочие визы H, L, O, P, Q
CREW      экипаж / транзит
```

---

## 8. Первый ручной запуск

Открой вкладку репозитория:

```text
Actions
```

Слева выбери:

```text
Check US visa wait times
```

Нажми:

```text
Run workflow
```

Затем ещё раз:

```text
Run workflow
```

При ручном запуске бот должен прислать статус в Telegram даже если изменений нет.

---

## 9. Как понять, что всё работает

Открой последний запуск во вкладке Actions.

Если всё нормально, будет зелёная галочка.

В логах будет одна из строк:

```text
Status sent
```

или:

```text
Notification sent
```

или:

```text
No meaningful changes
```

`No meaningful changes` — это не ошибка. Это значит, что проверка прошла, но новых подходящих изменений нет.

---

## 10. Как часто проверяет

В файле `.github/workflows/visa-check.yml` сейчас стоит:

```yaml
cron: "17,47 * * * *"
```

Это примерно 2 раза в час.

Можно сделать чаще, например каждые 15 минут:

```yaml
cron: "*/15 * * * *"
```

Но чаще 5 минут ставить нельзя.

---

## 11. Частые ошибки

### Ошибка: `TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set`

Ты не добавил Secrets или ошибся в названии.

Нужно именно:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

### Ошибка: `Resource not accessible by integration`

Не включены права записи.

Сделай:

```text
Settings → Actions → General → Workflow permissions → Read and write permissions → Save
```

### Ошибка: `Официальная таблица не найдена`

Сайт Госдепартамента временно не отдал таблицу. Запусти workflow позже ещё раз.

### Сообщение не пришло в Telegram

Проверь:

- Бот не заблокирован в Telegram.
- Ты правильно указал `TELEGRAM_CHAT_ID`.
- Ты правильно указал токен.
- В `Actions` нет красной ошибки.

---

## 12. Как обновлять код

После изменений в VS Code:

```powershell
git add .
git commit -m "Update visa checker"
git push
```

GitHub сам будет использовать новую версию.

