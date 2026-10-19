---
name: zt-archive
description: 项目归档：核对 成果/ 与 工作/ 是否完整，把成果和中间产物推回桶，更新项目说明（已出成果、状态）和案例索引（本项目一行）。
whenToUse: 用户说项目做完了、要归档、要把成果入库，或要把本项目登记进案例索引时。
---

# 项目归档

脚本 `scripts/archive.py`（零模型）：`"${ZT_PYTHON:-python3}" scripts/archive.py <check|apply> ...`。stdout 一个 JSON，`status` 与 `warning_items` 如实转述。归档就是三件事：核对、推送、登记。不做后台任务，不做锁；多人同时改案例索引靠桶的版本控制回退。

## 步骤

1. **拉齐本机副本**：`tos_ls 项目/<目录>/ recursive` 对照本机；成果和工作目录里别人新增的文件 `tos_pull` 到本机，别在缺文件的副本上归档。`tos_pull 案例索引.md`（要最新的）。
2. **核对**（只读）：
```sh
scripts/archive.py check --project-dir <本机项目目录> --index <本机案例索引.md>
```
   - `status=insufficient`（`not_ready_to_archive`）：有阻断项，`warning_items` 里 `level=error` 的逐条处理，不能跳过：
     `project_doc_missing` / `project_doc_incomplete` / `project_doc_undecided`（项目说明缺失、缺字段、咨询类型或阶段还是「待确认」——问用户后补）、
     `no_deliverables`（成果/ 是空的）、`deliverable_listed_but_missing`（项目说明登记的成果文件不在）。
   - `warning_items` 里 `level=warn` 的是提醒，不阻断，但要告诉用户并让他决定：`open_items`（`待确认清单.md` 还有未勾选事项——逐条问，处理不了的在项目说明里写明遗留）、`work_dir_name`（工作目录没按 `YYYY-MM-DD-任务` 命名）、`work_dir_empty`、`work_loose_files`、`deliverable_unlisted`（成果文件没登记，apply 会补）、`temp_file_in_deliverables`（临时文件不会登记）、`code_dir_mismatch`、`casebook_name_mismatch`。
3. **向用户确认**：把成果清单、提醒项、要写进案例索引的「关键指标」（单方造价等，只写成果里已有的数，不要现算）发给用户，用 `ask_user_question` 问一句「按这样归档？」。用户没确认不往下做。
4. **推送成果与中间产物**：对 `data.push_list` 里除项目说明以外的文件逐个 `tos_push`（`local_path` 用本机绝对路径，`path` 用 `项目/<目录>/` + `rel_path`）。回读 `sha256` 要与清单里的一致；`remoteChangedSincePull` 为 true 的文件说明别人改过，告诉用户，不要悄悄覆盖。
5. **登记**：
```sh
scripts/archive.py apply --project-dir <本机项目目录> --index <本机案例索引.md> [--key-metrics "单方 3200 元/㎡"] [--status 已归档]
```
   改写本机副本：项目说明的「已出成果」小节（成果/ 下的文件，相对路径）、YAML 头的 `状态`，案例索引里**只有本项目那一行**（没有则追加；成果链接填 `项目/<目录>/成果/`）。`apply` 再检查一遍，有阻断项就拒绝并保持文件不动。重复运行结果不变。
6. **推送登记**：`tos_push` 结果里 `files` 的两个文件（项目说明、案例索引）。案例索引回读 `remoteChangedSincePull` 为 true 时，别人同时改了它：重新 `tos_pull` 案例索引再 `apply` 一遍，不要覆盖别人的行。
7. 向用户汇报：推送了哪些文件（数量、大小）、项目说明和案例索引改了什么、遗留事项。

## 纪律

- 只改本项目的案例索引行，不重排、不删别人的行。
- 「关键指标」只写成果里已经算好的数并写出口径（如「单方 3200 元/㎡，含税，合同价口径」），不现场计算、不估算。
- 阻断项没修好不归档；提醒项用户知情后可以带着归档，但要在项目说明的「工作记录」写下遗留。
- 归档不删任何文件：中间产物保留在 `工作/`。桶开了版本控制，覆盖不会丢旧版本。
- 路径一律项目内相对路径、`/` 分隔；中文和空格路径是正常的。
