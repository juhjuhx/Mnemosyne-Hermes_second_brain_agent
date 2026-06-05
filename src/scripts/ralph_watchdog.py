#!/usr/bin/env python3
"""
ralph_watchdog.py — Eval-driven iteration loop.

Runs the eval suite on a schedule; on regression, pauses and notifies.

Usage:
    python ralph_watchdog.py --config ralph_watchdog.yaml
"""

import argparse
import json
import logging
import subprocess
import time
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("ralph")


class Watchdog:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.thresholds = self.config["thresholds"]
        self.actions = self.config["actions"]
        self.max_iterations = self.config.get("max_iterations", 5)

    def run_eval(self) -> dict:
        """Run the eval suite, return metrics."""
        log.info("Running eval suite...")
        result = subprocess.run(
            [
                "python",
                "src/scripts/eval_runner.py",
                "--eval-set",
                "tests/eval_v2_100.jsonl",
                "--hermes-url",
                "http://127.0.0.1:8642",
                "--output",
                f"tests/_results/{int(time.time())}.json",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.error(f"Eval failed: {result.stderr}")
            return {"ok": False, "stderr": result.stderr}
        # Read the latest result
        results_dir = Path("tests/_results")
        latest = max(results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        with open(latest) as f:
            data = json.load(f)
        return data["metrics"]

    def check_regression(self, metrics: dict) -> list:
        """Compare metrics to thresholds. Return list of failed checks."""
        failures = []
        for metric, threshold in self.thresholds.items():
            actual = metrics.get(metric)
            if actual is None:
                continue
            if actual < threshold:
                failures.append(
                    {
                        "metric": metric,
                        "actual": actual,
                        "threshold": threshold,
                    }
                )
        return failures

    def notify(self, failures: list, metrics: dict):
        """Notify (log + write to file)."""
        log.error(f"REGRESSION DETECTED: {len(failures)} metric(s) below threshold")
        for f in failures:
            log.error(f"  {f['metric']}: {f['actual']:.3f} < {f['threshold']:.3f}")

        # Write to regressions log
        with open("logs/regressions.log", "a") as f:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            f.write(
                f"[{ts}] {json.dumps({'failures': failures, 'metrics': metrics})}\n"
            )

    def run(self):
        """Main loop."""
        for iteration in range(self.max_iterations):
            log.info(f"=== Iteration {iteration + 1}/{self.max_iterations} ===")
            metrics = self.run_eval()
            if not metrics.get("ok", True):
                log.error("Eval failed; aborting")
                return
            failures = self.check_regression(metrics)
            if not failures:
                log.info("All metrics within thresholds. Sleep.")
                return
            self.notify(failures, metrics)
            # Don't auto-fix; just notify and exit
            log.info("Manual intervention required. Watchdog paused.")
            return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    Watchdog(args.config).run()


if __name__ == "__main__":
    main()
