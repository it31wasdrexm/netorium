# Netorium — тестирование блокировок сайтов и приложений

Этот файл для быстрого ручного теста controller + agent в офисной схеме.
Команды ниже можно копировать и вставлять.

## Что уже работает

- **Сайты** — блокировка через `hosts` на Windows endpoint (`youtube.com`, `vk.com` и т.д.)
- **Игры и exe** — блокировка исходящего трафика через Windows Firewall по имени (`dota2.exe`, `cs1.6.exe`) или по полному пути
- **Один агент или все сразу** — в коротких командах можно указать `agt_...`, hostname ПК или `all`
- **Dry-run по умолчанию** — сначала тест без реального применения, потом `--real`

Реальные команды работают только на **Windows endpoint** с правами администратора.

---

## 1. Подготовка (админский ПК)

```bash
netorium config init
netorium controller init --host 0.0.0.0 --port 8765
netorium controller start --host 0.0.0.0 --port 8765
```

В другом терминале на том же ПК:

```bash
netorium controller status
netorium controller token create --zone accounting --ttl 24h
netorium deploy instructions
```

Скопируй enrollment token и LAN-адрес controller, например `http://192.168.1.10:8765`.

---

## 2. Установка агента на рабочий ПК (Windows)

PowerShell на офисном ПК:

```powershell
irm https://raw.githubusercontent.com/it31wasdrexm/netorium/main/get.ps1 | iex
```

Регистрация агента:

```powershell
netorium-agent enroll --controller http://192.168.1.10:8765 --token ng_enroll_ВАШ_ТОКЕН
netorium-agent status
```

Запуск агента (PowerShell **от администратора** для `--real` команд):

```powershell
netorium-agent run
```

---

## 3. Посмотреть подключённых агентов

На админском ПК:

```bash
netorium policy agents
```

или

```bash
netorium controller agent list
```

Запомни `Agent ID` (например `agt_a1b2c3`) или hostname (например `pc-acc-01`).

---

## 4. Короткие команды policy (удобные)

Вместо длинного `netorium controller agent command ...` используй `netorium policy`.

### Блокировка сайта одному агенту (dry-run)

```bash
netorium policy site pc-acc-01 youtube.com -r "Урок, без YouTube"
```

или по ID:

```bash
netorium policy site agt_a1b2c3 youtube.com -r "Урок, без YouTube"
```

### Блокировка сайта всем агентам сразу

```bash
netorium policy site all youtube.com -r "Общая политика класса"
```

### Реальная блокировка сайта

```bash
netorium policy site all youtube.com -r "Общая политика класса" --real
```

На endpoint агент должен выполнить команду: `netorium-agent run` (от админа).

### Разблокировать сайт

```bash
netorium policy site all youtube.com -r "Перемена" --unblock --real
```

---

## 5. Блокировка игр и приложений

### Заблокировать CS 1.6 одному ПК

```bash
netorium policy game pc-game-01 cs1.6.exe -r "Игры запрещены"
```

### Заблокировать Dota 2 всем

```bash
netorium policy game all dota2.exe -r "Игры запрещены" --real
```

### Заблокировать по полному пути

```bash
netorium policy app pc-game-01 "C:\Games\Counter-Strike 1.6\cs1.6.exe" -r "Игры запрещены" --real
```

`policy game` и `policy app` — одно и то же, `game` просто короче для игр.

### Разблокировать игру

```bash
netorium policy game all dota2.exe -r "Конец перемены" --unblock --real
```

Если указано только имя `dota2.exe`, агент ищет exe в Program Files, Steam и `%LOCALAPPDATA%`.

---

## 6. Ограничение скорости

```bash
netorium policy speed pc-acc-01 -r "Временный лимит" --down 2048 --up 512
netorium policy speed all -r "Временный лимит" --up 512 --real
netorium policy clear-speed all -r "Лимит снят" --real
```

---

## 7. Проверить очередь команд

```bash
netorium policy list
netorium policy list agt_a1b2c3
```

или

```bash
netorium controller agent command list
netorium controller agent command list --agent-id agt_a1b2c3
```

---

## 8. Полный цикл теста (рекомендуется)

1. На админском ПК: `controller init` → `controller start`
2. Создай token: `controller token create --zone accounting --ttl 24h`
3. На рабочем ПК: установи CLI → `netorium-agent enroll` → `netorium-agent run` (админ)
4. На админском ПК: `netorium policy agents`
5. Dry-run:
   ```bash
   netorium policy site all youtube.com -r "Тест"
   netorium policy game all cs1.6.exe -r "Тест"
   ```
6. Проверь очередь: `netorium policy list`
7. На рабочем ПК снова `netorium-agent run` — должны быть `completed` dry-run
8. Реально:
   ```bash
   netorium policy site all youtube.com -r "Тест реальный" --real
   netorium policy game all cs1.6.exe -r "Тест реальный" --real
   ```
9. На рабочем ПК: `netorium-agent run`
10. Проверь:
    - `youtube.com` не открывается в браузере
    - `cs1.6.exe` / `dota2.exe` не ходят в интернет

---

## 9. Длинные команды (если нужны)

```bash
netorium controller agent command site --agent-id agt_a1b2c3 --action block --domain youtube.com --reason "Class policy"
netorium controller agent command app --agent-id agt_a1b2c3 --action block --executable dota2.exe --reason "No game traffic" --real
netorium controller agent command binary --agent-id agt_a1b2c3 --action block --executable cs1.6.exe --reason "No game traffic" --real
```

---

## 10. Частые проблемы

| Проблема | Что проверить |
|----------|----------------|
| `Agent was not found` | `netorium policy agents`, используй `all`, hostname или `agt_...` |
| Команда в очереди, но не применяется | На endpoint запущен `netorium-agent run` |
| `Windows-only` | Агент должен быть на Windows |
| Firewall rule failed | PowerShell от администратора |
| `dota2.exe` not found | Укажи полный путь через `policy app ... "C:\...\dota2.exe"` |
| Сайт всё ещё открывается | Очисти DNS: `ipconfig /flushdns`, проверь HTTPS/CDN поддомены |

---

## 11. Быстрая шпаргалка

```bash
netorium policy agents
netorium policy site all youtube.com -r "Причина"
netorium policy site all youtube.com -r "Причина" --real
netorium policy game all dota2.exe -r "Причина" --real
netorium policy game all cs1.6.exe -r "Причина" --unblock --real
netorium policy list
```

На endpoint:

```powershell
netorium-agent run
```
