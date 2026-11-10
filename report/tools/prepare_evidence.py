"""Tạo bảng và hình của báo cáo từ facts đã đóng băng, không chạy model."""
# ruff: noqa: E402
# Cấu hình cache và backend trước khi import pyplot trong môi trường không có GUI.

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

REPORT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(REPORT / "build" / "matplotlib"))
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

REPO = REPORT.parent
FACTS = REPO / "docs/v4/facts"
for folder in ("figures", "tables", "evidence"):
    (REPORT / folder).mkdir(exist_ok=True)
for family in ("arial.ttf", "times.ttf"):
    font = Path("C:/Windows/Fonts") / family
    if font.exists():
        font_manager.fontManager.addfont(str(font))
plt.rcParams.update(
    {
        "font.family": "Arial",
        "font.size": 10,
        "pdf.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titleweight": "bold",
        "axes.labelcolor": "#243447",
    }
)
BLUE, GREEN, GRAY, ORANGE = "#17477D", "#237A57", "#718096", "#B55A30"
records, snapshots = [], {}


def read(name):
    path = FACTS / f"{name}.json"
    raw = path.read_bytes()
    (REPORT / "evidence" / path.name).write_bytes(raw)
    snapshots[path.name] = {
        "source": path.relative_to(REPO).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return json.loads(raw)


def number(value, source, field, places=4):
    records.append(
        {
            "source_file": f"docs/v4/facts/{source}.json",
            "json_field": field,
            "value": value,
            "display_decimals": places,
        }
    )
    return f"{value:.{places}f}".replace(".", ",")


def table(name, spec, header, rows):
    columns = " & ".join(header)
    body = "\n".join(" & ".join(row) + r" \\" for row in rows)
    text = (
        "% Sinh bởi tools/prepare_evidence.py từ report/evidence.\n"
        + r"\begin{tabularx}{\textwidth}{@{}"
        + spec
        + "@{}}\n\\hline\n"
        + columns
        + r" \\\hline"
        + "\n"
        + body
        + "\n\\hline\n\\end{tabularx}\n"
    )
    (REPORT / "tables" / f"{name}.tex").write_text(text, encoding="utf-8")


def save(fig, name):
    fig.savefig(REPORT / "figures" / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


ev, online, prior, prior_online, enc, tuned = [
    read(n)
    for n in (
        "evaluation_new",
        "online_report",
        "prior_comparison",
        "prior_online_report",
        "encoder_comparison",
        "prior_litegator_tuned",
    )
]
read("preregistration")
read("develop")
read("prior_v2_selection_audit")

rows = []
for label, key, budget in [
    ("BM25", "bm25", "0"),
    (r"\Pstar", "p_star", "0"),
    ("Dense arctic", "dense", "100"),
    (r"\Hstar", "h_star", "100"),
    ("PE-GH v2 vận hành", "v2_operating", "80"),
    ("PE-GH v2 so khớp", "v2_matched", "50"),
    ("BM25-margin", "margin_matched", "50"),
    ("Ngẫu nhiên", "random_matched", "50"),
    ("PE-GH v1", "pe_gh_v1", "81,8"),
]:
    value = ev["macro"].get(key)
    if key in ("bm25", "dense"):
        value = np.mean([x[key] for x in ev["statics"].values()])
        field = f"mean(statics.*.{key})"
    else:
        field = f"macro.{key}"
    rows.append([label, number(float(value), "evaluation_new", field), budget])
table("quality", "Yrr", ["Phương pháp", r"\ndcg", r"Dense (\%)"], rows)

rows = []
for domain in ev["domains"]:
    fields = [
        ev["statics"][domain]["bm25"],
        ev["domain_means"]["h_star"][domain],
        ev["domain_means"]["v2_operating"][domain],
        ev["domain_means"]["v2_matched"][domain] - ev["domain_means"]["margin_matched"][domain],
    ]
    paths = [
        f"statics.{domain}.bm25",
        f"domain_means.h_star.{domain}",
        f"domain_means.v2_operating.{domain}",
        f"domain_means.v2_matched.{domain} - domain_means.margin_matched.{domain}",
    ]
    rows.append(
        [domain.capitalize()]
        + [number(v, "evaluation_new", path) for v, path in zip(fields, paths, strict=True)]
    )
table("domains", "Yrrrr", ["Miền", "BM25", r"\Hstar", r"V2 (80\%)", r"V2 $-$ margin (50\%)"], rows)

tests = list(ev["hypotheses"]["tests"].items())
rows = []
for i, (key, item) in enumerate(tests, 1):
    lo, hi = item["two_sided_95"]
    p = item["p_value"]
    rows.append(
        [
            f"K{i}",
            number(item["estimate"], "evaluation_new", f"hypotheses.tests.{key}.estimate"),
            "["
            + number(lo, "evaluation_new", f"hypotheses.tests.{key}.two_sided_95.0")
            + "; "
            + number(hi, "evaluation_new", f"hypotheses.tests.{key}.two_sided_95.1")
            + "]",
            "$<0{,}0001$"
            if p == 0
            else number(p, "evaluation_new", f"hypotheses.tests.{key}.p_value"),
            "Đạt" if item["holm_reject"] else "Chưa đạt",
        ]
    )
table(
    "hypotheses",
    "Yrrrl",
    ["Giả thuyết", "Chênh lệch", r"CI hai phía 95\%", "$p$ một phía", "Holm"],
    rows,
)

methods = [
    ("BM25", "bm25"),
    (r"\Pstar", "p_star"),
    (r"\Rstar", "r_star_v2"),
    (r"\Hstar", "h_star_v2"),
    (r"PE-GH v2 (30\%)", "pe_gh_v2_b30"),
    (r"PE-GH v2 (50\%)", "pe_gh_v2_b50"),
    (r"PE-GH v2 (80\%)", "pe_gh_v2_b80"),
]
rows = []
for label, key in methods:
    m = online["summary"][key]["all"]
    rows.append(
        [
            label,
            number(m["mean_ms"], "online_report", f"summary.{key}.all.mean_ms", 2),
            number(m["p95_ms"], "online_report", f"summary.{key}.all.p95_ms", 2),
            number(m["cpu_mean_ms"], "online_report", f"summary.{key}.all.cpu_mean_ms", 1),
            number(m["peak_rss_mib"], "online_report", f"summary.{key}.all.peak_rss_mib", 1),
            number(online["quality_oof"][key], "online_report", f"quality_oof.{key}"),
        ]
    )
table("online", "Yrrrrr", ["Phương pháp", "Mean", "p95", "CPU", "RSS", r"\ndcg"], rows)

rows = []
for label, key in [
    ("PE-GH v2", "pe_gh_v2"),
    ("LiteGator mặc định", "litegator"),
    ("BERT điều chỉnh", "arabzadeh_bert"),
    ("BM25-margin", "bm25_margin"),
]:
    rows.append(
        [label]
        + [
            number(
                prior["matched_budgets"][b][key], "prior_comparison", f"matched_budgets.{b}.{key}"
            )
            for b in ("0.3", "0.5", "0.8")
        ]
    )
rows.insert(
    2,
    ["LiteGator chọn cấu hình"]
    + [
        number(
            tuned["matched_budgets"][b]["litegator_tuned"],
            "prior_litegator_tuned",
            f"matched_budgets.{b}.litegator_tuned",
        )
        for b in ("0.3", "0.5", "0.8")
    ],
)
table("router_quality", "Yrrr", ["Bộ quyết định", r"30\%", r"50\%", r"80\%"], rows)

rows = []
for label, key in [
    ("PE-GH v2", "pe_gh_v2_b50"),
    ("LiteGator chọn cấu hình", "litegator_b50"),
    ("BERT điều chỉnh", "bert_b50"),
]:
    m = prior_online["summary"][key]["all"]
    rows.append(
        [
            label,
            number(m["mean_ms"], "prior_online_report", f"summary.{key}.all.mean_ms", 2),
            number(m["p95_ms"], "prior_online_report", f"summary.{key}.all.p95_ms", 2),
            number(prior_online["quality_oof"][key], "prior_online_report", f"quality_oof.{key}"),
        ]
    )
table("router_online", "Yrrr", [r"Bộ quyết định (50\%)", "Mean (ms)", "p95 (ms)", r"\ndcg"], rows)

rows = []
for key, label in [
    ("minilm", "MiniLM"),
    ("bge_small_q", "BGE-small"),
    ("arctic_xs", "Arctic ban đầu"),
    ("arctic_xs_q", "Arctic được chọn"),
]:
    m = enc["encoders"][key]
    rows.append(
        [
            label,
            number(m["h_star_macro"], "encoder_comparison", f"encoders.{key}.h_star_macro"),
            number(
                m["encode_median_ms"], "encoder_comparison", f"encoders.{key}.encode_median_ms", 2
            ),
        ]
    )
table("encoder", "Yrr", ["Encoder", r"\Hstar{} macro", "Mã hóa trung vị (ms)"], rows)


def box(ax, x, y, w, h, text, color):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        facecolor=color,
        edgecolor="none",
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        ha="center",
        va="center",
        color="white",
        fontsize=10,
        linespacing=1.5,
    )


fig, ax = plt.subplots(figsize=(7.6, 3.0))
ax.axis("off")
ax.set(xlim=(0, 1), ylim=(0, 1))
box(ax, 0.015, 0.38, 0.18, 0.26, "Truy vấn mới\nBM25", BLUE)
box(ax, 0.29, 0.38, 0.23, 0.26, "Thông tin BM25\nBộ quyết định", BLUE)
box(ax, 0.66, 0.67, 0.30, 0.24, "Nhánh P*\nKhông mã hóa mới", GREEN)
box(ax, 0.66, 0.10, 0.30, 0.30, "Nhánh H*\nMã hóa, tìm Dense\nvà kết hợp", ORANGE)
for a, b in [
    ((0.2, 0.51), (0.28, 0.51)),
    ((0.53, 0.57), (0.65, 0.78)),
    ((0.53, 0.45), (0.65, 0.25)),
]:
    ax.annotate("", xy=b, xytext=a, arrowprops={"arrowstyle": "->", "lw": 1.7, "color": GRAY})
save(fig, "pegh_principle")

fig, ax = plt.subplots(figsize=(7.6, 3.0))
ax.axis("off")
ax.set(xlim=(0, 1), ylim=(0, 1))
box(ax, 0.01, 0.48, 0.29, 0.35, "Sáu miền phát triển\nChọn phương pháp\nvà ngân sách", BLUE)
box(ax, 0.37, 0.48, 0.22, 0.35, "Đóng băng\nĐăng ký K1 đến K4", GRAY)
box(
    ax,
    0.67,
    0.48,
    0.32,
    0.35,
    "Sáu miền xác nhận\nGiữ nguyên bộ quyết định\nĐánh giá chất lượng",
    GREEN,
)
for a, b in [((0.31, 0.65), (0.36, 0.65)), ((0.60, 0.65), (0.66, 0.65))]:
    ax.annotate("", xy=b, xytext=a, arrowprops={"arrowstyle": "->", "lw": 1.6, "color": GRAY})
ax.text(
    0.5,
    0.17,
    "Đo online riêng trên Programmers và Unix\nHuấn luyện không có miền đang đo",
    ha="center",
    va="center",
    color=BLUE,
    fontsize=10,
)
save(fig, "evaluation_protocol")

fig, ax = plt.subplots(figsize=(6.7, 3.4))
for key, label, color, style in [
    ("gate_v2", "PE-GH v2", BLUE, "-"),
    ("bm25_margin", "BM25-margin", GREEN, "--"),
    ("random30", "Ngẫu nhiên", GRAY, ":"),
    ("oracle", "Oracle", ORANGE, "-."),
]:
    if key not in ev["macro_curves"] and key == "gate_v2":
        key = next(k for k in ev["macro_curves"] if k not in ("bm25_margin", "random30", "oracle"))
    ax.plot(
        np.array(ev["budgets"]) * 100,
        ev["macro_curves"][key],
        label=label,
        color=color,
        ls=style,
        lw=1.8,
    )
ax.set(xlabel="Ngân sách Dense (%)", ylabel="nDCG@10 trung bình macro")
ax.legend(frameon=False, ncol=2, fontsize=9)
ax.grid(alpha=0.15)
save(fig, "budget_curves")

fig, ax = plt.subplots(figsize=(6.7, 3.0))
domains = ev["domains"]
gain = [
    ev["domain_means"]["v2_matched"][d] - ev["domain_means"]["margin_matched"][d] for d in domains
]
ax.bar(domains, gain, color=[BLUE if x >= 0 else ORANGE for x in gain])
ax.axhline(0, color=GRAY, lw=0.8)
ax.set(ylabel="V2 trừ BM25-margin (nDCG@10)", xlabel="Miền xác nhận, cùng ngân sách 50%")
save(fig, "per_domain_gains")

fig, ax = plt.subplots(figsize=(6.7, 3.4))
for _label, key in methods:
    m = online["summary"][key]["all"]
    ax.scatter(
        m["mean_ms"], online["quality_oof"][key], s=45, color=BLUE if "pe_gh" in key else GREEN
    )
    plain = {
        "bm25": "BM25",
        "p_star": "P*",
        "r_star_v2": "R*",
        "h_star_v2": "H*",
        "pe_gh_v2_b30": "V2 30%",
        "pe_gh_v2_b50": "V2 50%",
        "pe_gh_v2_b80": "V2 80%",
    }[key]
    ax.annotate(
        plain,
        (m["mean_ms"], online["quality_oof"][key]),
        xytext=(5, 5),
        textcoords="offset points",
        fontsize=9,
    )
ax.set(
    xlabel="Độ trễ trung bình cùng phiên (ms)",
    ylabel="nDCG@10 macro hai miền",
    xlim=(0, 28),
    ylim=(0.275, 0.435),
)
ax.grid(alpha=0.15)
save(fig, "online_tradeoff")

fig, axes = plt.subplots(1, 2, figsize=(6.7, 3.0), gridspec_kw={"width_ratios": [3, 1]})
for ax, ids in [(axes[0], [0, 1, 3]), (axes[1], [2])]:
    for pos, i in enumerate(ids):
        item = tests[i][1]
        lo, hi = item["two_sided_95"]
        mean = item["estimate"]
        ax.errorbar(mean, pos, xerr=[[mean - lo], [hi - mean]], fmt="o", capsize=4, color=BLUE)
    ax.axvline(0, color=GRAY, lw=0.8)
    ax.set_yticks(range(len(ids)), [f"K{i + 1}" for i in ids])
    ax.set_xlabel("Chênh lệch nDCG@10")
    ax.set_ylim(-0.65, len(ids) - 0.35)
axes[0].axvline(-0.01, color=ORANGE, ls=":", lw=1)
fig.tight_layout()
save(fig, "hypotheses")

fig, ax = plt.subplots(figsize=(6.7, 3.0))
names = ["PE-GH v2", "LiteGator", "BERT"]
keys = ["pe_gh_v2_b50", "litegator_b50", "bert_b50"]
values = [prior_online["summary"][k]["all"]["mean_ms"] for k in keys]
ax.barh(names, values, color=[BLUE, GREEN, ORANGE])
ax.invert_yaxis()
for i, v in enumerate(values):
    ax.text(v + 2, i, f"{v:.2f}", va="center", fontsize=9)
ax.set(xlabel="Độ trễ trung bình (ms), cùng phiên đối chiếu ở 50%", xlim=(0, max(values) * 1.14))
save(fig, "router_latency")

with (REPORT / "evidence/number_sources.csv").open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(
        handle, fieldnames=["source_file", "json_field", "value", "display_decimals"]
    )
    writer.writeheader()
    writer.writerows(records)
(REPORT / "evidence/manifest.json").write_text(
    json.dumps(
        {
            "description": "Snapshots used to prepare the first report draft; not a new experiment run",
            "sources": snapshots,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(f"Prepared {len(records)} numeric source records, 7 tables and 7 figures.")
