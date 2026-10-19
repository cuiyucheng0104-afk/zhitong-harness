# Backend survey: yidu-nas (天工智通) + costai domain

Root: `/home/user/zhitong-cost-ai/后端` (all paths below are relative to it unless prefixed with `../`). Read-only; no `.env` files opened. Line numbers were checked against the working tree.

Two corrections to the brief up front:
- "23 tables + 19 endpoints" (`../README.md:75`) is stale. The code has 53 costai endpoints across 8 controllers. The SQL defines 21 tables in `cost-ai-schema` plus about 10 more costai-adjacent tables (listed in §2.1).
- The Python engine is reached through two separate paths. Java calls it directly (`EngineClient`). The browser also reaches it through an nginx `/ragapi` bypass that never passes through Java (§1.4).

---

## 1. Multi-tenancy, auth, roles

### 1.1 Tenant-to-database mapping
- **Code level.** One JDBC URL per app process, fixed in `bootstrap-*.yml`. For example `yidu-nas-server/src/main/resources/bootstrap-product.yml:9` points at `tian_gong_intelligence`.
  - No dynamic datasource and no MyBatis-Plus `TenantLineInnerInterceptor` exist anywhere. `sql/tenant-init/tenant-isolation-probe.sh:14-21` and `../docs/设计/租户拦截器可行性-20260914.md` both say so explicitly.
  - Every table carries `sys_company_code varchar(20) NOT NULL`. Isolation is 100% hand-written `AND sys_company_code = ?` in each SQL or Wrapper.
  - CI gates enforce this by convention: `.github/scripts/check_tenant_condition.py`, and the "漏租户条件" job in `.github/workflows/ci.yml:847`.
  - Known gap: bare `getById/updateById` calls with no tenant condition. `../scripts/tenant-bare-id-inventory.sh` counts about 212 such main-code calls, and the interceptor was judged "don't add now".
- **Deployment level** ("一租户一库 / 一租户一容器").
  - Each tenant gets its own Java container `zt-app-t<code>`, its own MySQL database `tenant_<code>`, and its own nginx port or server_name. See `../deploy/tenant-add.sh`, `../deploy/gen-compose.sh:154`, and `../deploy/tenants/3.env.example` (`TN_DB_NAME`, `TN_PORT`, per-tenant `TN_JWT_SECRET`).
  - Databases are created by `sql/tenant-init/init-tenant-db.sh` (8 steps, see §5).
  - Tenant 1 is the platform and registry node, in database `tian_gong_intelligence`. Codes 1 and 2 are reserved; new tenants start at 3.
  - One MySQL instance, one shared NAS (`/opt/zhitong/data/nas-data` mounted as `/work` in every container), one engine, one OCR service.
  - A single database can still hold several `sys_company_code` values. `NewSysInitController` `POST /nas/newSys/agree` (`controller/system/NewSysInitController.java:91`) opens a trial tenant as max+1 in the current database. It is gated to the platform tenant via the `TENANT_PLATFORM_CODE` env var.
- **Tenant registry** (replaces the vendor's ddns.chemball.com).
  - Pre-login lookup: `POST /nas/registry/listServerSelectorByKeyword` (`controller/system/TenantRegistryController.java:100`). The browser enters a company name and gets that tenant's endpoint URL.
  - Admin CRUD: `/nas/registry/admin/*`, platform sys_admin only.
  - Tables `tenant_registry` and `tenant_registry_alias` are cross-tenant global tables, a deliberate exception to the tenant-column rule (`sql/tenant-registry-schema-20260829.sql:1-40`). The authoritative copy is only the one on the registry node.

### 1.2 How a request resolves its tenant
There is no host or subdomain resolution inside Java. The tenant is bound three ways:
1. **Container and DB binding.** The nginx port or server_name routes to the container `app-t<code>`, which holds that tenant's database.
2. **Session claim.** `LoginCheckFilter.doFilter` (`yidu-nas-component/yidu-nas-component-security/.../filter/LoginCheckFilter.java:70`) runs on every request:
   - it normalizes the path (`RequestPathNormalizer`, returns 400 on hostile paths);
   - it matches against `LoginCheckWhiteList`;
   - it parses the JWT, reads `user_key` from the claims and loads the session row from table `redis_data` (key `login_tokens:<uuid>`);
   - it requires the JWT's `sysCompanyCode` claim to equal `redis_data.sys_company_code` (rejects with 401 "令牌与登录租户不匹配", line 136).
3. **In code.** `SecurityUtils.getLoginUser().getSysCompanyCode()` is passed explicitly into every repository call. A `@NeedSysCompanyCode` aspect (`SystemCompanyCodeInjectionAspect`) reflectively sets a `sysCompanyCode` field on DTO arguments.

### 1.3 Login and session
- `POST /nas/login`, body `{code?, username, password}` (`controller/LoginController.java:51`).
  - `LoginServiceImpl.login` (`impl/LoginServiceImpl.java:83`) calls `userMapper.listByUserName(sysCompanyCode?, username)`. If more than one user matches, it fails and asks for the company code.
  - Checks, in order: IP blacklist, account state, password (BCrypt), trial-license expiry.
  - It then fills the role list and company info and calls `TokenService.createToken` (`TokenService.java:61`), and updates `user.login_ip` and `login_date`.
- Session storage is the MySQL table `redis_data` (via `RedisDataService`), not real Redis. The session TTL is 5 days, refreshed at 3 days (`CacheConstants.java:12-17`).
- JWT is HS512. The signing key is derived per tenant: HMAC-SHA512(master `JWT_SECRET`, sysCompanyCode) (`JwtUtils.deriveTenantKey`, line 59). In the container model each tenant also has its own master secret.
- The JWT payload is `{user_key, user_id, user_name, sys_company_code}`.
- Other endpoints: `DELETE /nas/logout`; `/nas/refresh` and `/nas/register` are whitelisted.
- The whitelist (`LoginCheckWhiteList.java`) is a precise per-path list. Wildcard `noNeedSession` was removed (#95), and a CI "免登录面棘轮" job freezes the anonymous surface. Anonymous items:
  - `/nas/login`, `/nas/logout`, `/nas/refresh`, `/nas/register`
  - `/nas/open/file/**` (the service-token download variant is protected separately)
  - `/noNeedSession/healthcheck.html`, `/noNeedSession/druid/**`
  - the BI endpoint `bjswBI`
  - OnlyOffice callbacks
  - `/nas/registry/listServerSelectorByKeyword`
  - Two review endpoints under `/nas/projectReview/noNeedSession/...`: `reviewAllDirectoryByProjectId` and `processProjectFileReviewResult`. Both are still reachable without a session; the second is the callback for the AI review result.

### 1.4 `/nas/authCheck/ragapi`
`GET /nas/authCheck/ragapi` is in `controller/system/RagApiAuthCheckController.java:138`.
- Architecture: nginx `location /ragapi` rewrites to `/engine` and injects `X-Service-Token`, then talks to the engine directly without going through Java. Chat, `filetree/ask` and `extract/fields` can be reached this way. See `../README.md:39-52` and `../deploy/README.md §1.1`.
- Since #445/#446 (2026-09-13), nginx runs `auth_request /__ragapi_auth`, which rewrites to this endpoint. Because the endpoint is not in the whitelist, `LoginCheckFilter` already did the full session check before it runs, and the method body just returns "ok".
- On success it sets response headers that nginx copies onto the engine request with `auth_request_set` + `proxy_set_header` (overwrite semantics, so a client cannot spoof them):
  - `X-Sys-Company-Code` from the session
  - `X-Rag-Sftp-User` from the session
  - `X-Rag-Project-Id`: the caller claims a project id, and Java verifies tenant ownership plus project membership and file ACL through `ProjectAiAccessResolver` before echoing it back
  - `X-Rag-Project-Denied`: reason string, used only for the 403 text
- The engine narrows `FILE_ROOT` to `knowledge/<tenant>`, `project/<verified id>` and the caller's personal-home subtree in `app/files.py::resolve_safe_path`, and returns 403 if the header is missing (fail-closed).
- Residual limits are in §7.

### 1.5 Roles and permissions
- Tables: `user` (also has a denormalized `role_key`), `role` (type 1 level, 2 knowledge, 3 project), `user_role` (`entity_id` = project id for project roles), `company` (the organisation tree within a tenant, with `version_type`/`license_end_time`), `company_admin`, `knowledge_admin`. DDL is in `sql/schema-tian_gong_intelligence-20260821.sql`.
- `UserRoleEnum` (`yidu-nas-dao/.../user/enums/UserRoleEnum.java`): 1 sys_admin, 2 admin (company admin), 3 common, 4 knowledge_admin, 5 project_admin, 6 audit_admin.
- Project-level permission is `project_member.member_auth`, values from `MemberAuthEnum`: 1 no-access, 2 read-only, 3 editable, 4 manageable, 5 downloadable, 6 auditable, 7 visible, 0 default. File and folder overrides live in `project_file.permission_list` (JSON).
- `security/ProjectAuthority` + `ProjectAuthorityResolver` are the single source for "manager / auditor / writer".
  - manager = sysAdmin or companyAdmin(of that project's company) or projectAdmin.
  - projectAdmin additionally requires every member row to be level 4 AND a `project_admin` role row.
  - auditor = manager, or has an `audit_admin` role row.
- Annotations also exist (`@RequiresRoles`, `@RequiresPermissions`, `@InnerAuth`; aspects in the security component), but project-scoped gating is mostly done in service code.
- **All costai controllers** are covered by one aspect: `CostAiProjectAccessAspect` (`security/CostAiProjectAccessAspect.java:58`, pointcut `execution(public * com.yidu.nas.costai.controller..*.*(..))`).
  - It extracts `projectId` from a parameter, the body Map, or `getProjectId()`, and requires `ProjectAiAccess.ALLOWED` (membership plus no hidden files in the project).
  - On denial it returns HTTP 200 with `code:403` via `CostAiAccessDeniedAdvice`.
  - Endpoints that carry only a `taskId` call `TaskProjectGuard` inside the service instead.

---

## 2. The costai domain

### 2.1 Tables

All costai tables use `id varchar(20)` (snowflake from Java), `sys_company_code`, `del_flag`, `creator_id`, `modifier_id`, `create_time`, `modify_time`, except where noted. Append-only tables have no `del_flag`. The base DDL is `sql/cost-ai-schema-20260822.sql`; column additions come from `sql/migrations.d/*` and `tk-*.sql` as noted. The 21 core tables:

| # | Table | Key columns (type, meaning) | Written by |
|---|---|---|---|
| 1 | `project_file_cost_tag` | `project_id`, `file_id` (→project_file.id), `doc_category` v64 (document class code), `cost_stage` v32, `source` v16 (ai/manual), `confidence` dec(5,2). Added in 20261001: `evidence_json`, `needs_manual` tinyint default 1, `disposition` (rag/archive/skip/pending_ocr/pending_export), `evidence` (filename_rule / filename_bareword / ancestor_inherit / parent_dir_rule / content_signal / llm / manual), `tag_signal`, `content_text_source` (text_layer/ocr_sidecar/ocr_service/none), `reason` v1000, `confirm_state` (unconfirmed/confirmed/rejected), `confirmed_by`, `confirmed_at`, `file_sha256` (staleness check), `engine_task_id`. Unique key is now `uk_company_file(sys_company_code,file_id)` | `TagBatchRunner`, `CostTagPersister`; `CostTagAuditRepository` for human review |
| 2 | `cfg_checklist_stage` | `stage_code`, `stage_name`, `sort` | seed; read by `audit/stages` |
| 3 | `cfg_checklist_item` | `stage_code`, `doc_category`, `item_name`, `requirement_level` (1 must / 2 important / 3 optional), `aliases` json, `consulting_type_code` (set-specific checklists, 20260908 and 20261004) | seed; read by audit |
| 4 | `audit_check_result` | `project_id`, `stage_code`, `coverage_rate` dec(5,2), `missing` json, `engine_task_id`. Added: `evidence_json`, `status` (checked/no_required/not_tagged/checklist_missing), `required_total/covered/pending`, `optional_total`, `degraded_matches`, `covered`/`pending`/`advisory` json, `scope` json, `input_stats` json | `AuditCheckServiceImpl` |
| 5 | `project_cost_profile` | unique `project_id`; `consulting_type_code`, `project_type_codes` json, `project_status`, `current_cost_stage`, `bid_sections` json, `source` | **No Java reference (unused)** |
| 6 | `audit_wbs_unit` | `project_id`, `unit_name`, `gross_area` dec(14,2), `is_main`, `sort` | read-only in Java (`CostAiRepository.listAuditWbsUnit`); no writer found |
| 7 | `cfg_consulting_type` | `type_code`, `type_name`, `parent_code`, `commission_scope` json | **unused in Java** |
| 8 | `cfg_project_type` | `type_code`, `type_name`, `sort` | **unused in Java** |
| 9 | `project_baseline` | `project_id`, `wbs_unit_id`, `baseline_type`, `amount` dec(18,2), `detail` json. By design it holds only the submitted ("送审") basis, never approved/reduced amounts | read-only; no writer found |
| 10 | `audit_tk_anomaly` | `project_id`, `submission_id`, `anomaly_uid` v64 (engine fingerprint, uuid5; unique with tenant, added by `tk-anomaly-uid-20260830.sql`), `anomaly_type`, `severity` (low/medium/high), `detail` json (also carries `review_snapshots`), `hitl_state` (pending/confirmed/dismissed), `reviewed_by`, `reviewed_at` | `TkAnomalyRepository.upsertTkAnomaliesScoped` via `TkAnomalyUpsertPlanner` (632 lines of re-run merge logic); `TkDetectServiceImpl.review` |
| 11 | `audit_tk_submission` | `project_id`, `submission_no` v64, `period` v16, `state`, `submitted_amount` dec(18,2), `detail` json. Unique `(sys_company_code,project_id,submission_no)` | `TkDetectServiceImpl.createSubmission` |
| 12 | `audit_tk_decision_log` (append-only) | `project_id`, `submission_id`, `anomaly_id` (added 20260903), `from_state`, `to_state`, `decided_by`, `reason` v500 | `TkDetectServiceImpl.review` and batch review (lines 418, 503) |
| 13 | `cfg_report_template` | `template_code` (unique, no tenant), `template_name`, `description` | **unused**: templates come from the engine's static yaml |
| 14 | `cfg_report_section` | `template_code`, `section_code`, `title`, `sort`, `gen_prompt` text, `rag_query`, `source_categories` json | **unused**, same reason |
| 15 | `report_instance` | `project_id`, `template_code`, `period`, `state`, `finalized_at`, `file_id`. Added: `template_name`, `file_ids` json, `confirmed_claims` json, `context_hash`, `context_snapshot` longtext (frozen source text, reused for single-chapter retry), `context_sources`, `context_facts` (amount facts with cell provenance), `progress`, `error`, `warnings`, `started_at`, `heartbeat_at` (30 min without progress = interrupted), `finished_at` | `ReportGenerationJob`, `ReportRepository` |
| 16 | `report_section_state` | `report_id`, `section_code`, `state`, `content` longtext, `reasoning`. Added: `evidence_json`, `engine_task_id`, `title`, `seq`, `quality` (ok/partial/insufficient/empty), `needs_manual` (always 1), `flags`, `amount_refs`, `cited_files`, `used_files`, `missing_items`, `warnings`, `error`, `prompt_version`, `model`, `context_hash`, `finished_at`. Unique `(tenant,report_id,section_code)` | `ReportGenerationJob` |
| 17 | `report_audit_log` (append-only) | `report_id`, `action`, `actor`, `detail` json | **never written** (no Java reference) |
| 18 | `cost_indicator_result` | `project_id`, `wbs_unit_id`, `indicator_code`, `period`, `value`/`baseline_value` dec(18,4), `deviation` dec(10,4), `input_fingerprint`, `evidence_json`, `engine_task_id` | `CostsheetResultRepository.replaceCostIndicatorResults` |
| 19 | `cost_reconcile_result` | `project_id`, `reconcile_no`, `item_name`, `submitted_amount`, `approved_amount`, `diff` dec(18,2), `detail` json, `input_fingerprint`, `evidence_json`. Added index `(tenant,project_id,create_time)`; the table grows roughly 4,423 rows per run | `CostsheetResultRepository.saveCostReconcileResults` |
| 20 | `ai_usage_log` (append-only) | `actor_id`, `skill_id`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`, `ok`, `ts`. No project column | `CostAiRepository.saveAiUsageLog` from `EngineTaskRunner:276`, `ReportGenerationJob:582`, `TagBatchRunner:577`, `EstimateServiceImpl:969`, `QuantityListServiceImpl:366` |
| 21 | `engine_task` | `project_id`, `task_type`, `state` (queued/running/done/failed), `request` json, `result` json, `error` v1000, `started_at`, `finished_at`. Contract added 20260929: `outcome` (ok/partial/empty/insufficient/error), `outcome_reason`, `error_kind`, `summary`, `warnings`, `coverage`, `progress`, `dedup_key`, `deadline_at`, generated column `active_key` with unique `uk_engine_task_active` (one active task per tenant+dedup_key), a CHECK constraint tying state/outcome/error_kind together | `EngineTaskRunner`, `CostAiRepository` |

Also on `project_core_info` (cost-ai-schema, end): added `approve_state`, `approved_by`, `approved_at`, `approved_json`. These columns have no Java reference.

Other costai-adjacent tables:
- `cost_reconcile_result_archive` (`sql/reconcile-archive-schema-20260829.sql`): yearly RANGE partitions plus stored procedure `sp_archive_cost_reconcile`. No Java reference.
- `concept_indicator_item`, `concept_base_metric`, `concept_indicator_baseline` (`sql/concept-indicator-schema-20260829.sql`): estimate (概算) master data, with unique keys on `(tenant, item_code/metric_name/metric_code/indicator_code)`. The baseline table holds `unit_cost dec(14,4)`, `project_type`, `region`, `price_period`, `base_metric`. Read by `CostAiRepository:799-828`. Seeds: 193 items, 130 base metrics, 224 baselines per tenant.
- `ai_chat_session`, `ai_chat_message` (`migrations.d/20261001-ai-chat-history.sql`): chat history pushed by the browser to `/nas/aiChatHistory/save` after the SSE stream ends. `ai_chat_message` columns include `answer_kind`, `reference_json`, `usage_json`, `client_ip`; unique `(tenant,session_id,turn_id,role)`.
- `project_summary_value_log` (`migrations.d/20261002-project-summary-confirm.sql`): append-only history of project summary edits.
- `project_summary_info` gained `confirm_state`, `confirmed_by`, `confirmed_at`, `value_origin` (manual/ai_candidate/project_info), `engine_task_id`, `evidence` json.
- `knowledge_file` (`sql/knowledge-file-schema-20260823.sql`): sibling of `project_file`, keyed by `category_id`.
- `tenant_registry`, `tenant_registry_alias` (global).
- `task_message` gained `attempt_count`, `last_error`, `next_attempt_at` (20261002); terminal state 3 after 5 failures.

### 2.2 Controllers and engine routes

All paths are under `/nas/costai`, base class path `yidu-nas-server/src/main/java/com/yidu/nas/costai/`. All are guarded by the project aspect from §1.5. Responses use the `ResultForm<T>` envelope. Controllers wrap failures with `ExceptionMessageRedaction`.

Engine call mechanics:
- `client/EngineClient.java` uses hutool HTTP. Base URL is `costai.engine.base-url`, default `http://host.docker.internal:8900`.
- Header `X-Service-Token` is set from the env var `ENGINE_SERVICE_TOKEN` (lines 257 and 314).
- Read timeout comes from the per-task budget (`TaskBudget`); connect timeout is 5 s; GET timeout is 8 s.
- Async tasks go through `task/EngineTaskRunner.submit` (line 77): insert a queued `engine_task` row, return the `taskId`, then a bounded executor (`costAiEngineExecutor`) calls the engine, `TaskOutcomeJudge` classifies the result, and persistence happens in one transaction. A task that outlives its `deadline_at` is expired lazily per tenant on the next read.
- The engine receives file references as `rel_path = project/<projectId>/<disk_relative_parent_folder>/<disk_file_name>` (`source/SourceFile.java:56-62`) and reads the shared NAS itself. It does not touch MySQL.
- Reverse direction: the engine can download files from `GET /nas/open/file/download/{module}/{id}` (`controller/system/OpenFileController.java:248`), with `X-Service-Token` plus `X-Company-Code` verified server-side.

Endpoints (53 in total):

**CostAiController (26 endpoints)**

| Endpoint | Request | Response | Engine route (Java call site) | Persists to |
|---|---|---|---|---|
| POST `/extract/start` :122 | `{projectId, stageCode?, fields?[], skipConfirmed?, includeFeatures?}` | `{taskId, state, fileCount, ...}` | `/engine/extract/fields` (`EngineTaskServiceImpl:65`) | `engine_task.result` only (candidates) |
| GET `/extract/result` :180 | `taskId` | `engine_task` row | none | |
| POST `/tag/start` :207 | `{projectId}` | `{taskId, fileCount, batches, excluded, ...}` | `/engine/tag/classify` in batches (`TagBatchRunner:70,328`) | `project_file_cost_tag`, `ai_usage_log` |
| GET `/tag/list` :232 | `projectId` | `project_file_cost_tag[]` | none | |
| POST `/audit/start` :255 | `{projectId, stageCode?}` | `{taskId, state}` | `/engine/audit/check` (`AuditCheckServiceImpl:56`); request carries `files_with_tags`, `checklist`, `scope`, `input_stats` | `audit_check_result` |
| GET `/audit/result` :281 | `projectId` | latest `audit_check_result` | none | |
| GET `/audit/stages` :304 | | `cfg_checklist_stage[]` | none | |
| POST `/reconcile/start` :328 | `{projectId, submittedFileId, approvedFileId, basis?}` | `{taskId, deadlineAt}` | `/engine/reconcile/run` (`ReconcileServiceImpl:59`) | `cost_reconcile_result` |
| GET `/reconcile/result` :358 | `projectId, taskId?` | `cost_reconcile_result[]` | none | |
| POST `/indicator/start` :383 | `{projectId, priceFileIds[], grossArea?, totalAmount?}` | `{taskId}` | `/engine/indicator/calc` (`IndicatorServiceImpl:69`); sends `baseline.indicator_baselines` read from Java | `cost_indicator_result` |
| GET `/indicator/result` :417 | `projectId` | `cost_indicator_result[]` | none | |
| POST `/tk/submission` :442 | `{projectId, submissionNo, period?}` | new `audit_tk_submission` | none | `audit_tk_submission` |
| GET `/tk/submissions` :470 | `projectId` | list | none | |
| POST `/tk/detect` :495 | `{projectId, submissionFileIds[1..50], baselineFileIds?[≤20], submissionId?, basis?}` | `{taskId}` | `/engine/tk/detect` (`TkDetectServiceImpl:74`) | `audit_tk_anomaly` (upsert by `anomaly_uid`) |
| GET `/tk/anomalies` :523 | `projectId` | `audit_tk_anomaly[]` | none | |
| POST `/tk/review` :548 | `{projectId, anomalyId, hitlState, reason, evidence?="current"}` | `{anomalyId, fromState, hitlState, ...}` | none | updates `audit_tk_anomaly`, appends `audit_tk_decision_log` |
| POST `/quantity/generate` :587 | `{projectId, fileIds[], codeVersion?}` | `{taskId}` | `/engine/quantity/generate` (`QuantityListServiceImpl:77,249`) | xlsx saved into `project_file` (source=2), `engine_task.result` |
| GET `/quantity/result` :637 | `taskId` | `engine_task` | none | |
| GET `/dashboard/summary` :616 | `projectId` | KPI map | none (Java aggregates `DashboardServiceImpl` over file counts, audit, tk, `ai_usage_log`, recent tasks) | |
| GET `/estimate/template` :665 | `templateCode?` | pass-through | GET `/engine/estimate/template` (`EngineClient`) | |
| POST `/estimate/extract` :689 | `{projectId, fileIds[], templateCode?}` | `{taskId}` | `/engine/estimate/extract` (`EstimateServiceImpl:305`); task type `estimate_extract` | `engine_task.result` |
| GET `/estimate/extract/result` :718 | `taskId` | `engine_task` | none | |
| POST `/estimate/suggest` :757 | `{projectId, inputs{}, dims?, feeBases?, feeAttrs?, templateCode?}` | engine output verbatim (suggestions/unresolved/fee/coverage/warnings) | `/engine/estimate/suggest` (`EstimateServiceImpl:449`); sync, no `engine_task`; Java attaches `baselines` read from `concept_indicator_baseline` | `ai_usage_log` only |
| POST `/estimate/compute` :798 | `{projectId, inputs{}, rates?, projectName?, templateCode?, areaChecks?, slotLabels?, acknowledgedChecks?[]}` | `{taskId}` | `/engine/estimate/compute` (`EstimateServiceImpl:648`); task type `estimate_generate` | generated xlsx in `project_file`, `engine_task.result` |
| GET `/estimate/result` :840 | `taskId` | `engine_task` | none | |
| GET `/tasks` :868 | `projectId, taskType?, state?, page, size≤50` | `{records,total,page,size}` | none | |

**CostAiReportController (9)**
- GET `/report/templates` → engine GET `/engine/report/templates` (allow-listed fields only).
- GET `/report/candidates` (Java only).
- POST `/report/start` `{projectId, templateCode, fileIds[], confirmedClaims[]}` returns `reportId` within about 1 s; the browser polls GET `/report/{reportId}`.
  - Background `ReportGenerationJob` calls `/engine/report/context` (line 245), `/engine/report/facts` (333), and `/engine/report/section` once per chapter (415).
  - Persists `report_instance`, `report_section_state`, `ai_usage_log`.
- GET `/report/list` (latest 20).
- GET `/report/{reportId}`.
- POST `/report/{reportId}/sections/{sectionCode}/retry` (reuses `context_snapshot`).
- GET `/report/{reportId}/export` → `/engine/report/export` (bytes, docx; `ReportSectionServiceImpl:450`).
- `POST /report/section` and `GET /report/sections` are retired stubs.

**Remaining controllers**
- CostAiTagReviewController: POST `/tag/review` `{projectId, fileId, action: confirm|override|reject|reset, docCategory?, costStage?}` writes `project_file_cost_tag.confirm_*`. GET `/tag/vocabulary` → engine GET `/engine/tag/vocabulary` (`TagServiceImpl:56,288`).
- CostAiTaskController: GET `/tasks/detail` `{projectId, taskId}`.
- CostsheetController (`/costsheet`): GET `/candidates` (Excel candidates; purpose tk|indicator|reconcile), GET `/candidates/probe` → POST `/engine/costsheet/probe` (`CostsheetProbeCache:42,143`, process-local cache), GET `/task-view`.
- CostsheetExportController: GET `/reconcile/export`, GET `/indicator/export`, GET `/tk/anomalies/export`. These build xlsx in Java (`ReconcileWorkbook`, `IndicatorWorkbook`, `TkAnomalyWorkbook`); no engine call.
- ProjectSummaryController (`/summary`): GET `/overview`, POST `/edit`, POST `/confirm` (adopt an AI candidate; the server re-reads the value and task), GET `/extract-sources`, GET `/history`, GET `/export` (xlsx). All Java-only; they write via `SummaryValueWriter` (the only write path to `project_summary_info.value`) and `project_summary_value_log`.
- TkReviewController (`/tk`): GET `/anomaly/logs`, POST `/review/batch` (only `dismissed`, reason required, at most 200, all-or-nothing), GET `/decision-logs`.

Other costai-related Java endpoints:
- `/nas/aiChatHistory/{save,sessions,messages,delete,company,empty}`
- `/nas/aiReports/*` (legacy `AIReports` entity)
- `/nas/aiBusinessData/{listCurrentFileInfo,listMyCanReadFileIdList}`

Engine routes with no Java caller: `/engine/filetree/ask`, `/engine/chat/complete`, `/engine/chat/history/*`, `/engine/query/empty`, `/engine/reportform/render|inspect`, `/engine/health`. These are reached via the nginx `/ragapi` path (or not at all). The engine has about 26 routes in total.

---

## 3. Project and file model of the base platform

### 3.1 Tables
- `project` (`schema-…20260821.sql`): `name`, `nature`, `folder_path` v300, `eng_category` int (building / installation / municipal / …), `service_scope_id`, `project_node` (1 in progress / 2 done), `template_id`, `company_id`, `department_id`, `charge_person_id`, `auditor_person_id`, contract dates, `total_amount` dec(15,2) in 万元, `scale`, `file_info`, `total_output_value`, `allocated_output_value`, `entrusted_company`, `report_code`. Indexed only by `sys_company_code`.
- `project_subitem`: `type` (0 master project / 1 sub-project / 2 service item), `summary_template_id`, `file_list` json, `is_data_ready`, `data_ready_err_msg`.
- `project_member`: `project_id`, `user_id`, `member_auth`.
- `project_core_info` (key/value per project, links to `project_core_info_dict`), `project_service_scope`.
- `project_file` is the only file/folder table. No foreign keys.
  - `item_type` 0 file / 1 folder; `parent_id`.
  - `relative_parent_folder` (display path) and `disk_relative_parent_folder` (on-disk path), both text.
  - `file_name` (display) vs `disk_file_name` (real name on disk, with a (n) suffix on collision).
  - `source` 0 template / 1 upload / 2 AI-generated; `file_type`; `suffix`; `file_info` (size / child count); `sha256` + `sha256_time`.
  - `permission_list` json; `history_list` json; `sort`; `business_code`/`business_id`.
  - Creator/modifier fields (`creator`, `creator_id`, `modifier`, `modifier_id`) and `del_flag`.
  - Iron rule 6 in the SQL comments: no column of `project_file` may be changed. Several migrations restate this.
- `project_file_edit_lock` (unique per `file_id`, generated `hash_path`), `project_file_text` (extracted text), `file_upload_record` (chunked upload bookkeeping: `sha256`, `slice_folder_path`, `save_path`, `completion_percentage`; a `tenant` column was added in `sql/file-upload-record-tenant-20260908.sql`).
- Siblings: `knowledge_category` + `knowledge_entity` (legacy) and `knowledge_file`; `personal_space` + `personal_space_file`; `template*`; `recycle_bin` + `recycle_bin_log`; `project_report*`; `spread_report_*`; `wt_*` time-tracking tables; `project_operation_log`.

### 3.2 NAS layout
The absolute path is never stored; it is computed on each access. Config keys in table `config` (seed at `sql/tenant-init/tenant-seed-template.sql:67-77`):
- `yidu.nas.disk.base.path` = `/work`
- relative paths: `/project`, `/knowledge`, `/personal.home`, `/recycle.bin`, `/company.logo`, `/template.file`, `/template.report`

Layouts:
- Project file: `/work/project/<projectId>/<disk_relative_parent_folder>/<disk_file_name>`. There is no tenant segment; the project id is the isolation unit.
- Knowledge base: `/work/knowledge/<sysCompanyCode>/<分类名__categoryId>/<file>` (`utils/TenantKnowledgePaths.java`). Old files remain in flat `knowledge/`; `sql/tenant-init/knowledge-tenant-migrate.sh` moves them but has not been run in production.
- Personal space: `/work/personal.home/<sftp_user_name>/…`.
- Chunked upload staging goes under `slice_folder_path`.

### 3.3 Versions and "AI slots"
- Versions: `project_file.history_list` json is a list of `ProjectFileHistory {diskRelativeParentFolder, diskFileName, fileInfo, sha256, sha256Time, creator*, modifier*, modifyTime}`.
  - `FileUploadUtils.combineHistories` (`utils/FileUploadUtils.java:262`; `targetSize=3` at line 282) prepends the old current version and physically deletes older ones, keeping at most 3 historical versions.
  - Endpoints: `POST /nas/file/getProjectFileHistory`, `POST /nas/file/useHistory`.
  - Re-uploading identical sha256 content is rejected with "文件内容与当前版本一致"; template-sourced files cannot be overwritten by upload.
- Edit locking: `/nas/file/lockFile`, `/unLockFile`, `listEditLockedProjectFileByProjectId`. Online editing uses OnlyOffice (`/nas/file/openOnline`, `saveProjectFile` callback, `ooForceSave`). There is also a `编辑锁连续两小时没有自动上传自动解锁.sql` MySQL event for auto-unlock.
- **"AI function slots"** are not a table.
  - Per `../前端诊断-实机UI走查-20260822.md` §4, they are 7 pre-built UI areas in the project workspace: AI resource review, AI summary compare, report management, spreadsheet management, an embedded AI input box / AI home, and a project cockpit.
  - Backend side, the project home app list comes from the config row `project.home.function` (JSON list with `code`). `sql/tenant-init/costai-app-card-upgrade.sql` appends `{"code":"costAi"}` and does nothing if the row is absent.
  - The slot backends in this repo: `project_review*` and `project_file_review_result` (AI review), `project_summary_*` (AI summary), `project_report*` (OnlyOffice-based report drafts) and `spread_report_*` (spreadsheet formula reports). These were originally filled by the vendor's cloud AI via `task_message` and MQ consumers.
  - Those vendor calls are now switched off. `tg.vendor-ai.information-extraction.enabled` defaults to false, and `TaskMessageServiceImpl.ERROR_VENDOR_AI_DISABLED = "vendor_ai_disabled"`. `component/core/constant/VendorDomains.java` blocks the domains `chemball.com` and `tgzt.cn`.
- File endpoints (`controller/project/ProjectFileController.java`, base `/nas/file`):
  - upload: `checkCacheExists` :132, `uploadFileSlice` :152, `mergeSliceFile` :183, `checkMergeFileStatus/{projectFileId}` :265 (the `/upload/cache/*` family is the generic variant)
  - download: `download/{projectFileId}` :287, `downloadProjectFile/{id}` :1197
  - preview: `view/{fileId}/{pageNum}` :466, `/p/**` and `/v/**` (now authenticated)
  - folders and listing: `makeFileDirectory`, `listProjectFile`, `queryProjectFile`, `searchProjectFile`
  - file ops: `rename`, `copy`, `move`, `deleteToRecycling`, `sortProjectFile`
  - permissions: `getPermission`, `setPermission`, `batchSetPermission`
  - others: `getShareUrl`, `postAllFileToRAG` :1579
  - ticketed downloads: `/nas/fileAccess/{ticket,zipTicket,t/{ticket}/{displayName}}`
  - Knowledge files: `/nas/knowledgeFile/*` (7 endpoints); personal files: `/nas/personalSpaceFile/*`.
- **Object storage.** No S3/TOS use on the request path.
  - `config/MinioConfig.java`, `utils/MinioUtil.java` and `impl/thirdparty/MinioFileService.java` exist, but the only call sites in `ProjectFileServiceImpl` (lines 324, 848, 2099) are commented out, with a "TODO: remove before go-live, minIO debugging" at line 840.
  - Volcano-engine TOS is used only for nightly DB dump uploads: `../deploy/tos-backup-upload.py` and `backup-offsite.sh`.

---

## 4. Flowable / workflow

- Dependency: `yidu-nas-component/yidu-nas-component-flowable` (Flowable 6.x starter plus BPMN JSON helpers). There are 82 `ACT_*`/`FLW_*` tables in the base DDL. `init-tenant-db.sh` step 4 deliberately DROPs them so Flowable recreates them at startup, otherwise the version property is null.
- Business use: only the folder-level project review flow.
  - `projectReview/impl/ProjectReviewServiceImpl.java:485-535`: when a review is set to review-state on a folder that has a bound process template (`project_review_folder_process.process_template_id`), it looks up the process definition by key `PROCESS_PREFIX + templateId`, starts an instance with variables (form value, initiator, `root` user JSON), auto-completes the first task, and stores `process_instance_id` back on the folder-process row.
  - The `else` branch for an already-started instance is `// todo 待继续` (line 533). The approval-by-next-node logic was never finished.
  - Related tables: `project_review_folder_process` (folder-to-process binding), `project_template_process`, `wf_template_group`, `wf_process_template` (BPMN JSON), `wf_template_group_relation`, `wf_cc` (CC list); `sql/workflow.sql` is a standalone copy of these four.
- Generic Flowable demo and admin endpoints exist: `/nas/process/v1.0/*` (`FlowableProcessController`: db init, deploy XML, start, todo/applied/completed task lists, approve, reject, diagram), `/nas/processAdmin/*` (form groups, deploy template), `/nas/flowable/saveBpmnModel`. `ProcessUserController` is almost entirely commented out. `../后端/README.md` is literally the upstream Flowable demo README. These are template/design tooling, not an active approval pipeline.
- The costai review loops (tag review, anomaly review, summary confirm, report retry) do NOT use Flowable. They are plain state columns plus append-only logs.
- `project.auditor_person_id` and `audit_admin` role row are the 审核人 for project-level review; `project_core_info.approve_state` columns are unused.

---

## 5. SQL migrations mechanism and tests

- **Base:** `sql/schema-tian_gong_intelligence-20260821.sql`, 155 tables including Flowable. Seeds are in `sql/tenant-init/tenant-seed-template.sql` and others. `sql/passed/` and the dated one-off files are historical.
- **New tenant database:** `sql/tenant-init/init-tenant-db.sh` (8 steps, fail-stop with the step name):
  1. preflight
  2. `CREATE DATABASE` utf8mb4
  3. DDL, in this order: base 155 tables; costai 21 tables; `tk-anomaly-uid`; `tk-submission`; `config` unique index; `template` unique index; `file-upload-record` tenant column; `knowledge_file`; the 3 concept tables; the 2 registry tables; `checklist-audit-report-stage`; then `migrations.d/*.sql`
  4. drop Flowable shell tables
  5. seed config, role, user_role, dictionaries, service scope, checklists, concept data, registry self-row
  6. create the admin user (password from `TG_ADMIN_PASSWORD` or a BCrypt hash)
  7. append the costAi app card
  8. verify (character-set HEX checks, seed counts, admin integrity)
- **Incremental:** `sql/migrations.d/` (README in the same directory; registry code in `sql/tenant-init/migrations-lib.sh`).
  - Filename `YYYYMMDD-slug.sql`, run in bytewise (`LC_ALL=C`) order.
  - Every run of `init-tenant-db.sh` re-runs all of them. There is no applied-migrations table, so each file must be idempotent (`information_schema` checks, `PREPARE`).
  - Any failure aborts initialization. Foreign files or empty files in the directory also fail.
  - Existing production databases do NOT pick migrations up automatically (#696 / D6). The operator runs `docker exec -i zt-mysql mysql … < file` by hand, schema first, then the jar.
  - Older migrations (`tk-anomaly-uid`, `config-unique-index` and others) stay as `TG_*_DDL` variables in the script.
  - 15 files today: engine-task contract, role-seed backfill, ai-chat-history, checklist alias/stage/consulting-sets seeds, tag-audit evidence, report AI-draft provenance, member-output orphan cleanup, project-summary confirm, report-form name width, report-instance context facts, task-message terminal, upload-name length, review-comment content length.
  - MySQL 8.0.16+ required for the CHECK constraint on `engine_task`.
- **Tests:** `sql/tests/*.sh` (37 files) are "replay" tests on a real MySQL. They run a migration twice (idempotent, `SHOW CREATE TABLE` identical) and use mutation checks (a variant that should fail turns red). Examples: `migrations-d-replay.sh`, `engine-task-contract-replay.sh`, `tk-anomaly-uid-replay.sh`, `costai-tag-audit-evidence-replay.sh`, `report-ai-draft-provenance-replay.sh`; plus `migrations-lib-test.sh` and `summary-shape-lib-test.sh` (no DB). Fixtures: `sql/tests/fixtures/`.
- `sql/tenant-init/tenant-isolation-probe.sh` is a mutation validator for tenant-condition SQL against throwaway DBs `tg_iso_*_tmp`. It states that it cannot see the Java code.
- **Java tests:** `yidu-nas-server/src/test/java` has 350 files, 174 named `Security*`, plus `MapperBinding*` (SQL/mapper binding ratchets), `TenantIsolation*`, `EngineTask*`, `Costsheet*`, `Estimate*`, `Indicator*`. Only the OnlyOffice component has its own tests.
- **CI:** `../.github/workflows/ci.yml` runs jobs for engine-service, ocr-service, frontend, java (estimate + security lanes), JDK17, secrets scan, tenant-condition gate, anonymous-surface ratchet, typed-equality ratchet, deploy-doc, seed credentials, and merge audits (`../.github/scripts/*.py`).

---

## 6. Human review trail, audit logs, anomaly results

| What | Where it is stored |
|---|---|
| Anomaly detection results | `audit_tk_anomaly` (`detail` json holds the engine payload plus `review_snapshots`; `hitl_state`, `reviewed_by`, `reviewed_at`) and the raw `engine_task.result` / `request` / `warnings` / `coverage`. Re-runs merge by `anomaly_uid` via `TkAnomalyUpsertPlanner`; rows can be marked "evidence changed" or "not hit this round". |
| Anomaly review trail | `audit_tk_decision_log` (append-only: `anomaly_id`, `from_state`, `to_state`, `decided_by`, `reason`). Read by `TkReviewTrail` (`support/TkReviewTrail.java`), `GET /tk/anomaly/logs`, `GET /tk/decision-logs`. |
| Tag review | `project_file_cost_tag.confirm_state`, `confirmed_by`, `confirmed_at`, `evidence`, `needs_manual`, `file_sha256`. It is updated in place with no history table, so overrides are not versioned. |
| Summary field review | `project_summary_info.confirm_state/confirmed_by/confirmed_at/value_origin/engine_task_id/evidence` plus append-only `project_summary_value_log` (old/new value, operator, evidence, `amount_ack`). |
| Report chapters | `report_section_state` (`needs_manual` always 1, `quality`, `flags`, `cited_files`, `prompt_version`, `model`, `context_hash`). `report_audit_log` exists but nothing writes to it. |
| AI cost and usage | `ai_usage_log` (no project dimension; the dashboard says project-level token attribution is deferred). |
| Folder / file review (base platform) | `project_review` (JSON result lists, `review_state`), `project_review_log` (state transitions), `project_review_comment`, `project_file_review_result`. |
| Other operation logs | `project_operation_log` (upload/edit/delete), `project_member_output_log`, `recycle_bin_log`, `spread_report_operation_log`, `task_message` (outbox with retry state). |
| Chat Q&A | `ai_chat_session`, `ai_chat_message` (`answer_kind` such as not_found / unreadable). |

---

## 7. Known defects and security issues

- **`/ragapi` cross-tenant file read (#445 / #446, residual #462 / #323).**
  - Before 2026-09-13 anyone on the internet could read any tenant's files without logging in (`../.kb/changelog.d/445-ragapi-entry-auth.md`).
  - The `auth_request` gate (`deploy/README.md §1.1`) closed the anonymous path. #462 added tenant, personal-space and verified-project scoping in the engine (`app/files.py::resolve_safe_path`) and nginx `auth_request_set`.
  - Still open by the changelog's own words: "只降级、不关闭". The full fix, which is removing `/ragapi` and bridging through Java, is deferred.
  - Per-project ACL (#709): the check is all-or-nothing per project. A member with any file hidden from them is refused for the whole project, because the engine reads the whole `project/<id>` tree.
  - Dependency: the gate needs a real HTTP 401 from Java. A fix to #218 corrected the earlier "HTTP 200 + body code 401" behavior, and rolling back to the old jar would silently reopen the gate.
  - The `/ragapi` path remains outside Java for audit and persistence. Chat history is re-posted by the browser to `/nas/aiChatHistory/save` after the stream ends.
- **Tenant isolation is convention-only.** Zero `TenantLineInnerInterceptor`; about 212 bare `getById/updateById` calls on main code (42 on `project_file`, 8 on `user`). The 2026-09-14 design note recommended against adding one now because the MyBatis-Plus version lacks it and `user`, which must be excluded, is exactly the table that most needs protection.
- **`project/<id>/` on the shared NAS has no tenant segment**, unlike `knowledge/<tenant>/`. Isolation relies on unguessable ids plus the checks above. All tenant containers mount the same `/work`.
- **Security-fix history in comments** (all fixed, but they show the weak spots): `/p/**` and `/v/**` anonymous file reads (#93, fixed by switching the frontend to fetch-with-header); `/nas/open/file` path traversal (B-07); `mergeSliceFile` file-name traversal; whitelist wildcard `noNeedSession` (#95); path-normalization bypass (#234); response header injection guarded in `RagApiAuthCheckController.SAFE_SEGMENT`; `fix-464-user-role-audit-type.sql` and `role-seed-backfill` for role data errors; error-message leakage of tenant codes and table names (#278, `ExceptionMessageRedaction`).
- **Security backlog** in `../docs/安全待办-B线红线-相对main-20260827.md`: B-03 auto-login back door via `CallBackAutoLoginInterceptor` (`/nas/vika/callback/**`), B-05 soft tenant check in callbacks, B-08 credential rotation. B-01 and B-07 are marked fixed; B-02 (per-tenant JWT key) has since been implemented in code (`JwtUtils.deriveTenantKey`). The document is a snapshot at commit `4d06c77`; re-verify before relying on a status.
- **Dead or half-built code left in tree:**
  - RAG upload/delete MQ consumers are deliberate no-ops (`rocketMQConsumer/rag/*`, class comments); the producers still publish.
  - Folder review workflow stops at `// todo 待继续` (`ProjectReviewServiceImpl.java:533`).
  - Vika callback paths with relaxed validation: `ProjectServiceImpl.java:1729,1734,1959` (TODO "release before go-live" for validation skipped to adapt Vika callbacks).
  - Fake demo department `VikaServiceImpl.java:1195`.
  - `UserServiceImpl.java:1605,1618`: disabling a user does not log them out (TODO).
  - Template tree for 园林绿化 not implemented (`TemplateServiceImpl.java:134`).
  - Unused schema: `project_cost_profile`, `cfg_consulting_type`, `cfg_project_type`, `cfg_report_template`, `cfg_report_section`, `report_audit_log`, `cost_reconcile_result_archive`, `project_core_info.approve_*`; `audit_wbs_unit` and `project_baseline` are read but never written, so indicator baselines come from the Excel instead.
  - Total TODO/FIXME markers in Java main code: 65.
- **Engine/Java contract risks:** the engine is stateless and does not touch MySQL (iron rule 4), so Java must ship baselines and fee bases with each request. `EngineClient` still carries legacy methods (`extractFields`, `classifyTags`, …), with a comment that they are to be deleted once all callers move to `EngineTaskRunner`. Two timeouts (60 s front, 120 s Java, 600 s nginx) were historically misaligned.
- **Operational:**
  - `uk_file_id` → `uk_company_file` index swap on `project_file_cost_tag`.
  - `cost_reconcile_result` grows without bound (about 4,423 rows per run); the archive procedure exists but is manual.
  - Orphan tasks after a restart are only expired lazily on the next read per tenant.
  - Shared consumerGroup across tenant containers caused cross-consumption (#382), now prefixed by `tg.mq.group-prefix`.

---

## 8. CRUD/record-keeping versus embedded domain logic

**Plain CRUD / record keeping (can stay or move to a thin storage API):**
- Identity and tenancy: `user`, `role`, `user_role`, `company`, `company_admin`, `department`, `config`, `redis_data` sessions, `tenant_registry*`, the JWT/login/filter chain, `/nas/user|company|dept|profile|config/*`.
- Projects and files: `project`, `project_subitem`, `project_member`, `project_core_info*`, `project_service_scope`, `project_file` (+ NAS layout, upload slicing, sha256 dedupe, history list, edit lock, recycle bin, permissions), `knowledge_*`, `personal_space*`, `template*`, `project_operation_log`.
- Costai result stores: `engine_task` as a generic job table (the queue/dedup/deadline/outcome contract is generic), `ai_usage_log`, `ai_chat_*`, result tables (`cost_reconcile_result`, `cost_indicator_result`, `audit_check_result`, `project_file_cost_tag`, `audit_tk_*`, `report_*`), seed config tables, the `/tasks`, `/tasks/detail`, `*/result`, `/tag/list`, `/tk/anomalies`, `/tk/submissions`, `/report/list` readers, and Java-side xlsx exporters.

**Embeds domain logic that must be ported if Java goes away (in `yidu-nas-server/.../costai/`, 22.8k lines):**
- Source-file selection and eligibility: `source/SourceFileSelector`, `SourceFileSelection`, `ExtractSourceFilter`, `TagInputFilter`, `CostsheetFileCandidates`, `MissingDiskFilePreflight`.
- Audit input building and checklist scoping: `AuditCheckInputBuilder`, `AuditScopeResolver`, `AuditCheckResultRows`, `CostTagAuditRepository` (stage cumulative basis, consulting-type fallback, tag evidence grading).
- Tag batching and confirm/override rules: `TagBatchRunner`, `CostTagPersister`.
- Result judging and task lifecycle: `task/TaskOutcomeJudge` (371 lines), `TaskBudget`, `EngineTaskRunner`.
- Anomaly lifecycle: `TkAnomalyUpsertPlanner` (632 lines, merges repeated detections), `TkSweepScope`, `TkHitlState`, `TkReviewAccess`, `TkSubmissionPeriod`, `TkSubmissionBinding`, `TkDetectServiceImpl` review rules (white-listed states, evidence-changed re-review, batch dismiss only).
- Summary rules: `SummaryValueWriter` (the only writer of `project_summary_info.value`), `SummaryCandidateMapper`, `SummaryFieldCatalog` + `resources/costai/summary-field-catalog.json`, `SummaryStagedFieldsGate`, amount acknowledgement rules.
- Report orchestration: `ReportGenerationJob`, `ReportContextSnapshot`, `ReportAmountFacts`, `ReportSourceClassifier`, `ReportSectionJudge`, `ReportSectionServiceImpl` (judging and retry).
- Estimate: `EstimateServiceImpl` (988 lines), `EstimateComputeContextValidator`, `EstimateTaskSummary`.
- Reconcile/indicator/quantity request shaping: `ReconcileServiceImpl`, `IndicatorServiceImpl` (area fallback, baseline injection), `QuantityListServiceImpl`.
- Cross-cutting: `CostAiProjectAccessAspect`, `TaskProjectGuard`, `ProjectAiAccessResolver` (membership/file-ACL decision), `ProjectAuthority`, `FileAccessPolicy`, `ExceptionMessageRedaction`.
- Base platform: `ProjectFileServiceImpl` path/permission inheritance, `ProjectServiceImpl`, member output allocation (`ProjectMemberOutput*`, `MemberOutputLedger`), time-tracking (`wt_*`), and OnlyOffice callbacks.

---

## Assessment: the durable system of record

Anything that replaces the Java layer must keep writing, with the same `sys_company_code` / `project_id` keys:

1. **Identity, tenancy, authorization:** `user`, `role`, `user_role`, `company`, `company_admin`, `config`, `redis_data` (or an equivalent session store), `project`, `project_member`, `project_subitem`, `project_core_info(+dict)`, `project_service_scope`, `tenant_registry(+alias)`.
2. **Files:** `project_file` (do not change its columns; the NAS paths and `history_list` are derived from it), `knowledge_*`, `personal_space_file`, `file_upload_record`, `project_file_edit_lock`, `recycle_bin(+log)`, `project_operation_log`. The NAS layout under `/work` is shared with the engine.
3. **AI evidence and review trail, the actual product record:**
   - `engine_task` (request, result, outcome, warnings, coverage, deadline): the cross-feature job and provenance ledger.
   - `project_file_cost_tag` (human confirm/override fields).
   - `audit_check_result`, `audit_tk_anomaly`, `audit_tk_submission`, `audit_tk_decision_log` (review history).
   - `cost_reconcile_result`, `cost_indicator_result`, `project_summary_info` + `project_summary_value_log`.
   - `report_instance`, `report_section_state` (with `context_snapshot` / `context_hash` / `prompt_version` / `model`).
   - `ai_usage_log`, `ai_chat_session` / `ai_chat_message`.
4. **Reference data the logic depends on:** `cfg_checklist_stage`, `cfg_checklist_item`, `concept_indicator_item`, `concept_base_metric`, `concept_indicator_baseline`, `project_summary_template`/`category`/`*_init`, `project_core_info_dict`, `template*`.

Safely droppable or already inert: `project_cost_profile`, `cfg_consulting_type`, `cfg_project_type`, `cfg_report_template`, `cfg_report_section`, `report_audit_log`, `cost_reconcile_result_archive`, `project_core_info.approve_*`, the RAG MQ consumers, `knowledge_entity` (legacy), the 82 Flowable engine tables (only the unfinished folder-review binding uses them), MinIO classes, and the vendor-AI `task_message` paths.

Constraints a replacement must preserve:
- The engine reads files by `rel_path` from the shared NAS, so keep `/work/project/<id>/…` and the `disk_*` columns.
- The `engine_task` CHECK and dedupe contract is relied on by the UI polling (`queued/running/done/failed` plus `outcome`).
- Human-in-the-loop fields stay write-protected on re-runs (confirmed or rejected tags, `hitl_state` rows with decisions).
- Iron rules from the schema comments: every query carries `sys_company_code`; AI output always needs manual confirmation (`needs_manual` = 1); only the submitted ("送审") basis is stored in `project_baseline`; the engine never connects to MySQL.