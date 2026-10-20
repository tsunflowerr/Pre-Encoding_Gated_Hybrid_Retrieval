from __future__ import annotations

import argparse
import json

from pegh.profiling.report import make_figures, summarize_run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize complete online runs and produce figures"
    )
    parser.add_argument("--run", required=True)
    parser.add_argument("--quality-csv")
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    args = parser.parse_args()
    summary = summarize_run(args.run, bootstrap_samples=args.bootstrap_samples)
    figures = make_figures(args.run, args.quality_csv)
    print(json.dumps({"summary": summary, "figures": figures}, indent=2))


if __name__ == "__main__":
    main()
