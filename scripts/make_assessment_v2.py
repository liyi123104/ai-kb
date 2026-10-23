"""生成《项目评估报告 v2》docx + md：修复后复评，含前后对照。

数据取自 2026-10-23 复评实测（功能用例、30 题评测、延迟与磁盘测量）。
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUT_DOCX = Path(r"D:\ai-kb\docs\项目评估报告-v2.docx")
OUT_MD = Path(r"D:\ai-kb\docs\assessment-v2.md")
GREY = RGBColor(0x66, 0x66, 0x66)
RED = RGBColor(0xB0, 0x2A, 0x2A)
GREEN = RGBColor(0x1E, 0x6B, 0x2E)

FACTS = [
    ("功能测试", "30 / 30 通过", "tests/run_tests.py，75.9 秒"),
    ("检索召回率", "90.0%（27/30）", "全量库与 AI 专用库一致"),
    ("答案准确率", "73.3%（22/30）", "两次重复采样结果完全相同（评测稳定）"),
    ("检索质量", "平均名次 1.48，Top-1 19/30", "缺 rerank，仍有提升空间"),
    ("检索耗时", "全量库 0.92s / AI 库 0.31s", "分库后快 3 倍"),
    ("问答延迟", "热态整轮 5.7–6.2s；流式首段 2.34s", "流式整轮 3.7s"),
    ("语料", "34,395 片（AI 10,942 / 参考 23,453）", "另有 5 个实验集合共 49,728 片"),
    ("磁盘", "向量库 1,021 MB；项目 1,897 MB", "实验集合约占 60%"),
    ("代码", "Python 4,976 行 / 24 文件；前端 641 行", "13 个接口；15 篇文档"),
    ("安全", "可选令牌鉴权已实现（默认关闭）", "401/200/?token= 三条路径实测"),
]

SCORES = [
    ("功能完整度", "9.0", "13 接口全可用；上传/问答/流式/高亮/模型切换/多文件/进度"),
    ("回答质量", "7.5", "召回 90%、准确 73.3%；Top-1 19/30，未接 rerank"),
    ("性能", "7.5", "AI 库检索 0.31s；入库 45–55 片/秒；容器内生成仍慢 2–4 倍"),
    ("健壮性", "7.5", "任务落库可恢复、入库串行化；仍缺并发压测"),
    ("安全性", "8.0", "令牌鉴权 + 路径穿越防护 + 密钥不入库；但默认不开启"),
    ("可维护性", "8.0", "模块清晰、日志落文件轮转、无 TODO 与裸 except"),
    ("文档", "9.0", "计划书 v1.14 + 15 篇文档 + 技术栈/技术点/评估三份"),
    ("测试", "7.5", "30 个功能用例；缺并发、异常注入与浏览器端到端"),
    ("部署交付", "7.5", "Docker 实机验证、镜像 1.29GB、一键脚本"),
    ("综合", "8.0", "从 7.5 提升：两个 P0 已解决，剩余风险均可控"),
]

BEFORE_AFTER = [
    ("鉴权", "完全开放，任何人可上传/删除", "可选令牌（X-Auth-Token / ?token=），前端 401 弹窗",
     "401/401/200/?token= 四条路径实测"),
    ("语料领域", "74% 是 PostgreSQL/Adobe 等非 AI 资料，检索 0.92s",
     "复制出 ai-kb-ai（10,942 片）与 ai-kb-ref（23,453 片），原库保留",
     "切 AI 库后检索 0.31s，召回/准确不变"),
    ("上传任务", "状态只在内存，重启即丢", "落 SQLite；启动把残留任务标记为中断",
     "重启后仍能查到 done / 1 片"),
    ("并发入库", "两个上传互抢显存", "全局锁串行化", "代码路径加锁，未做并发压测"),
    ("日志", "7 处 print，无轮转", "logging + data/app.log（5MB×3）", "日志文件已生成并写入"),
    ("前端中断", "长回答只能等", "生成中「发送」变「停止」，AbortController", "构建通过，交互路径已接"),
    ("评测噪声", "单次 30 题，每题 3.3 分", "evaluate_repeat.py 多次采样", "两次结果完全一致"),
]

REMAINING = [
    ("P1", "缺 rerank", "Top-1 只有 19/30；计划书 E2 一直未做，需 ollama pull bge-reranker-v2-m3",
     "拉模型后接上，观察 Top-1 与准确率"),
    ("P1", "实验集合占 60% 磁盘", "5 个 exp-* 集合共 49,728 片，向量库 1,021 MB 里大半是它们",
     "加 scripts/cleanup_experiments.py，或确认实验数据已归档后删掉"),
    ("P1", "鉴权默认关闭", "本机方便，但一旦部署到公网而忘了设置，仍然等于开放",
     "部署文档里把「设置 AUTH_TOKEN」写成必做步骤；或在检测到非本机访问时警告"),
    ("P2", "无并发与端到端测试", "30 个用例都是串行单请求；浏览器交互靠人工截图验证",
     "加并发上传用例、Ollama 宕机用例、Playwright 端到端"),
    ("P2", "容器内生成慢 2–4 倍", "Docker Desktop 的 WSL2 与宿主抢 CPU，非代码问题",
     "演示用本机模式；Linux 服务器上复测"),
    ("P2", "单用户设计", "无多租户、无配额、无上传频率限制",
     "若对外开放需加限流与用户隔离"),
]

PLAN_CHECK = [
    ("F1 切片 512 / 重叠 50", "达标", "E1/E4 实验确定，切片校验通过"),
    ("F2 向量库可持久", "达标", "34,395 片，重启后仍在；分库后两个新集合也可用"),
    ("F3 答案带出处", "达标", "文件名+页码+相似度+片段，可点击回原文并高亮"),
    ("F4 无关问题拒答", "达标", "5/5 拒答"),
    ("F5 首字 ≤3s / 完整 ≤15s", "达标", "流式首段 2.34s、整轮 3.7s（AI 库）"),
    ("F6 召回 ≥80% / 准确 ≥70%", "达标", "90.0% / 73.3%"),
    ("F7 一条命令启动", "达标", "start.bat / docker compose up"),
    ("F8 界面可用", "达标", "多文件上传+进度、模型切换、出处高亮、停止生成"),
]

ROADMAP = [
    ("本周（半天）", [
        "拉 bge-reranker-v2-m3 并接上精排，复测 Top-1 与准确率",
        "加 cleanup_experiments.py 清理 5 个实验集合（约 60% 磁盘）",
        "把 AUTH_TOKEN 写进部署 checklist，避免公网裸奔",
    ]),
    ("下周（1–2 天）", [
        "补 3 类测试：并发上传、Ollama 宕机、浏览器端到端",
        "评测扩到 60–100 题，降低单题权重",
        "容器内性能复测（Linux 环境）",
    ]),
    ("上线前", [
        "加限流与配额（单 IP 上传频率、单次大小）",
        "日志接入 request_id，便于排查",
        "备份策略：data/chroma 与 app.db 定期快照",
    ]),
]


def set_style(doc: Document) -> None:
    style = doc.styles["Normal"]
    style.font.name = "微软雅黑"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    style.paragraph_format.space_after = Pt(4)
    style.paragraph_format.line_spacing = 1.25


def add_table(doc, headers, rows, widths, size=9):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(size)
    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(str(val))
            run.font.size = Pt(size)
    for row in table.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
        tr_pr = row._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        cant.set(qn("w:val"), "true")
        tr_pr.append(cant)
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)
    doc.add_paragraph()
    return table


def build_docx() -> None:
    doc = Document()
    set_style(doc)
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Cm(2.2)
        section.left_margin = section.right_margin = Cm(2.3)

    title = doc.add_heading("AI 学习资料知识库 · 项目评估报告 v2", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph("2026-10-23 复评 · 修复两个 P0 后的实测结论，含修复前对照")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.runs[0].font.size = Pt(9)
    sub.runs[0].font.color.rgb = GREY

    doc.add_heading("一、复评结论", level=1)
    p = doc.add_paragraph()
    p.add_run("综合评分 8.0 / 10（上一版 7.5）。").bold = True
    p.add_run(
        "上一版报告指出的两个 P0 —— 无鉴权、语料领域漂移 —— 都已解决并实测验证："
        "令牌鉴权四条路径正确；分库后检索从 0.92 秒降到 0.31 秒，而召回率与准确率完全不变。"
        "同时补上了任务持久化、入库串行化、日志落盘、前端中断、多次采样评测。"
        "30 个功能用例仍全部通过。剩下的问题集中在「没有 rerank」「实验数据占磁盘」「默认不开鉴权」三类，"
        "都属于可控范围，不再有「一出事就完蛋」的隐患。"
    )
    add_table(doc, ["项目", "结论", "依据"], FACTS, [3.4, 5.6, 7.4])

    doc.add_heading("二、分维度评分", level=1)
    add_table(doc, ["维度", "评分", "评价"], SCORES, [3.0, 1.6, 11.8])

    doc.add_heading("三、修复前后对照", level=1)
    add_table(doc, ["项", "修复前", "修复后", "验证方式"], BEFORE_AFTER, [2.6, 5.0, 5.6, 3.4])

    doc.add_heading("四、剩余问题（按严重程度）", level=1)
    for level, name, desc, advice in REMAINING:
        h = doc.add_heading(f"{level} · {name}", level=2)
        if level == "P1":
            for run in h.runs:
                run.font.color.rgb = RED
        doc.add_paragraph(desc)
        p = doc.add_paragraph()
        run = p.add_run("建议：")
        run.bold = True
        p.add_run(advice)

    doc.add_heading("五、与计划书验收目标的对照", level=1)
    add_table(doc, ["验收项", "结论", "依据"], PLAN_CHECK, [4.6, 2.6, 9.2])

    doc.add_heading("六、改进路线", level=1)
    for stage, items in ROADMAP:
        doc.add_heading(stage, level=2)
        for item in items:
            doc.add_paragraph(item, style="List Bullet")

    doc.add_heading("七、本轮值得肯定", level=1)
    for item in [
        "每个隐患都有可复现的验证：鉴权四条路径、任务重启后可查、分库前后同题同指标对比。",
        "分库选择了「复制而非搬移」，原库完好，切换只改一个环境变量 —— 没有为了修问题而破坏数据。",
        "补的是可观测性而不只是功能：日志落盘、评测可重复、任务状态可追溯。",
        "修 P0 时没有引入新依赖，也没改技术栈。",
    ]:
        doc.add_paragraph(item, style="List Bullet")

    for para in doc.paragraphs:
        if para.style.name.startswith("Heading"):
            para.paragraph_format.keep_with_next = True
    doc.save(OUT_DOCX)


def build_md() -> None:
    def tbl(headers, rows):
        out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
        out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
        return "\n".join(out)

    md = [
        "# 项目评估报告 v2\n",
        "> 2026-10-23 复评 · 修复两个 P0 后的实测结论，含修复前对照\n",
        "## 一、复评结论\n",
        "**综合评分 8.0 / 10（上一版 7.5）。** 无鉴权与语料漂移两个 P0 已解决并实测："
        "令牌鉴权四条路径正确；分库后检索 0.92s → 0.31s，召回与准确率不变。"
        "另补任务持久化、入库串行化、日志落盘、前端中断、多次采样评测；30 个功能用例仍全通过。\n",
        tbl(["项目", "结论", "依据"], FACTS),
        "\n## 二、分维度评分\n",
        tbl(["维度", "评分", "评价"], SCORES),
        "\n## 三、修复前后对照\n",
        tbl(["项", "修复前", "修复后", "验证方式"], BEFORE_AFTER),
        "\n## 四、剩余问题\n",
    ]
    for level, name, desc, advice in REMAINING:
        md.append(f"### {level} · {name}\n")
        md.append(desc + "\n")
        md.append(f"**建议**：{advice}\n")
    md += ["\n## 五、与计划书验收目标的对照\n", tbl(["验收项", "结论", "依据"], PLAN_CHECK)]
    md.append("\n## 六、改进路线\n")
    for stage, items in ROADMAP:
        md.append(f"### {stage}\n")
        md += [f"- {i}" for i in items]
        md.append("")
    md.append("\n## 七、本轮值得肯定\n")
    md += [
        "- 每个隐患都有可复现的验证（鉴权四条路径、任务重启可查、分库前后同题同指标）。",
        "- 分库选择复制而非搬移，原库完好，切换只改一个环境变量。",
        "- 补的是可观测性而不只是功能：日志落盘、评测可重复、任务状态可追溯。",
        "- 修 P0 未引入新依赖，也未改技术栈。",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    build_docx()
    build_md()
    print("生成:", OUT_DOCX, OUT_DOCX.stat().st_size // 1024, "KB")
    print("生成:", OUT_MD, OUT_MD.stat().st_size // 1024, "KB")
