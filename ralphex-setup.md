# Запуск через ralphex — что куда положить

Свод из доки ralphex: точная раскладка файлов и шаги до первого запуска.

## 1. Раскладка файлов (что куда)

ralphex стартует из корня git-репозитория. Положи seed-файлы так:

```
job-agent/                      ← корень репо (здесь .git)
├── CLAUDE.md                   ← конвенции, читается в начале КАЖДОЙ задачи
├── config.schema.json          ← seed (контракт конфига)
├── config.example.json         ← seed
├── prompts/                    ← seed (5 промтов)
│   ├── normalize.md  scoring.md  prefilter-routing.md  cover-letter.md  contact-search.md
├── design/                     ← seed (ориентир по UI)
│   ├── prototype.html  design-tokens.md
└── docs/plans/
    └── job-agent-plan.md       ← ПЛАН, который исполняет ralphex
```

`src/`, `tests/`, `pyproject.toml`, `compose.yml`, `webui/` и прочее **создаст сам ralphex** по ходу задач — руками не клади.

Откуда что из этого чата:
- `job-agent-plan.md` → `docs/plans/`
- `CLAUDE.md` → корень
- `config.schema.json`, `config.example.json` → корень
- `prompts/*` → `prompts/`
- `design/*` → `design/`

## 2. Подготовка репозитория

1. `git init` (если ещё нет). ralphex требует git-репо с хотя бы одним коммитом — он работает через ветки.
2. Разложи seed-файлы по схеме выше.
3. **Закоммить seed на master/main ДО запуска.** ralphex стартует с дефолтной ветки и сам создаёт feature-ветку из имени плана; diff ревью считается против master. Если seed не закоммичен, ревьюеры увидят свою же инфраструктуру как «новый код».
   ```
   git add . && git commit -m "chore: seed job-agent plan, prompts, config, design"
   ```

## 3. Решения до запуска

**Движок ralphex (важно из-за биллинга).** По умолчанию ralphex гоняет Claude Code через `claude --print`, а это с 15 июня 2026 отдельный пул Agent SDK-кредитов у подписки. Варианты:
- ничего не менять (лёгкий прогон влезает в включённый кредит);
- `ralphex --codex docs/plans/job-agent-plan.md` — весь пайплайн через codex CLI (нужен codex ≥ 0.130.0), остаёшься на OpenAI-плане;
- обёртка `fya` (PTY-режим Claude Code) — `claude_command = /opt/homebrew/bin/fya` в конфиге.

Это про движок **самого ralphex** и не путать с `scoring_engine` продукта (тот BYO и настраивается в `config.json`).

**Docker для валидации compose (Task 4.1).** Задача гоняет `docker compose config -q`. Если запускаешь ralphex нативно на хосте — работает сразу. Если ralphex сам в контейнере — добавь `--docker` (монтирует Docker-сокет).

**uv на PATH.** Команды валидации — `uv run ...`. Убедись, что `uv` установлен там, где исполняется ralphex (нативный запуск: на хосте; Docker-образ ralphex его не содержит — поставить в кастомном образе или взять нативный запуск).

**Опционально:**
- `ralphex --init` — создаст локальный `.ralphex/` с закомментированными дефолтами (свои агенты/промты ревью на проект).
- Добавить python-агента ревью в `.ralphex/agents/` (дефолтная пятёрка языко-независима; можно дотюнить под ruff/mypy/pytest).

## 4. Запуск

```
# из корня репо, с master/main
ralphex docs/plans/job-agent-plan.md

# с web-дашбордом (SSE-стрим прогресса)
ralphex --serve docs/plans/job-agent-plan.md          # http://localhost:8080

# если подписка часто упирается в лимит — ждать и ретраить
ralphex --wait=1h docs/plans/job-agent-plan.md

# только задачи, без тяжёлого 5-агентного ревью (быстрее/дешевле на первом проходе)
ralphex --tasks-only docs/plans/job-agent-plan.md
```

Что делает: создаёт ветку из имени плана → исполняет задачи по очереди (свежая сессия на каждую) → после каждой гоняет `## Validation Commands` → отмечает `[x]`, коммитит → мульти-агентное ревью → по успеху переносит план в `docs/plans/completed/`.

## 5. По ходу и после

- **Прервалось / остановил** — просто перезапусти ту же команду: ralphex найдёт первую незакрытую `[ ]` и продолжит. Завершённые задачи уже в коммитах.
- **Поменять поведение на лету** (стиль, библиотеки, ограничения) — правь `CLAUDE.md`, подхватится со следующей задачи без остановки.
- **Структурно поменять план** (переставить/добавить/убрать задачи) — Ctrl+C, отредактируй план (сними `[x]`→`[ ]` чтобы переделать), перезапусти.
- **Мониторинг** — `tail` прогресс-файла `.ralphex/progress/progress-*.txt` или `--serve`.

## 6. Чек-лист перед стартом

- [ ] git-репо, есть хотя бы один коммит
- [ ] seed-файлы разложены по схеме (§1) и закоммичены на master (§2.3)
- [ ] план в `docs/plans/job-agent-plan.md`
- [ ] выбран движок ralphex (claude / `--codex` / fya) с учётом биллинга
- [ ] `uv` доступен там, где бежит ralphex
- [ ] (если ralphex в контейнере и нужен compose-config) флаг `--docker`
- [ ] запуск: `ralphex docs/plans/job-agent-plan.md`
