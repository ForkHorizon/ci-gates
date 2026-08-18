# CI Scope v2 — ci-gates implementation report

Дата отчёта: 2026-08-13  
Репозиторий: `ForkHorizon/ci-gates`  
Ветка: `daliys/fix-empty-coverage-args`  
PR: [#64](https://github.com/ForkHorizon/ci-gates/pull/64)  
Итоговый commit на момент локальной сверки: `a94e73b2f0935bd11f47f269f1c18bc9469daaa4`

## 1. Назначение отчёта

Этот документ предназначен для агента, который будет объединять и проверять
три репозитория CI Scope v2:

1. `ForkHorizon/CI-Scope` — Swift UI, Go Agent и Watchdog;
2. `ForkHorizon/CI-Scope-Web` — Worker, RunnerPool Durable Object, D1 и GitHub App;
3. `ForkHorizon/ci-gates` — workflow-facing contract и gate scripts.

Отчёт описывает только выполненную работу в `ci-gates`. Он не является доказательством
готовности server/client частей и не объявляет production cutover.

## 2. Граница ответственности ci-gates

В этом репозитории реализованы и проверяются:

- reusable workflow inputs для routing generation;
- совместимый v1 routing contract и additive v2 contract;
- group + labels + generation validation;
- workflow trust-facing structural checks;
- release manifest validation;
- additive `::ci-scope-progress::` marker contract;
- v2 canary workflow с двумя same-label jobs;
- workflow/action pinning checks;
- self-check CI для exact revision, который проверяется.

В этом репозитории намеренно не реализованы:

- scheduler, claim, reservation, lease или generation barrier;
- webhook ingress и authoritative event transitions;
- Durable Object/D1 state;
- GitHub App token/JIT runner lifecycle;
- local Agent session, process или runner cleanup;
- production migration уже созданных queued/leased/assigned jobs.

Эти состояния должны иметь единственного owner в server/client репозиториях и
проверяться совместно по cross-repository plan.

## 3. Реализованный routing contract

### v1 backward-compatible contract

Все существующие reusable gate workflows сохраняют v1 defaults. В production
по умолчанию остаются прежние runner groups:

- `ci-scope` для Code Linter, Go, Python, Slop Review, Unity и Web gates;
- `ci-scope-broker` для Swift Compile и Swift Quality gates.

v1 остаётся default до отдельной миграции consumer repository.

### v2 contract

Canonical routing object:

```json
{
  "generation": "v2",
  "group": "ci-scope-v2-canary",
  "labels": ["self-hosted", "macOS", "ARM64", "ci-scope-v2"]
}
```

Reusable workflows принимают следующие inputs:

| Input | Значение |
|---|---|
| `runner-group` | GitHub runner group; v2 требует `ci-scope-v2-canary` |
| `runner-labels` | JSON array labels; v2 требует полный набор v2 labels |
| `routing-generation` | Только `v1` или `v2`; unknown generation отклоняется |
| `workflow-contract-version` | `v1` или `v2`, должен совпадать с generation |
| `trust-fixture-mode` | Пустой в production; `canary-only` разрешён только для canary v2 |
| `gates-ref` | Ref ci-gates; `main` сохранён для backward compatibility, production должен pin-ить SHA |

Все reusable gate workflows формируют `runs-on` как group + labels и имеют
guard, который допускает только согласованные пары:

```text
(routing-generation == v1 && workflow-contract-version == v1)
||
(routing-generation == v2 && workflow-contract-version == v2)
```

Это не даёт одному job одновременно стать eligible в v1 и v2 routing domains.

### Runtime validation

`scripts/gates_contract.py` предоставляет `validate_routing()` и CLI. Проверяются:

- object shape и обязательные поля;
- допустимые aliases (`routing-generation`, `runner-group`, `runner-labels`);
- неизвестные поля и неизвестные generations;
- непустой group и labels;
- ограничения длины и числа labels;
- case-insensitive duplicate labels;
- обязательные v2 group/label;
- запрет смешивания v1/v2 inputs;
- соответствие `workflow-contract-version` generation;
- canary-only mode только в canary environment и только для v2;
- отказ от произвольного untrusted group в production.

Последний commit дополнительно разделил `validate_routing()` на небольшие
семантические validators. Это исправило реальную ошибку CI Code Linter по лимиту
размера функции, а не отключило правило линтера и не добавило suppress-комментарий.

## 4. Trust-facing workflow checks

`scripts/workflow_policy.py` выполняет dependency-free structural validation
workflow text. При наличии manifest/check input проверяется source SHA.

Проверки включают:

- external fork `pull_request` не может попасть в trusted group без same-repository guard;
- `pull_request_target` не должен checkout-ить untrusted head;
- production reusable workflow не должен использовать floating `@main`;
- reusable workflow origin должен быть approved;
- v1 и v2 routing fields не могут использоваться одновременно;
- generation, group и labels должны соответствовать approved routing;
- отсутствующий/невалидный source SHA в manifest отклоняется;
- release enforcement требует наблюдаемый workflow SHA из внешнего CI context;
  одного self-declared `workflow_sha` недостаточно.

Это structural policy, а не замена server trust predicate. Реальная eligibility
также должна проверяться server-side по repository ID, head repository ID, event,
ref/SHA, workflow source и webhook metadata.

## 5. Progress marker contract

`scripts/_progress.py` сохраняет additive marker:

```text
::ci-scope-progress:: {"step":"lint","current":1,"total":7,"detail":"...","version":1}
```

Гарантии:

- `step` обязателен и не пустой;
- `current` и `total` опциональны, но являются bounded non-negative integers;
- `current <= total`, когда оба значения заданы;
- `detail` ограничен по длине;
- secrets, bearer credentials, API keys, JWT-подобные значения и absolute paths redacted;
- schema version равен `1`;
- marker не является scheduler state и не меняет terminal job result.

Progress marker должен оставаться observability-only протоколом между gate logs и
consumer tailer. Его нельзя использовать как доказательство runner assignment,
claim, lease или GitHub terminal conclusion.

## 6. Release manifest contract

`scripts/release_manifest.py` предоставляет `validate_manifest()` для проверки
release metadata. Обязательные поля:

- `ci_gates_sha`;
- `workflow_sha`;
- deployment identity: `worker_deployment_id` for Cloudflare Worker manifests,
  or `deployment_kind: vps` with `control_plane_endpoint` for VPS manifests;
- `routing_generation`;
- `group` и `labels`;
- `progress_marker_version`;
- `release_manifest_version`;
- `activation_timestamp` с timezone;
- `rollback_target`.

Проверяется полный lowercase 40-character SHA, routing contract, версии,
timestamp и совпадение `ci_gates_sha` с ожидаемым SHA. Floating `main` не может
быть принят как release SHA.

Для control-plane migration manifest поддерживает additive metadata:

- `deployment_kind`: `cloudflare-worker` (legacy default) или `vps`;
- `control_plane_endpoint`: абсолютный HTTPS endpoint control plane; для `vps`
  поле обязательно и `worker_deployment_id` не используется.

Существующие Cloudflare manifests остаются совместимыми: отсутствие
`deployment_kind` означает `cloudflare-worker`, который по-прежнему требует
проверенный `worker_deployment_id`. Для VPS external provenance содержит
`workflow_sha` и `control_plane_endpoint` с source `vps-control-plane`; для
Cloudflare сохраняется provenance `worker_deployment_id` с source
`cloudflare-workers`. Endpoint является metadata и не меняет scheduler,
routing или gate execution contract.

Сами `workflow_sha` и deployment claim являются только claims до тех пор, пока
`scripts/release_enforcement.py` не получает внешний provenance handoff. Каждый
handoff обязан содержать для `workflow_sha` и соответствующего deployment поля
`value`, ожидаемый внешний `source`, `verified: true` и непустой `evidence_id`;
shape-only SHA/UUID/endpoint, placeholder и локально объявленный
`observed_workflow_sha` не являются proof.
Локальный fixture `tests/fixtures/release-provenance-unresolved.json` намеренно
содержит unresolved evidence и должен блокировать release. Этот репозиторий не
создаёт и не подменяет GitHub run evidence или Cloudflare deployment evidence.

Важно: validator существует в `ci-gates`, но фактический release manifest,
consumer migration matrix и deployment IDs должны быть заполнены интеграционным
агентом на основании реальных SHA всех трёх репозиториев.

## 7. Canary workflow

`.github/workflows/v2-canary.yml` — manual evidence fixture:

- использует dedicated group `ci-scope-v2-canary`;
- использует labels `self-hosted`, `macOS`, `ARM64`, `ci-scope-v2`;
- передаёт `routing-generation: v2` и `workflow-contract-version: v2`;
- включает `trust-fixture-mode: canary-only`;
- запускает два same-label jobs (`same-label-a` и `same-label-b`);
- не меняет v1 defaults и не активирует production routing.

Сам факт существования YAML и прохождения structural CI не доказывает, что в
GitHub organization реально существует корректно ограниченная runner group.
Canary необходимо запустить в реальной организации и сохранить run/job evidence.

Локальная сверка fixture pins выполнена с текущим `ci-gates` `HEAD`
`a94e73b2f0935bd11f47f269f1c18bc9469daaa4`. Это pin текущего репозитория, а не
утверждение о внешнем workflow run или Worker deployment.

## 8. Затронутые ключевые файлы

| Файл | Роль |
|---|---|
| `.github/workflows/code-linter.yml` | reusable Code Linter gate contract |
| `.github/workflows/go-quality.yml` | reusable Go gate contract |
| `.github/workflows/python-quality.yml` | reusable Python gate contract |
| `.github/workflows/slop-review.yml` | reusable review gate contract |
| `.github/workflows/swift-compile.yml` | reusable Swift compile contract |
| `.github/workflows/swift-quality.yml` | reusable Swift quality contract |
| `.github/workflows/unity-quality.yml` | reusable Unity gate contract |
| `.github/workflows/web-quality.yml` | reusable Web gate contract |
| `.github/workflows/v2-canary.yml` | manual v2 canary fixture |
| `scripts/gates_contract.py` | canonical routing validation |
| `scripts/workflow_policy.py` | workflow trust/routing structural policy |
| `scripts/release_manifest.py` | release manifest validation |
| `scripts/_progress.py` | progress marker schema, bounds and redaction |
| `tests/test_gates_contract.py` | routing positive/negative tests |
| `tests/test_workflow_contract.py` | all reusable workflow inputs/defaults/guards |
| `tests/test_workflow_policy.py` | trust and pinning policy tests |
| `tests/test_release_manifest.py` | manifest fail-closed tests |
| `tests/fixtures/release-provenance-unresolved.json` | deterministic missing/unverified external evidence fixture |
| `CI_SCOPE_V2_GATES_ROLLBACK_RUNBOOK.md` | Gates-local rollback and evidence runbook |
| `tests/test_progress_scripts.py` | marker schema/redaction/bounds tests |
| `tests/test_workflow_ref_pinning.py` | ref fetch, SHA and detached checkout tests |
| `CI_SCOPE_V2_GATES_PLAN.md` | gates scope, phases, test strategy and DoD |

## 9. Verification evidence

### Local verification

На итоговом состоянии были выполнены:

```text
python3 -m unittest discover -s tests -p 'test_*.py' -q
Ran 902 tests ... OK (skipped=1)

python3 scripts/check-test-discovery.py --start-directory tests --pattern 'test_*.py'
Test discovery: 64/64 test module(s), 902 test case(s).

python3 scripts/code-linter.py --config .code-linter.json --mode all
Code Linter passed: scanned 148 file(s) in all mode.

ruff check --config configs/ruff-strict.toml scripts tests
All checks passed.

ruff format --check --config configs/ruff-strict.toml scripts tests
135 files already formatted.

go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
exit 0

python3 -m compileall -q scripts tests
git diff --check
```

После изменения кода также выполнен `graphify update .`; граф репозитория
обновлён до 1775 nodes и 3427 edges.

### GitHub CI

Для PR #64 после исправления запущен run `31713357185`, job `94491745569`.
`Self Check` завершился успешно. Зелёными были:

- Python syntax;
- test discovery;
- unit tests;
- Python line/branch coverage;
- Code Linter;
- Ruff;
- workflow syntax;
- whitespace checks.

CI annotations от негативных тестов валидаторов являются ожидаемыми diagnostics;
job завершился `SUCCESS`.

## 10. Что должен проверить интеграционный агент

### Обязательная cross-repository matrix

Заполнить фактическими значениями:

| Поле | CI-Scope | CI-Scope-Web | ci-gates |
|---|---|---|---|
| repository SHA | required | required | `a94e73b2f0935bd11f47f269f1c18bc9469daaa4` |
| workflow SHA | required | n/a или required | required |
| ci-gates SHA | required | n/a | `a94e73b2f0935bd11f47f269f1c18bc9469daaa4` |
| routing generation | v1/v2 | v1/v2 | v1/v2 contract |
| runner group + labels | required | n/a | v2 values above |
| progress marker version | required | consumer compatibility | `1` |
| rollback target | required | required | previous approved SHA |
| activation timestamp | required | required | required |

### Проверить до activation

- Consumer workflows реально передают inputs с теми же именами и типами.
- v1 defaults не были изменены непреднамеренно.
- v2 consumer использует exact `group + labels + generation` из этого отчёта.
- Production workflows используют pinned `ci-gates` SHA, а не floating `main`.
- Server generation barrier принимает и проверяет ту же routing generation.
- Один `githubJobKey` не получает более одного active scheduler owner.
- External fork, `pull_request_target` с untrusted head и missing source metadata дают deny/quarantine.
- Workflow source SHA и reusable workflow origin входят в server trust predicate.
- Progress marker читается как observability-only и не влияет на scheduler/terminal state.
- Same-label jobs, requeue, rerun и queued → in_progress → queued → completed проверены live или GitHub-shaped fixtures.
- Existing queued/leased/assigned v1 jobs получили явный drain/adopt/cancel/re-run/quarantine disposition.
- Webhook mutation owner, scheduler authority и rollback owner назначены однозначно.
- Все affected checks трёх репозиториев terminal and green перед release gate.

### Нельзя считать доказанным только по этому репозиторию

- наличие runner group и её GitHub restrictions;
- server-side authorization по repository/head repository/event/ref/SHA;
- отсутствие duplicate webhook consumers;
- правильность DO/D1 authority и lease fencing;
- поведение Agent при restart, sleep/wake, network partition и stale session;
- adoption/rollback уже созданных GitHub jobs;
- 24-hour canary soak и production rollback drill.

## 11. Итоговый handoff

`ci-gates` готов передать интеграции следующие стабильные значения:

```text
ci-gates SHA: a94e73b2f0935bd11f47f269f1c18bc9469daaa4
v2 generation: v2
v2 group: ci-scope-v2-canary
v2 labels: [self-hosted, macOS, ARM64, ci-scope-v2]
workflow-contract-version: v2
progress marker version: 1
canary fixture mode: canary-only (canary only)
rollback runbook: [CI_SCOPE_V2_GATES_ROLLBACK_RUNBOOK.md](CI_SCOPE_V2_GATES_ROLLBACK_RUNBOOK.md)
```

Итоговая release readiness может быть объявлена только после совместной проверки
client, server и gates DoD, заполнения migration matrix фактическими SHA,
проверки authority barrier, state adoption ledger, live trust fixtures,
rollback evidence и terminal green checks всех трёх репозиториев.
