# -*- coding: utf-8 -*-
"""
竞驰管理通 (KSPC) → 管家婆财贸双全 (GraspCM) 基础资料直导引擎
------------------------------------------------------------
设计原则（沿用管家婆数据库维护经验）：
1. 编号数字化 + 级联编号：类型编号按 5 位一段生成（00001 / 0000100001），
   父编号 = 子编号去掉末 5 位；UserCode 与内部 typeId 同值，原编号写入备注。
2. 层级保留：按源 par_id 重建，不平铺。
3. deleted=0/1 定量；UpdateTag=10000；XW_BaseUpdateTag 归零。
4. 子级计数 soncount/sonnum 按 ParId 真实直接子级数重算。
5. 每商品必须写 T_Jxc_PtypeUnit(nUnit=1)，否则财贸价格/单据取不到单位。
6. 幂等：导入行统一备注前缀“竞驰导入|”，重复导入先按标记清理旧行，不碰目标自有数据。
7. 每次写入前可自动备份目标库；导入后清客户端 BaseInfo 缓存。

只依赖 pyodbc + ODBC Driver 17 for SQL Server。
"""

import datetime
import os
import re
import time

import pyodbc

MARK = "竞驰导入|"
DRIVER_CANDIDATES = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
]

# 竞驰往来单位 type → 财贸 isclient / 中文含义
WLDW_TYPE = {
    0: (1, "商场专柜"),
    1: (1, "普通客户"),
    2: (1, "加盟代理"),
    3: (0, "供应商"),
}

# 财贸价格位（T_Jxc_PtypeUnit / ptype 预设售价）语义
PRICE_RULES = [
    ("price", "RetailPrice / ptype.preprice4", "零售价"),
    ("price1", "TradePrice1 / ptype.preprice1", "预设售价1"),
    ("price2", "TradePrice2 / ptype.preprice2", "预设售价2"),
    ("price3", "TradePrice3 / ptype.preprice3", "预设售价3"),
    ("price4", "TradePrice4 / ptype.preprice5", "预设售价4"),
    ("price5", "TradePrice5 / ptype.preprice6", "预设售价5"),
    ("pf_price", "TradePrice6", "批发价"),
    ("lowprice", "MinSalePrice", "最低售价"),
]

MAPPING_ROWS = [
    # 对象, 源表/字段, 目标表/字段, 规则
    ("往来单位", "t_base_wldw_inner.code", "Btype.UserCode / typeId", "级联数字化 00001 起，原编号入备注"),
    ("往来单位", "t_base_wldw_inner.fullname", "Btype.FullName", "直接对应"),
    ("往来单位", "t_base_wldw_inner.name", "Btype.Name", "直接对应"),
    ("往来单位", "t_base_wldw_inner.pym", "Btype.Namepy", "转大写"),
    ("往来单位", "t_base_wldw_inner.type", "Btype.isclient", "0/1/2→客户(1)，3→供应商(0)，类型名入备注"),
    ("往来单位", "t_base_wldw_inner.addr", "Btype.TelAndAddress", "直接对应"),
    ("往来单位", "t_base_wldw_inner.tel", "Btype.Mobile", "直接对应"),
    ("往来单位", "t_base_wldw_inner.postcode", "Btype.PostCode", ""),
    ("往来单位", "t_base_wldw_inner.person", "Btype.Person", ""),
    ("往来单位", "t_base_wldw_inner.tax", "Btype.TaxNumber", ""),
    ("往来单位", "t_base_wldw_inner.bankcount", "Btype.BankAndAcount / BankAcount", "双列同写"),
    ("往来单位", "t_base_wldw_inner.email / fax", "Btype.Email / fax", ""),
    ("往来单位", "t_base_wldw_inner.comment", "Btype.Comment", "前置竞驰导入标记"),
    ("往来单位", "t_base_wldw_inner.del / isstop", "Btype.deleted", "任一为 1 即停用"),
    ("往来单位", "t_base_wldw_join", "Btype 追加一条客户", "SettleBtypeId=关联单位，源 1 行"),
    ("商品", "t_base_goods_inner.code", "ptype.UserCode / typeId", "按 PAR_ID 级联编号"),
    ("商品", "t_base_goods_inner.fullname / name / pym", "ptype.FullName / Name / Namepy", ""),
    ("商品", "t_base_goods_inner.standard", "ptype.Standard", "规格"),
    ("商品", "t_base_goods_inner.xh", "ptype.Type", "型号"),
    ("商品", "t_base_goods_inner.addr", "ptype.Area", "产地"),
    ("商品", "t_base_goods_inner.barcode", "ptype.barcode / T_Jxc_PtypeUnit.BarCode", ""),
    ("商品", "t_base_goods_inner.unit1..unit4", "ptype.Unit1..Unit3 + UnitOther + T_Jxc_PtypeUnit", "空单位补默认‘个’"),
    ("商品", "t_base_goods_inner.unitrelation*", "ptype.UnitRate1/2 + T_Jxc_PtypeUnit.UnitRate", ""),
    ("商品", "t_base_goods_inner.price", "ptype.preprice4 / T_Jxc_PtypeUnit.RetailPrice", "零售价"),
    ("商品", "t_base_goods_inner.price1..price5", "ptype.preprice1/2/3/5/6 + T_Jxc_PtypeUnit.TradePrice1..5", "预设售价"),
    ("商品", "t_base_goods_inner.pf_price", "T_Jxc_PtypeUnit.TradePrice6", "批发价"),
    ("商品", "t_base_goods_inner.lowprice", "ptype.MinSalePrice / T_Jxc_PtypeUnit.MinSalePrice", "最低售价"),
    ("商品", "t_base_goods_inner.recprice / recprice1", "RecPrice.BuyPrice / SalePrice", "最近进价/售价"),
    ("商品", "t_base_goods_inner.del", "ptype.deleted", ""),
    ("商品", "t_base_goods_inner.costmode", "ptype.costmode", "0/1/3/4 合法值校验"),
    ("商品", "t_base_goods_inner.warnup / warndown", "ptype.warnup / warndown", "库存上下限"),
    ("商品", "t_base_goods_inner.comment", "ptype.Comment", "前置竞驰导入标记"),
    ("仓库", "t_base_storage_inner.code", "Stock.UserCode / typeId", "按 par_id 级联编号"),
    ("仓库", "t_base_storage_inner.fullname / name / pym", "Stock.FullName / Name / Namepy", ""),
    ("仓库", "t_base_storage_inner.comment + type/needcheck", "Stock.Comment", "源仓库类型、是否盘点入备注"),
    ("仓库", "t_base_storage_inner.del", "Stock.deleted", ""),
    ("职员", "t_base_employees.code", "Employee.UserCode / typeId", "根下顺延 00002（目标已有 00001）"),
    ("职员", "t_base_employees.fullname / name / pym", "Employee.FullName / Name / Namepy", ""),
    ("职员", "t_base_employees.depid", "Employee.Department", "映射到 Department.typeid"),
    ("职员", "t_base_employees.tel / addr / mobileNo", "Employee.Tel / Address / Mobile", ""),
    ("职员", "t_base_employees.comment + LowDiscount", "Employee.Comment", "折扣入备注"),
    ("职员", "t_base_employees.del / candel", "Employee.deleted", ""),
    ("部门", "t_base_department.name / fullname", "Department.FullName", "fullname 无意义时取 name"),
    ("部门", "t_base_department.code", "Department.usercode / typeid", "00001 起"),
    ("部门", "t_base_department.pym / del / comment", "Department.namepy / deleted / Comment", ""),
    ("期初库存", "t_prime_goodsstock.goodsid", "IniGoodsStocks.PtypeId", "商品编号映射"),
    ("期初库存", "t_prime_goodsstock.stid", "IniGoodsStocks.KtypeId", "仓库编号映射"),
    ("期初库存", "t_prime_goodsstock.goodsqty / price / total", "IniGoodsStocks.Qty / Price / Total", "金额与数量单价校验"),
    ("期初库存", "t_prime_goodsstock.jobnumber / outdate", "IniGoodsStocks.JobNumber / OutFactoryDate", ""),
    ("结存库存", "t_base_goodsstock.goodsqty/price/total", "GoodsStocks.Qty", "当前库存快照，默认写"),
    ("结存库存", "t_base_goodsstock.goodsqty/price/total", "GoodsStockscost.Qty/Price/Total/Period", "成本层，库存状况读取，默认写"),
    ("条码", "t_base_GoodsBar.goodsID/barCode/Unit", "xw_PtypeBarCode.PTypeId/BarCode/UnitID", "UnitID 必须写数字串 0"),
    ("客户价格追踪", "t_base_price.costprice/saleprice/折扣", "xw_P_PriceFollow", "PRTypeId 0005/0007/0006/0008，默认写"),
    ("最近价格", "t_base_goods_inner.recprice/recprice1", "RecPrice.BuyPrice/SalePrice", "默认写"),
]

TABLES_TARGET = ["Btype", "ptype", "Stock", "Employee", "Department",
                 "IniGoodsStocks", "GoodsStocks", "GoodsStockscost", "T_Jxc_PtypeUnit", "xw_PtypeUnit",
                 "xw_PtypeBarCode", "xw_P_PtypePrice", "xw_P_PriceFollow", "RecPrice",
                 "AreaType", "XW_BaseUpdateTag"]


class MigrateError(Exception):
    pass


def pick_driver():
    installed = set(pyodbc.drivers())
    for d in DRIVER_CANDIDATES:
        if d in installed:
            return d
    raise MigrateError("未找到可用的 SQL Server ODBC 驱动，请安装 ODBC Driver 17 for SQL Server")


def connect(server, database, user="sa", password="", timeout=10):
    drv = pick_driver()
    cs = (f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};UID={user};PWD={password};"
          f"TrustServerCertificate=yes;Connection Timeout={timeout};")
    try:
        return pyodbc.connect(cs, autocommit=True, timeout=timeout)
    except pyodbc.Error as e:
        raise MigrateError(f"连接 {server} / {database} 失败：{e}")


def list_databases(server, user="sa", password=""):
    cn = connect(server, "master", user, password)
    cur = cn.cursor()
    cur.execute("SELECT name FROM sys.databases WHERE state_desc='ONLINE' ORDER BY name")
    names = [r[0] for r in cur.fetchall()]
    cn.close()
    return names


def table_exists(cn, table):
    cur = cn.cursor()
    cur.execute("SELECT COUNT(*) FROM sys.tables WHERE name=?", table)
    return cur.fetchone()[0] > 0


def read_rows(cn, table, where=""):
    cur = cn.cursor()
    cur.execute(f"SELECT * FROM [{table}] {where}")
    names = [d[0] for d in cur.description]
    return [{names[i]: r[i] for i in range(len(names))} for r in cur.fetchall()]


def s(v):
    return "" if v is None else str(v).strip()


def n(v, default=0):
    try:
        if v is None or str(v).strip() == "":
            return default
        return float(v)
    except Exception:
        return default


def i(v, default=0):
    try:
        if v is None or str(v).strip() == "":
            return default
        if isinstance(v, bool):
            return 1 if v else 0
        return int(float(v))
    except Exception:
        return default


def fget(row, key, default=None):
    """大小写不敏感取值（竞驰列名大小写不统一）"""
    if key in row:
        return row[key]
    lk = key.lower()
    for k, v in row.items():
        if k.lower() == lk:
            return v
    return default


def upper_py(v):
    v = s(v)
    return v.upper() if v else ""


def cut(v, limit):
    v = s(v)
    return v[:limit] if limit else v


class SourceData:
    """竞驰源库基础资料快照"""

    def __init__(self, cn):
        self.wldw = read_rows(cn, "t_base_wldw_inner")
        self.wldw_join = read_rows(cn, "t_base_wldw_join") if table_exists(cn, "t_base_wldw_join") else []
        self.goods = read_rows(cn, "t_base_goods_inner")
        self.stock = read_rows(cn, "t_base_storage_inner")
        self.employees = read_rows(cn, "t_base_employees")
        self.departments = read_rows(cn, "t_base_department")
        self.area = read_rows(cn, "t_base_area") if table_exists(cn, "t_base_area") else []
        self.ini_stock = read_rows(cn, "t_prime_goodsstock") if table_exists(cn, "t_prime_goodsstock") else []
        self.cur_stock = read_rows(cn, "t_base_goodsstock") if table_exists(cn, "t_base_goodsstock") else []
        self.goods_price = read_rows(cn, "t_base_goodsprice") if table_exists(cn, "t_base_goodsprice") else []
        self.price = read_rows(cn, "t_base_price") if table_exists(cn, "t_base_price") else []
        self.barcode = read_rows(cn, "t_base_GoodsBar") if table_exists(cn, "t_base_GoodsBar") else []


def analyze_source(cn):
    """预检源库：返回表存在性/行数，供 GUI 概览与导入前保护"""
    result = {}
    for t in ("t_base_wldw_inner", "t_base_wldw_join", "t_base_goods_inner",
              "t_base_storage_inner", "t_base_employees", "t_base_department",
              "t_prime_goodsstock", "t_base_goodsstock", "t_base_GoodsBar",
              "t_base_price", "t_base_goodsprice", "t_base_area"):
        if not table_exists(cn, t):
            result[t] = {"exists": False, "count": 0}
            continue
        cur = cn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM [{t}]")
        result[t] = {"exists": True, "count": cur.fetchone()[0]}
    return result


def analyze_target(cn):
    result = {t: table_exists(cn, t) for t in TABLES_TARGET}
    counts = {}
    for t in ("Btype", "ptype", "Stock", "Employee", "Department",
              "IniGoodsStocks", "GoodsStocks", "T_Jxc_PtypeUnit",
              "xw_PtypeUnit", "xw_PtypeBarCode", "xw_P_PtypePrice"):
        if result.get(t):
            cur = cn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM [{t}]")
            counts[t] = cur.fetchone()[0]
    result["_counts"] = counts
    return result


def existing_top_level(cn, table, id_col="typeId", par_col="Parid", comment_col="Comment"):
    """目标表已有顶级编号的最大值（忽略上一次竞驰导入的行，保证重复导入编号稳定）"""
    cur = cn.cursor()
    cur.execute(f"""SELECT {id_col} FROM [{table}]
                    WHERE {par_col} IN ('0','00000') AND {id_col}<>'00000'
                      AND ({comment_col} IS NULL OR {comment_col} NOT LIKE ?)""", MARK + "%")
    nums = []
    for r in cur.fetchall():
        m = re.search(r"(\d{5})$", s(r[0]))
        if m:
            nums.append(int(m.group(1)))
    return max(nums) if nums else 0


def assign_tree(rows, oid="id", pid="par_id", value_keys=None, start_top=1):
    """
    按源父子关系重建级联编号。
    返回 records: [{old, new, parent_new, depth, row}]，按 depth/顺序排列。
    """
    ids = {i(r[oid]) for r in rows}
    children = {}
    roots = []
    for r in rows:
        p = i(r.get(pid))
        if p in ids and p != i(r[oid]):
            children.setdefault(p, []).append(r)
        else:
            roots.append(r)
    # 防止环
    seen = set()
    order = []
    queue = [(r, None, 1) for r in roots]
    top_seq = start_top
    counters = {}
    while queue:
        r, parent_new, depth = queue.pop(0)
        o = i(r[oid])
        if o in seen:
            continue
        seen.add(o)
        if parent_new is None:
            seq = top_seq
            top_seq += 1
            parent_new = "00000"
            new = f"{seq:05d}"
        else:
            seq = counters.get(parent_new, 1)
            counters[parent_new] = seq + 1
            new = parent_new + f"{seq:05d}"
        order.append({"old": o, "new": new, "parent_new": parent_new,
                      "depth": depth, "row": r})
        for c in children.get(o, []):
            queue.append((c, new, depth + 1))
    # 未挂上的（环/孤儿）兜底为顶级
    for r in rows:
        o = i(r[oid])
        if o not in seen:
            seq = top_seq
            top_seq += 1
            order.append({"old": o, "new": f"{seq:05d}", "parent_new": "00000",
                          "depth": 1, "row": r})
    order.sort(key=lambda x: (x["depth"], x["new"]))
    return order


def _marker(code, oid, extra=""):
    txt = f"{MARK}原编号:{s(code)}|原ID:{oid}"
    if extra:
        txt += "|" + extra
    return cut(txt, 120)


def _clean_comment(user_comment, mark):
    uc = s(user_comment)
    if not uc:
        return cut(mark, 512)
    return cut(mark + "|" + uc, 512)


def plan_import(src_data_dict, target_cn, options):
    """
    生成导入计划（不写库）。options:
      default_unit: 空单位补的默认单位
      include_join: 是否把往来关系表作为客户导入
      include_cur_stock: 是否写当前库存快照
      include_price_follow: 是否写 xw_P_PriceFollow
      include_compat_price: 是否写 xw_P_PtypePrice
    """
    src = src_data_dict
    plan = {"groups": {}, "warnings": []}

    # ---------- 部门 ----------
    dept_rows = assign_tree(src["departments"], oid="ID", pid="par_id",
                            start_top=existing_top_level(target_cn, "Department", "typeid", "parid") + 1)
    dept_map = {d["old"]: d["new"] for d in dept_rows}
    dept_rec_map = {}

    # ---------- 职员 ----------
    emp_rows = assign_tree(src["employees"], oid="id", pid="par_id",
                           start_top=existing_top_level(target_cn, "Employee") + 1)
    emp_map = {e["old"]: e["new"] for e in emp_rows}

    # ---------- 往来单位 ----------
    wl_rows = assign_tree(src["wldw"], oid="id", pid="par_id",
                          start_top=existing_top_level(target_cn, "Btype") + 1)
    wl_map = {w["old"]: w["new"] for w in wl_rows}

    join_rows = []
    join_note = {}
    if src["wldw_join"]:
        for j in src["wldw_join"]:
            relate = i(j.get("wldwid"))
            reason = "兼客户" if i(j.get("type")) == 1 else "兼供应商"
            join_note[relate] = reason
    if options.get("include_join") and src["wldw_join"]:
        start = max([int(x["new"]) for x in wl_rows if x["parent_new"] == "00000"] or [0]) + 1
        for idx, j in enumerate(sorted(src["wldw_join"], key=lambda r: i(r["id"]))):
            join_rows.append({"old": i(j["id"]), "new": f"{start + idx:05d}",
                              "parent_new": "00000", "depth": 1, "row": j})

    # ---------- 商品 ----------
    start_p = existing_top_level(target_cn, "ptype", "typeId", "ParId") + 1
    goods_rows = assign_tree(src["goods"], oid="ID", pid="PAR_ID", start_top=start_p)
    goods_map = {g["old"]: g["new"] for g in goods_rows}

    # ---------- 仓库 ----------
    st_rows = assign_tree(src["stock"], oid="id", pid="par_id",
                          start_top=existing_top_level(target_cn, "Stock", "typeId", "parid") + 1)
    st_map = {x["old"]: x["new"] for x in st_rows}

    # ---------- 库存映射 ----------
    stock_qty = {}
    for r in src["ini_stock"]:
        gid, kid = i(r["goodsid"]), i(r["stid"])
        if gid not in goods_map:
            plan["warnings"].append(f"期初库存 goodsid={gid} 无对应商品，跳过")
            continue
        if kid not in st_map:
            plan["warnings"].append(f"期初库存 stid={kid} 无对应仓库，跳过")
            continue
        stock_qty[(gid, kid)] = r

    # ---------- 金额一致性 ----------
    for r in src["ini_stock"]:
        q, p, t = n(r.get("goodsqty")), n(r.get("price")), n(r.get("total"))
        if q and abs(p - t / q) > 0.01:
            plan["warnings"].append(
                f"期初库存 商品{i(r['goodsid'])} 单价×数量≠金额（{q}×{p}≠{t}），按金额/数量重算单价")

    plan["groups"] = {
        "departments": dept_rows,
        "employees": emp_rows,
        "wldw": wl_rows,
        "wldw_join": join_rows,
        "goods": goods_rows,
        "stocks": st_rows,
    }
    plan["maps"] = {"dept": dept_map, "emp": emp_map, "wldw": wl_map,
                    "goods": goods_map, "stock": st_map}
    plan["join_note"] = join_note
    plan["stock_rows"] = stock_qty
    plan["src"] = src
    plan["options"] = options
    return plan


def _insert(cn, table, values):
    cols = list(values.keys())
    sql = f"INSERT INTO [{table}] ({','.join('['+c+']' for c in cols)}) VALUES ({','.join('?'*len(cols))})"
    cur = cn.cursor()
    cur.execute(sql, [values[c] for c in cols])
    cur.execute("SELECT SCOPE_IDENTITY()")
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else None


def stock_period(cn):
    """取当前会计期间（int）；用于 GoodsStockscost.Period"""
    cur = cn.cursor()
    for sql in ("SELECT SubValue FROM T_GBL_SysDataCW WHERE SubName='Period'",
                "SELECT SubValue FROM T_GBL_SysDataCW WHERE SubName='OpenPeriod'"):
        try:
            cur.execute(sql)
            row = cur.fetchone()
            if row and str(row[0]).isdigit():
                return int(row[0])
        except Exception:
            pass
    return 200601


def _delete_previous(cn, log):
    """按备注标记清理上一次竞驰导入的数据，保留目标自有数据"""
    cur = cn.cursor()
    ptypes = []
    cur.execute("SELECT typeId FROM ptype WHERE Comment LIKE ?", MARK + "%")
    ptypes = [r[0] for r in cur.fetchall()]
    if ptypes:
        ph = ",".join("?" * len(ptypes))
        for t in ("T_Jxc_PtypeUnit", "xw_PtypeUnit", "xw_PtypeBarCode",
                  "xw_P_PtypePrice", "xw_P_PriceFollow", "IniGoodsStocks",
                  "GoodsStocks", "GoodsStockscost", "RecPrice"):
            if table_exists(cn, t):
                col = "PtypeId" if t in ("T_Jxc_PtypeUnit", "xw_P_PtypePrice", "GoodsStocks", "GoodsStockscost") else (
                    "PTypeId" if t in ("xw_PtypeUnit", "xw_PtypeBarCode", "xw_P_PriceFollow", "IniGoodsStocks") else "PtypeID")
                try:
                    cur.execute(f"DELETE FROM [{t}] WHERE {col} IN ({ph})", ptypes)
                except Exception as e:
                    log(f"清理 {t} 失败：{e}")
    for t, col in (("Btype", "Comment"), ("ptype", "Comment"), ("Stock", "Comment"),
                   ("Employee", "Comment"), ("Department", "Comment")):
        cur.execute(f"DELETE FROM [{t}] WHERE {col} LIKE ?", MARK + "%")
    log(f"已清理上次导入：商品 {len(ptypes)} 个及关联价格/库存行")


def import_all(src_cn, tgt_cn, options=None, log=None, backup_path=None):
    """执行直导。返回统计字典。"""
    options = options or {}
    log = log or (lambda m: None)
    t0 = time.time()
    src = analyze_source(src_cn)
    tgt = analyze_target(tgt_cn)
    missing = [t for t, ok in tgt.items() if not ok and not t.startswith("_") and t != "XW_BaseUpdateTag"]
    must = ["Btype", "ptype", "Stock", "Employee", "Department", "IniGoodsStocks", "T_Jxc_PtypeUnit"]
    miss_must = [t for t in must if not tgt.get(t)]
    if miss_must:
        raise MigrateError("目标库缺少必需表：" + ", ".join(miss_must) + "，已中止（防破坏非财贸账套）")
    for t in ("t_base_wldw_inner", "t_base_goods_inner", "t_base_storage_inner", "t_base_employees"):
        if not src[t]["exists"]:
            raise MigrateError(f"源库缺少表 {t}，不是竞驰账套，已中止")

    data = SourceData(src_cn)
    plan = plan_import({
        "wldw": data.wldw, "wldw_join": data.wldw_join, "goods": data.goods,
        "stock": data.stock, "employees": data.employees,
        "departments": data.departments, "ini_stock": data.ini_stock,
        "cur_stock": data.cur_stock, "price": data.price,
        "barcode": data.barcode,
    }, tgt_cn, options)

    # 备份
    if backup_path:
        log(f"备份目标库 → {backup_path}")
        cur = tgt_cn.cursor()
        cur.execute(f"BACKUP DATABASE [{quote_db(tgt_cn)}] TO DISK=N'{backup_path.replace(chr(39), chr(39)*2)}' "
                    f"WITH INIT, NAME=N'竞驰直导前自动备份'")
        while cur.nextset():
            pass
        cur.close()
        log("备份完成")

    tgt_cn.autocommit = False
    stats = {"units": 0, "goods": 0, "stocks": 0, "employees": 0,
             "departments": 0, "ini_rows": 0, "cur_rows": 0,
             "unit_rows": 0, "barcode_rows": 0, "price_rows": 0, "rec_rows": 0}
    try:
        _delete_previous(tgt_cn, log)
        default_unit = options.get("default_unit", "个") or "个"
        root_rec = {}
        for table, idc in (("Department", "typeid"), ("Employee", "typeId"),
                           ("Btype", "typeId"), ("ptype", "typeId"), ("Stock", "typeId")):
            cur = tgt_cn.cursor()
            cur.execute(f"SELECT Rec FROM [{table}] WHERE [{idc}]='00000'")
            row = cur.fetchone()
            root_rec[table] = int(row[0]) if row else 1

        # 1) 部门
        dept_rec = {}
        for d in plan["groups"]["departments"]:
            r = d["row"]
            name = s(r.get("name")) or s(r.get("fullname"))
            full = s(r.get("fullname"))
            if not full or full.isdigit():
                full = name
            vals = {
                "typeid": d["new"], "parid": d["parent_new"], "leveal": d["depth"],
                "sonnum": 0, "soncount": 0, "usercode": d["new"],
                "FullName": cut(full, 100), "Comment": _clean_comment(r.get("comment"), _marker(r.get("code"), d["old"])),
                "namepy": upper_py(r.get("pym")), "deleted": 1 if i(r.get("del")) else 0,
                "OrderNo": d["old"], "deptype": 0, "Costtype": 0,
                "Atypeid": "00001", "EtypeID": "", "UpdateTag": 10000,
            }
            rec = _insert(tgt_cn, "Department", vals)
            dept_rec[d["old"]] = rec
            stats["departments"] += 1
        # 回填 ParRec
        for d in plan["groups"]["departments"]:
            prec = (dept_rec.get(i(d["row"].get("par_id")), root_rec["Department"])
                    if d["parent_new"] != "00000" else root_rec["Department"])
            tgt_cn.cursor().execute("UPDATE Department SET parrec=? WHERE rec=?", (prec, dept_rec[d["old"]]))

        # 2) 职员
        emp_rec = {}
        for e in plan["groups"]["employees"]:
            r = e["row"]
            dep_old = i(r.get("depid"))
            dep_new = plan["maps"]["dept"].get(dep_old, "")
            vals = {
                "typeId": e["new"], "Parid": e["parent_new"], "leveal": e["depth"],
                "soncount": 0, "sonnum": 0, "FullName": cut(s(r.get("fullname")) or s(r.get("name")), 132),
                "Name": cut(s(r.get("name")), 60), "UserCode": e["new"],
                "Department": dep_new, "Tel": cut(r.get("tel"), 40), "Address": cut(r.get("addr"), 132),
                "Comment": _clean_comment(r.get("comment"), _marker(r.get("code"), e["old"],
                        "折扣:" + str(n(r.get("LowDiscount"))))),
                "deleted": 1 if i(r.get("del")) else 0, "Namepy": upper_py(r.get("pym")),
                "Pay": 0, "Incumbency": 1, "birthday": cut(r.get("birthday"), 20),
                "OrderNo": e["old"], "creditupperlimit": 0, "yshouupperlimit": 0,
                "clerk": 0, "Account": "", "Sex": "", "Education": "", "ID": "",
                "Birthplace": "", "UpdateTag": 10000,
            }
            rec = _insert(tgt_cn, "Employee", vals)
            emp_rec[e["old"]] = rec
            stats["employees"] += 1
        for e in plan["groups"]["employees"]:
            prec = (emp_rec.get(i(e["row"].get("par_id")), root_rec["Employee"])
                    if e["parent_new"] != "00000" else root_rec["Employee"])
            tgt_cn.cursor().execute("UPDATE Employee SET ParRec=? WHERE Rec=?", (prec, emp_rec[e["old"]]))

        # 3) 往来单位
        wl_rec = {}
        for w in plan["groups"]["wldw"]:
            r = w["row"]
            typ = i(r.get("type"))
            isclient, label = WLDW_TYPE.get(typ, (1, f"类型{typ}"))
            etype = plan["maps"]["emp"].get(i(r.get("BelongUserId")), "")
            extra = "单位类型:" + label
            note = plan.get("join_note", {}).get(w["old"])
            if note:
                extra += "|" + note
            vals = {
                "typeId": w["new"], "parid": w["parent_new"], "leveal": w["depth"],
                "soncount": 0, "sonnum": 0, "UserCode": w["new"],
                "FullName": cut(s(r.get("fullname")) or s(r.get("name")), 132),
                "Name": cut(s(r.get("name")), 60), "Area": "",
                "TelAndAddress": cut(r.get("addr"), 132), "PostCode": cut(r.get("postcode"), 100),
                "Person": cut(r.get("person"), 100), "TaxNumber": cut(r.get("tax"), 100),
                "BankAndAcount": cut(r.get("bankcount"), 100), "BankAcount": cut(r.get("bankcount"), 200),
                "Comment": _clean_comment(r.get("comment"), _marker(r.get("code"), w["old"], extra)),
                "ARTotal": 0, "APTotal": 0, "ARTotal00": n(r.get("ystotal00")), "APTotal00": n(r.get("yftotal00")),
                "deleted": 1 if (i(r.get("del")) or i(r.get("isstop"))) else 0,
                "Namepy": upper_py(r.get("pym")), "isclient": isclient,
                "AreaTypeID": "00000", "OrderNo": i(r.get("orderly")) or w["old"],
                "fax": cut(fget(r, "Fax", fget(r, "fax", "")), 60), "Email": cut(fget(r, "EMAIL", fget(r, "Email", "")), 200),
                "Mobile": cut(r.get("tel"), 120), "EtypeID": etype,
                "SettleMode": 1, "RDate": 0, "preprice": 0, "PrePriceType": 0,
                "SettleBtypeId": "", "UpdateTag": 10000,
            }
            rec = _insert(tgt_cn, "Btype", vals)
            wl_rec[w["old"]] = rec
            stats["units"] += 1
        for w in plan["groups"]["wldw"]:
            prec = (wl_rec.get(i(w["row"].get("par_id")), root_rec["Btype"])
                    if w["parent_new"] != "00000" else root_rec["Btype"])
            tgt_cn.cursor().execute("UPDATE Btype SET ParRec=? WHERE Rec=?", (prec, wl_rec[w["old"]]))

        # 3b) 往来关系
        for j in plan["groups"]["wldw_join"]:
            r = j["row"]
            relate = plan["maps"]["wldw"].get(i(r.get("wldwid")), "")
            vals = {
                "typeId": j["new"], "parid": "00000", "leveal": 1, "soncount": 0, "sonnum": 0,
                "UserCode": j["new"], "FullName": cut(s(r.get("fullname")) or s(r.get("name")), 132),
                "Name": cut(s(r.get("name")), 60), "Comment": _clean_comment(
                    r.get("comment"), _marker("", j["old"], "来源:往来关系|关联单位:" + relate)),
                "deleted": 0, "Namepy": upper_py(r.get("pym")), "isclient": 1,
                "AreaTypeID": "00000", "SettleBtypeId": relate, "SettleMode": 1,
                "EtypeID": "", "UpdateTag": 10000,
            }
            _insert(tgt_cn, "Btype", vals)
            stats["units"] += 1

        # 4) 商品
        stock_map = plan["maps"]["stock"]
        price_by_goods = {}
        for r in plan.get("src", {}).get("price", []):
            price_by_goods.setdefault(i(r.get("goodsid")), []).append(r)

        goods_rec = {}
        for g in plan["groups"]["goods"]:
            r = g["row"]
            unit1 = s(r.get("unit1")) or default_unit
            unit2 = s(r.get("unit2"))
            unit3 = s(r.get("unit3"))
            unit4 = s(r.get("unit4"))
            ktype = ""
            for (gid, kid) in plan["stock_rows"].keys():
                if gid == g["old"]:
                    ktype = stock_map.get(kid, "")
                    break
            vals = {
                "typeId": g["new"], "ParId": g["parent_new"], "leveal": g["depth"],
                "sonnum": 0, "soncount": 0, "CanModify": "1", "UserCode": g["new"],
                "FullName": cut(s(r.get("fullname")) or s(r.get("name")), 132),
                "Name": cut(s(r.get("name")), 60), "Standard": cut(r.get("standard"), 240),
                "Type": cut(r.get("xh"), 120), "Area": cut(r.get("addr"), 60),
                "Unit1": cut(unit1, 16), "Unit2": cut(unit2, 16),
                "Unit3": cut(unit3, 16) if unit3 else "", "UnitOther": cut(unit4, 16),
                "UnitRate1": n(r.get("unitrelation"), 1) or 1,
                "UnitRate2": n(r.get("unitrelation2"), 1) or 1,
                "preprice1": n(r.get("price1")), "preprice2": n(r.get("price2")),
                "preprice3": n(r.get("price3")), "preprice4": n(r.get("price")),
                "preprice5": n(r.get("price4")), "preprice6": n(r.get("price5")),
                "Comment": _clean_comment(r.get("comment"), _marker(r.get("code"), g["old"],
                        "规格组:" + s(r.get("sizegroupid")))),
                "recPrice": n(r.get("recprice")), "deleted": 1 if i(r.get("del")) else 0,
                "costmode": i(r.get("costmode")) if i(r.get("costmode")) in (0, 1, 3, 4) else 0,
                "Namepy": upper_py(r.get("pym")), "warnup": n(r.get("warnup")),
                "warndown": n(r.get("warndown")), "barcode": cut(r.get("barcode"), 100),
                "Barcode1": "", "OrderNo": i(r.get("orderly")), "KtypeId": ktype,
                "Tax": 13, "IsTaxPrice": 1, "bPurchase": 1, "bReceive": 1,
                "DefInUnit": 1, "DefOutUnit": 1, "ShelfLife": 0, "UpdateTag": 10000,
            }
            rec = _insert(tgt_cn, "ptype", vals)
            goods_rec[g["old"]] = rec
            stats["goods"] += 1

            # 单位价格表（叶子也要写，folder 不写也行；统一写便于查看）
            units = [(1, unit1, 1, r.get("price"), r.get("price1"), r.get("price2"),
                     r.get("price3"), r.get("price4"), r.get("price5"),
                     r.get("lowprice"), r.get("pf_price"), r.get("barcode"))]
            if unit2:
                units.append((2, unit2, n(r.get("unitrelation2"), 1) or 1, r.get("U2Price"),
                              r.get("U2Price1"), r.get("U2Price2"), r.get("U2Price3"),
                              r.get("U2Price4"), r.get("U2Price5"), r.get("U2LowPrice"),
                              r.get("U2PfPrice"), ""))
            if unit3:
                units.append((3, unit3, n(r.get("unitrelation3"), 1) or 1, r.get("U3Price"),
                              r.get("U3Price1"), r.get("U3Price2"), r.get("U3Price3"),
                              r.get("U3Price4"), r.get("U3Price5"), r.get("U3LowPrice"),
                              r.get("U3PfPrice"), ""))
            if unit4:
                units.append((4, unit4, n(r.get("unitrelation4"), 1) or 1, r.get("U4Price"),
                              r.get("U4Price1"), r.get("U4Price2"), r.get("U4Price3"),
                              r.get("U4Price4"), r.get("U4Price5"), r.get("U4LowPrice"),
                              r.get("U4PfPrice"), ""))
            for u in units:
                nu, nm, rate, retail, p1, p2, p3, p4, p5, low, pf, bcode = u
                _insert(tgt_cn, "T_Jxc_PtypeUnit", {
                    "PtypeId": g["new"], "nUnit": nu, "UnitName": cut(nm, 16),
                    "UnitRate": rate or 1, "RetailPrice": n(retail),
                    "TradePrice1": n(p1), "TradePrice2": n(p2), "TradePrice3": n(p3),
                    "TradePrice4": n(p4), "TradePrice5": n(p5), "TradePrice6": n(pf),
                    "MinSalePrice": n(low), "DefaultPrice": n(retail), "BarCode": cut(bcode, 100),
                })
                stats["unit_rows"] += 1
                if nu == 1:
                    _insert(tgt_cn, "xw_PtypeUnit", {
                        "PTypeId": g["new"], "Unit1": cut(nm, 16), "URate": rate or 1,
                        "IsBase": 1, "Comment": "", "Ordid": "0", "keyid": new_key(),
                    })
            # 兼容价格表（可选）
            if options.get("include_compat_price"):
                for pr, val in (("0001", r.get("price")), ("0002", r.get("price1")),
                                ("0003", r.get("price2")), ("0004", r.get("price3")),
                                ("0005", r.get("pf_price"))):
                    _insert(tgt_cn, "xw_P_PtypePrice", {
                        "PTypeId": g["new"], "UnitID": "0", "PRTypeId": pr,
                        "Price": n(val), "UpDateDt": datetime.datetime.now(),
                        "KeyId": new_key(),
                    })
                    stats["price_rows"] += 1

        # 回填商品 ParRec
        for g in plan["groups"]["goods"]:
            prec = (goods_rec.get(i(g["row"].get("PAR_ID")), root_rec["ptype"])
                    if g["parent_new"] != "00000" else root_rec["ptype"])
            tgt_cn.cursor().execute("UPDATE ptype SET ParRec=? WHERE Rec=?", (prec, goods_rec[g["old"]]))

        # 5) 仓库
        st_rec = {}
        for k in plan["groups"]["stocks"]:
            r = k["row"]
            vals = {
                "typeId": k["new"], "parid": k["parent_new"], "leveal": k["depth"],
                "sonnum": 0, "soncount": 0, "FullName": cut(s(r.get("fullname")) or s(r.get("name")), 132),
                "Name": cut(s(r.get("name")), 60), "UserCode": k["new"],
                "Comment": _clean_comment(r.get("comment"), _marker(r.get("code"), k["old"],
                        "仓库类型:" + s(r.get("type")) + "|需盘点:" + s(r.get("needcheck")))),
                "deleted": 1 if i(r.get("del")) else 0, "Namepy": upper_py(r.get("pym")),
                "OrderNo": i(r.get("orderly")) or k["old"], "bPosition": 0, "UpdateTag": 10000,
            }
            rec = _insert(tgt_cn, "Stock", vals)
            st_rec[k["old"]] = rec
            stats["stocks"] += 1
        for k in plan["groups"]["stocks"]:
            prec = (st_rec.get(i(k["row"].get("par_id")), root_rec["Stock"])
                    if k["parent_new"] != "00000" else root_rec["Stock"])
            tgt_cn.cursor().execute("UPDATE Stock SET ParRec=? WHERE Rec=?", (prec, st_rec[k["old"]]))

        # 6) 期初库存
        for (gid, kid), r in plan["stock_rows"].items():
            q, p, t = n(r.get("goodsqty")), n(r.get("price")), n(r.get("total"))
            if q and abs(t - q * p) > 0.01:
                p = round(t / q, 4)
            _insert(tgt_cn, "IniGoodsStocks", {
                "PtypeId": plan["maps"]["goods"][gid], "KtypeId": plan["maps"]["stock"][kid],
                "JobNumber": cut(r.get("jobnumber"), 40),
                "OutFactoryDate": cut(r.get("outdate"), 20), "Qty": q, "Price": p,
                "Total": t, "GoodsOrder": 0, "InStockDate": "", "OutStockDate": "",
            })
            stats["ini_rows"] += 1

        # 7) 结存库存（当前库存）：GoodsStocks 快照 + GoodsStockscost 成本层
        if options.get("include_cur_stock", True):
            period = stock_period(tgt_cn)
            for r in plan["src"].get("cur_stock", []):
                gid, kid = i(r.get("goodsid")), i(r.get("stid"))
                if gid in plan["maps"]["goods"] and kid in plan["maps"]["stock"]:
                    q, p, t = n(r.get("goodsqty")), n(r.get("price")), n(r.get("total"))
                    if q and abs(t - q * p) > 0.01:
                        p = round(t / q, 4)
                        t = round(q * p, 2)
                    pid, kid2 = plan["maps"]["goods"][gid], plan["maps"]["stock"][kid]
                    _insert(tgt_cn, "GoodsStocks", {
                        "PtypeId": pid, "KtypeId": kid2,
                        "Qty": q, "Custom1": "", "Custom2": "",
                        "BlockNo": "", "ProDate": "", "QtyOther": 0, "Custom3": "", "Custom4": "",
                    })
                    _insert(tgt_cn, "GoodsStockscost", {
                        "PtypeId": pid, "Qty": q, "Price": p, "Total": t,
                        "GoodsOrder": 0, "KTypeID": kid2, "Period": period, "BlockNo": "",
                    })
                    stats["cur_rows"] += 1
            if plan["src"].get("cur_stock"):
                log(f"结存库存写入 {stats['cur_rows']} 行（GoodsStocks + GoodsStockscost，期间 {period}）")

        # 8) 条码
        for r in plan["src"].get("barcode", []):
            gid = i(r.get("goodsID"))
            if gid in plan["maps"]["goods"] and s(r.get("barCode")):
                _insert(tgt_cn, "xw_PtypeBarCode", {
                    "PTypeId": plan["maps"]["goods"][gid], "UnitID": "0",
                    "BarCode": cut(r.get("barCode"), 60),
                    "Ordid": str(i(r.get("Unit"), 1)), "keyid": new_key(),
                })
                stats["barcode_rows"] += 1

        # 9) 客户价格追踪（xw_P_PriceFollow）+ 最近价格（RecPrice）
        if options.get("include_price_follow", True):
            price_rows = 0
            for r in plan["src"].get("price", []):
                gid, wid = i(r.get("goodsid")), i(r.get("wldwid"))
                if gid not in plan["maps"]["goods"] or wid not in plan["maps"]["wldw"]:
                    continue
                for pr, val in (("0005", r.get("costprice")), ("0007", r.get("saleprice")),
                                ("0006", r.get("buydiscount")), ("0008", r.get("salediscount"))):
                    if n(val) == 0:
                        continue
                    _insert(tgt_cn, "xw_P_PriceFollow", {
                        "PTypeId": plan["maps"]["goods"][gid], "UnitID": "0", "Price": n(val),
                        "BTypeId": plan["maps"]["wldw"][wid], "KTypeId": "", "BillDt": datetime.datetime.now(),
                        "PRTypeId": pr, "PPType": 6, "KeyId": new_key(), "JGTypeId": "", "MDTypeId": "",
                    })
                    price_rows += 1
                    stats["price_rows"] += 1
            log(f"客户价格追踪写入 {price_rows} 行")
            # 最近进价/售价（源商品行 recprice/recprice1）
            for g in plan["groups"]["goods"]:
                r = g["row"]
                bp, sp = n(r.get("recprice")), n(r.get("recprice1"))
                if bp == 0 and sp == 0:
                    continue
                _insert(tgt_cn, "RecPrice", {
                    "PtypeID": plan["maps"]["goods"][i(g["row"].get("ID"))],
                    "BuyPrice": bp, "SalePrice": sp,
                })
                stats["rec_rows"] += 1
            if stats["rec_rows"]:
                log(f"最近价格写入 {stats['rec_rows']} 行")

        # 10) 子级计数重算 + UpdateTag 归位
        recalc_children(tgt_cn, log)
        normalize_tags(tgt_cn, log)

        tgt_cn.commit()
    except Exception:
        tgt_cn.rollback()
        raise

    stats["elapsed"] = round(time.time() - t0, 1)
    stats["warnings"] = plan["warnings"]
    log(f"导入完成：单位 {stats['units']}、商品 {stats['goods']}、仓库 {stats['stocks']}、"
        f"职员 {stats['employees']}、部门 {stats['departments']}、期初 {stats['ini_rows']}、"
        f"结存 {stats['cur_rows']}、单位价格 {stats['unit_rows']}、客户价格 {stats['price_rows']}，"
        f"用时 {stats['elapsed']}s")
    return stats


def quote_db(cn):
    cur = cn.cursor()
    cur.execute("SELECT DB_NAME()")
    return cur.fetchone()[0]


def new_key():
    import uuid
    return "{" + str(uuid.uuid4()).upper() + "}"


def recalc_children(cn, log=None):
    """按 ParId 重算子级数 soncount/sonnum"""
    pairs = [("Btype", "typeId", "parid"), ("ptype", "typeId", "ParId"),
             ("Stock", "typeId", "parid"), ("Employee", "typeId", "Parid"),
             ("Department", "typeid", "parid")]
    cur = cn.cursor()
    for table, idc, parc in pairs:
        cur.execute(f"""UPDATE [{table}] SET soncount=(SELECT COUNT(*) FROM [{table}] c WHERE c.[{parc}]=[{table}].[{idc}]),
                        sonnum=(SELECT COUNT(*) FROM [{table}] c WHERE c.[{parc}]=[{table}].[{idc}])""")
        if log:
            log(f"{table} 子级计数已重算")


def normalize_tags(cn, log=None):
    cur = cn.cursor()
    for t in ("Btype", "ptype", "Stock", "Employee", "Department"):
        cur.execute(f"UPDATE [{t}] SET UpdateTag=10000 WHERE UpdateTag<10000")
    if table_exists(cn, "XW_BaseUpdateTag"):
        cur.execute("UPDATE XW_BaseUpdateTag SET UpdateTag=0 WHERE BaseType IN ('BType','Ptype','Stock','Employee','Department','AreaType','BrandType')")
    if log:
        log("UpdateTag 已归位 10000，XW_BaseUpdateTag 已清零")


def clear_cache(account_name, root=r"F:\GraspServer\CMSQ\Data\BaseInfo"):
    """清理财贸客户端基本信息缓存目录"""
    p = os.path.join(root, account_name)
    if not os.path.isdir(p):
        return 0, f"未找到缓存目录 {p}（客户端未打开过该账套时可忽略）"
    n = 0
    for f in os.listdir(p):
        fp = os.path.join(p, f)
        try:
            if os.path.isfile(fp):
                os.remove(fp); n += 1
            elif os.path.isdir(fp):
                import shutil
                shutil.rmtree(fp); n += 1
        except Exception:
            pass
    return n, f"已清理缓存目录 {p}（{n} 项）"


def verify(src_cn, tgt_cn, options=None, log=None):
    """数据校验，返回 [(检查项, 结果, 详情)]"""
    log = log or (lambda m: None)
    options = options or {}
    checks = []
    src = SourceData(src_cn)

    def count_sql(cn, sql):
        cur = cn.cursor(); cur.execute(sql); return cur.fetchone()[0]

    # 1 行数
    expect = {
        "Btype": len(src.wldw) + (len(src.wldw_join) if options.get("include_join") else 0),
        "ptype": len(src.goods), "Stock": len(src.stock),
        "Employee": len(src.employees), "Department": len(src.departments),
        "IniGoodsStocks": len(src.ini_stock),
    }
    for t, n_exp in expect.items():
        got = count_sql(tgt_cn, f"SELECT COUNT(*) FROM [{t}] WHERE "
                                + ("Comment LIKE '竞驰导入|%'" if t != "IniGoodsStocks" else "1=1"))
        ok = (got == n_exp)
        checks.append((f"{t} 导入行数", "通过" if ok else "不符", f"源 {n_exp} / 目标 {got}"))

    # 2 编号规范（对全表，含目标自有数据）
    for t, idc in (("Btype", "typeId"), ("ptype", "typeId"), ("Stock", "typeId"),
                   ("Employee", "typeId"), ("Department", "typeid")):
        letters = count_sql(tgt_cn, f"SELECT COUNT(*) FROM [{t}] WHERE [{idc}] LIKE '%[A-Za-z]%'")
        dup = count_sql(tgt_cn, f"SELECT COUNT(*) FROM (SELECT [{idc}] FROM [{t}] GROUP BY [{idc}] HAVING COUNT(*)>1) x")
        badlen = count_sql(tgt_cn, f"SELECT COUNT(*) FROM [{t}] WHERE LEN([{idc}])%5<>0 AND [{idc}]<>'0'")
        ok = letters == dup == badlen == 0
        checks.append((f"{t} 编号规范", "通过" if ok else "异常",
                       f"字母 {letters} / 重复 {dup} / 长度非5倍数 {badlen}"))

    # 3 父子引用
    for t, idc, parc in (("Btype", "typeId", "parid"), ("ptype", "typeId", "ParId"),
                         ("Stock", "typeId", "parid"), ("Employee", "typeId", "Parid"),
                         ("Department", "typeid", "parid")):
        missing = count_sql(tgt_cn, f"""SELECT COUNT(*) FROM [{t}] x WHERE x.leveal>0 AND NOT EXISTS
              (SELECT 1 FROM [{t}] p WHERE p.[{idc}]=x.[{parc}])""")
        checks.append((f"{t} 父级引用", "通过" if missing == 0 else "悬空", f"缺失父级 {missing}"))

    # 4 子级计数
    bad = 0
    for t, idc, parc in (("Btype", "typeId", "parid"), ("ptype", "typeId", "ParId"),
                         ("Stock", "typeId", "parid"), ("Employee", "typeId", "Parid"),
                         ("Department", "typeid", "parid")):
        bad += count_sql(tgt_cn, f"""SELECT COUNT(*) FROM [{t}] x WHERE x.soncount <>
              (SELECT COUNT(*) FROM [{t}] c WHERE c.[{parc}]=x.[{idc}])""")
    checks.append(("子级计数", "通过" if bad == 0 else "异常", f"不一致行 {bad}"))

    # 5 单位价格表
    leaf = count_sql(tgt_cn, "SELECT COUNT(*) FROM ptype WHERE sonnum=0 AND typeId<>'00000'")
    leaf_nu = count_sql(tgt_cn, "SELECT COUNT(*) FROM ptype WHERE sonnum=0 AND typeId<>'00000' AND deleted=0 AND NOT EXISTS (SELECT 1 FROM T_Jxc_PtypeUnit u WHERE u.PtypeId=ptype.typeId AND u.nUnit=1)")
    checks.append(("商品单位价格表 nUnit=1", "通过" if leaf_nu == 0 else "缺失",
                   f"叶子商品 {leaf}，缺单位行 {leaf_nu}"))

    # 6 期初库存引用
    bad_ini = count_sql(tgt_cn, """SELECT COUNT(*) FROM IniGoodsStocks i WHERE NOT EXISTS
             (SELECT 1 FROM ptype p WHERE p.typeId=i.PtypeId) OR NOT EXISTS
             (SELECT 1 FROM Stock k WHERE k.typeId=i.KtypeId)""")
    checks.append(("期初库存引用", "通过" if bad_ini == 0 else "悬空", f"无效引用 {bad_ini}"))

    # 6b 结存库存（当前库存）行数与读取
    imported_pt = "SELECT typeId FROM ptype WHERE Comment LIKE '竞驰导入|%'"
    for t, col in (("GoodsStocks", "PtypeId"), ("GoodsStockscost", "PtypeId")):
        if table_exists(tgt_cn, t):
            got = count_sql(tgt_cn, f"SELECT COUNT(*) FROM [{t}] WHERE [{col}] IN ({imported_pt})")
            exp = len(src.cur_stock) if options.get("include_cur_stock", True) else 0
            checks.append((f"结存库存 {t} 行数", "通过" if got == exp else "不符", f"源 {len(src.cur_stock)} / 目标 {got}"))
    try:
        cur = tgt_cn.cursor()
        cur.execute("EXEC dbo.p_jxc_PkuCunList '00000','','',1,''")
        desc = [d[0].upper() for d in (cur.description or [])]
        rows = cur.fetchall()
        qi = desc.index("QTY") if "QTY" in desc else 18
        qty = sum(n(r[qi]) for r in rows)
        exp_qty = sum(n(r.get("goodsqty")) for r in src.cur_stock) if options.get("include_cur_stock", True) else 0
        ok = abs(qty - exp_qty) <= 0.01
        checks.append(("财贸库存状况读取", "通过" if ok else "不符",
                       f"返回 {len(rows)} 行，合计数量 {qty}（期望 {exp_qty}）"))
    except Exception as e:
        checks.append(("财贸库存状况读取", "失败", str(e)[:120]))

    # 6c 客户价格追踪 / 最近价格
    exp_price = 0
    if options.get("include_price_follow", True):
        gids = {i(fget(g, "ID")) for g in src.goods}
        wids = {i(fget(w, "id")) for w in src.wldw}
        for r in src.price:
            gid, wid = i(r.get("goodsid")), i(r.get("wldwid"))
            if gid in gids and wid in wids:
                exp_price += sum(1 for v in (r.get("costprice"), r.get("saleprice"),
                                             r.get("buydiscount"), r.get("salediscount")) if n(v) != 0)
    got_price = count_sql(tgt_cn, f"""SELECT COUNT(*) FROM xw_P_PriceFollow
          WHERE PTypeId IN ({imported_pt})""")
    checks.append(("客户价格追踪 xw_P_PriceFollow", "通过" if got_price == exp_price else "不符",
                   f"源可导 {exp_price} / 目标 {got_price}"))

    exp_rec = 0
    if options.get("include_price_follow", True):
        exp_rec = sum(1 for g in src.goods if n(g.get("recprice")) or n(g.get("recprice1")))
    got_rec = count_sql(tgt_cn, f"SELECT COUNT(*) FROM RecPrice WHERE PtypeID IN ({imported_pt})")
    checks.append(("最近价格 RecPrice", "通过" if got_rec == exp_rec else "不符",
                   f"源可导 {exp_rec} / 目标 {got_rec}"))

    # 7 UpdateTag
    tags = count_sql(tgt_cn, "SELECT COUNT(*) FROM Btype WHERE UpdateTag<10000")
    checks.append(("UpdateTag=10000", "通过" if tags == 0 else "异常", f"Btype 低值行 {tags}"))

    # 8 读取链路
    for mode, label, expect_min in (("B", "往来单位", expect["Btype"] + 1),
                                    ("C", "客户", 1), ("V", "供应商", 1),
                                    ("P", "商品", expect["ptype"] + 1),
                                    ("K", "仓库", expect["Stock"] + 1),
                                    ("E", "职员", expect["Employee"] + 1),
                                    ("D", "部门", expect["Department"] + 1)):
        try:
            cur = tgt_cn.cursor()
            cur.execute("DECLARE @o int; EXEC dbo.xw_GetBasicData ?,0,0,0,@o OUTPUT", mode)
            rows = len(cur.fetchall())
            checks.append((f"财贸读取 {mode}({label})", "通过" if rows >= expect_min else "偏少",
                           f"返回 {rows} 行（期望≥{expect_min}）"))
        except Exception as e:
            checks.append((f"财贸读取 {mode}({label})", "失败", str(e)[:120]))

    return checks


def plan_preview(plan):
    rows = []
    for key, label in (("wldw", "往来单位"), ("wldw_join", "往来关系"),
                       ("goods", "商品"), ("stocks", "仓库"),
                       ("employees", "职员"), ("departments", "部门")):
        for x in plan["groups"].get(key, []):
            r = x["row"]
            rows.append((label, s(r.get("code")) or "-", s(r.get("fullname")) or s(r.get("name")),
                         x["new"], x["depth"]))
    return rows


def _preview_struct(src_cn, options):
    data = SourceData(src_cn)
    return {
        "wldw": data.wldw, "wldw_join": data.wldw_join, "goods": data.goods,
        "stock": data.stock, "employees": data.employees,
        "departments": data.departments, "ini_stock": data.ini_stock,
        "cur_stock": data.cur_stock, "price": data.price, "barcode": data.barcode,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="竞驰管理通 → 管家婆财贸 基础资料直导")
    ap.add_argument("--src-server", required=True)
    ap.add_argument("--src-db", required=True)
    ap.add_argument("--dst-server", required=True)
    ap.add_argument("--dst-db", required=True)
    ap.add_argument("--user", default="sa")
    ap.add_argument("--password", default="")
    ap.add_argument("--apply", action="store_true", help="执行导入（缺省只预演）")
    ap.add_argument("--verify", action="store_true", help="导入后校验")
    ap.add_argument("--backup", default="", help="导入前备份目标库的完整路径")
    ap.add_argument("--default-unit", default="个")
    ap.add_argument("--join", action="store_true", help="把往来关系表另建为客户（默认折算为备注）")
    ap.add_argument("--no-cur-stock", action="store_true", help="不写结存库存 GoodsStocks/GoodsStockscost（默认写）")
    ap.add_argument("--no-price-follow", action="store_true", help="不写客户价格追踪 xw_P_PriceFollow/RecPrice（默认写）")
    ap.add_argument("--compat-price", action="store_true")
    a = ap.parse_args()

    src_cn = connect(a.src_server, a.src_db, a.user, a.password)
    tgt_cn = connect(a.dst_server, a.dst_db, a.user, a.password)
    options = {
        "default_unit": a.default_unit,
        "include_join": a.join,
        "include_cur_stock": not a.no_cur_stock,
        "include_price_follow": not a.no_price_follow,
        "include_compat_price": a.compat_price,
    }
    data = _preview_struct(src_cn, options)
    plan = plan_import(data, tgt_cn, options)
    print("=== 编号映射预览 ===")
    for row in plan_preview(plan):
        print(" | ".join(str(x) for x in row))
    for w in plan["warnings"]:
        print("WARN:", w)
    if a.apply:
        stats = import_all(src_cn, tgt_cn, options, log=lambda m: print(m),
                           backup_path=a.backup or None)
        print(stats)
    if a.verify:
        for c in verify(src_cn, tgt_cn, options):
            print(f"[{c[1]}] {c[0]} - {c[2]}")


if __name__ == "__main__":
    main()
