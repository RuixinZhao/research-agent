"""Reference implementation for D-02: BM25 hyperparameter tuning and ranking."""
from collections import Counter
import math
import re
from typing import Any, Dict, List


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def build_bm25_index(documents: List[Dict[str, Any]]) -> Dict[str, Any]:
    N = len(documents)
    doc_ids = [d["id"] for d in documents]

    text_tokens_list = [tokenize(d.get("text", "")) for d in documents]
    title_tokens_list = [tokenize(d.get("title", "")) for d in documents]

    text_lens = [len(tokens) for tokens in text_tokens_list]
    title_lens = [len(tokens) for tokens in title_tokens_list]

    avg_text_len = (sum(text_lens) / N) if N > 0 else 1.0
    if avg_text_len == 0.0:
        avg_text_len = 1.0

    avg_title_len = (sum(title_lens) / N) if N > 0 else 1.0
    if avg_title_len == 0.0:
        avg_title_len = 1.0

    text_tfs = [Counter(tokens) for tokens in text_tokens_list]
    title_tfs = [Counter(tokens) for tokens in title_tokens_list]

    text_dfs = Counter()
    for tf in text_tfs:
        text_dfs.update(tf.keys())

    title_dfs = Counter()
    for tf in title_tfs:
        title_dfs.update(tf.keys())

    return {
        "N": N,
        "doc_ids": doc_ids,
        "text_lens": text_lens,
        "title_lens": title_lens,
        "avg_text_len": avg_text_len,
        "avg_title_len": avg_title_len,
        "text_tfs": text_tfs,
        "title_tfs": title_tfs,
        "text_dfs": text_dfs,
        "title_dfs": title_dfs,
    }


def rank_query(
    query_text: str,
    index: Dict[str, Any],
    k1: float,
    b: float,
    title_weight: float,
) -> List[Dict[str, Any]]:
    q_tokens = tokenize(query_text)
    N = index["N"]
    doc_ids = index["doc_ids"]
    avg_text_len = index["avg_text_len"]
    avg_title_len = index["avg_title_len"]

    scores = [0.0] * N

    for token in q_tokens:
        df_text = index["text_dfs"].get(token, 0)
        idf_text = math.log(1.0 + (N - df_text + 0.5) / (df_text + 0.5)) if df_text > 0 else 0.0

        df_title = index["title_dfs"].get(token, 0)
        idf_title = math.log(1.0 + (N - df_title + 0.5) / (df_title + 0.5)) if df_title > 0 else 0.0

        for i in range(N):
            f_text = index["text_tfs"][i].get(token, 0)
            if f_text > 0:
                len_t = index["text_lens"][i]
                tf_norm = (f_text * (k1 + 1.0)) / (f_text + k1 * (1.0 - b + b * (len_t / avg_text_len)))
                scores[i] += idf_text * tf_norm

            f_title = index["title_tfs"][i].get(token, 0)
            if f_title > 0 and title_weight != 0.0:
                len_title = index["title_lens"][i]
                tf_norm_title = (f_title * (k1 + 1.0)) / (f_title + k1 * (1.0 - b + b * (len_title / avg_title_len)))
                scores[i] += title_weight * idf_title * tf_norm_title

    doc_scores = [{"id": doc_ids[i], "score": scores[i]} for i in range(N)]
    doc_scores.sort(key=lambda x: (-x["score"], x["id"]))
    return doc_scores


def evaluate_query(ranking: List[Dict[str, Any]], relevant_ids: List[str]) -> Dict[str, float]:
    rel_set = set(relevant_ids)
    if not rel_set:
        return {"recall_at_5_percent": 0.0, "mrr_at_10": 0.0}

    top5_ids = [r["id"] for r in ranking[:5]]
    hits5 = len(set(top5_ids) & rel_set)
    recall_at_5_percent = (hits5 / len(rel_set)) * 100.0

    top10_ids = [r["id"] for r in ranking[:10]]
    mrr_at_10 = 0.0
    for idx, doc_id in enumerate(top10_ids, start=1):
        if doc_id in rel_set:
            mrr_at_10 = 1.0 / idx
            break

    return {
        "recall_at_5_percent": recall_at_5_percent,
        "mrr_at_10": mrr_at_10,
    }


def compute_group_metrics(
    eval_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    groups_dict: Dict[str, List[Dict[str, float]]] = {}
    for item in eval_results:
        grp = item["group"]
        if grp not in groups_dict:
            groups_dict[grp] = []
        groups_dict[grp].append(item["metrics"])

    groups_summary = {}
    for grp, m_list in groups_dict.items():
        g_rec = sum(m["recall_at_5_percent"] for m in m_list) / len(m_list)
        g_mrr = sum(m["mrr_at_10"] for m in m_list) / len(m_list)
        groups_summary[grp] = {
            "recall_at_5_percent": g_rec,
            "mrr_at_10": g_mrr,
        }

    worst_mrr_at_10 = min(g["mrr_at_10"] for g in groups_summary.values())
    macro_mrr_at_10 = sum(g["mrr_at_10"] for g in groups_summary.values()) / len(groups_summary)
    macro_recall_at_5_percent = sum(g["recall_at_5_percent"] for g in groups_summary.values()) / len(groups_summary)

    return {
        "groups": groups_summary,
        "worst_mrr_at_10": worst_mrr_at_10,
        "macro_mrr_at_10": macro_mrr_at_10,
        "macro_recall_at_5_percent": macro_recall_at_5_percent,
    }


def run_experiment(request: Dict[str, Any]) -> Dict[str, Any]:
    phase = request.get("phase", "run")
    data = request.get("data", {})
    protocol = request.get("protocol", {})
    documents = data.get("documents", [])
    index = build_bm25_index(documents)

    if phase == "rank":
        selected = data.get("selected")
        if not selected:
            raise ValueError("phase=rank requires data.selected")
        k1 = float(selected["k1"])
        b = float(selected["b"])
        title_weight = float(selected["title_weight"])

        test_queries = data.get("test_queries", [])
        candidate_rankings = {}
        for q in test_queries:
            candidate_rankings[q["id"]] = rank_query(
                q.get("text", ""), index, k1, b, title_weight
            )
        return {"candidate": candidate_rankings}

    # phase == "run"
    dev_queries = data.get("dev_queries", [])
    test_queries = data.get("test_queries", [])
    grid = protocol.get("grid", [])

    search_rows = []

    for cfg in grid:
        k1 = float(cfg["k1"])
        b = float(cfg["b"])
        title_weight = float(cfg["title_weight"])

        dev_rankings = {}
        query_evals = []
        for q in dev_queries:
            r = rank_query(q.get("text", ""), index, k1, b, title_weight)
            dev_rankings[q["id"]] = r
            m = evaluate_query(r, q.get("relevant", []))
            query_evals.append({
                "group": q.get("group", "default"),
                "metrics": m,
            })

        group_metrics = compute_group_metrics(query_evals)
        ordinary_recall = sum(qe["metrics"]["recall_at_5_percent"] for qe in query_evals) / len(query_evals)
        ordinary_mrr = sum(qe["metrics"]["mrr_at_10"] for qe in query_evals) / len(query_evals)

        search_rows.append({
            "config": cfg,
            "rankings": dev_rankings,
            "recall_at_5_percent": ordinary_recall,
            "mrr_at_10": ordinary_mrr,
            "group_metrics": group_metrics,
        })

    def selection_sort_key(item: Dict[str, Any]):
        gm = item["group_metrics"]
        cfg = item["config"]
        w_mrr = round(gm["worst_mrr_at_10"], 12)
        m_mrr = round(gm["macro_mrr_at_10"], 12)
        m_rec = round(gm["macro_recall_at_5_percent"], 12)
        return (
            -w_mrr,
            -m_mrr,
            -m_rec,
            float(cfg["title_weight"]),
            float(cfg["k1"]),
            float(cfg["b"]),
        )

    best_item = min(search_rows, key=selection_sort_key)
    selected_config = best_item["config"]

    default_config = protocol.get("default_config", {"b": 0.75, "k1": 1.2, "title_weight": 0.0})
    base_k1 = float(default_config["k1"])
    base_b = float(default_config["b"])
    base_tw = float(default_config["title_weight"])

    cand_k1 = float(selected_config["k1"])
    cand_b = float(selected_config["b"])
    cand_tw = float(selected_config["title_weight"])

    baseline_rankings = {}
    candidate_rankings = {}
    for q in test_queries:
        q_text = q.get("text", "")
        baseline_rankings[q["id"]] = rank_query(q_text, index, base_k1, base_b, base_tw)
        candidate_rankings[q["id"]] = rank_query(q_text, index, cand_k1, cand_b, cand_tw)

    return {
        "baseline": baseline_rankings,
        "candidate": candidate_rankings,
        "details": {
            "selected": selected_config,
            "search": search_rows,
        },
    }
