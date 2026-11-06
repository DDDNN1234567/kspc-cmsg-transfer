# -*- coding: utf-8 -*-
"""
竞驰管理通 → 管家婆财贸双全 基础资料直导工具（GUI）
V1.0
交互沿用既有项目规范：
- 单窗口 + 分页签；连接参数默认空白手工填写，不预填不记忆
- 每个动作新建独立连接，避免源/目标串库
- 耗时操作 busy 锁 + 线程安全日志（队列 → 主线程刷新）
- 一键串联：备份 → 直导 → 归位 → 校验 → 清客户端缓存
- 日志超 3000 行自动裁剪
"""

import datetime
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk, filedialog

import kpsc_to_cmsg as eng

VERSION = "V1.0"
APP_TITLE = "竞驰转财贸直导工具 " + VERSION
DEFAULT_BACKUP_DIR = r"F:\GraspServer\CMSQ\BackUp"
CACHE_ROOT = r"F:\GraspServer\CMSQ\Data\BaseInfo"


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1180x780")
        self.root.minsize(980, 640)
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        self.q = queue.SimpleQueue()
        self._running = False
        self._lock = threading.Lock()
        self._buttons = []
        self._checks = []
        self.last_plan = None

        self.var = {}
        for key, val in (
            ("srv_src", ""), ("usr_src", ""), ("pwd_src", ""), ("db_src", ""),
            ("srv_dst", ""), ("usr_dst", ""), ("pwd_dst", ""), ("db_dst", ""),
            ("default_unit", "个"), ("backup_path", ""), ("status", "就绪"),
        ):
            self.var[key] = tk.StringVar(value=val)
        self.opt_backup = tk.BooleanVar(value=True)
        self.opt_join = tk.BooleanVar(value=False)
        self.opt_cur = tk.BooleanVar(value=True)
        self.opt_compat = tk.BooleanVar(value=False)
        self.opt_pf = tk.BooleanVar(value=True)
        self.opt_cache = tk.BooleanVar(value=True)

        self._build()
        self._bind_keys()
        self.root.after(120, self._drain)
        self.log("工具启动，版本 " + VERSION)
        self.log("提示：连接参数不预填；先填两侧服务器/账号/密码并刷新库列表。")

    # ---------------- UI ----------------
    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Big.TButton", padding=(10, 6))
        style.configure("Danger.TButton", padding=(10, 6))

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.nb = nb

        self.page_conn = ttk.Frame(nb)
        self.page_run = ttk.Frame(nb)
        self.page_check = ttk.Frame(nb)
        self.page_mapping = ttk.Frame(nb)
        self.page_log = ttk.Frame(nb)
        nb.add(self.page_conn, text=" 1. 连接与预检 ")
        nb.add(self.page_run, text=" 2. 一键直导 ")
        nb.add(self.page_check, text=" 3. 数据校验 ")
        nb.add(self.page_mapping, text=" 字段映射 ")
        nb.add(self.page_log, text=" 操作日志 ")

        self._build_conn()
        self._build_run()
        self._build_check()
        self._build_mapping()
        self._build_log()

        # 状态栏
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom", padx=8, pady=(0, 6))
        ttk.Separator(bar, orient="horizontal").pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="状态：").pack(side="left")
        ttk.Label(bar, textvariable=self.var["status"], foreground="#0a5").pack(side="left")
        self.pb = ttk.Progressbar(bar, mode="indeterminate", length=180)
        self.pb.pack(side="right", padx=(8, 0))
        ttk.Label(bar, text=APP_TITLE, foreground="#777").pack(side="right")

    def _src_group(self, parent):
        g = ttk.LabelFrame(parent, text="源库：竞驰管理通（KSPC）")
        row = 0
        ttk.Label(g, text="服务器 / 实例").grid(row=row, column=0, sticky="e", padx=6, pady=5)
        e = ttk.Entry(g, textvariable=self.var["srv_src"], width=34)
        e.grid(row=row, column=1, sticky="we", padx=4)
        ttk.Label(g, text="例：DESKTOP-8P5G8VQ\\SQLEXPRESS", foreground="#777").grid(row=row, column=2, sticky="w", padx=4)
        row += 1
        ttk.Label(g, text="用户名").grid(row=row, column=0, sticky="e", padx=6, pady=5)
        ttk.Entry(g, textvariable=self.var["usr_src"], width=20).grid(row=row, column=1, sticky="w", padx=4)
        ttk.Label(g, text="密码").grid(row=row, column=2, sticky="e", padx=(20, 4))
        ttk.Entry(g, textvariable=self.var["pwd_src"], width=20, show="*").grid(row=row, column=3, sticky="w")
        row += 1
        ttk.Label(g, text="数据库").grid(row=row, column=0, sticky="e", padx=6, pady=5)
        self.cb_src = ttk.Combobox(g, textvariable=self.var["db_src"], width=32)
        self.cb_src.grid(row=row, column=1, sticky="w", padx=4)
        b = ttk.Button(g, text="测试连接", command=lambda: self.test_conn("src"))
        b.grid(row=row, column=2, padx=4)
        self._buttons.append(b)
        b2 = ttk.Button(g, text="刷新库列表", command=lambda: self.refresh_dbs("src"))
        b2.grid(row=row, column=3, padx=4)
        self._buttons.append(b2)
        g.columnconfigure(1, weight=1)
        return g

    def _dst_group(self, parent):
        g = ttk.LabelFrame(parent, text="目标库：管家婆财贸双全（GraspCM）")
        row = 0
        ttk.Label(g, text="服务器 / 实例").grid(row=row, column=0, sticky="e", padx=6, pady=5)
        ttk.Entry(g, textvariable=self.var["srv_dst"], width=34).grid(row=row, column=1, sticky="we", padx=4)
        ttk.Label(g, text="例：DESKTOP-8P5G8VQ\\SQLSERVER", foreground="#777").grid(row=row, column=2, sticky="w", padx=4)
        row += 1
        ttk.Label(g, text="用户名").grid(row=row, column=0, sticky="e", padx=6, pady=5)
        ttk.Entry(g, textvariable=self.var["usr_dst"], width=20).grid(row=row, column=1, sticky="w", padx=4)
        ttk.Label(g, text="密码").grid(row=row, column=2, sticky="e", padx=(20, 4))
        ttk.Entry(g, textvariable=self.var["pwd_dst"], width=20, show="*").grid(row=row, column=3, sticky="w")
        row += 1
        ttk.Label(g, text="账套库").grid(row=row, column=0, sticky="e", padx=6, pady=5)
        self.cb_dst = ttk.Combobox(g, textvariable=self.var["db_dst"], width=32)
        self.cb_dst.grid(row=row, column=1, sticky="w", padx=4)
        b = ttk.Button(g, text="测试连接", command=lambda: self.test_conn("dst"))
        b.grid(row=row, column=2, padx=4)
        self._buttons.append(b)
        b2 = ttk.Button(g, text="刷新库列表", command=lambda: self.refresh_dbs("dst"))
        b2.grid(row=row, column=3, padx=4)
        self._buttons.append(b2)
        g.columnconfigure(1, weight=1)
        return g

    def _build_conn(self):
        p = self.page_conn
        top = ttk.Frame(p)
        top.pack(fill="x", padx=10, pady=10)
        self._src_group(top).pack(fill="x", pady=(0, 8))
        self._dst_group(top).pack(fill="x")

        mid = ttk.Frame(p)
        mid.pack(fill="x", padx=10, pady=(4, 8))
        b = ttk.Button(mid, text="预检两侧账套结构", style="Big.TButton", command=self.precheck)
        b.pack(side="left")
        self._buttons.append(b)
        ttk.Label(mid, text="只读检查：源端基础表行数、目标端必需表是否齐全，不写任何数据。",
                  foreground="#777").pack(side="left", padx=10)

        box = ttk.LabelFrame(p, text="预检结果")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tv = ttk.Treeview(box, columns=("a", "b", "c"), show="headings", height=12)
        tv.heading("a", text="项目")
        tv.heading("b", text="结果")
        tv.heading("c", text="说明")
        tv.column("a", width=260, anchor="w")
        tv.column("b", width=110, anchor="center")
        tv.column("c", width=560, anchor="w")
        tv.tag_configure("ok", foreground="#0a6")
        tv.tag_configure("bad", foreground="#c00")
        ys = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tv_pre = tv

    def _build_run(self):
        p = self.page_run
        info = ttk.LabelFrame(p, text="迁移口径（与字段映射表一致）")
        info.pack(fill="x", padx=10, pady=10)
        txt = ("往来单位 4 类按 isclient 分流（商场专柜/普通客户/加盟代理→客户，供应商→供应商）；"
               "编号数字化+级联（00001 / 0000100001）；仓库保留父子层级；"
               "期初库存写 IniGoodsStocks；结存库存写 GoodsStocks + GoodsStockscost；"
               "价格/单位写 T_Jxc_PtypeUnit；客户价格追踪写 xw_P_PriceFollow；"
               "导入行备注统一前缀“竞驰导入|”，重复导入自动替换，不碰目标自有数据。")
        ttk.Label(info, text=txt, wraplength=1080, justify="left", foreground="#333").pack(anchor="w", padx=8, pady=8)

        opt = ttk.LabelFrame(p, text="执行选项")
        opt.pack(fill="x", padx=10, pady=(0, 8))
        r1 = ttk.Frame(opt)
        r1.pack(fill="x", padx=8, pady=6)
        ttk.Label(r1, text="空单位补为").pack(side="left")
        ttk.Entry(r1, textvariable=self.var["default_unit"], width=8).pack(side="left", padx=4)
        ttk.Checkbutton(r1, text="导入前备份目标库", variable=self.opt_backup).pack(side="left", padx=(18, 6))
        ttk.Checkbutton(r1, text="导入后清客户端缓存", variable=self.opt_cache).pack(side="left", padx=6)
        r2 = ttk.Frame(opt)
        r2.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Checkbutton(r2, text="往来关系表另建为客户（默认折算为备注）", variable=self.opt_join).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(r2, text="写结存库存 GoodsStocks+GoodsStockscost（默认写）", variable=self.opt_cur).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(r2, text="写兼容价格表 xw_P_PtypePrice", variable=self.opt_compat).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(r2, text="写客户价格追踪 xw_P_PriceFollow（默认写）", variable=self.opt_pf).pack(side="left")

        r3 = ttk.Frame(opt)
        r3.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(r3, text="备份到").pack(side="left")
        ttk.Entry(r3, textvariable=self.var["backup_path"], width=80).pack(side="left", padx=4, fill="x", expand=True)
        b = ttk.Button(r3, text="选择…", command=self.choose_backup)
        b.pack(side="left")
        self._buttons.append(b)

        act = ttk.Frame(p)
        act.pack(fill="x", padx=10, pady=8)
        b = ttk.Button(act, text="预览编号与映射", command=self.preview_plan)
        b.pack(side="left")
        self._buttons.append(b)
        b = ttk.Button(act, text="备份目标库", command=self.do_backup)
        b.pack(side="left", padx=8)
        self._buttons.append(b)
        self.btn_run = ttk.Button(act, text="一键直导（备份→导入→归位→校验）",
                                  style="Big.TButton", command=self.run_all)
        self.btn_run.pack(side="left", padx=12)
        self._buttons.append(self.btn_run)

        sumbox = ttk.LabelFrame(p, text="本次迁移汇总")
        sumbox.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        tv = ttk.Treeview(sumbox, columns=("k", "v"), show="headings", height=8)
        tv.heading("k", text="项目")
        tv.heading("v", text="数值 / 说明")
        tv.column("k", width=260, anchor="w")
        tv.column("v", width=800, anchor="w")
        tv.pack(fill="both", expand=True, padx=6, pady=6)
        self.tv_sum = tv

    def _build_check(self):
        p = self.page_check
        top = ttk.Frame(p)
        top.pack(fill="x", padx=10, pady=10)
        b = ttk.Button(top, text="执行数据校验", style="Big.TButton", command=self.do_verify)
        b.pack(side="left")
        self._buttons.append(b)
        b = ttk.Button(top, text="重算子级计数 + 归位 UpdateTag", command=self.do_fix)
        b.pack(side="left", padx=8)
        self._buttons.append(b)
        b = ttk.Button(top, text="清客户端缓存", command=self.do_cache)
        b.pack(side="left", padx=8)
        self._buttons.append(b)
        ttk.Label(top, text="校验项覆盖行数、编号规则、父子引用、子级计数、单位价格、期初引用、财贸读取链路 B/C/V/P/K/E/D。",
                  foreground="#777").pack(side="left", padx=10)

        box = ttk.LabelFrame(p, text="校验结果")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tv = ttk.Treeview(box, columns=("no", "item", "res", "detail"), show="headings")
        tv.heading("no", text="#")
        tv.heading("item", text="检查项")
        tv.heading("res", text="结果")
        tv.heading("detail", text="详情")
        tv.column("no", width=46, anchor="center")
        tv.column("item", width=330, anchor="w")
        tv.column("res", width=90, anchor="center")
        tv.column("detail", width=620, anchor="w")
        tv.tag_configure("ok", foreground="#0a6")
        tv.tag_configure("bad", foreground="#c00")
        ys = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        self.tv_chk = tv

    def _build_mapping(self):
        p = self.page_mapping
        ttk.Label(p, text="字段对应关系（源库字段 → 目标库字段 / 处理规则）",
                  font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        box = ttk.Frame(p)
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tv = ttk.Treeview(box, columns=("obj", "src", "dst", "rule"), show="headings")
        tv.heading("obj", text="对象")
        tv.heading("src", text="源（竞驰）")
        tv.heading("dst", text="目标（财贸）")
        tv.heading("rule", text="规则")
        tv.column("obj", width=90, anchor="center")
        tv.column("src", width=330, anchor="w")
        tv.column("dst", width=390, anchor="w")
        tv.column("rule", width=330, anchor="w")
        ys = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        for row in eng.MAPPING_ROWS:
            tv.insert("", "end", values=row)
        self.tv_map = tv

    def _build_log(self):
        p = self.page_log
        top = ttk.Frame(p)
        top.pack(fill="x", padx=10, pady=8)
        b = ttk.Button(top, text="复制全部", command=self.copy_log)
        b.pack(side="left")
        self._buttons.append(b)
        b = ttk.Button(top, text="导出日志", command=self.export_log)
        b.pack(side="left", padx=8)
        self._buttons.append(b)
        b = ttk.Button(top, text="清空显示", command=self.clear_log)
        b.pack(side="left")
        self._buttons.append(b)

        box = ttk.Frame(p)
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.txt = tk.Text(box, wrap="none", height=20, font=("Consolas", 9), bg="#1e1e1e", fg="#ddd",
                           insertbackground="#ddd")
        ys = ttk.Scrollbar(box, orient="vertical", command=self.txt.yview)
        xs = ttk.Scrollbar(box, orient="horizontal", command=self.txt.xview)
        self.txt.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.txt.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.txt.tag_configure("err", foreground="#ff6b6b")
        self.txt.tag_configure("ok", foreground="#5cd68a")
        self.txt.configure(state="disabled")

    def _bind_keys(self):
        self.root.bind("<F5>", lambda e: self.precheck())

    # ---------------- helpers ----------------
    def _params(self, side):
        return (self.var["srv_" + side].get().strip(),
                self.var["db_" + side].get().strip(),
                self.var["usr_" + side].get().strip(),
                self.var["pwd_" + side].get())

    def _conn(self, side):
        srv, db, usr, pwd = self._params(side)
        if not srv or not db:
            raise eng.MigrateError("请先填写%s的服务器和数据库" % ("源库" if side == "src" else "目标库"))
        return eng.connect(srv, db, usr or "sa", pwd)

    def log(self, msg, level="info"):
        self.q.put((datetime.datetime.now().strftime("%H:%M:%S"), str(msg), level))

    def _append_log(self, ts, msg, level):
        self.txt.configure(state="normal")
        self.txt.insert("end", f"[{ts}] {msg}\n", level if level in ("err", "ok") else "")
        lines = int(self.txt.index("end-1c").split(".")[0])
        if lines > 3000:
            self.txt.delete("1.0", "1501.0")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                ts, msg, level = self.q.get_nowait()
                self._append_log(ts, msg, level)
        except queue.Empty:
            pass
        self.root.after(120, self._drain)

    def _set_busy(self, busy, text=None):
        self._running = busy
        state = "disabled" if busy else "normal"
        for b in self._buttons:
            try:
                b.configure(state=state)
            except Exception:
                pass
        if busy:
            self.pb.start(12)
            if text:
                self.var["status"].set(text)
        else:
            self.pb.stop()
            self.var["status"].set(text or "就绪")

    def _work(self, fn, done_text="完成"):
        with self._lock:
            if self._running:
                messagebox.showwarning("正在执行", "已有任务在执行，请等待完成。")
                return False
            self._set_busy(True, "执行中…")

        def runner():
            err = None
            try:
                fn()
            except eng.MigrateError as e:
                err = str(e)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            if err:
                self.log("失败：" + err, "err")
            self.root.after(0, lambda: self._finish(err, done_text))

        threading.Thread(target=runner, daemon=True).start()
        return True

    def _finish(self, err, done_text):
        self._set_busy(False, ("失败，见日志" if err else done_text))
        if err:
            messagebox.showerror("执行失败", err)

    def _clear_tree(self, tv):
        for i in tv.get_children():
            tv.delete(i)

    # ---------------- actions --------------
    def test_conn(self, side):
        def job():
            srv, db, usr, pwd = self._params(side)
            self.log(f"连接{'源库' if side == 'src' else '目标库'}：{srv} / {db}")
            cn = self._conn(side)
            cur = cn.cursor()
            cur.execute("SELECT @@VERSION, DB_NAME()")
            ver, dbn = cur.fetchone()
            self.log(f"连接成功，当前库 {dbn}", "ok")
            self.log("版本：" + str(ver).split("\n")[0])
            cn.close()
        self._work(job, "连接测试完成")

    def refresh_dbs(self, side):
        def job():
            srv, _, usr, pwd = self._params(side)
            if not srv:
                raise eng.MigrateError("请先填写服务器/实例")
            names = eng.list_databases(srv, usr or "sa", pwd)
            self.log(f"{srv} 共 {len(names)} 个在线库")
            combo = self.cb_src if side == "src" else self.cb_dst
            self.root.after(0, lambda: combo.configure(values=names))
            if names:
                hit = [x for x in names if (("kspc" in x.lower()) if side == "src" else ("财贸" in x or "CMSQ" in x.upper()))]
                if hit:
                    self.root.after(0, lambda: self.var["db_" + side].set(hit[0]))
                    self.log("已自动选中 " + hit[0])
        self._work(job, "库列表已刷新")

    def precheck(self):
        def job():
            self._clear_tree(self.tv_pre)
            src_info = eng.analyze_source(self._conn("src"))
            self.log("=== 源库（竞驰）===")
            for t, v in src_info.items():
                mark = "存在" if v["exists"] else "缺失"
                self.root.after(0, lambda t=t, v=v, mark=mark: self.tv_pre.insert(
                    "", "end", values=(t, f"{mark} / {v['count']} 行", "基础资料表" if v["exists"] else "该表不存在"),
                    tags=("ok" if v["exists"] else "bad",)))
                if v["exists"]:
                    self.log(f"{t}: {v['count']} 行")
            tgt = eng.analyze_target(self._conn("dst"))
            self.log("=== 目标库（财贸）===")
            must = ["Btype", "ptype", "Stock", "Employee", "Department", "IniGoodsStocks", "T_Jxc_PtypeUnit"]
            for t in eng.TABLES_TARGET:
                if t == "_counts":
                    continue
                ok = tgt.get(t)
                n = tgt["_counts"].get(t, "")
                note = "必需表" if t in must else "可选表"
                self.root.after(0, lambda t=t, ok=ok, n=n, note=note: self.tv_pre.insert(
                    "", "end", values=(t, "存在" if ok else "缺失", f"{note}；现有 {n} 行" if ok else "缺失"),
                    tags=("ok" if ok else "bad",)))
            miss = [t for t in must if not tgt.get(t)]
            if miss:
                self.log("目标库缺必需表：" + ", ".join(miss), "err")
                raise eng.MigrateError("目标库不是可用的财贸账套，缺表：" + ", ".join(miss))
            self.log("预检通过：两侧结构满足直导条件", "ok")
        self._work(job, "预检完成")

    def choose_backup(self):
        path = filedialog.asksaveasfilename(
            title="选择目标库备份文件（须为 SQL Server 服务账户可写路径）",
            initialdir=DEFAULT_BACKUP_DIR,
            initialfile=f"竞驰直导前_{datetime.datetime.now():%Y%m%d_%H%M%S}.bak",
            defaultextension=".bak", filetypes=[("备份文件", "*.bak")])
        if path:
            self.var["backup_path"].set(path)

    def _ensure_backup_path(self):
        p = self.var["backup_path"].get().strip()
        if not p:
            p = os.path.join(DEFAULT_BACKUP_DIR, f"竞驰直导前_{datetime.datetime.now():%Y%m%d_%H%M%S}.bak")
            self.var["backup_path"].set(p)
        return p

    def do_backup(self):
        def job():
            path = self._ensure_backup_path()
            cn = self._conn("dst")
            srv, db, _, _ = self._params("dst")
            self.log(f"备份 {db} → {path}")
            cur = cn.cursor()
            cur.execute(f"BACKUP DATABASE [{db}] TO DISK=N'{path.replace(chr(39), chr(39)*2)}' WITH INIT, "
                        f"NAME=N'竞驰直导前手工备份'")
            while cur.nextset():
                pass
            cur.close()
            cn.close()
            size = os.path.getsize(path) if os.path.exists(path) else 0
            self.log(f"备份完成，{size/1048576:.1f} MB", "ok")
        self._work(job, "备份完成")

    def preview_plan(self):
        def job():
            src = self._conn("src")
            dst = self._conn("dst")
            data = eng._preview_struct(src, {})
            plan = eng.plan_import(data, dst, {
                "include_join": self.opt_join.get(),
                "default_unit": self.var["default_unit"].get().strip() or "个",
            })
            self.last_plan = plan
            rows = eng.plan_preview(plan)
            self.root.after(0, lambda: self._show_plan(rows, plan["warnings"]))
            for w in plan["warnings"]:
                self.log("提醒：" + w, "err")
            self.log(f"编号预览完成，共 {len(rows)} 条", "ok")
        self._work(job, "预览完成")

    def _show_plan(self, rows, warnings):
        win = tk.Toplevel(self.root)
        win.title("编号映射预览")
        win.geometry("860x560")
        tv = ttk.Treeview(win, columns=("obj", "old", "name", "new", "lvl"), show="headings")
        for c, t, w in (("obj", "对象", 90), ("old", "原编号", 100), ("name", "名称", 300),
                        ("new", "新编号", 180), ("lvl", "层级", 60)):
            tv.heading(c, text=t)
            tv.column(c, width=w, anchor="w" if c == "name" else "center")
        for r in rows:
            tv.insert("", "end", values=r)
        ys = ttk.Scrollbar(win, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=ys.set)
        tv.pack(side="left", fill="both", expand=True)
        ys.pack(side="right", fill="y")
        if warnings:
            ttk.Label(win, text="提醒：" + "；".join(warnings), foreground="#c00",
                      wraplength=840).pack(side="bottom", anchor="w")

    def run_all(self):
        srv_s, db_s, _, _ = self._params("src")
        srv_d, db_d, _, _ = self._params("dst")
        if not (srv_s and db_s and srv_d and db_d):
            messagebox.showwarning("参数不足", "请先填写源库与目标库的服务器、数据库。")
            return
        if db_s == db_d and srv_s == srv_d:
            messagebox.showerror("参数错误", "源库与目标库不能是同一个库。")
            return
        if not messagebox.askyesno(
                "确认直导",
                f"将把源库【{db_s}】的基础资料写入目标库【{db_d}】。\n\n"
                "• 仅替换备注带“竞驰导入|”的旧导入行，目标自有数据保留\n"
                "• 导入前默认整库备份\n\n是否继续？"):
            return
        if self.opt_backup.get():
            self._ensure_backup_path()

        def job():
            t0 = time.time()
            src = self._conn("src")
            dst = self._conn("dst")
            options = {
                "default_unit": self.var["default_unit"].get().strip() or "个",
                "include_join": self.opt_join.get(),
                "include_cur_stock": self.opt_cur.get(),
                "include_compat_price": self.opt_compat.get(),
                "include_price_follow": self.opt_pf.get(),
            }
            backup = self.var["backup_path"].get().strip() if self.opt_backup.get() else ""
            self.log("=== 开始一键直导 ===")
            self.log("源：%s / %s → 目标：%s / %s" % (srv_s, db_s, srv_d, db_d))
            stats = eng.import_all(src, dst, options, log=lambda m: self.log(m),
                                   backup_path=backup or None)
            for w in stats.get("warnings", []):
                self.log("提醒：" + w, "err")
            self.root.after(0, lambda: self._show_stats(stats))
            self.log("导入完成，进入校验…")
            checks = eng.verify(src, dst, options, log=lambda m: self.log(m))
            self.root.after(0, lambda: self._show_checks(checks))
            bad = [c for c in checks if c[1] != "通过"]
            if bad:
                self.log(f"校验完成：{len(checks)-len(bad)}/{len(checks)} 通过，{len(bad)} 项异常", "err")
            else:
                self.log(f"校验完成：{len(checks)}/{len(checks)} 全部通过", "ok")
            if self.opt_cache.get():
                n, msg = eng.clear_cache(db_d, CACHE_ROOT)
                self.log(msg, "ok" if n else "info")
            src.close()
            dst.close()
            self.log(f"总用时 {time.time()-t0:.1f}s")

        self._work(job, "直导与校验完成")

    def _show_stats(self, stats):
        self._clear_tree(self.tv_sum)
        rows = [
            ("往来单位（含客户/供应商分流）", f"{stats['units']} 条"),
            ("存货商品", f"{stats['goods']} 个"),
            ("仓库", f"{stats['stocks']} 个"),
            ("职员", f"{stats['employees']} 人"),
            ("部门", f"{stats['departments']} 个"),
            ("期初库存行", f"{stats['ini_rows']} 行"),
            ("单位价格行（T_Jxc_PtypeUnit）", f"{stats['unit_rows']} 行"),
            ("条码行", f"{stats['barcode_rows']} 行"),
            ("兼容价格行", f"{stats['price_rows']} 行"),
            ("当前库存快照行", f"{stats['cur_rows']} 行"),
            ("耗时", f"{stats['elapsed']} 秒"),
        ]
        for k, v in rows:
            self.tv_sum.insert("", "end", values=(k, v))

    def do_verify(self):
        def job():
            src = self._conn("src")
            dst = self._conn("dst")
            options = {"include_join": self.opt_join.get()}
            checks = eng.verify(src, dst, options, log=lambda m: self.log(m))
            self.root.after(0, lambda: self._show_checks(checks))
            bad = [c for c in checks if c[1] != "通过"]
            self.log(f"校验完成：{len(checks)-len(bad)}/{len(checks)} 通过", "ok" if not bad else "err")
        self._work(job, "校验完成")

    def _show_checks(self, checks):
        self._clear_tree(self.tv_chk)
        for idx, (item, res, detail) in enumerate(checks, 1):
            self.tv_chk.insert("", "end", values=(idx, item, res, detail),
                               tags=("ok" if res == "通过" else "bad",))

    def do_fix(self):
        def job():
            cn = self._conn("dst")
            eng.recalc_children(cn, log=lambda m: self.log(m))
            eng.normalize_tags(cn, log=lambda m: self.log(m))
            cn.close()
            self.log("修复完成：子级计数与刷新标记已归位", "ok")
        self._work(job, "修复完成")

    def do_cache(self):
        def job():
            db = self.var["db_dst"].get().strip()
            n, msg = eng.clear_cache(db, CACHE_ROOT)
            self.log(msg, "ok" if n else "info")
            if n:
                self.log("请重新启动财贸客户端并登录账套查看", "ok")
        self._work(job, "缓存处理完成")

    # ---------------- log tools --------------
    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.txt.get("1.0", "end-1c"))
        self.var["status"].set("日志已复制到剪贴板")

    def export_log(self):
        path = filedialog.asksaveasfilename(
            title="导出操作日志", defaultextension=".txt",
            initialfile=f"竞驰直导日志_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt",
            filetypes=[("文本文件", "*.txt")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.txt.get("1.0", "end-1c"))
        self.var["status"].set("日志已导出：" + path)

    def clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")


def main():
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
