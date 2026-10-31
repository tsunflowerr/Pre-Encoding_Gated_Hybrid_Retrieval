"""PE-GH v2 search demo: type a question, see the gate's decision, timings and results.

Uses the frozen gate (configs/v4/gate_v2.json) and its fixed fusion choices; the threshold
encodes the operating budget of this domain's (unlabeled) query set. Standard library only:

    python scripts_shared/demo_v4.py --domain unix --port 8765
"""

from __future__ import annotations

import argparse
import html
import json
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from contracts.io import iter_corpus, load_queries
from contracts.types import Query
from pegh.data.artifacts import file_hash
from pegh.v4 import gate as g
from pegh.v4.online import create_v2_method
from pegh.v4.workspace import SEEN_DOMAINS, Workspace

ROOT = Path.home() / ".cache/pegh"


class DemoTrace:
    """Stage timings for one request, same interface as the benchmark trace sink."""

    def __init__(self):
        self.times, self.counters = {}, {}

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.times[name] = self.times.get(name, 0.0) + (time.perf_counter() - started) * 1000

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def reset(self) -> None:
        self.times, self.counters = {}, {}


class Engine:
    def __init__(self, ws: Workspace, domain: str, budget: float | None):
        frozen = json.loads((ws.repo / "configs/v4/gate_v2.json").read_text(encoding="utf-8"))
        self.domain, key, tiers = domain, frozen["encoder"], frozen["tiers"]
        gate = g.LinearGate.from_json(frozen["gate"])
        with np.load(ws.features(key, domain)) as stored:
            x = np.hstack([stored[group] for group in gate.spec.groups])
            forced = (stored["v1"][:, 1] == 0) | (stored["v1"][:, 12] == 1)
        stats = g.domain_stats(x) if gate.spec.norm == "domain" else None
        self.budget = budget if budget is not None else frozen["operating_budget"]
        scores = gate.score(x, stats)
        self.threshold = g.quantile_threshold(scores, forced, self.budget)
        gate_path = ws.root / "artifacts/gates/demo" / f"{domain}.json"
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(
            json.dumps({"domain": domain, "gate": frozen["gate"], "domain_stats": stats}),
            encoding="utf-8",
        )
        common = {
            "domain": domain,
            "fold": 0,
            "sparse_dir": str(ws.sparse(domain)),
            "dense_dir": str(ws.dense(key, domain)),
            "expected_sparse_sha256": file_hash(ws.sparse(domain) / "index.sqlite3"),
            "expected_dense_sha256": file_hash(ws.dense(key, domain) / "index.faiss"),
            "query_prefix": frozen["query_prefix"],
            "cache_folder": str(ws.models),
            "proxy_dir": str(ws.proxy(key, domain)),
            "expected_proxy_hash": json.loads(
                (ws.proxy(key, domain) / "manifest.json").read_text()
            )["manifest_hash"],
            "p_star": tiers["p_star"],
            "h_star": tiers["h_star"],
        }
        self.trace = DemoTrace()
        self.gated = create_v2_method(
            trace=self.trace,
            route="gated",
            scorer="gate_v2",
            gate_path=str(gate_path),
            expected_gate_sha256=file_hash(gate_path),
            threshold=self.threshold,
            protocol_path=str(ws.repo / "configs/gating/protocol_v1.yaml"),
            **common,
        )
        self.encoder_name, self.tiers = key, tiers
        self.docs = {
            d.doc_id: (d.title, d.body)
            for d in iter_corpus(ws.raw(domain) / "corpus.jsonl", domain)
        }
        self.examples = [
            q.text for q in load_queries(ws.raw(domain) / "queries.jsonl", domain)[:400:40]
        ]

    def search(self, text: str) -> dict:
        query = Query(f"{self.domain}:demo-{time.time_ns()}", self.domain, text)
        self.trace.reset()
        started = time.perf_counter()
        response = self.gated.search(query, k=100)
        total = (time.perf_counter() - started) * 1000
        stages = dict(self.trace.times)  # before the comparison-only BM25 call below
        bm25 = self.gated.sparse.search(query, k=100) if text.strip() else response.ranking

        def items(ranking):
            out = []
            for hit in ranking.hits[:10]:
                title, body = self.docs.get(hit.doc_id, ("", ""))
                out.append(
                    {
                        "id": hit.doc_id,
                        "title": title,
                        "snippet": body[:220],
                        "score": round(hit.score, 4),
                    }
                )
            return out

        return {
            "encoded": response.use_dense,
            "gate_score": None if response.gate_score is None else round(response.gate_score, 4),
            "threshold": round(self.threshold, 4),
            "total_ms": round(total, 2),
            "stages_ms": {k: round(v, 2) for k, v in stages.items()},
            "results": items(response.ranking),
            "bm25": items(bm25),
        }


PAGE = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PE-GH v2 demo</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1f2328;--muted:#5f6670;--line:#e3e3df;--skip:#1a7f37;--enc:#9a6700}
body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--ink)}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px} .sub{color:var(--muted);margin:0 0 16px}
form{display:flex;gap:8px} input{flex:1;padding:10px 12px;font-size:15px;border:1px solid var(--line);border-radius:8px}
button{padding:10px 16px;border:0;border-radius:8px;background:var(--ink);color:#fff;cursor:pointer}
.ex{margin:10px 0 18px;display:flex;flex-wrap:wrap;gap:6px}
.ex a{font-size:13px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 10px;cursor:pointer;text-decoration:none}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;color:#fff;font-weight:600}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px} @media(max-width:800px){.cols{grid-template-columns:1fr}}
ol{padding-left:20px;margin:0} li{margin:0 0 10px} .t{font-weight:600} .s{color:var(--muted);font-size:13px}
.kv{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:14px} .kv b{color:var(--ink)}
</style></head><body><main>
<h1>PE-GH v2 – tìm câu hỏi tương tự (__DOMAIN__)</h1>
<p class="sub">Gate quyết định trước khi encode: BM25 có khả năng thất bại không? Nếu có → encode (__ENCODER__) + tìm FAISS (H*); nếu không → P* (BM25 + proxy tĩnh, không chạy transformer). Ngân sách encode: __BUDGET__%.</p>
<form id="f"><input id="q" placeholder="Nhập câu hỏi tiếng Anh, ví dụ: how to show hidden files with ls" autofocus><button>Tìm</button></form>
<div class="ex">__EXAMPLES__</div><div id="out"></div></main>
<script>
const out=document.getElementById('out'),q=document.getElementById('q');
function esc(s){return s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function list(items){return '<ol>'+items.map(i=>`<li><div class="t">${esc(i.title||i.id)}</div><div class="s">${esc(i.snippet)}</div></li>`).join('')+'</ol>'}
async function run(text){q.value=text;out.innerHTML='<div class="panel">Đang tìm…</div>';
 const r=await (await fetch('/search?q='+encodeURIComponent(text))).json();
 const badge=r.encoded?'<span class="badge" style="background:var(--enc)">Encode → H*</span>':'<span class="badge" style="background:var(--skip)">Bỏ qua encode → P*</span>';
 const stages=Object.entries(r.stages_ms).map(([k,v])=>`${k} <b>${v} ms</b>`).join(' · ');
 out.innerHTML=`<div class="panel">${badge}<div class="kv" style="margin-top:8px"><span>Điểm gate <b>${r.gate_score}</b></span><span>Ngưỡng <b>${r.threshold}</b></span><span>Tổng <b>${r.total_ms} ms</b></span></div><div class="kv" style="margin-top:4px">${stages}</div></div>
 <div class="cols"><div class="panel"><b>Kết quả PE-GH v2</b>${list(r.results)}</div><div class="panel"><b>Chỉ BM25 (so sánh)</b>${list(r.bm25)}</div></div>`}
document.getElementById('f').onsubmit=e=>{e.preventDefault();if(q.value.trim())run(q.value.trim())};
document.querySelectorAll('.ex a').forEach(a=>a.onclick=()=>run(a.dataset.q));
</script></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default="unix", choices=SEEN_DOMAINS)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--budget", type=float)
    args = parser.parse_args()
    ws = Workspace.create(
        ROOT / "v4", ROOT / "v3", ROOT / "integration-20261026", ROOT / "artifacts/final-v1"
    )
    engine = Engine(ws, args.domain, args.budget)
    examples = "".join(
        f'<a data-q="{html.escape(e, quote=True)}">{html.escape(e)}</a>' for e in engine.examples
    )
    page = (
        PAGE.replace("__DOMAIN__", args.domain)
        .replace("__ENCODER__", engine.encoder_name)
        .replace("__BUDGET__", str(int(round(engine.budget * 100))))
        .replace("__EXAMPLES__", examples)
    ).encode("utf-8")
    engine.search("warm up the encoder")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/search":
                text = parse_qs(url.query).get("q", [""])[0][:500]
                body, kind = (
                    json.dumps(engine.search(text), ensure_ascii=False).encode("utf-8"),
                    "application/json",
                )
            elif url.path == "/":
                body, kind = page, "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    print(f"PE-GH v2 demo on http://127.0.0.1:{args.port} ({args.domain})", flush=True)
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()  # one request at a time


if __name__ == "__main__":
    main()
