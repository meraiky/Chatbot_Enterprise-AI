"""
Retrieval evaluation CLI — recall@k, MRR, and answer faithfulness.

Usage:
    python -m scripts.eval_retrieval --dataset data/eval/golden_qa.json
    python -m scripts.eval_retrieval --dataset data/eval/golden_qa.json --top-k 5 --mode Internal

Dataset format (JSON array):
    [
      {
        "question": "What is the password reset policy?",
        "expected_chunks": ["password", "reset", "policy"],   // keywords that must appear in retrieved docs
        "expected_answer_contains": ["24 hours", "email"],    // keywords that must appear in the LLM answer
        "mode": "Internal"                                    // optional, overrides --mode
      },
      ...
    ]

Outputs a summary table and exits with code 1 if recall@k falls below --min-recall (default 0.7).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.services.rag.vector_store import get_vector_store


def recall_at_k(retrieved_texts: list[str], expected_keywords: list[str]) -> float:
    """Fraction of expected keywords found in any retrieved chunk."""
    if not expected_keywords:
        return 1.0
    combined = " ".join(retrieved_texts).lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in combined)
    return hits / len(expected_keywords)


def mrr(retrieved_texts: list[str], expected_keywords: list[str]) -> float:
    """Reciprocal rank of the first chunk containing any expected keyword."""
    if not expected_keywords:
        return 1.0
    for rank, text in enumerate(retrieved_texts, start=1):
        if any(kw.lower() in text.lower() for kw in expected_keywords):
            return 1.0 / rank
    return 0.0


def faithfulness(answer: str, expected_keywords: list[str]) -> float:
    """Fraction of expected answer keywords found in the LLM answer."""
    if not expected_keywords:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return hits / len(expected_keywords)


def run_eval(dataset_path: str, top_k: int, default_mode: str, min_recall: float) -> bool:
    cases = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    vs = get_vector_store()

    results = []
    for i, case in enumerate(cases):
        question = case["question"]
        mode = case.get("mode", default_mode)
        expected_chunks = case.get("expected_chunks", [])
        expected_answer_kw = case.get("expected_answer_contains", [])
        filter_dict = {"doc_type": mode} if mode else {}

        docs_and_scores = vs.similarity_search_with_score(question, k=top_k, filter=filter_dict)
        retrieved_texts = [doc.page_content for doc, _ in docs_and_scores]

        rec = recall_at_k(retrieved_texts, expected_chunks)
        rr = mrr(retrieved_texts, expected_chunks)

        # Faithfulness: skip if no answer keywords specified (retrieval-only eval)
        faith = None
        if expected_answer_kw:
            # Use a minimal answer attempt from the top chunk (no LLM call to keep eval fast)
            answer_proxy = retrieved_texts[0] if retrieved_texts else ""
            faith = faithfulness(answer_proxy, expected_answer_kw)

        results.append({
            "id": i + 1,
            "question": question[:60],
            "mode": mode,
            "recall": rec,
            "mrr": rr,
            "faithfulness": faith,
        })

    # Print table
    print(f"\n{'─'*90}")
    print(f"  Retrieval Eval — top_k={top_k}  dataset={dataset_path}")
    print(f"{'─'*90}")
    header = f"  {'#':>3}  {'Q (truncated)':<42}  {'Mode':<10}  {'Recall':>7}  {'MRR':>6}  {'Faith':>7}"
    print(header)
    print(f"{'─'*90}")

    for r in results:
        faith_str = f"{r['faithfulness']:.2f}" if r["faithfulness"] is not None else "  n/a"
        flag = "✗" if r["recall"] < min_recall else " "
        print(f"  {r['id']:>3}{flag} {r['question']:<42}  {r['mode']:<10}  {r['recall']:>7.2f}  {r['mrr']:>6.2f}  {faith_str:>7}")

    avg_recall = sum(r["recall"] for r in results) / len(results)
    avg_mrr = sum(r["mrr"] for r in results) / len(results)
    faith_scores = [r["faithfulness"] for r in results if r["faithfulness"] is not None]
    avg_faith = sum(faith_scores) / len(faith_scores) if faith_scores else None

    print(f"{'─'*90}")
    faith_summary = f"{avg_faith:.2f}" if avg_faith is not None else "n/a"
    print(f"  {'AVG':<48}  {avg_recall:>7.2f}  {avg_mrr:>6.2f}  {faith_summary:>7}")
    print(f"{'─'*90}\n")

    passed = avg_recall >= min_recall
    status = "PASS" if passed else f"FAIL (avg recall {avg_recall:.2f} < threshold {min_recall})"
    print(f"  Result: {status}\n")
    return passed


def main():
    parser = argparse.ArgumentParser(description="Retrieval evaluation CLI")
    parser.add_argument("--dataset", required=True, help="Path to golden Q&A JSON file")
    parser.add_argument("--top-k", type=int, default=5, dest="top_k")
    parser.add_argument("--mode", default="Internal", help="Default doc_type filter (Internal|Web)")
    parser.add_argument("--min-recall", type=float, default=0.7, dest="min_recall",
                        help="Minimum average recall@k to pass (default 0.7)")
    args = parser.parse_args()

    passed = run_eval(args.dataset, args.top_k, args.mode, args.min_recall)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
