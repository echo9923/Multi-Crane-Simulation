from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.schemas.training import StgnnConversionOptions, TrainingConversionError
from backend.app.training.converter import StgnnDatasetConverter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Module P STGNN training samples.")
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--split", action="append", default=None)
    parser.add_argument("--max-nodes", type=int, default=None)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--strict", action="store_true", default=False)
    mode.add_argument("--lenient", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-npz", action="store_true")
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--output-json", action="store_true")
    args = parser.parse_args(argv)

    dataset_root = Path(args.dataset_root)
    output_root = Path(args.output_root) if args.output_root else dataset_root / "training" / "stgnn"
    strict = not args.lenient
    if args.strict:
        strict = True
    try:
        options = StgnnConversionOptions(
            dataset_root=dataset_root,
            output_root=output_root,
            strict=strict,
            splits=args.split,
            max_nodes=args.max_nodes,
            dry_run=args.dry_run,
            write_npz=args.write_npz and not args.index_only,
        )
        result = StgnnDatasetConverter(options=options).convert(
            dataset_root=dataset_root,
            output_root=output_root,
            splits=args.split,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    payload = result.model_dump(mode="json")
    if args.output_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"dataset_id={result.summary.dataset_id} "
            f"samples={len(result.samples)} "
            f"output_root={output_root}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
