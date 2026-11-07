# GitHub 推送记录_V8.0

- 推送日期：2026-11-07（Asia/Shanghai）
- 授权：用户本轮明确要求“把上述完工汇总和报告一起共享至 GitHub”，视为已授权；不再列“待用户点头”。
- 账号：`DDDNN1234567`；分支：`main`；三个仓库均为 public、admin+push。
- 推送方式：GitHub MCP `create_or_update_file` / `push_files`（本机无 git/gh CLI）。

## 一、三个仓库

| 仓库 | 本轮新增文档 | 最新 commit |
|---|---|---|
| `DDDNN1234567/kspc-cmsg-transfer` | `V8.0/文档/` 下：共享备忘、README_索引、项目完工汇总、项目完成度报告、四路径深度过滤与补强清单、四路径补强清单 CSV | `28af574ab355010b208a79fddf02a508522592c0`（CSV） |
| `DDDNN1234567/kspc-grasp-transfer` | `V8.0/文档/` 下：项目完成度报告、项目完工汇总、共享备忘、四路径深度过滤与补强清单、README_索引 | `b7cae86f8c613425aab4486eca6638ff570ad770`（四路径） |
| `DDDNN1234567/grasp-top15-import-tool` | `V8.0/文档/` 下：项目完成度报告、项目完工汇总、共享备忘、四路径深度过滤与补强清单、README_索引 | `871eae9aa220d5939afdef1633a4611082f610fd`（四路径） |

## 二、逐文件回执

### `kspc-cmsg-transfer`

- `V8.0/文档/共享备忘_V8.0.md`：`cec976c60c0ca173a1ee88a0fdb81469935b5fcd`
- `V8.0/文档/README_索引.md`：`4bd5af6622e563d6a33d8924c4983f8032a5e5be`
- `V8.0/文档/项目完工汇总_V8.0.md`：`474969916a5d379bd6fb36801136ad13696f62e0`（blob `536f5d679c41db10354d58cbcd52bd1d94e8c5c9`，3,866 B）
- `V8.0/文档/项目完成度报告_V8.0.md`：`e065c1b6df11c3abebba525690b55fb2726da5c3`（blob `8201a5fb6cb92728e7af1c5571e6222288b722c2`，9,940 B）
- `V8.0/文档/四路径深度过滤与补强清单_V8.0.md`：`f9d581cf3cfa9856b6c62541463f08155412ae3b`（blob `ff43097437670fd1592f0075360742ecfd49f821`，16,872 B）
- `V8.0/文档/四路径补强清单_V8.0.csv`：`28af574ab355010b208a79fddf02a508522592c0`（blob `2a216de6a7b0687d3f7f19f28598f77e3f40b3ac`，10,238 B）

### `kspc-grasp-transfer`

- `V8.0/文档/项目完成度报告_V8.0.md`：`8d25b8992d9c8a5472704ca0817f87e6c8e20490`
- `V8.0/文档/项目完工汇总_V8.0.md`：`d49647e3a9c6cc25e6ba9f3bab181d4cd31095bf`
- `V8.0/文档/共享备忘_V8.0.md`：`141044f1e43f6391196d131382d64a108052bb8a`
- `V8.0/文档/四路径深度过滤与补强清单_V8.0.md`：`b7cae86f8c613425aab4486eca6638ff570ad770`
- `V8.0/文档/README_索引.md`：`1b5a093936d22c4a278e0ca8ec79ab15986104cd`

### `grasp-top15-import-tool`

- `V8.0/文档/项目完成度报告_V8.0.md`：`7f01a200c5ee7c77c4f0da66fe38d150f1c8fd8b`
- `V8.0/文档/项目完工汇总_V8.0.md`：`b15f4083c80359edcd09c408303aa0440cf253c8`
- `V8.0/文档/共享备忘_V8.0.md`：`b523233e8f4acc3dad1a7ee8282f5a8fc66fd517`
- `V8.0/文档/README_索引.md`：`f086c30e687c2c988614cec3315c26f97cd78e1a`
- `V8.0/文档/四路径深度过滤与补强清单_V8.0.md`：`871eae9aa220d5939afdef1633a4611082f610fd`

## 三、内容口径

- 三仓库 `项目完成度报告_V8.0.md` 均为同内容，blob `8201a5fb6cb92728e7af1c5571e6222288b722c2`（9,940 B）；核心结论：原口径 36/37（97.3%），双版本语义复核 **34/37（91.9%）**，P0-4 三项返工。
- 三仓库 `项目完工汇总_V8.0.md` 均为同内容，blob `536f5d679c41db10354d58cbcd52bd1d94e8c5c9`（3,866 B），37 行摘要表 + 结论分布 + 三项返工。
- 三仓库 `四路径深度过滤与补强清单_V8.0.md` 均为同内容，blob `ff43097437670fd1592f0075360742ecfd49f821`（16,872 B），含四路径盘点、决定性证据、P0 三项、P1 七项、P2 六项、落地顺序与验收口径。
- `kspc-cmsg-transfer` 额外有完整 `四路径补强清单_V8.0.csv`（18 行 × 9 列，10,238 B）；另两仓库目前只有 MD 版清单。
- 三仓库均未覆盖 `V8.0/README_V8.0.md`；`grasp-top15-import-tool` 根目录的 `gpj_top15_core.py`（39,617 B 旧版）**未覆盖**，避免误改现行 41,497 B 版本。

## 四、后续待办

1. 三仓库的 `项目完工汇总_V8.0.csv`（完整六列）尚未逐个上传；当前以 `项目完工汇总_V8.0.md` 摘要 + 本地完整 CSV 交付。
2. `kspc-grasp-transfer`、`grasp-top15-import-tool` 尚未上传完整 18 行补强 CSV；当前以 MD 清单交付。
3. Feishu 共享版 `GyTEd9TaGogZ7sx1FUIcoa1d6Fd` 仍是 36/37 旧口径，待 P0 修复后统一更新，不在本轮改动。
4. `grasp-top15-import-tool` 根目录旧版 core 是否在后续覆盖，需用户单独确认；本轮未动。

> 备注：以上 commit SHA 均来自本轮 GitHub MCP 返回；`kspc-cmsg-transfer` 的 `项目完工汇总_V8.0.md` 与 `V8.0/README_V8.0.md` 不冲突，未覆盖旧文件。
