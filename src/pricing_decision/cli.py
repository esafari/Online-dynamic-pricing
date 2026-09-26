from __future__ import annotations

import argparse
import json
import sys

from pricing_decision.orchestrator import PricingOrchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pricing Decision Service")
    sub = parser.add_subparsers(dest="cmd", required=True)

    decide = sub.add_parser("decide", help="Run one pricing decision from JSON")
    decide.add_argument("--file", "-f", help="Path to request JSON. Reads stdin if omitted.")
    decide.add_argument("--explain", action="store_true", help="Print internal scores and arms")

    sub.add_parser("serve", help="Run the FastAPI server")

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn

        from pricing_decision.config import get_settings

        settings = get_settings()
        uvicorn.run("pricing_decision.api.app:app", host=settings.host, port=settings.port, reload=False)
        return 0

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = json.load(sys.stdin)

    orch = PricingOrchestrator()
    decision = orch.decide(payload)
    if args.explain:
        print(
            json.dumps(
                {
                    "response": decision.response.model_dump(mode="json", exclude_none=True),
                    "arms": [a.model_dump() for a in decision.context.arms],
                    "scores": [s.model_dump() for s in decision.context.scores],
                    "bandit": decision.context.bandit.model_dump() if decision.context.bandit else None,
                    "experience": decision.experience,
                    "timings_ms": decision.context.stage_timings_ms,
                },
                indent=2,
                default=str,
            )
        )
    else:
        print(json.dumps(decision.response.model_dump(mode="json", exclude_none=True), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
