import argparse
from pathlib import Path

from schedule_agent.storage import seed_db


def main():
    parser = argparse.ArgumentParser(description="初始化合成数据库；不会隐式清空已有数据")
    parser.add_argument("--db", type=Path, default=Path("data/app.db"))
    parser.add_argument("--fixture", choices=["base", "slot_swap"], default="base")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    seed_db(args.db, args.fixture, args.reset)
    print(f"Seeded {args.db} ({args.fixture})")


if __name__ == "__main__":
    main()
