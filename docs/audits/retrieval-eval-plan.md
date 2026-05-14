# Retrieval Evaluation Plan

## Goal

Continuously measure retrieval quality to catch regressions before they reach users.

## Metrics

| Metric | Definition | Target |
|---|---|---:|
| Recall@k | Fraction of expected keywords found in top-k retrieved chunks | ≥ 0.70 |
| MRR | Mean Reciprocal Rank — position of first relevant chunk | ≥ 0.60 |
| Faithfulness (proxy) | Fraction of expected answer keywords in top retrieved chunk | ≥ 0.60 |

## Dataset

`backend/data/eval/golden_qa.json` — JSON array of test cases:

```json
{
  "question": "What is the password reset policy?",
  "expected_chunks": ["password", "reset"],
  "expected_answer_contains": ["24 hours"],
  "mode": "Internal"
}
```

Fields:
- `question` — the query sent to the retrieval pipeline
- `expected_chunks` — keywords that must appear in at least one retrieved chunk
- `expected_answer_contains` — keywords expected in a correct LLM answer (optional)
- `mode` — `Internal` or `Web` doc_type filter

The dataset ships with 5 positive cases and 2 negative/out-of-scope cases. **Expand it with real queries from your indexed documents before relying on the scores.**

## Running the eval

```bash
# via Make (requires running Docker stack)
make eval

# directly
python -m scripts.eval_retrieval \
  --dataset data/eval/golden_qa.json \
  --top-k 5 \
  --mode Internal \
  --min-recall 0.7
```

Exit code 0 = pass, 1 = fail (avg recall below `--min-recall`).

## CI Integration

Add to `.github/workflows/ci.yml` after migrations are applied:

```yaml
- name: Retrieval eval
  run: |
    docker compose exec -T backend python -m scripts.eval_retrieval \
      --dataset data/eval/golden_qa.json --top-k 5 --min-recall 0.7
```

This requires the test database to have documents indexed. Use a fixture document during CI setup or skip this step until a persistent test dataset exists.

## Future improvements

- Replace keyword-match recall with embedding similarity (cosine distance to expected answer).
- Add RAGAS metrics (answer relevancy, context precision, context recall).
- Track scores over time in `docs/audits/retrieval-eval-results/`.
- Add negative-case assertions: out-of-scope queries should return zero relevant chunks.
