# repo-snapshot

旧仓 `zhitong-cost-ai` 的源文件副本，目录结构与旧仓相同（`engine-service/app/engine/...`），供 `kbsrc.py` 以文件方式读取，替代 `git show 33601ca8:<path>`。

| 文件 | 状态 |
|---|---|
| `engine-service/app/engine/data/gb50854_zj2025.yaml` | sha256 `6a61c6d196c8b420ec675b73323395cc0eec91ffa02872181ac83fc8f041e730`，与 33601ca8 登记值一致 |
| `engine-service/app/engine/data/quantity_rules.yaml` | 迁移时旧仓工作树版本，sha256 `314a9f84…`；登记的 33601ca8 版本为 `f15101cd…`，二者不同 |
| `engine-service/app/engine/quantity_rules.py` | 迁移时旧仓工作树版本，未与 33601ca8 版本比对 |

文件内容不要手改；更新快照时同步更新 `../../expected_manifest.json`。
