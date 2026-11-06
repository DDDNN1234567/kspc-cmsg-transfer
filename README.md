# 竞驰管理通 → 管家婆财贸双全 资料直导

把 **竞驰管理通 V8.1**（库 `kspcDefault`）的基础资料、期初库存、结存库存与客户价格追踪，
按字段对应关系直接写入 **管家婆财贸双全（CMSQ）** 账套库，并自动校验。

> 这是“竞驰 → 管家婆”适配器家族的**财贸分支**。
> 另两个实例见：
> - [kspc-grasp-transfer](https://github.com/DDDNN1234567/kspc-grasp-transfer)（竞驰 → 辉煌 TOP15，走官方过程通道）
> - [grasp-gpj-tools](https://github.com/DDDNN1234567/grasp-gpj-tools)（辉煌版维护工具集）
>
> 目标产品不同，表结构与读取链路不同，**不能把辉煌版的做法直接搬过来**。

---

## 一、能导什么

| 模块 | 竞驰源 | 财贸目标 | 关键处理 |
|---|---|---|---|
| 往来单位 | `t_base_wldw_inner` | `Btype` | `type` → `isclient`（3=供应商，其余=客户） |
| 往来关系 | `t_base_wldw_join` | `Btype` 备注 | 财贸无“兼职”字段，折算为“兼客户/兼供应商” |
| 存货（分类/明细） | `t_base_goods_inner` | `ptype` | 级联编号 + 层级保留 + 单位/价格 |
| 商品单位与价格 | 商品价格字段 | `T_Jxc_PtypeUnit` | 财贸价格主载体，每个商品至少 `nUnit=1` |
| 仓库 | `t_base_storage_inner` | `Stock` | 保留子仓层级 |
| 职员 | `t_base_employees` | `Employee` | 部门引用映射 |
| 部门 | `t_base_department` | `Department` | 修正源 `fullname` 脏值 |
| 期初库存 | `t_prime_goodsstock` | `IniGoodsStocks` | `Qty*Price=Total` 校验 |
| 结存库存（当前库存） | `t_base_goodsstock` | `GoodsStocks` + `GoodsStockscost` | 库存状况读取链路 |
| 客户价格追踪 | `t_base_price` | `xw_P_PriceFollow` | 0005/0007/0006/0008 四类 |
| 最近价格 | 商品 `recprice/recprice1` | `RecPrice` | 最近进价/售价 |
| 条码（可选） | `t_base_GoodsBar` | `xw_PtypeBarCode` | `UnitID` 必须是数字串 `0` |

不导：单据、权限、程序配置、会计科目（目标已有同编号体系）。

---

## 二、快速开始

### 方式 A：图形工具（推荐）

1. 运行 `竞驰转财贸直导工具V1.0.exe`（Windows，免安装，约 11.9 MB；随交付目录提供，仓库仅存源码与文档）
2. 两侧分别填服务器（命名实例）、用户名、密码，刷新库列表
3. 预检 → 一键直导（备份 → 导入 → 归位 → 校验 → 清缓存）
4. 重登财贸客户端查看“基本信息 / 期初库存 / 库存状况”

### 方式 B：命令行 / 批处理

```bat
python kpsc_to_cmsg.py ^
  --src-server "DESKTOP-8P5G8VQ\SQLEXPRESS" --src-db kspcDefault ^
  --dst-server "DESKTOP-8P5G8VQ\SQLSERVER" --dst-db "财贸测试demo" ^
  --user sa --password *** --apply --verify ^
  --backup "F:\GraspServer\CMSQ\BackUp\竞驰直导前.bak"
```

不带 `--apply` 只打印编号映射预览，不写库。

依赖：Python 3.9+、`pyodbc`、`ODBC Driver 17 for SQL Server`。

---

## 三、实测结果（2026-11-06）

源：`DESKTOP-8P5G8VQ\SQLEXPRESS` / `kspcDefault`（SQL2008 Express SP4）
目标：`DESKTOP-8P5G8VQ\SQLSERVER` / `财贸测试demo`（SQL2016）

| 模块 | 条数 |
|---|---|
| 往来单位 | 4（客户 3 + 供应商 1） |
| 商品 | 2（分类 00001 + 明细 0000100001） |
| 仓库 | 4（含子仓 0000200001） |
| 职员 | 1（00002 管理员） |
| 部门 | 1（00001 业务部） |
| 期初库存 | 1 行：100 × 1000 = 100000 |
| 结存库存 | `GoodsStocks` 1 行 + `GoodsStockscost` 1 行，库存状况读回 100 / 100000 |
| 客户价格追踪 | 0 行（源 3 张价格表均 0 行，完整导入结果即 0） |

校验 **32 项全部通过**：

- 六表导入行数与源一致
- 编号无字母 / 无重复 / 长度均为 5 的倍数
- 父级引用无悬空、子级计数与真实直接子级一致
- 叶子商品均有 `nUnit=1`
- 期初库存商品/仓库引用有效
- 结存库存 `GoodsStocks`、`GoodsStockscost` 行数与源一致，`p_jxc_PkuCunList` 合计数量=100
- 客户价格追踪/最近价格行数与源可导数一致（源 0 → 目标 0）
- `UpdateTag` 全部 ≥10000

财贸真实读取链路：

| 过程 | 结果 |
|---|---|
| `xw_GetBasicData 'B'` | 5 行（4 + 根） |
| `xw_GetBasicData 'C'` | 4 行（3 客户 + 根） |
| `xw_GetBasicData 'V'` | 2 行（1 供应商 + 根） |
| `xw_GetBasicData 'P'` | 3 行（2 + 根） |
| `xw_GetBasicData 'K'` | 7 行 |
| `xw_GetBasicData 'E'` | 4 行 |
| `xw_GetBasicData 'D'` | 3 行 |
| `p_Jxc_GetIniGoodsStocks 'A','00000'` | 00001 测试商品 100 / 100000 / 1000 |
| `p_jxc_PkuCunList '00000','','',1,''` | 00001 测试商品 QTY=100 / TOTAL=100000 |

---

## 四、财贸与辉煌的关键差异

| 维度 | 辉煌 TOP | 财贸 CMSQ | 本项目做法 |
|---|---|---|---|
| 商品价格/单位 | `xw_P_PtypePrice`（3000+ 引用） | **`T_Jxc_PtypeUnit`**（135 引用） | 主写 `T_Jxc_PtypeUnit`，兼容表默认不写 |
| 期初/结存库存 | `IniGoodsStocks` | 期初 → `IniGoodsStocks`；结存 → `GoodsStocks`+`GoodsStockscost` | 期初/结存两条链路同时写入 |
| 客户/供应商 | 分表/分字段 | **`Btype.isclient`**（1 客户 / 0 供应商） | `type 3 → 0`，其余 → 1 |
| 仓库层级 | 必须平铺 | 支持子仓 | 保留 `00002 → 0000200001` |
| 刷新标记 | `updatetag=10000` + `xw_BaseUpdateTag=0` | `UpdateTag=10000` + `XW_BaseUpdateTag=0` | 按财贸机制归位 |
| 读取过程 | 5 参数含 `@EtypeID` | 5 参数含 `@nUsePage/@Rec/@OutRecords` | 直接调用验证 |

---

## 五、仓库结构

```
README.md
校验清单.txt
源码/
  kpsc_to_cmsg.py        迁移引擎（读取、映射、写入、校验、清缓存）
  kpsc_gui.py            tkinter 界面（busy 锁 / 线程安全日志 / 一键串联）
文档/
  字段映射表_竞驰到财贸.md   逐字段规则、未迁移对象、刷新机制
  使用说明.md              操作步骤、常见问题、回滚
  迁移报告_20261106.md     本次实机迁移与 32 项校验记录
  功能日志_V1.0.md          功能清单、界面交互、后续版本
  经验日志_竞驰转财贸.md    踩坑与结论（换目标产品前先读）
```

---

## 六、已知限制

- 竞驰源无价格/条码数据时，目标价格与条码为 0/空；报告会明确标注“源无数据”（本次已逐表核对 32 张价格相关表），不是映射遗漏。
- 结存库存按源当前值写入 `GoodsStocks`/`GoodsStockscost`（期间取账套当前期间），后续开账/过账会按财贸成本算法重算。
- 财贸没有“兼客户/兼供应商”字段，往来关系折算为备注（可配置另建单位）。
- 会计科目不新建：目标 `atypecw` 已含 1001/1131/1243/1501/2121 等同编号科目。
- 未做财贸客户端界面截图验收；验收依据是与客户端同源的 `xw_GetBasicData` / `p_Jxc_GetIniGoodsStocks` / `p_jxc_PkuCunList` 读取链路。

---

## 七、安全与回滚

- 导入前默认整库备份，路径必须是 SQL Server 服务账户可写目录（不要放用户目录）。
- 导入行统一备注 `竞驰导入|原编号:...`，重复导入自动替换，不碰目标自有数据。
- 回滚见《使用说明.md》第六节；最干净的回滚点是迁移前整库 `.bak`。

---

## 八、变更记录

- **V1.0（2026-11-06）**：首个财贸双全适配器。双实例直连、六类基础资料 + 期初/结存库存 + 客户价格追踪、32 项校验、tkinter GUI、PyInstaller 单文件。