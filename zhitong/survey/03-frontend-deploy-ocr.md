# Survey of /home/user/zhitong-cost-ai: frontend, deploy, OCR, CI, agent-like code

I did not modify anything and did not read any .env file. I read `.env.example` and `deploy/*.example` with values masked. Root = `/home/user/zhitong-cost-ai`. FE = `前端/frontend` (a Vue 3 + Vite + ant-design-vue renderer, about 58k lines under `src/views/project` and `src/views/aiHome`). It was an Electron app and is being Web-ified.

## 0. Corrections to what you were told
- **Verify gates:** the README and `.kb/testing.md` say 11 gates. There are actually **95 `*.check.ts` files** in `FE/scripts/verify/`, and CI globs all of them. The "11" are the named ones in `.kb/testing.md` (listed in section 1.3).
- **Chat tiers:** the README says "四档路由". `FE/src/parts/aiChat/scope.ts` has **3 tiers**: general, knowledge and currentProject. The "pure writing" tier was deleted (H1-3).
- **OCR engine:** `deploy/README.md` says "PaddleOCR". The running service is **RapidOCR on onnxruntime**, using PP-OCR models.
- **Which skills are "real":** the 63 chat "skills" are catalog labels only. Only the 8 "写作" skills (f01-f08) change behavior, by selecting a writing system prompt (see section 6).

## 1. Frontend

### 1.1 Route map
All routes are in `FE/src/router/routerMap.ts`, under `/layout` (the "YiduCloud" shell, hash router).

- **Public:** `/login`, `/trial`, `/reload`, `/middle`, `/online` (OnlyOffice editor), `/rfiw` (report-form window), and a 404 catch-all.
- **Top-level pages:** `/aiHome` (default landing page), `/home` (project files), `/template`, `/knowledgeBase`, `/personalSpace`, `/recyclebin`, `/setting`, and `/user/{list,company,:id}` (admin only).
- **`/project/*`:**
  - `list`, `:id` (project home)
  - `report`, `reportForm`, `memberManagement`
  - `summaryInfo` (摘要对比), `aiReview` (资料审阅: 标注 + 齐套)
  - `dashboard`, `tkControl` (投控)
  - `costai` (workbench), `costai/estimate/wizard`, `costai/estimate/result`
- **Project home** (`views/project/detail/Index.vue`):
  - It is a desktop-style grid of 9 icon "apps": file, member, brief, aiReview, report, form, dashboard, tkControl, costAi. You double-click an icon to open it.
  - The icon to route mapping is `views/project/list/pageMap.ts`. The `project.home.function` config row in the customer DB decides which icons appear.
  - It also has a free-text project chat input (`AIAssistantInput`) that opens a floating chat bubble (`ProjectChatBubble`). The bubble searches only that project's files.
- **Menu:** hard-coded in `parts/layout/menu.ts`, with 8 first-level items.
- **Roles:** the route layer does almost no role checks. Real authorization is on the backend, plus a project-level `myAccess.auditor` flag that gates AI资料审阅.

### 1.2 AI screens: step-by-step flows
Almost every capability uses the same pattern: button, then optional picker modal, then async engine task, then polling, then a result drawer or table, then edit/review, then export.

**AI 首页对话** (`views/aiHome/Index.vue`)
- The user picks a scope: 通用, 知识库, or 当前项目.
- Optional: pick one of 63 skills from `SkillPicker`, and attach files. Attachments are uploaded through the same sliced uploader as project files.
- Send a message. The answer streams over SSE. Reference pop-overs and a "process steps" panel are rendered from the stream.
- A stop button aborts the stream. Each turn is saved through `/nas/aiChatHistory/save`. A left menu lists history sessions.

**文件树导航** (a mode of chat, not its own screen)
- It is the "当前项目" or "知识库" tier. The agent is `engine-service/app/filetree/agent.py`, covered in section 6.
- The user sees "plan/step" frames as a process-steps panel, then an answer with `[ID:k]` citations.

**摘要对比** (`views/project/summaryInfo/Index.vue`, titled "项目概要")
1. Open the app (double-click).
2. Click "AI 智能提取". If the backend returns a stage list (sign-off switch on), first pick stages and fields in `AiExtractButton`. Otherwise it runs the 14-field legacy extract directly.
3. Wait. A drawer shows the task banner and polling progress. Closing the drawer does not stop the task.
4. Review the fields table: value, quote, source file, verify level, conflicts and candidates.
5. Per field: edit (modal), adopt a suggestion, or confirm a candidate (`ConfirmCandidateModal`). The history drawer is also per field.
6. Export Excel (`/costai/summary/export`, a browser download).
- Page cues: "只看未填" filter, category nav with `filled/total` counts, and a "上次提取后新增 N 份资料" stale banner.
- A candidate field can need ~2 clicks, so 14 fields is up to ~28 clicks.

**资料标注** (`views/project/aiReview/components/AiTagButton.vue`)
1. Open the aiReview app. This needs `auditor` access, otherwise a "no permission" modal appears.
2. Click "AI 智能标注". If there is no previous result it starts directly, with no selection.
3. A wide drawer shows a table with columns: file, category, stage, confidence, reason, status.
4. Per row: 确认 / 改标 (modal with two selects, category and stage, then 保存) / 否决 (popconfirm) / 撤销.
5. There is no export here. The output feeds 齐套核查.

**齐套核查** (`AiAuditButton.vue`)
- It hard-depends on tags. With no valid tags it shows "请先点「AI 智能标注」".
1. Click "AI 智能核查" to open the drawer. If a stage cannot be inferred, a dropdown asks for one ("全部阶段" is allowed).
2. Click 开始核查 / 重新核查 and wait.
3. Read the coverage rate, covered/pending/advisory counts, and the missing-items table, across `AuditEvidenceTabs`.
4. You can fix tags inline. A banner then says "标签改过 → 重新核查".
- The tree page (`aiReview/Index.vue`) shows directory review state. There is also a per-node "设置审阅项" modal, a comment modal, a NotifyOthers modal, and a "档案移交书" generator.

**数据核对 and 指标计算** (`views/project/reportForm/Index.vue` hosts both buttons; components are `AiReconcileButton.vue` and `AiIndicatorButton.vue`)
- Reconcile:
  1. Click 数据核对. `CostsheetFilePicker` opens.
  2. Choose the 送审 Excel and the 审定 Excel plus a "basis" (the picker pre-ticks the previous same-type task).
  3. Click 开始核对 and wait.
  4. A 1400px drawer shows summary cards, warning buckets and 5 status tags. It also has a keyword box, a unit-project select, and a "只看有标记" checkbox. The table is paged with a 2300px horizontal scroll.
  5. Export xlsx (with an optional "只导出有差异的行").
- Indicator:
  1. Click 指标计算 and the same picker opens, this time with different files.
  2. Optionally enter gross area and total tax-inclusive cost.
  3. Click 开始计算 and read the result drawer.
  4. Export xlsx.
- Both buttons also show a "上次结果" link. The original OnlyOffice report editor iframe is disabled by default (`reportForm/Editor.vue`).

**全过程投控** (`views/project/tkControl/Index.vue`)
1. Click "AI 异常检测". The picker opens. Pick 送审 xls/xlsx files, and optionally a contract list (a second group) plus a basis.
2. Wait.
3. The page shows alignment conflicts and suggestions, then tabs per anomaly type with filters (type, keyword, etc.).
4. Per anomaly: 复核 (modal with a decision and an optional reason) or a batch "判为误报". There is a per-anomaly log drawer and a project-level 复核记录 drawer. Re-detection marks stale reviews.
5. Export xlsx of anomalies plus review trail.
- Review access is role-gated.

**报告生成** (`views/project/report/components/aiDraft/AiDraftModal.vue`)
1. Open the report page and click AI 起草.
2. Step 1: choose 1 of 24 templates. These come from `engine-service/app/engine/data/report_templates.yaml` (24 templates, 172 sections).
3. Step 2: pick source files (`SourcePicker`, with a candidate limit).
4. Step 3: tick "claims" (procedural statements) to confirm. Unticked ones are written as 【待核】.
5. Step 4: generation runs in the background, polled every 3 s. Each section shows a state tag, a note, and a "reused from last time" label.
6. Per section: 复制 or 重新生成本章. Then export Word (`/costai/report/{id}/export`).
- A separate older path, `generateTempAndReportModal`, makes a report from an uploaded file template (a save-location and file-template form).

**算量清单** (`views/project/costAi/Index.vue`, `QuantityResultPanel.vue`)
1. In 项目资料 (the file page), box-select the design-instruction files.
2. Click the toolbar button "造价AI · 生成清单框架". The page jumps to the 造价AI workbench, carrying the selected file ids through `sessionStorage` (this is what the `incomingFiles` list is).
3. Optionally remove files with the × button.
4. Click 生成清单框架 and wait.
5. The result panel shows counts, coverage, and a filterable "待核/未匹配" table. Download the xlsx or "到项目资料页定位".
- Scope: GB50854 (zj2025), 房建 sections 0101-0118 only. The quantity column is always left blank.

**概算向导** (an eleventh capability you did not list: `costAi/estimate/Wizard.vue`, 4090 lines, plus `estimateModel.ts` at 2659 lines and `Result.vue`)
- Five steps: 工程结构, 经济技术指标 (three input channels: manual, AI extract, Excel import), 费用明细 (forward calculation with fee suggestions to adopt), 计算参数, 生成.
- The draft is stored only in the browser's localStorage. The result is a true-formula xlsx to download.

**驾驶舱** (`views/project/dashboard/Index.vue`)
- Read-only aggregates: KPI cards, per-capability latest task, anomaly distribution, AI usage table.
- Each card or row is a link into the relevant app.
- It re-fetches every 5 s, up to 24 times, while any task is active (`summaryPolling.ts`).

**Supporting UI that is not AI:** project list/detail/members/permissions, file tree with versions and locks, templates, knowledge base, personal space, recycle bin, settings, and user/company/workload admin (the `/user` routes), plus OnlyOffice integration.

### 1.3 Manual-step count and redundancy evidence
- **Rough click count for a full project audit.** This is my estimate from the code, not a measurement. Upload, then at least 11 separate "open app, click, pick, wait, review, export" cycles across summary, tag, audit, reconcile, indicator, tkControl, report, quantity and estimate. That is about 60-150 clicks for a typical project, dominated by per-row tag review and per-anomaly review.
- **Re-selecting files.**
  - 数据核对, 指标计算 and 投控 each open the same `CostsheetFilePicker`, and selection is not shared between capabilities.
  - Pre-ticking only reuses the last completed task of the same type (`costsheetFiles.ts` `presetSelection`). A "basis" must also be re-chosen, and the failure case has its own "改用自动口径重新选择" retry.
  - The quantity feature has a third mechanism: the `sessionStorage` handoff from the file page.
- **Stage re-entry.** The stage is chosen separately in 摘要提取 (when staged) and in 齐套核查. It can be inferred, but when inference fails the user must pick one.
- **Ordering dependency.** 齐套核查 refuses to run without 标注, so the user must run capabilities in a fixed order by hand.
- **Estimate data is re-entered.** `Wizard.vue` has no link to the 摘要 fields (a grep for summary/概要/摘要 in `Wizard.vue` finds nothing). It does its own `estimate/extract`, and the fields (area, etc.) are re-entered or re-extracted, so token cost and effort are paid twice.
- **Context passing between apps.** Navigating between apps rebuilds an 8-key query every time (`utils/projectApps.ts`: id, projectId (duplicate), folderPath, projectName, companyId, effectPictureUrl, projectPermission, templateId).
- **Revisit machinery.** "上次结果" links, `peekLatest`, and the dashboard task list exist because results are scattered across 8 drawers and each page re-implements "latest task / latest failure / previous result" banners.

### 1.4 The named verify gates (`FE/scripts/verify/`)
All run as `tsc` single-file compile, then `node`.

| Gate | What it protects |
|---|---|
| `attribution.check.ts` | Chat answer segments: sentences without a source are flagged "no basis" |
| `deployParity.check.ts` | The Vite dev proxy and the nginx template have the same location list in both directions; `/ragapi` still rewrites to `/engine` and injects the token; `proxy_buffering off` |
| `draggable.check.ts` | vuedraggable v4: real SSR render plus `item-key` / `#item` scans |
| `endpoints.check.ts` | Managed domains are hard-coded only in `src/config/endpoints.ts` (plus the Electron baseline) |
| `ipcFallback.check.ts` | Wrapper for `scripts/verify-ipc-fallback.mjs` (Web mode ipc fallback), so it runs in CI |
| `loginBaseUrl.check.ts` | Login baseURL allow-list (blocks sending credentials to an arbitrary http address) |
| `messageState.check.ts` | Chat message status machine (a stopped message cannot become done) |
| `planStep.check.ts` | Rendering of plan/step frames |
| `reconcileTable.check.ts` | Reconcile drawer wiring, logic, pagination liveness and filtering |
| `scope.check.ts` | Chat scope to request-parameter mapping |
| `skills.check.ts` | Skill snapshot is exactly 63 skills in 8 groups |

Gate types in the other ~84: endpoint/route contracts, XSS and innerHTML safety, `catchSwallow`, i18n/Chinese wording, task-state/polling rules, tenant-registry, deploy and compose consistency (`deployComposeBase`, `deployNonRoot`, `imageTagConsistency`, `httpsRedirect`, `deployDatedTenantCensus`), and per-feature semantics. CI also runs 124 files in `FE/tests/unit` (vitest + `@vue/test-utils`, mounting components for real).

## 2. How the frontend talks to the backend

- **REST:**
  - `FE/src/api/request.ts` creates an axios instance with baseURL `${company server}/nas`, a 60 s timeout, and a Bearer token from localStorage.
  - Retry happens only for `/login` on a network error. Only a real 401 or `code:401` logs the user out; 403 does not.
  - Some calls override the timeout (estimate compute, quantity generate, file download at 5 min).
  - The Java side is the only writer to MySQL.
- **Main `/nas/costai/*` endpoints** (`FE/src/api/costai/*.ts`):
  - Start/result pairs (async task id plus polling):
    - `extract/start` and `extract/result`
    - `tag/start`, `tag/list`, `tag/review`, `tag/vocabulary`
    - `audit/start`, `audit/result`, `audit/stages`
    - `reconcile/start` and `reconcile/result`
    - `indicator/start` and `indicator/result`
    - `tk/detect`, `tk/anomalies`, `tk/review`, `tk/review/batch`
    - `quantity/generate` and `quantity/result`
    - `estimate/{template,extract,extract/result,suggest,compute,result}`
  - Summary: `summary/{overview,edit,confirm,extract-sources,history,export}`.
  - Report: `report/{templates,candidates,start,list,{id},{id}/sections/{code}/retry,{id}/export}`.
  - Others:
    - `costsheet/{candidates,candidates/probe,task-view}`
    - `reconcile/export` and `indicator/export`
    - `tk/{anomalies/export,anomaly/logs,decision-logs}`
    - `tasks`, `tasks/detail`, `dashboard/summary`
  - Chat history: `/nas/aiChatHistory/{sessions,messages,delete,save}` plus company-level queries.
  - File and project APIs (about 230 endpoints in total): `/file/*`, `/project/*`, `/knowledgeBase*`, `/personalSpace*`, `/recycle*`, `/user*`.
- **SSE:**
  - Only chat uses SSE. `api/aiChat/index.ts` `sseRequest` uses `@microsoft/fetch-event-source` to POST `${baseUrl}/ragapi/chat/complete`.
  - The body includes: sysCompanyCode, messages (last 10 turns), query, module, retrieval_mode, project_ids, businessId, session_id, user_id, skill_id and attachment_file_ids / attachment_paths.
  - The frontend adds an `X-Rag-Project-Id` header (self-reported, verified server-side).
  - Frames are OpenAI-like: `choices[0].delta` plus extras (`plan`, `step`, `attribution`, `reference.chunks`). A top-level `usage` and `nav` ride on the last frame, then `data: [DONE]`.
- **`/ragapi` bypass:**
  - Nginx `location /ragapi` first calls `auth_request /__ragapi_auth` (which rewrites to Java `/nas/authCheck/ragapi`).
  - It then copies back the verified `X-Sys-Company-Code`, `X-Rag-Sftp-User` and `X-Rag-Project-Id` headers.
  - It rewrites `/ragapi` to `/engine`, injects `X-Service-Token`, and proxies straight to engine :8900 with `proxy_buffering off` and a 3600 s read timeout.
  - So chat is not bridged by Java, and Java does not write the chat log; the frontend calls `/nas/aiChatHistory/save` after `[DONE]`.
  - `README.md` says this still lets a logged-in user in tenant A read tenant B's files. Only the "no-login" hole was closed (#445, #446).
- **Polling:**
  - `utils/composables/useEngineTask.ts` is the single poller. It polls every 2 s for the first 30 s, then every 5 s.
  - The soft limit is the server deadline plus 60 s, after which the phase becomes `detached` (not failed). 5 consecutive network errors also detach.
  - Terminal states come only from `utils/engineTaskState`.
  - Other pollers: quantity (2 s × 30), the report draft modal (3 s), the dashboard (5 s × 24), and upload-merge status checks.
- **File upload** (`parts/file/transfer/index.ts` plus `api/file/index.ts`):
  - The file is hashed (sha256), then `checkCacheExists` skips re-upload when the content is already present.
  - It is sliced into **5 MB chunks** and sent with `uploadFileSlice` (multipart). Then `mergeSliceFile` is called and `checkMergeFileStatus` is polled.
  - Progress and records are kept in IndexedDB. Nginx `/upload` has `proxy_request_buffering off`, and `client_max_body_size` is 200m.
  - Chat attachments go through the same uploader.
- **Web vs desktop:** `utils/ipcRenderer.ts` gives Web fallbacks for Electron-only calls. `scripts/verify-ipc-fallback.mjs` checks them.

## 3. deploy/

### 3.1 `deploy/docker-compose.prod.yml` (project name `zhitong`, network `zt`)
Five long-running services, plus `*-build` services under the `build` profile:

| Service | Image | Port | Volumes | Memory |
|---|---|---|---|---|
| `mysql` | `mysql:8.0` | internal 3306 | `/opt/zhitong/data/mysql`, `/opt/zhitong/backup:/backup` | 2g (buffer pool 1G) |
| `app` | `tg-app:prod` (or `APP_IMAGE_T1`) | 9600 internal | `/opt/zhitong/data/nas-data` (rw, also `/work`), `/opt/zhitong/logs/app` | 5g (`-Xms1024m -Xmx3584m`) |
| `engine` | `tg-engine:prod` (or `ENGINE_IMAGE`) | 8900 internal | `nas-data:/data:ro`, `/opt/zhitong/data/llm-cache:/cache` | 2g |
| `ocr` | `tg-ocr:prod` (or `OCR_IMAGE`) | 8901 internal | `nas-data:/data:ro` | 3g |
| `nginx` | `nginx:1.25-alpine` | 80, 443 | `./nginx/conf.d`, `/opt/zhitong/nginx/{ssl,html}`, `/opt/zhitong/logs/nginx` | 256m |

- The sum of limits is 12.25g against a cap of 13.5g, declared in `deploy/host-capacity.conf` (4C16G host). A second tenant requires lowering app to 3g first.
- The `app` container uses `eclipse-temurin:17-jre-jammy`, with LibreOffice and CJK fonts for office conversions. The JAR is built with JDK8 outside Docker.
- Target host: a Volcano Engine ECS single machine named `zhitong-prod-web`.
- **Not in compose:** RocketMQ (the compose file only points `--rocketmq.name-server` at a default `127.0.0.1:9876`; README says it is not deployed, which affects async ingest), and the OnlyOffice document server (a separate `oo5-prod` container the README expects).

### 3.2 nginx
- **Single source of truth:** `FE/deploy/nginx.conf.template`. `deploy/nginx/conf.d/00-http-tuning.conf` is http-level tuning only; its header says it deliberately has no locations.
- **Locations:** `/` (static SPA with `try_files`, with security headers including a CSP), `/nas`, `/upload` (unbuffered request), `/personalSpaceFile`, `/v`, `/p` (all proxy to Java), `/ragapi/health`, `/ragapi`, and the internal `/__ragapi_auth`. HTTP redirects to canonical HTTPS.
- **Rendering:** `FE/deploy/render-nginx.sh` runs `envsubst` with an explicit whitelist of variables: `TG_LISTEN`, `TG_SERVER_NAME`, `TG_WEB_ROOT`, `TG_JAVA_UPSTREAM`, `TG_ENGINE_UPSTREAM`, `TG_ENGINE_SERVICE_TOKEN`, the SSL variables, `TG_CANONICAL_HOST[_RE]` and `TG_HTTPS_REDIRECT`.
- **Safety checks:** `deploy.sh render` asserts `/ragapi` is present and no `${TG_` remains. The rendered `10-site.conf` contains the engine token in plaintext, is chmod 600, and is gitignored.
- **Per tenant:** `deploy/gen-nginx-tenant.sh` renders another server block with `TG_LISTEN=<TN_PORT>` and `TG_JAVA_UPSTREAM=http://app-t<code>:9600`.

### 3.3 `deploy/deploy.sh` subcommands
`check`, `build [svc…]`, `stamp-version`, `tag-version`, `render`, `verify-gate`, `verify-routes`, `verify-app-route`, `verify-images`, `reload-nginx`, `up` (check + render + start), `initdb`, `backup-status`, `logs`, `status`, `down`.
- Images get immutable sha tags from `deploy/VERSION`, with a refusal to silently re-tag.
- The server has no `.git`: the repo is rsynced to `/opt/zhitong/app`.
- A usage-block vs `case` consistency check is enforced by `deployComposeBase.check.ts`.

### 3.4 Credential generation
`deploy/gen-secrets.sh` uses `openssl rand` to print 40-char strings for: `DATABASE_PASSWORD`, `JWT_SECRET`, `DRUID_STAT_LOGIN_PASSWORD`, `OO_JWT_SECRET`, `ENGINE_SERVICE_TOKEN` and `OCR_SERVICE_TOKEN`. `DEEPSEEK_API_KEY` is filled in by hand.

### 3.5 Backups
- **Schedule:** `deploy/systemd/zt-mysql-backup.timer` fires daily at **02:30** (`Persistent=true`). It runs `deploy/backup-nightly.sh` with `TimeoutStartSec=3h`.
- **Sequence:** nightly waits for mysql to be ready, then calls `mysql-backup.sh`, which does:
  - `mysqldump` per database via `docker exec`, with `--source-data=2`, gzip, then verify (`gzip -t`, header and tail check).
  - Publish atomically as `<db>-<YYYY-MM-DD>.sql.gz` into `/opt/zhitong/backup`.
  - Keep 7 days (`TG_BACKUP_KEEP_DAYS`), only for databases that produced a fresh backup.
  - Orphan thresholds (20 files / 1024 MB) turn the exit code into 3.
  - A directory lock prevents concurrent runs.
- **Offsite:** `backup-offsite.sh` uploads the same day's dumps to a **Volcano TOS private bucket** through `deploy/tos-backup-upload.py`.
  - Object key is `<TOS_PREFIX default mysql/><db>/<db>-<date>.sql.gz`.
  - It reads back the object size via `head_object` and compares with the local size.
  - The upload account has no delete permission; expiry is a bucket lifecycle rule (30 days) with versioning.
  - The credential file is `/opt/zhitong/app/deploy/.tos-backup.env`, which must be root-owned with mode 600. Its keys are `TOS_BUCKET`, `TOS_REGION`, `TOS_ENDPOINT`, `TOS_ACCESS_KEY_ID` and `TOS_SECRET_ACCESS_KEY`.
  - `backup-offsite.env.example` has non-secret keys only: `OFFSITE_MODE` (tos or rsync), `TOS_CRED_FILE`, `TOS_PREFIX`, `TOS_PYTHON`, `RSYNC_DEST` and `RSYNC_SSH_KEY`. It refuses credential-looking keys.
- **What is NOT backed up:** only MySQL dumps go to TOS. I found no backup of `/opt/zhitong/data/nas-data` (the files and `.ocr.txt` sidecars). The README says a disk loss would take the DB and local backups together, which is why offsite exists, but there is no equivalent for the file store. I grepped the README, so this is likely but not certain.
- **Watchdog:** `deploy/upstream-watchdog.sh` runs every 5 minutes via a systemd timer. It probes `/ragapi/health` through nginx and reloads nginx when upstreams have gone stale.
- **Alerting:** the optional `TG_BACKUP_ALERT_CMD` hook writes to `backup-alert.log`. `./deploy.sh backup-status` reports the result.

### 3.6 Tenant pattern
- `deploy/tenants/<code>.env`: copy of `3.env.example`, gitignored, chmod 600. It holds per-tenant values only: `TN_CODE` (new codes start at 3; 1 and 2 are reserved), `TN_COMPANY_NAME`, `TN_DB_NAME`, `TN_PORT` (convention 8080+code), `TN_SERVER_NAME`, `TN_PUBLIC_BASE_URL`, the per-tenant `JWT_SECRET` and Druid password (separate secrets per tenant), and `TN_ADMIN_PASSWORD_HASH` (BCrypt).
- Shared secrets stay in `deploy/.env` only.
- `deploy/tenant-add.sh <code>` automates steps 0-10 (it does not touch the firewall, and it prints the registry upsert command instead of running it).
- `deploy/gen-compose.sh` generates `docker-compose.tenants.yml` (one `app-t<code>` container per tenant, same engine/ocr/mysql). `tenant-lib.sh` holds shared helpers.
- This is **one app container and one MySQL database per tenant**, with shared engine, OCR and nginx.

### 3.7 `.env.example` variable names and purposes (values not shown)
- **Core secrets:** `JWT_SECRET` (app token signing), `OO_JWT_SECRET` (OnlyOffice JWT), `DRUID_STAT_LOGIN_PASSWORD`, `DRUID_STAT_LOGIN_USERNAME`.
- **DB:** `DATABASE_PASSWORD`, `DATABASE_USERNAME`, `TABLE_SCHEMA`. (Compose also uses `DATABASE_NAME`.)
- **MinIO:** `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`.
- **OCR vendors for the Java side:** `BAIDU_SEAL_API_KEY`, `BAIDU_SEAL_SECRET_KEY`, `BAIDU_TEXT_API_KEY`, `BAIDU_TEXT_SECRET_KEY`, `OCR_SPACE_API_KEY`.
- **Other third parties:** `KIMI_TOKEN`, `VIKA_API_TOKEN`, `OMV_USERNAME`, `OMV_PASSWORD`, `CUSTOMER_USER_KEY`.
- **WeCom alert webhooks:** `WECOM_WEBHOOK_KEY`, `WECOM_WEBHOOK_KEY_MONITOR`, `WECOM_WEBHOOK_KEY_DEV`.
- **Engine link:** `ENGINE_SERVICE_TOKEN`.
- **Tenant platform:** `TENANT_PLATFORM_CODE` (commented out on purpose).
- **Deploy-script DB creds:** `DEPLOY_DB_USER`, `DEPLOY_DB_PASSWORD`, `DEPLOY_DB_HOST`, `DEPLOY_DB_NAME`, `DEPLOY_DB_PORT`.
- **Code generator:** `GENERATOR_DB_HOST`, `GENERATOR_DB_USER`, `GENERATOR_DB_PASSWORD`.
- **Referenced in compose and engine config:**
  - LLM: `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`.
  - OCR link: `OCR_SERVICE_TOKEN`.
  - Parse limits: `EXTRACT_PARSE_PROCS`, `EXTRACT_PARSE_MEM_MB`, `EXTRACT_PARSE_TIMEOUT_SEC`, `EXTRACT_MAX_FILE_MB`, `EXTRACT_MAX_PDF_PAGES`, `GRID_MAX_SHEET_XML_MB`, `EXTRACT_TOKEN_BUDGET`, `EXTRACT_FILE_TOKEN_SHARE`, `TAG_LLM_TOTAL_SEC`.
  - RocketMQ: `ROCKETMQ_NAME_SERVER`, `ROCKETMQ_PRODUCER_GROUP`.
  - App flags: `SPRING_PROFILE`, `TENANT_REGISTRY_WRITE_ENABLED`, `TG_COSTAI_SUMMARY_STAGED_FIELDS_ENABLED`, `TG_COSTAI_SUMMARY_STAGED_FIELDS_PREVIEW_PROJECT_IDS`.
  - Run-as: `APP_RUN_AS`, `APP_UID`, `APP_GID`.
  - Image pins: `APP_IMAGE_T1`, `ENGINE_IMAGE`, `OCR_IMAGE`.

## 4. ocr-service (`/home/user/zhitong-cost-ai/ocr-service`)

- **API:**
  - `POST /ocr/recognize`, authenticated by `X-Service-Token`.
    - Request: `{content_b64, file_name, lang?, max_pages?, deadline_ms?}`.
    - Response: `{text, pages, engine, engine_version, latency_ms, total_pages, truncated, stop_reason, page_texts}`.
    - Errors: 401 (bad token, with a message when the token was randomly generated), 413 (too large, default 30 MB), 422 (unsupported format), 503 (queued past the deadline).
  - `GET /health` is unauthenticated, used for HEALTHCHECK.
  - Inputs: PDF (magic-byte detection, rendered per page with pypdfium2 at scale 2.0) and bitmaps (png, jpg, bmp, tiff, webp).
  - Contract: `engine-service/docs/契约-ocr-service-v1.md` (v1.1 adds `deadline_ms`).
- **Weights:**
  - RapidOCR 3.9.2 (version pinned) running on onnxruntime ≥1.29. Default models are PP-OCRv6 small detection and recognition, plus PP-OCRv4 mobile classifier.
  - The weights are baked into the image at build time by `warmup.py`, so there is no network at runtime.
  - The image is about 272 MB (python:3.11-slim, non-root user 10001) and works on both arm64 and x86.
  - The engine name and version (`RapidOCR-PPOCRv6`, plus the rapidocr package version) go into cache keys. Upgrading the pin invalidates the cache.
- **Performance:**
  - The code comments claim about 0.6-1 s/page on arm64 dev. The contract says **2.1-4.1 s/page was measured in production**, and a 50-page PDF hit the 120 s client timeout.
  - Inference is **serialized per instance** by a module-level lock; scale out with more instances.
  - The engine client slices PDFs into chunks of up to 6 pages (`OCR_CHUNK_PAGES`) and uses a per-request budget (`OCR_REQUEST_BUDGET_SEC`, default 60).
  - A circuit breaker trips on the first service failure, but an empty OCR result does not trip it.
- **The four-state chain** (`engine-service/app/text_chain.py`, `textextract.pdf_text_with_sidecar`):
  - Order: `text_layer` → `ocr_sidecar` → `ocr_service` → `none`.
  - It degrades **per page**: native text pages are used directly, truly blank pages are skipped, and the remaining pages are taken from the sidecar, then sent to the OCR service.
  - The source is always returned (`text_source`, plus page and truncation info). OCR-sourced fields are forced to `needs_manual=true`.
  - Caches: a per-process content-hash cache, plus a per-page OCR cache keyed by (sha256, page, engine, version, scale).
  - Heavy parsing can run in an isolated subprocess (WS22-h, extract only).
- **Sidecar storage:**
  - A sidecar is a file named `<原文件名>.ocr.txt` **next to the original on the NAS** (`/opt/zhitong/data/nas-data`).
  - The format is paged text. It has a header with the original path, type, engine (the existing 2882 production sidecars say `paddleocr-vl-1.6`) and page counts. Each page then has a `## pN` anchor, a quality line (chars, abnormal-char %, verdict), the text, and sometimes OTSL table markup.
  - Parsed by `engine/sidecar_format.py`. Verdicts `ok`, `thin` and `repetitive` are usable; failed, empty and garbled pages fall through to live OCR.
  - Nothing in production writes sidecars at runtime, because Java does not and engine/ocr mount the NAS read-only. They are made by the offline tool `engine-service/app/tools/ocr_backfill.py` (`new` and `refill` modes, resumable, jsonl report), and an operator copies results onto the NAS by hand (`docs/运维/runbook-OCR旁车补跑.md`).
  - The reader (`files.py` `read_ocr_sidecar_doc`) includes path-escape and cross-tenant symlink checks (issue #462).

## 5. CI (`.github/workflows/ci.yml`, one workflow)
- **Triggers:** pull requests to `dev`, `main`, `feat/**` or `fix/**`; pushes to `dev` and `main`; manual dispatch. In-flight runs are cancelled.
- **Honesty rules in the file:** skipped steps must be reported explicitly (never silently green), and the final summary lists what actually ran.
- **Jobs:**
  - **engine-service:**
    - Installs requirements and LibreOffice, then runs `pytest tests/` (201 test files).
    - Followed by a silent-skip ratchet (`check_test_skips.py`, with a self-test first).
  - **ocr-service:**
    - Runs pytest and asserts at least 21 tests ran with 0 skips.
  - **frontend:**
    - `vite build`.
    - All `scripts/verify/*.check.ts` (95 files; zero files found counts as failure).
    - vitest render-level tests (a run of 0 passed counts as failure).
  - **java-estimate:**
    - `mvn test` on a whitelist (Estimate, tk-control, seed, task-list, registry and security lanes) in a JDK8 container.
    - A ratchet (`check_java_test_coverage.py`) requires every test class to be covered, plus an assertion that tests actually ran.
  - **java-jdk17:**
    - The same tests on JDK 17, since production runs a JRE 17.
  - **secrets:**
    - gitleaks on PR commits (blocking), plus a full-history scan that only reports. Config is `.github/gitleaks.toml`.
  - **tenant:**
    - Flags new data-access code that is missing a tenant condition (`check_tenant_condition.py`).
  - **nonneedsession:**
    - Ratchet that anonymous endpoints can only decrease.
  - **typedequality:**
    - Flags type-mismatched `==` comparisons that compile but are always false.
  - **deploy-doc:**
    - README vs Dockerfile jar-path check.
  - **seedcreds:**
    - Config seeds must not contain plaintext credential values.
  - **cisummary:**
    - Reconciles the summary job's needs/conditions with the local-script coverage.
  - **pr-base:**
    - Fails when a PR targets the wrong base.
  - **landed:**
    - Audits recently merged PRs ("MERGED ≠ in dev").
  - **summary:**
    - Final aggregate that fails if any job failed.
- **Extra gates:** `.githooks/` blocks direct pushes to main (installed by hand with `git config core.hooksPath .githooks`). A mutation-coverage lane (`mutation_coverage.py`) exists but is not wired as a CI job (I did not see it run in the workflow).

## 6. What is already an "agent"
- **No MCP, no tool-calling API, no runtime skill system.** I found no `tool_calls`, no `tools=[…]` and no MCP server or client in the application code. `llm_client.chat()` sends plain `messages` with `stream:false` (even chat is fake-streamed by slicing the full answer in `chat.py`), and `chat_json()` adds retry, truncation handling and a cache. LLM is DeepSeek (`DEEPSEEK_MODEL`, default `deepseek-chat`) via an OpenAI-compatible URL.
- **The one real agent loop: the file-tree navigator.**
  - Files: `engine-service/app/filetree/agent.py` (2181 lines), `tools.py` (2242), `closing.py` (2582), `answer_guard.py` (1147), `mapper.py`, `deadline.py`. Entry: `navigate(query, root, max_steps=8)`.
  - It is a **text-protocol** loop, not JSON function calling. Each step the model outputs one line with a verb: `LIST`, `OUTLINE`, `SHEET`, `DOC`, `PDF`, `GREP`, `SCAN_HEADS` or `ANSWER`.
  - The system prompt includes a "map" of the root directory (generated on the fly by `mapper.py`). The loop parses the line, executes the read-only tool, appends an observation with evidence ids like 〔E3〕, and loops.
  - Guards (hard-coded, not prompts): step budget 8 plus 4 failures, an LLM-call cap, repeat-instruction replay without charging a step, range-based read dedup, unreadable-file blocking, path auto-repair, verb/file-type rewriting, and wall-clock deadline closing.
  - On exhaustion, `closing.closing_answer` composes an answer from evidence read so far.
  - `answer_guard` then does post-processing: numbers without a source get underlined (`attribution`), sums are re-checked, citations `〔E#〕` become `[ID:k]`, and instructions inside documents are not executed (injection defense).
  - Exposed through `POST /engine/chat/complete` (modules `knowledge` and `project`) and `POST /engine/filetree/ask`.
  - `chat.py` also does follow-up rewriting, writing-skill drafting after navigation, and GB-code checks on general answers.
- **"Skills":**
  - `engine-service/app/engine/data/skills.json` and `FE/src/parts/aiChat/skills.data.ts` are generated snapshots of a 63-skill catalog from an external gateway (`zhitong-gateway/manifest.json`, not in this repo). It has 8 groups: 写作, 表格, 演示, 阅读, 沟通, 思考, 语音, 日程.
  - The only effect is that skill ids f01-f08 switch to a writing system prompt (`chat_writing.py`, `_is_writing_skill`) with date and 【待填】 rules.
  - `调研-算量层skill化评估.md` is research about wrapping an external `building-cost-estimator` SKILL.md. It reaches no conclusion that is implemented here. The quantity feature is a deterministic GB50854 lookup (`quantity_list.py`, `gb50854_zj2025.yaml`) plus LLM classification.
- **Prompt templates:**
  - Structured prompts live in the engine modules, each with a `prompt_version` (`field_extract.py`, `classify_llm.py`, `report_sections.py`, `estimate_suggest.py`, `quantity_segment.py`) and YAML data in `engine/data/*.yaml` (classify rules, report templates, summary fields, tk detection, audit evidence rules).
  - These are fixed-pipeline LLM calls (extract / classify / write a section), not loops.
- **Deterministic engines (not LLM):** reconcile, indicator, tk-detect and audit checks (`reconcile_engine.py`, `indicator_engine.py`, `tk_engine.py`, `audit_check.py`) plus costsheet parsing and the estimate computation. Rule-based, with the Java layer owning the task ledger (`engine_task`).
- **"superpowers"**: `docs/superpowers/{plans,specs}` are Claude Code planning outputs (design docs), not runtime code. `CLAUDE.md` is a contributor operating manual (branching, mutation acceptance, "real-run evidence"); there is no `.claude/` skills folder in this repo.

## 7. Assessment: what needs structured UI vs what a chat agent could absorb

1. **Needs real structured UI (review and approve):**
   - 资料标注 review table (per-row confirm / re-tag / reject);
   - 摘要 field table (value, quote, source, conflicting candidates, adopt/edit/history);
   - 投控 anomaly review (evidence, decision, reason, batch dismiss, audit trail).
   - Reason: these are human-sign-off workflows with legal-style traceability, and each decision is written to the decision log.
2. **Needs table and diff UI:**
   - 数据核对 (thousands of rows, e.g. an 8855-row synthetic test case, five statuses, filters, red/black deltas) and 指标计算 results.
   - An agent can run them and summarize, but the table, filters and xlsx export stay structured.
3. **Needs a document or editor UI:**
   - 报告生成 section viewer (per-section status tags, 【待核】 marks, regenerate, Word export), and the 概算 wizard result.
   - The wizard's 200+ input cells are a spreadsheet job, not chat. Its estimate extract could be agent-driven, but the cell grid and "adopt this fee suggestion" step stay.
4. **Just a form around one backend call (a chat agent can absorb it):**
   - 齐套核查 (one stage dropdown plus a button; the real output is a missing-items list that a message can render);
   - 算量清单 (select files, click, download xlsx);
   - 摘要提取 trigger and stage/field selection;
   - the three file pickers, which exist mainly to say which files and which basis. An agent that knows the project tree and the last choice can fill them in.
5. **Pure navigation or aggregation, replaceable by chat plus a lightweight view:** 驾驶舱 (read-only aggregates), the project-home icon grid, the task-record "revisit" drawers, and 文件树导航 (already a chat mode).
6. **Orchestration is the real redundancy:** the fixed order (标注, then 齐套), the pickers, the stage choice, and the 8 separate result drawers exist because the user is the scheduler. This is where an agent saves the most clicks.
7. **Keep as a thin deterministic backend (do not re-implement as prompts):** reconcile, indicator, tk-detect, audit check, costsheet parsing and the estimate computation, plus the sliced upload and `engine_task` ledger. Money numbers and the "Iron Rules" (every AI extraction needs human confirmation, `needs_manual`) are deliberately code, not model output.
8. **Cost to carry over:** the repo's hard-won guards (OCR chain with per-page degradation and source tracking, answer guard against hallucinated amounts, nav budgets, tenant isolation, redaction). A harness that replaces `agent.py` must reproduce or reuse them.
9. **Operational footprint to decide:** a 5-container compose plus one app container per tenant, JRE17 plus LibreOffice, a RapidOCR sidecar serialized at about 2-4 s/page, a MySQL-only offsite backup (NAS files appear to be unprotected offsite), RocketMQ not deployed, OnlyOffice outside compose, and the `/ragapi` bypass, which has no cross-tenant isolation.
10. **Net:** keep roughly 4 to 5 structured screens (tag/field/anomaly review, reconcile/indicator table, report sections, estimate grid), and everything else becomes a chat-addressable action over the same async-task endpoints.
