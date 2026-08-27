from __future__ import annotations


def run_weekly_pipeline(dry_run: bool = False) -> None:
    steps = [
        "ingest results",
        "evaluate frozen predictions",
        "update Elo ratings",
        "recompute features",
        "train challengers",
        "register model versions",
        "promote champion by RPS",
        "freeze next predictions",
    ]
    for step in steps:
        prefix = "[dry-run]" if dry_run else "[run]"
        print(f"{prefix} {step}")


if __name__ == "__main__":
    run_weekly_pipeline(dry_run=True)
