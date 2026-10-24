# Задание: выпустить Lost Zone 2026.10.24.3 (патч 000042)

Ты продолжаешь работу другой сессии. Нужно выложить обновление 2026.10.24.3:
клиент в лаунчер, архив сервера, и поставить его на копию игры владельца.
Отвечай владельцу по-русски.

## Правила (обязательно)
- Не печатай и не публикуй ключи, токены, пароль админа (`ADMIN_PASSWORD.txt` читается скриптами сами).
- Движок локально НЕ собирать: только готовый артефакт CI.
- Не удалять аккаунты, миры, сохранения. Перед перезаписью смотреть, что перезаписываешь.
- Не закрывать запущенный клиент владельца (`LostZoneClientDX11.exe`).
- Ветка `engine-restructure`, worktree `C:\Users\Mahito\Desktop\NetAnomaly_Engine_Console_2026-09-10\NetAnomaly_Full\engine-restructure`. Пуш: `git push gostn1ght engine-restructure`.

## Что уже готово
- Код: коммит `3a962d7b6c3c9feba331594a61c047163b32ff03` (C++ мастер с вкладкой «Локации»; Definitive Car Pack — 50 машин `dcp_*`; старые 17 машин GAMMA убраны).
- Сборка CI: run `40116494535` (workflow «Lost Zone DX11»). Проверь: `gh run view 40116494535 -R Gostn1ght/AnomalyMP --json status,conclusion`. Нужен `completed success`. Если упала — смотри `--log-failed`, чини, пушь, запускай `gh workflow run lostzone-dx11.yml -R Gostn1ght/AnomalyMP --ref engine-restructure`, затем пересобирай патч (ниже) на новом коммите.
- Патч уже собран: `J:\LostZone_Work\_work\patch_000042` (база — выпуск 000041 = `505a9e4f252a068d531d8ffc59db55b7ae9d946a`, head = 3a962d7b6).
  - клиент: `archives\client\99_lz_patch_000042.db0`, `..._000042_v1.db0`, `..._000042_v2.db0` (ТРИ тома, впервые — упаковщик `J:\LostZone_Work\Compressor\lzpack.py` теперь делит патч на тома ≤850 МБ);
  - сервер: `archives\server\99_lz_patch_000042_server.db0` (без текстур и звуков).
  - Пересборка (если коммит поменялся): `python scripts/make-release-patch.py --version 000042 --out "J:\LostZone_Work\_work\patch_000042" --client-base 505a9e4f252a068d531d8ffc59db55b7ae9d946a --server-base 505a9e4f252a068d531d8ffc59db55b7ae9d946a` (папку patch_000042 перед этим удалить — она ещё не опубликована).
- Предыдущий выпуск: 2026.10.24.2 = native 505a9e4f2, патч 000041, мастер (Python) ac79704f9 — не менять.

## Шаги
Папка скриптов: `J:\LostZone_Work\_work\owner_remote_bugs_20261013`.

1. Сделай `make_000042_scripts.py` по образцу `make_000041_scripts.py` (он генерирует скрипты из версии 000041 заменами). Замены для 000042:
   - `000041`→`000042`, `000040`→`000041` (но строку `99_lz_patch_000040` в списке publish оставить и добавить), `launcher_client_000040`→`launcher_client_000041`;
   - версии: `2026.10.24.2`→`2026.10.24.3`, `2026.10.24.1`→`2026.10.24.2`;
   - коммиты: head `505a9e4f2…`→`3a962d7b6c3c9feba331594a61c047163b32ff03`, база `ecfea5fdc…`→`505a9e4f252a068d531d8ffc59db55b7ae9d946a`; run → `40116494535`;
   - `LZ_RESUME_000041`→`LZ_RESUME_000042`.
2. ВАЖНО — три тома клиентского патча. Скрипты 000041 рассчитаны на один архив. Поправь в сгенерированных:
   - `prepare_release_000042.py`: вместо `archives=list(...glob('*.db0')); assert len(archives)==1` — цикл по всем `*.db0` роли; каждый проверить по своему `.manifest.json` (version=='000042', sha256) и положить `put(...)`; проверка «Immutable patch number reused» — для каждого тома.
   - `verify_release_000042.py`: цикл по всем томам (sha, `lzpack.verify`, наличие в addon/stage).
   - `install_owner_000042_offline.py`: класть все тома, не только первый (`next(glob)` → цикл).
   - `publish_fixes_000042.py`: в списке `required` должны быть `resources/99_lz_patch_000042.db0`, `..._000042_v1.db0`, `..._000042_v2.db0`, `...000041.db0`, `...000040.db0`, `...000039.db0`, `...000036.db0`, `...000034.db0`.
   - Сервер получает новые незапакованные конфиги (`configs/models/vehicles/*.ltx`, `mod_system_lz_dcp_vehicles.ltx`, `plugins/spawner_blacklist.ltx`): в prepare уже есть правило «новый конфиг сервера кладётся, клиентский конфиг, которого нет в серверном аддоне, пропускается» — проверь, что оно осталось.
3. `python -I make_000042_scripts.py <commit> <run>` → получишь `prepare/verify/publish_fixes/mark_published/package_server/install_owner/complete_release_000042.py`. Скомпилируй их (`python -m py_compile`).
4. Сервер раздачи должен работать: `http://127.0.0.1:8787/` отвечает 200 (иначе запусти его ярлыком на рабочем столе).
5. Запусти выпуск отвязанно (чтобы не умер с сессией):
   `Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine="cmd /c python -u complete_release_000042.py > complete_000042.log 2>&1"; CurrentDirectory='J:\LostZone_Work\_work\owner_remote_bugs_20261013'}`
   Он ждёт CI, качает артефакт (`download_verified_native.py`), делает prepare (проверка, затем `--apply`), verify, publish (лаунчер), mark_published, verify --published, package_server (архив `J:\LostZone_Work\Lost Zone Server.zip`). Смотри лог; конец — строка `DONE 2026.10.24.3`.
6. Если упало на `prepare --apply` посередине: второй раз apply не пройдёт («stage exists»). Сделай `resume_release_000042.py` (как `resume_release_000040.py`): выставь `LZ_RESUME_000042=1`, повтори apply и дальше verify → publish → mark → verify --published → package. Если упало после apply — продолжай с того шага, где упало.
7. Копия владельца: когда `LostZoneClientDX11.exe` не запущен — `python install_owner_000042_offline.py` (из папки engine-steamnet, как в 000041). Если клиент запущен — не трогать, сказать владельцу, что обновится лаунчером.
8. Обнови память `lost-zone-release-state` (последний выпуск 2026.10.24.3 = native 3a962d7b6 + патч 000042 из трёх томов; следующий патч 000043; lzpack умеет тома).

## Что сказать владельцу (по-русски)
- Выпущено 2026.10.24.3: клиент в лаунчере, архив сервера `J:\LostZone_Work\Lost Zone Server.zip`, его копия обновлена (или нет — почему).
- Мастер теперь C++ в окне сервера (хостер запускает его, если в `dedicated\` есть `sqlite3.dll`): вкладка «Локации», 33 карты, кнопки «Включить/Выключить выбранные». Python-мастер остаётся запасным.
- Машины: 50 машин Definitive Car Pack (`dcp_*` в спавнере), 17 старых GAMMA убраны, стоявшие в мире удаляются при старте сервера вместе с багажником. Вертолёты на месте.
- Всё проверено тестами и сборкой, в игре не проверялось. Патч большой (~2,1 ГБ клиент).
- Вкладки КПК как в New Way в этот выпуск не вошли.
