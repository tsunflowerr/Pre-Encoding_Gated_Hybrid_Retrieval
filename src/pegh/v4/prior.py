"""Prior-work routers on the PE-GH tiers: Arabzadeh et al. [1] and LiteGator [2].

Both are adaptations, re-implemented on the same corpora, tiers (P* -> H*) and budgets as
PE-GH v2 and trained on the same six seen subforums, so only the routing decision differs:

- LiteGator (Muhammad, Darmanto, Atimi; iCAST-ES 2025): linear SVM over the paper's eight
  shallow features (query entropy, IDF min/mean/std, BM25 top-1, top-1/top-2 gap, top-10
  mean/std; `pegh.v3.pipeline.GENERAL`), label "the dense tier helps" (H* > P* nDCG@10).
- Arabzadeh, Yan, Clarke (CIKM 2021), sparse-vs-hybrid classifier: BERT-base cross-encoder
  over the query and the top BM25 document, fine-tuned for one epoch with batch size 8, label
  "BM25 has no relevant result within the top T". T = 10 here because the target is
  nDCG@10; the paper used T = 50 for recall@1000.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import numpy as np

from contracts.io import iter_corpus, load_queries
from pegh.evaluation.runs import load_rankings

BERT_ID = "google-bert/bert-base-uncased"
BERT_REVISION = "86b5e0934494bd15c9632b12f734a8a67f723594"
BERT_MAX_LENGTH = 256
ARABZADEH_T = 10


@dataclass(frozen=True)
class LinearSVM:
    """Portable StandardScaler + LinearSVC; column indices remain one-based."""

    feature_indices: tuple[int, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coef: tuple[float, ...]
    intercept: float

    def score(self, v1: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(v1)[:, np.asarray(self.feature_indices) - 1]
        return ((x - self.mean) / self.scale) @ np.asarray(self.coef) + self.intercept

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, value: dict) -> LinearSVM:
        return cls(
            *(tuple(value[k]) for k in ("feature_indices", "mean", "scale", "coef")),
            float(value["intercept"]),
        )

    @property
    def sha256(self) -> str:
        from pegh.data.artifacts import object_hash

        return object_hash(self.to_json())


def fit_litegator(xs, ys, *, c: float = 1.0, class_weight: str | None = None):
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import LinearSVC

    from pegh.v3.pipeline import GENERAL

    x = np.vstack(xs)[:, np.asarray(GENERAL) - 1]
    y = np.concatenate(ys)
    scaler = StandardScaler().fit(x)
    model = LinearSVC(C=c, class_weight=class_weight, dual=False, max_iter=5000, random_state=42)
    model.fit(scaler.transform(x), y)
    return LinearSVM(
        GENERAL,
        tuple(scaler.mean_),
        tuple(scaler.scale_),
        tuple(model.coef_[0]),
        float(model.intercept_[0]),
    )


def bert_path(cache_folder) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(
        BERT_ID, revision=BERT_REVISION, cache_dir=str(cache_folder), local_files_only=True
    )


def top_document_pairs(ws, domain: str, ids: list[str]) -> list[tuple[str, str]]:
    """(query text, title + body of the top BM25 document) for each query ID, in order."""
    queries = {q.query_id: q.text for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)}
    sparse, _ = load_rankings(ws.quality("bm25", domain), domain=domain)
    top = {q: (sparse[q].hits[0].doc_id if sparse[q].hits else None) for q in ids}
    wanted = {d for d in top.values() if d is not None}
    text = {
        d.doc_id: f"{d.title} {d.body}".strip()
        for d in iter_corpus(ws.raw(domain) / "corpus.jsonl", domain)
        if d.doc_id in wanted
    }
    return [(queries[q], text.get(top[q], "")) for q in ids]


class BertRouter:
    """Binary sequence classifier; class 1 = "run the hybrid tier"."""

    def __init__(self, path, threads: int, *, seed: int | None = None):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(threads)
        if seed is not None:
            torch.manual_seed(seed)
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path, num_labels=2)

    def _batch(self, pairs):
        queries, documents = zip(*pairs, strict=True)
        return self.tokenizer(
            list(queries),
            list(documents),
            truncation="only_second",
            max_length=BERT_MAX_LENGTH,
            padding=True,
            return_tensors="pt",
        )

    def train(self, pairs, labels, *, epochs=1, batch=8, lr=2e-5, seed=42, log=None) -> dict:
        """Seed shuffling and dropout; the classifier was already initialized in __init__."""
        from transformers import get_linear_schedule_with_warmup

        torch = self.torch
        torch.manual_seed(seed)
        order = np.random.default_rng(seed).permutation(len(pairs))
        steps = epochs * int(np.ceil(len(pairs) / batch))
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=lr)
        schedule = get_linear_schedule_with_warmup(optimizer, int(0.1 * steps), steps)
        self.model.train()
        losses, started, step = [], time.perf_counter(), 0
        for _ in range(epochs):
            for start in range(0, len(order), batch):
                rows = order[start : start + batch]
                inputs = self._batch([pairs[i] for i in rows])
                target = torch.tensor([int(labels[i]) for i in rows], dtype=torch.long)
                loss = self.model(**inputs, labels=target).loss
                loss.backward()
                optimizer.step()
                schedule.step()
                optimizer.zero_grad()
                losses.append(loss.item())
                step += 1
                if log is not None and step % 50 == 0:
                    log(step=step, steps=steps, loss=round(float(np.mean(losses[-50:])), 4))
        self.model.eval()
        return {
            "steps": step,
            "mean_loss": float(np.mean(losses)),
            "last_50_loss": float(np.mean(losses[-50:])),
            "seconds": round(time.perf_counter() - started, 1),
        }

    def score(self, pairs, batch: int = 32) -> np.ndarray:
        torch = self.torch
        self.model.eval()
        out = []
        with torch.inference_mode():
            for start in range(0, len(pairs), batch):
                logits = self.model(**self._batch(pairs[start : start + batch])).logits
                out.append(torch.softmax(logits, dim=-1)[:, 1].numpy())
        return np.concatenate(out).astype(np.float64)

    def latency(self, pairs, warmup: int = 30) -> dict:
        """One routing decision per call (tokenize + forward), batch size 1."""
        import statistics

        for pair in pairs[:warmup]:
            self.score([pair], batch=1)
        times = []
        for pair in pairs:
            started = time.perf_counter_ns()
            self.score([pair], batch=1)
            times.append((time.perf_counter_ns() - started) / 1e6)
        times.sort()
        return {
            "queries": len(times),
            "median_ms": statistics.median(times),
            "mean_ms": statistics.fmean(times),
            "p95_ms": times[int(0.95 * len(times)) - 1],
        }
