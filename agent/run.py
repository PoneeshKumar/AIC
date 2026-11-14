"""Agent entrypoint. Owner: CORE.

Run: bash scripts/dev.sh agent --shipment BIO-2048

The loop, in order:
  1. Register this worker (pid, worker id) in `workers` so the chaos button can kill it.
  2. Load or create the run for the shipment.
  3. RESUME FIRST: for every step still `sent`, call agent.verify before doing anything else.
  4. If there is no plan, or the world changed, call agent.planner and write `planned` steps.
  5. Take the next planned step, mark it `sent`, call the system, then verify with a separate read.
  6. On an unexpected failure, call agent.adapt (which uses agent.memory) and wait for approval.
  7. Write one Event per decision so the UI log is the real record.
"""
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shipment", required=True)
    parser.add_argument("--worker-id", default="worker-1")
    args = parser.parse_args()
    raise SystemExit("agent.run is a stub. Shipment: " + args.shipment)


if __name__ == "__main__":
    main()
