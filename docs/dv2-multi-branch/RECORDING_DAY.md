# DV2.0 Demo — Recording Day Runbook

Пошаговый чек-лист для записи 2-минутного видео по
[`pitch.md`](./pitch.md). Один проход = 15-25 минут общего времени
(setup + 3-5 дублей с интервалом 30 сек на перевод дыхания).

## За 1 час до записи

- [ ] Подключиться к iMac: `ssh julia@192.168.1.133`
- [ ] Проверить кластер: должно вернуться `clickhouse-0 / postgres-0 / minio-0` Running + `argo-server` + `workflow-controller` Running

```bash
export PATH=$HOME/lima/bin:$HOME/bin:$PATH
kubectl get pods -n dv2
kubectl get pods -n argo
```

Если `kubectl` не видит кластер после плановой паузы iMac, сначала поднять
Lima/Docker и повторить проверку; данные остаются в Docker volumes:

```bash
export PATH=$HOME/lima/bin:$HOME/bin:$PATH
limactl start docker
kubectl get pods -n dv2
kubectl get pods -n argo
```

К `infrastructure/dv2/bootstrap.sh` переходить только если Lima поднялась, но
kind-кластер, namespace или StatefulSet'ы реально потеряны (≈10 мин на
пересборку).

- [ ] Caffeinate обновить: `nohup caffeinate -dimsu -t 7200 >/tmp/caffeinate.log 2>&1 & disown` (2 часа запас)

## За 10 минут до записи

Cache-warm каждый beat-command. Первый запуск некоторых kubectl запросов
~2-3 секунды, последующие — 200 мс. На видео разница заметна.

```bash
# beat-1
kubectl get nodes --show-labels >/dev/null

# beat-2
kubectl exec -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo \
  --query "SELECT 1" >/dev/null

# beat-3 (тот же CH client, warm)
# beat-4 (тот же CH client, warm)

# beat-5: prep cold-offload (cleanup test-job если остался)
kubectl get jobs -n dv2 | grep -v "Active\|NAME" | awk '{print $1}' | xargs -I {} kubectl delete job {} -n dv2 2>/dev/null
```

## Перед нажатием Record

- [ ] Терминал на 110×30 минимум (моноширинный шрифт ≥14pt)
- [ ] Закрыть Slack/Telegram/Mail (нотификации просочатся)
- [ ] Тёмная тема в терминале (parquet output читается без перенапряжения)
- [ ] Открыть в браузере на втором мониторе:
  - `docs/dv2-multi-branch/architecture.md` (mermaid рисунок)
  - `warehouse/agentflow/dv2/spec.yaml` (на случай вопроса «как добавить
    источник»)
- [ ] **`pitch.md`** открыт в edge-окне (виден глазам, не камере) для шпаргалки

## Запись (2:00 ровно)

Прочитать `pitch.md` от начала до 02:00. Команды выполняются между
блоками речи. Тайминг ёмкий:

| Time   | Что делать                              | Команда beat                    |
|--------|----------------------------------------|---------------------------------|
| 00:00  | Хук — про бизнес-проблему              | (ничего не запускать)           |
| 00:25  | Beat 1 — `kubectl get nodes`           | один Enter                      |
| 00:45  | Beat 2 — table-kinds                   | один Enter                      |
| 01:05  | Beat 3 — multi-branch distribution     | один Enter                      |
| 01:25  | Beat 4 — Business Vault MDM            | один Enter                      |
| 01:50  | Beat 5 — cold-offload + MinIO          | два Enter подряд (create + ls)  |
| 02:00  | Закрытие — про bootstrap.sh + demo_evidence.md | (ничего не запускать)   |

Если ошиблись на 01:30 — спокойно стоп, повторить с 00:00. На каждый
дубль уйдёт ровно 2 минуты, не больше.

## Опциональный extended cut (4:00 общее)

Если интервьюер просит технического глубже — после Beat 6 не закрывать
видео, перейти к Beat 7 (per-branch CDC fan-out) из `pitch.md`. Это
добавит 30-40 секунд и покажет operational-thinking.

После Beat 7 — обязательный cleanup перед следующим дублем:

```bash
kubectl exec -i -n dv2 postgres-0 -- psql -U ops -d ops_msk_db \
  -c "DELETE FROM customers WHERE customer_id='msk-c-DEMO'"
```

## После записи

- [ ] Скопировать MP4 в `D:\DE_project\` (НЕ коммитить — `.gitignore` `*.mp4`)
- [ ] Залить на YouTube **unlisted** или Google Drive (НЕ public до проверки)
- [ ] Получить shareable link
- [ ] В резюме / hire-портфолио — линк подписать «Live demo, 2-min screen recording»
- [ ] (Опционально) добавить ссылку в `proof-pack` если запись будет
      использоваться публично

## Fallback при отказе кластера

Если iMac недоступен прямо в момент записи и времени на восстановление
нет — пересобрать запись из скриншотов:

1. Открыть `docs/dv2-multi-branch/demo_evidence.md`
2. На каждый beat — скриншот соответствующего блока (§1, §3-§5, §8, §9)
3. Поверх — голосовой комментарий из `pitch.md`
4. Тайминг тот же (2:00); тон чуть «слайдовее», но allowed для demo-day

## Что не делать

- ❌ НЕ запускать новый `dv2-refresh` Argo workflow прямо перед записью
  (90s execution + cleanup pods загромоздят namespace)
- ❌ НЕ удалять MinIO bucket — beat 5 показывает накопленные parquet
- ❌ НЕ менять CH password — beats 2-4-5 hardcoded на `demo`
- ❌ НЕ запускать запись без caffeinate refresh (iMac засыпает на 10 минут idle)
