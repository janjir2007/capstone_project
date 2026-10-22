"""Every number + chart the defense deck needs, in one file (task 7.1c).

Reads the results that earlier tasks already produced (nothing is retrained, no model is changed):

- docs/ml_tuning.json, docs/ml_results.md, docs/ml_evaluation.md   (ML, synthetic data, 9 routes)
- models/plate_yolo/test_metrics.json, models/plate_ocr/*.json      (CV, git-ignored; same numbers
  are in docs/cv_detection_results.md and docs/cv_ocr_results.md, which this script cross-checks)
- docs/latency_7_1c.json                                            (scripts/latency_bench.py)

Every number in docs/slide_facts.md is printed next to its source file and the last commit that
touched that file. As a check, the SAVED serving model (models/next_change_model.joblib) is scored
again on the current test split; the script stops if that does not reproduce the docs.

    .venv/bin/python -m scripts.slide_facts
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_MD = Path("docs/slide_facts.md")
FIG_DIR = Path("docs/figures/slides")

ML_TUNING = Path("docs/ml_tuning.json")
ML_RESULTS = Path("docs/ml_results.md")
ML_EVAL = Path("docs/ml_evaluation.md")
YOLO_JSON = Path("models/plate_yolo/test_metrics.json")
OCR_JSON = Path("models/plate_ocr/test_metrics.json")
OCR_FINAL_JSON = Path("models/plate_ocr/final_3_6b.json")
CV_DET_DOC = Path("docs/cv_detection_results.md")
CV_OCR_DOC = Path("docs/cv_ocr_results.md")
LATENCY_JSON = Path("docs/latency_7_1c.json")

# Same palette as src/ml/baselines.py (validated with the dataviz validator, task 7.1c).
SURFACE, TEXT, TEXT_MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#a9a8a2"
SYNTHETIC_MN = "СИНТЕТИК ӨГӨГДӨЛ — Geo-Expert-ийн бодит үйлчлүүлэгч биш"

# Model names in the docs -> slide labels (Mongolian).
NAME_MN = {
    "Oracle (noise floor)": "Шуугианы доод хязгаар",
    "B0 (median)": "B0 тогтмол интервал",
    "B1 (17,500 km)": "B1 маршрутын томьёо",
    "Ridge": "Ridge (ашиглаж буй)",
    "Current Ridge (served)": "Ridge (ашиглаж буй)",
    "Random Forest": "Random Forest",
    "XGBoost": "XGBoost",
    "Best tuned: Ridge+XGB average": "Ridge+XGB дундаж",
}
# Feature names -> slide labels (Mongolian). Needs Ari's check (see handoff).
FEATURE_MN = {
    "one_way_km": "Нэг талын зай (км)",
    "route_km_per_day": "Маршрутын км/хоног",
    "past_late_share": "Өмнө хоцорсон хувь",
    "km_per_day_hist": "Машины өөрийн км/хоног",
    "season": "Улирал",
    "past_interval_mean_days": "Өмнөх дундаж интервал",
    "destination_name": "Очих газар",
    "route": "Маршрутын төрөл",
    "days_since_prev_visit": "Өмнөх засвараас хойш хоног",
    "has_history": "Түүхтэй эсэх",
}


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def git_commit(path: Path, root: Path = ROOT) -> str:
    """Short hash of the last commit that touched ``path``; 'git-ignored' / 'uncommitted' otherwise."""
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(path)], cwd=root,
                             capture_output=True).returncode == 0
    if not tracked:
        return "git-ignored" if subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=root
                                               ).returncode == 0 else "this commit (task 7.1c)"
    out = subprocess.run(["git", "log", "-1", "--format=%h", "--", str(path)], cwd=root,
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(path)], cwd=root).returncode != 0
    return out + (" + local edits" if dirty else "")


def cite(path: Path, where: str = "") -> str:
    """'`file` §where @ hash' for the Source column."""
    return f"`{path}`{' ' + where if where else ''} @ {git_commit(path)}"


def md_table(text: str, header: list[str]) -> pd.DataFrame:
    """The first Markdown table whose header cells are exactly ``header`` (cells stay strings)."""
    lines = text.splitlines()
    want = [h.strip() for h in header]
    for i, line in enumerate(lines):
        if line.startswith("|") and [c.strip() for c in line.strip().strip("|").split("|")] == want:
            rows = []
            for row in lines[i + 2:]:  # skip the |---| line
                if not row.startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return pd.DataFrame(rows, columns=want)
    raise ValueError(f"table with header {want} not found")


def num(cell: str) -> float:
    """'38.6%' -> 38.6, '+0.98' -> 0.98, '1,752' -> 1752."""
    return float(cell.replace("%", "").replace(",", "").replace("+", ""))


RESULTS_HEADER = ["Baseline", "Buffer (days early)", "RMSE (days)", "MAE (days)", "R²", "Reminder hit rate",
                  "Too early", "Too late", "Hit rate, no buffer"]
STATUS_HEADER = ["Predictor", "F1 OK", "F1 due soon", "F1 overdue", "Macro F1", "Accuracy",
                 "ROC-AUC overdue (pooled)", "ROC-AUC overdue (same day)", "ROC-AUC needs reminder"]
SHAP_HEADER = ["Feature", "Ridge", "XGBoost"]
OCR_3_6B_HEADER = ["test set", "model", "threshold", "exact read", "correct auto-fills", "wrong auto-fills",
                   "sent to manual"]


@dataclass
class Facts:
    """Everything read from the sources (tables keep the docs' own rounding)."""

    tuning: dict
    results: pd.DataFrame      # ml_results.md §3 test table, index = model
    status: pd.DataFrame       # ml_evaluation.md §3, index = model
    shap: pd.DataFrame         # ml_evaluation.md §1 importance, index = feature
    yolo: dict                 # yolo26n row of models/plate_yolo/test_metrics.json
    ocr: dict                  # model -> {exact, auto, wrong, manual, plates}
    latency: dict | None


def load_facts(root: Path = ROOT) -> Facts:
    """Read every source file."""
    tuning = json.loads((root / ML_TUNING).read_text(encoding="utf-8"))
    results = md_table((root / ML_RESULTS).read_text(encoding="utf-8"), RESULTS_HEADER).set_index("Baseline")
    ev = (root / ML_EVAL).read_text(encoding="utf-8")
    status = md_table(ev, STATUS_HEADER).set_index("Predictor")
    shap = md_table(ev, SHAP_HEADER).set_index("Feature")
    yolo = next(m for m in json.loads((root / YOLO_JSON).read_text(encoding="utf-8"))["models"]
                if m["model"] == "yolo26n (fine-tuned)")
    ocr = ocr_comparison(json.loads((root / OCR_JSON).read_text(encoding="utf-8")),
                         json.loads((root / OCR_FINAL_JSON).read_text(encoding="utf-8")))
    lat = root / LATENCY_JSON
    latency = json.loads(lat.read_text(encoding="utf-8")) if lat.exists() else None
    return Facts(tuning, results, status, shap, yolo, ocr, latency)


def ocr_comparison(test_metrics: dict, final_3_6b: dict) -> dict[str, dict[str, int]]:
    """EasyOCR (task 3.3) vs char CNN v1 / v2 at threshold 0.6 on the same 27 old test plates."""
    def counts(m: dict) -> dict[str, int]:
        return {"plates": m["plates"], "exact": round(m["exact_match"] * m["plates"]),
                "auto": m["auto_correct"], "wrong": m["wrong_auto_fill"], "manual": m["manual"]}

    easy = next(m for m in test_metrics["models"] if m["model"].startswith("A: EasyOCR"))
    cnn = {r["model"]: r["metrics"] for r in final_3_6b["sets"]["old_test"] if r["threshold"] == 0.6}
    return {"EasyOCR": counts(easy), "CNN v1": counts(cnn["v1"]), "CNN v2": counts(cnn["v2"])}


# ---------------------------------------------------------------------------
# Cross-checks
# ---------------------------------------------------------------------------

def check_cv_docs(f: Facts, root: Path = ROOT) -> list[str]:
    """The git-ignored CV JSONs must match the committed CV docs (so the doc commit is a valid citation)."""
    det = (root / CV_DET_DOC).read_text(encoding="utf-8")
    y = f.yolo
    row = f"| yolo26n (fine-tuned) | {y['map50']:.3f} | {y['map50_95']:.3f} | {y['precision']:.3f} | {y['recall']:.3f} |"
    problems = [] if row in det else [f"{CV_DET_DOC}: yolo26n row differs from {YOLO_JSON}"]
    ocr_doc = (root / CV_OCR_DOC).read_text(encoding="utf-8")
    table = md_table(ocr_doc[ocr_doc.index("3.6b"):], OCR_3_6B_HEADER)
    for name, model in (("CNN v1", "v1"), ("CNN v2", "v2")):
        r = table[(table["test set"] == "old_test") & (table["model"] == model) & (table["threshold"] == "0.60")]
        c = f.ocr[name]
        if r.empty or (r.iloc[0]["exact read"], r.iloc[0]["correct auto-fills"], r.iloc[0]["wrong auto-fills"]) != \
                (f"{c['exact']}/27", f"{c['auto']}/27", str(c["wrong"])):
            problems.append(f"{CV_OCR_DOC}: {model} row differs from {OCR_FINAL_JSON}")
    return problems


def verify_served(f: Facts) -> dict[str, tuple[float, float]]:
    """Score the SAVED Ridge (+ B0, B1) on today's test split; returns metric -> (recomputed, doc value).

    No fitting: the pipeline is loaded from models/next_change_model.joblib, B0 is the TRAIN median,
    B1 is the route formula.
    """
    import joblib

    from src.common.features import FEATURE_COLUMNS
    from src.ml import explain as X
    from src.ml.baselines import predict_b0, predict_b1, score
    from src.ml.dataset import TARGET, build_dataset, load_ml_config, make_split
    from src.ml.evaluate import status_checks, status_metrics

    cfg = load_ml_config(ROOT / "configs/ml.yaml")
    saved = joblib.load(ROOT / cfg["models"]["model_dir"] / "next_change_model.joblib")
    df, _ = build_dataset(cfg)
    split = make_split(df, cfg)
    train, test = df.loc[split.train], df.loc[split.test]
    y, window = test[TARGET], tuple(cfg["reminder"]["window_days_early"])
    ridge = pd.Series(saved["pipeline"].predict(test[FEATURE_COLUMNS]), index=test.index)
    b0 = predict_b0(train[TARGET], test.index)
    b1 = predict_b1(test["route_km_per_day"], cfg["baselines"]["b1_interval_km"], b0)
    st = cfg["evaluation"]["status"]
    out: dict[str, tuple[float, float]] = {"test visits": (len(test), f.tuning["test"]["n_test"])}
    for name, pred, buf in (("Ridge", ridge, saved["buffer_days"]), ("B0 (median)", b0, num(f.results.loc["B0 (median)", "Buffer (days early)"])),
                            ("B1 (17,500 km)", b1, num(f.results.loc["B1 (17,500 km)", "Buffer (days early)"]))):
        s = score(y, pred, window, int(buf))
        doc = f.results.loc[name]
        out[f"{name} MAE"] = (round(s["MAE"], 1), num(doc["MAE (days)"]))
        out[f"{name} hit rate %"] = (round(100 * s["hit_rate"], 1), num(doc["Reminder hit rate"]))
        sm = status_metrics(status_checks(y, pred, st["check_every_days"], st["check_after_due_days"]),
                            st["due_soon_days"])
        out[f"{name} macro F1"] = (round(sm["f1_macro"], 2), num(f.status.loc[name, "Macro F1"]))
        out[f"{name} ROC-AUC needs reminder"] = (round(sm["auc_attention"], 3),
                                                 num(f.status.loc[name, "ROC-AUC needs reminder"]))
    imp = X.grouped_importance(X.explain("Ridge", saved["pipeline"], train[FEATURE_COLUMNS], test[FEATURE_COLUMNS]))
    for feat in imp.index[:3]:
        out[f"SHAP Ridge {feat}"] = (round(float(imp[feat]), 2), num(f.shap.loc[feat, "Ridge"]))
    return out


# ---------------------------------------------------------------------------
# Charts (slide size 16:9, Mongolian labels)
# ---------------------------------------------------------------------------

def _style(ax: plt.Axes, grid_axis: str = "x") -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_MUTED, labelsize=17, length=0)
    ax.grid(axis=grid_axis, color=GRID, linewidth=1)
    ax.set_axisbelow(True)


def _figure(title: str, subtitle: str) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(13.33, 7.5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    fig.text(0.03, 0.95, title, fontsize=26, weight="bold", color=TEXT, va="top")
    fig.text(0.03, 0.885, subtitle, fontsize=16, color=TEXT_MUTED, va="top")
    return fig, ax


def _save(fig: plt.Figure, path: Path, footer: str) -> None:
    fig.text(0.03, 0.025, footer, fontsize=12, color=TEXT_MUTED)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def plot_mae(f: Facts, path: Path) -> None:
    """Horizontal MAE bars, noise floor as a dashed line; served model in blue."""
    rows = f.tuning["test"]["rows"]
    mae = {NAME_MN[k]: v["mae"] for k, v in rows.items()}
    for k in ("Random Forest", "XGBoost"):  # not in ml_tuning.json -> ml_results.md (1 decimal)
        mae[NAME_MN[k]] = num(f.results.loc[k, "MAE (days)"])
    floor = mae.pop(NAME_MN["Oracle (noise floor)"])
    order = sorted(mae, key=mae.get, reverse=True)
    fig, ax = _figure("Дундаж алдаа (MAE): бага байх тусам сайн",
                      f"Тест: {f.tuning['test']['n_test']} үйлчилгээ, {f.tuning['test']['n_test_trucks']} машин · хоногоор")
    colors = [BLUE if k == NAME_MN["Ridge"] else (ORANGE if k.startswith("B") else GRAY) for k in order]
    bars = ax.barh(order, [mae[k] for k in order], color=colors, height=0.62, edgecolor=SURFACE, linewidth=2)
    for b, k in zip(bars, order):
        ax.text(b.get_width() + 0.15, b.get_y() + b.get_height() / 2, f"{mae[k]:.1f}", va="center",
                fontsize=18, color=TEXT, weight="bold" if k == NAME_MN["Ridge"] else "normal")
    ax.axvline(floor, color=TEXT, linestyle="--", linewidth=2)
    ax.annotate(f"Шуугианы доод хязгаар {floor:.1f} (санамсаргүй хэсгийг урьдчилах боломжгүй)",
                xy=(floor, 1.0), xycoords=("data", "axes fraction"), xytext=(0, 8), textcoords="offset points",
                ha="center", va="bottom", fontsize=15, color=TEXT)
    ax.set_xlim(0, max(mae.values()) * 1.12)
    ax.set_xlabel("Дундаж алдаа, хоног", fontsize=17, color=TEXT_MUTED)
    _style(ax)
    ax.tick_params(axis="y", labelsize=18, labelcolor=TEXT)
    fig.subplots_adjust(left=0.27, right=0.97, top=0.78, bottom=0.14)
    _save(fig, path, SYNTHETIC_MN)


def plot_reminder(f: Facts, path: Path) -> None:
    """100% stacked bars: hit / too early / too late per method, buffer in the label."""
    names = ["B0 (median)", "B1 (17,500 km)", "Ridge", "Random Forest", "XGBoost"]
    parts = [("Reminder hit rate", "Цагтаа (1–14 хоногийн өмнө)", BLUE),
             ("Too early", "Хэт эрт", AQUA), ("Too late", "Хэт оройтсон", ORANGE)]
    fig, ax = _figure("Сануулга хэзээ очсон бэ?",
                      "Тест дээр · сануулга = таамагласан өдөр − урьдчилах хоног (validation дээр тохируулсан)")
    labels = [f"{NAME_MN[n]}\n(−{num(f.results.loc[n, 'Buffer (days early)']):.0f} хоног)" for n in names][::-1]
    left = [0.0] * len(names)
    for col, label, color in parts:
        vals = [num(f.results.loc[n, col]) for n in names][::-1]
        bars = ax.barh(labels, vals, left=left, color=color, height=0.62, label=label, edgecolor=SURFACE, linewidth=2)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + v / 2, b.get_y() + b.get_height() / 2, f"{v:.0f}%", ha="center", va="center",
                    fontsize=17, color="white" if color == BLUE else TEXT, weight="bold")
        left = [a + v for a, v in zip(left, vals)]
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    _style(ax)
    ax.grid(False)
    ax.tick_params(axis="y", labelsize=16, labelcolor=TEXT)
    ax.legend(loc="upper center", bbox_to_anchor=(0.45, 1.1), ncol=3, frameon=False, fontsize=16)
    fig.subplots_adjust(left=0.25, right=0.97, top=0.78, bottom=0.12)
    _save(fig, path, SYNTHETIC_MN)


def plot_shap(f: Facts, path: Path, top: int = 8) -> None:
    """Top features of the served Ridge by mean |SHAP| (days)."""
    s = f.shap["Ridge"].map(num).sort_values(ascending=False).head(top)[::-1]
    fig, ax = _figure(f"Ridge загвар юуг ашигладаг вэ? (SHAP, эхний {top})",
                      f"Нэг таамаглалыг дунджаар хэдэн хоногоор өөрчилдөг · тест {f.tuning['test']['n_test']} үйлчилгээ")
    bars = ax.barh([FEATURE_MN[k] for k in s.index], s.values, color=BLUE, height=0.62, edgecolor=SURFACE, linewidth=2)
    for b, v in zip(bars, s.values):
        ax.text(b.get_width() + 0.03, b.get_y() + b.get_height() / 2, f"{v:.2f}", va="center", fontsize=17, color=TEXT)
    ax.set_xlim(0, s.max() * 1.15)
    ax.set_xlabel("Дундаж |SHAP|, хоног", fontsize=17, color=TEXT_MUTED)
    _style(ax)
    ax.tick_params(axis="y", labelsize=18, labelcolor=TEXT)
    fig.subplots_adjust(left=0.3, right=0.97, top=0.82, bottom=0.14)
    _save(fig, path, SYNTHETIC_MN + " · дундаж алдаа ~12 хоног")


def plot_ocr(f: Facts, path: Path, target: int = 18) -> None:
    """Grouped bars: exact reads / correct auto-fills / wrong auto-fills, three recognizers, of 27 plates."""
    models = [("EasyOCR", "EasyOCR (бэлэн загвар)", GRAY), ("CNN v1", "Өөрийн CNN v1 (ашиглаж буй)", BLUE),
              ("CNN v2", "Өөрийн CNN v2 (хадгалсан)", AQUA)]
    groups = [("exact", "7 тэмдэгт бүгд зөв"), ("auto", "Автоматаар зөв бөглөсөн"), ("wrong", "Буруу бөглөсөн")]
    n = f.ocr["CNN v1"]["plates"]
    fig, ax = _figure("Дугаар таних: бэлэн OCR ба өөрийн CNN",
                      f"Ижил {n} тест зураг (сургалтад ороогүй) · итгэлийн босго 0.6")
    width = 0.26
    for i, (key, label, color) in enumerate(models):
        xs = [g + (i - 1) * width for g in range(len(groups))]
        vals = [f.ocr[key][g] for g, _ in groups]
        ax.bar(xs, vals, width=width, color=color, label=label, edgecolor=SURFACE, linewidth=2)
        for x, v in zip(xs, vals):
            ax.text(x, v + 0.4, f"{v}/{n}", ha="center", fontsize=16, color=TEXT)
    ax.plot([1 - 1.6 * width, 1 + 1.6 * width], [target, target], color=TEXT, linestyle="--", linewidth=2)
    ax.text(1 + 1.7 * width, target, f"Зорилт {target}/{n}", va="center", fontsize=15, color=TEXT)
    ax.set_xticks(range(len(groups)), [g for _, g in groups], fontsize=18, color=TEXT)
    ax.set_ylim(0, n)
    ax.set_ylabel("Зургийн тоо", fontsize=17, color=TEXT_MUTED)
    _style(ax, grid_axis="y")
    ax.legend(loc="upper right", frameon=False, fontsize=16)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.82, bottom=0.12)
    _save(fig, path, f"Бодит дугаартай зураг · {n} тест зураг дээр буруу дугаар нэг ч удаа бөглөөгүй (эргэлзээтэйг гараар шалгуулна)")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def regression_rows(f: Facts, src_t: str, src_r: str) -> list[list[str]]:
    """One row per method: MAE/RMSE/gain from ml_tuning.json (2.9) when there, else ml_results.md §3; R² from §3."""
    tuned_name = {"Current Ridge (served)": "Ridge"}  # same model, two names in the two files
    rows, seen = [], set()
    for k, v in f.tuning["test"]["rows"].items():
        doc = tuned_name.get(k, k)
        seen.add(doc)
        r2 = f.results.loc[doc, "R²"] if doc in f.results.index else "—"
        gain = "—" if k == "B0 (median)" else \
            f"{v['gain_vs_b0'][0]:+.2f} ({v['gain_vs_b0'][1]:+.2f} … {v['gain_vs_b0'][2]:+.2f})"
        rows.append([f"{NAME_MN[k]} ({k})", f"{v['mae']:.2f}", f"{v['rmse']:.1f}", r2, gain,
                     src_t + (f"; R² {src_r}" if r2 != "—" else "")])
    for k in f.results.index.difference(sorted(seen), sort=False):
        rows.append([f"{NAME_MN[k]} ({k})", f.results.loc[k, "MAE (days)"], f.results.loc[k, "RMSE (days)"],
                     f.results.loc[k, "R²"], "in `docs/ml_results.md` §3 (MAE gain table)", src_r])
    return rows


def build_markdown(f: Facts, check: dict[str, tuple[float, float]], cv_problems: list[str], head: str) -> str:
    """docs/slide_facts.md."""
    t, r, s = f.tuning, f.results, f.status
    src_t, src_r, src_e = cite(ML_TUNING), cite(ML_RESULTS, "§3"), cite(ML_EVAL)
    rows_t = t["test"]["rows"]

    reg = regression_rows(f, src_t, src_r)

    rem = [[NAME_MN[k] + f" ({k})", r.loc[k, "Buffer (days early)"], r.loc[k, "Reminder hit rate"], r.loc[k, "Too early"],
            r.loc[k, "Too late"], r.loc[k, "Hit rate, no buffer"], src_r] for k in r.index]
    stat = [[NAME_MN[k] + f" ({k})", s.loc[k, "Macro F1"], s.loc[k, "Accuracy"], s.loc[k, "ROC-AUC needs reminder"],
             s.loc[k, "ROC-AUC overdue (pooled)"], s.loc[k, "ROC-AUC overdue (same day)"], src_e + " §3"] for k in s.index]
    shap = [[i + 1, FEATURE_MN[k], f"`{k}`", f.shap.loc[k, "Ridge"], src_e + " §1"] for i, k in enumerate(f.shap.index[:8])]

    cov, wid, rng = t["test"]["coverage"], t["test"]["range_width_days"], t["cv"]["ranges"]
    ranges = [["Ridge (served)", f"{100 * cov['current']:.1f}%", f"{wid['current']:.0f}", f"{rng['current'][0]:+.0f} / {rng['current'][1]:+.0f}", src_t],
              ["Ridge+XGB average", f"{100 * cov['best']:.1f}%", f"{wid['best']:.0f}", f"{rng['best'][0]:+.0f} / {rng['best'][1]:+.0f}", src_t],
              ["B0", f"{100 * cov['b0']:.1f}%", f"{wid['b0']:.0f}", f"{rng['b0'][0]:+.0f} / {rng['b0'][1]:+.0f}", src_t]]

    y = f.yolo
    det_src = f"`{YOLO_JSON}` (git-ignored) = {cite(CV_DET_DOC)}"
    yolo = [["mAP50", f"{y['map50']:.3f}", det_src], ["mAP50-95", f"{y['map50_95']:.3f}", det_src],
            ["Precision", f"{y['precision']:.3f}", det_src], ["Recall", f"{y['recall']:.3f}", det_src],
            ["Missed / false boxes", f"{y['missed']} / {y['false_positives']} (of {y['gt_boxes']} plates)", det_src],
            ["CPU ms/image (median / p95), PyTorch", f"{y['ms_median']} / {y['ms_p95']}", det_src],
            ["Weights", f"{y['weights_mb']} MB", det_src]]
    ocr_src = {"EasyOCR": f"`{OCR_JSON}` (git-ignored) = {cite(CV_OCR_DOC, '§ Test results')}",
               "CNN v1": f"`{OCR_FINAL_JSON}` (git-ignored) = {cite(CV_OCR_DOC, '§ Task 3.6b')}",
               "CNN v2": f"`{OCR_FINAL_JSON}` (git-ignored) = {cite(CV_OCR_DOC, '§ Task 3.6b')}"}
    ocr = [[k, f"{c['exact']}/{c['plates']}", f"{c['auto']}/{c['plates']}", f"{c['wrong']}", f"{c['manual']}/{c['plates']}", ocr_src[k]]
           for k, c in f.ocr.items()]

    lat_md = "_Not measured: run `python -m scripts.latency_bench` first._"
    if f.latency:
        L = f.latency
        lsrc = cite(LATENCY_JSON)
        pr, vp = L["plates_recognize"], L["vehicle_prediction"]
        lat_md = _table(["Endpoint", "Calls (200 OK)", "p50 ms", "p95 ms", "p99 ms", "Source"], [
            ["POST /plates/recognize (round trip)", f"{pr['calls']} ({pr['ok_200']})", pr["round_trip_ms"]["p50"],
             pr["round_trip_ms"]["p95"], pr["round_trip_ms"]["p99"], lsrc],
            ["  ↳ server-side `ms` field (detect + read)", "same calls", pr["server_ms"]["p50"], pr["server_ms"]["p95"],
             pr["server_ms"]["p99"], lsrc],
            ["GET /vehicles/{id}/prediction (round trip)", f"{vp['calls']} ({vp['status_codes'].get('200', 0)})",
             vp["round_trip_ms"]["p50"], vp["round_trip_ms"]["p95"], vp["round_trip_ms"]["p99"], lsrc]])
        lat_md += (f"\n\nSetup: {L['setup']}. Code at {L['code_commit']}, {L['date']}, {L['machine']}, "
                   f"{L['warmup_calls']} warm-up calls not timed. Photo: {L['photo']}. "
                   f"Prediction calls cycle through {vp['vehicles']} synthetic demo vehicles.\n"
                   "**Caveat:** with no plate found the character CNN does not run; on a real plate add roughly "
                   "3 ms (CNN median per plate, docs/cv_ocr_results.md) plus segmentation. Cloud numbers will differ.")

    ok = all(abs(a - b) < 1e-9 for a, b in check.values())
    chk = _table(["Metric", "Recomputed now", "In docs", "Match"],
                 [[k, a, b, "✓" if abs(a - b) < 1e-9 else "✗"] for k, (a, b) in check.items()])

    return f"""# Slide facts (task 7.1c)

Generated by `python -m scripts.slide_facts` at code commit `{head}`. **Do not edit by hand**:
rerun the script. Every number has its source file and the last commit that changed that file.
Nothing was retrained for this file.

- **ML numbers are on SYNTHETIC data** (9 routes, task 1.6; split cutoff {t['cv']['split_cutoff']}; train
  {t['cv']['n_train']:,} visits / {t['cv']['n_train_trucks']} trucks, test {t['test']['n_test']} visits /
  {t['test']['n_test_trucks']} trucks, no truck in both). There is no real-record test set (RISK-10, D-063).
- **CV numbers are on real photos** (held-out test split, 27 plates / 20 trucks). Model JSONs are git-ignored;
  the cited commit is the committed doc that reports the same numbers (cross-checked by the script:
  {"OK" if not cv_problems else "PROBLEMS: " + "; ".join(cv_problems)}).

## Charts (docs/figures/slides/)

| File | Slide | Shows |
|---|---|---|
| `slide_mae.png` | 6 | MAE of every method on test + noise floor |
| `slide_reminder.png` | 6 | Reminder hit / too early / too late per method, with buffers |
| `slide_shap_ridge.png` | 7 | Top 8 Ridge features by mean \\|SHAP\\| |
| `slide_ocr.png` | 6 | EasyOCR vs char CNN v1 / v2: exact, correct auto-fill, wrong auto-fill |

## 1. Next-oil-change prediction: error on test

| Method | MAE (days) | RMSE (days) | R² | MAE gain vs B0 (95% CI) | Source |
|---|---|---|---|---|---|
{chr(10).join("| " + " | ".join(map(str, row)) + " |" for row in reg)}

The noise floor is an oracle that knows each truck's hidden generator values but not the random
draws after the service (src/ml/noise_floor.py). Served Ridge is **{rows_t['Current Ridge (served)']['mae'] - rows_t['Oracle (noise floor)']['mae']:.1f} days**
above the floor, B0 **{rows_t['B0 (median)']['mae'] - rows_t['Oracle (noise floor)']['mae']:.1f} days**. Tuned models (2.9) did not pass
the keep rule D-093 (needs ≥ {t['cv']['keep_margin_days']} days CV gain, best = Ridge+XGB average with {t['cv']['current']['cv_mae'] - t['cv']['cv_mae']['Ridge+XGB average']:+.2f} days) → served Ridge stays.
R² "—" = not reported in the source (oracle, Ridge+XGB average). RF / XGBoost have 1-decimal values only.

## 2. Reminder timing (window 1–14 days before the actual visit, D-051)

| Method | Buffer (days early) | Hit | Too early | Too late | Hit, no buffer | Source |
|---|---|---|---|---|---|---|
{chr(10).join("| " + " | ".join(map(str, row)) + " |" for row in rem)}

Buffers are tuned on TRAIN out-of-fold predictions, never on test. The served Ridge buffer (16) is also in
`models/next_change_model.json` (git-ignored); B0 = 13, B1 = 4 in `models/serving_params.json`.

## 3. Status classes OK / due soon / overdue (D-007), 9 routes

| Method | Macro F1 | Accuracy | ROC-AUC needs reminder | ROC-AUC overdue (pooled) | ROC-AUC overdue (same day) | Source |
|---|---|---|---|---|---|---|
{chr(10).join("| " + " | ".join(map(str, row)) + " |" for row in stat)}

These were recomputed on the 9-route data in task 1.6 part 2 (0ff7e8e: 2,222 → 2,058 checks). "Same day"
is the fair one: B0 = 0.500 by construction. The check protocol (every 7 days) is an [ESTIMATE].

## 4. SHAP: top 8 features of the served Ridge (mean |SHAP|, days)

| # | Feature (slide) | Feature (code) | Ridge | Source |
|---|---|---|---|---|
{chr(10).join("| " + " | ".join(map(str, row)) + " |" for row in shap)}

## 5. Prediction range ("≈ date (low – high)", intended 80%)

| Method | Coverage on test | Width (days) | Offsets from prediction (days) | Source |
|---|---|---|---|---|
{chr(10).join("| " + " | ".join(map(str, row)) + " |" for row in ranges)}

## 6. Plate detection: yolo26n (fine-tuned), test 27 images

| Metric | Value | Source |
|---|---|---|
{chr(10).join("| " + " | ".join(map(str, row)) + " |" for row in yolo)}

The API serves the ONNX export on CPU; the ms above are the PyTorch evaluation (task 3.2). For the served
path see §8. Baseline comparison caveat RISK-11 still applies.

## 7. Plate reading: same 27 test plates, threshold 0.6

| Recognizer | Exact (7/7 chars) | Auto-filled & correct | Auto-filled WRONG | Sent to manual | Source |
|---|---|---|---|---|---|
{chr(10).join("| " + " | ".join(map(str, row)) + " |" for row in ocr)}

CNN v1 is served (D-086, D-088); v2 is saved, "promising, not proven" (target D-087 = 18/27 not met).
EasyOCR model 98 MB vs CNN 1.2 MB (docs/cv_ocr_results.md).

## 8. Local latency (task 7.1c, 200 calls each)

{lat_md}

## 9. Reproduction check (saved model scored again, no training)

The saved `models/next_change_model.joblib` was loaded and scored on today's test split; B0/B1 recomputed
from their formulas. **{"All match the docs." if ok else "MISMATCH — do not use these numbers."}**

{chk}
"""


def main(argv: list[str] | None = None) -> int:
    """Read sources, run the checks, write charts + docs/slide_facts.md."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--skip-verify", action="store_true", help="skip rescoring the saved model (tests)")
    args = p.parse_args(argv)
    f = load_facts()
    cv_problems = check_cv_docs(f)
    check = {} if args.skip_verify else verify_served(f)
    bad = [k for k, (a, b) in check.items() if abs(a - b) >= 1e-9]
    plot_mae(f, ROOT / FIG_DIR / "slide_mae.png")
    plot_reminder(f, ROOT / FIG_DIR / "slide_reminder.png")
    plot_shap(f, ROOT / FIG_DIR / "slide_shap_ridge.png")
    plot_ocr(f, ROOT / FIG_DIR / "slide_ocr.png")
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    (ROOT / OUT_MD).write_text(build_markdown(f, check, cv_problems, head), encoding="utf-8")
    print(f"-> {OUT_MD}, {FIG_DIR}/ (4 charts); cv doc problems: {cv_problems or 'none'}; mismatches: {bad or 'none'}")
    return 1 if bad or cv_problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
