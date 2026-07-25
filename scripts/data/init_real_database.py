from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.data.import_official_workbook import import_workbook


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="构建受控 Real 数据发布版本")
    parser.add_argument("--source", type=Path, required=True, help="Git 忽略目录中的官方工作簿")
    parser.add_argument("--real-root", type=Path, default=root / "data" / "real")
    parser.add_argument("--private-root", type=Path, default=root / "data" / "private")
    args = parser.parse_args()
    result = import_workbook(args.source, args.real_root, args.private_root)
    print(json.dumps({"run_id": result["run_id"], "status": "published"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
