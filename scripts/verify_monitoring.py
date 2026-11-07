"""Verify private local monitoring without publishing credentials or trace payloads."""

import json
import math
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main() -> None:
    with httpx.Client(timeout=20) as client:
        client.get("http://localhost:8000/health/ready").raise_for_status()
        time.sleep(3)
        targets = client.get("http://localhost:9090/api/v1/targets").json()["data"]["activeTargets"]
        password = Path(".docker-local/grafana-password").read_text().strip()
        dashboard = client.get(
            "http://localhost:3000/api/dashboards/uid/smartrag-operations",
            auth=("admin", password),
        )
        checks = [
            {"check": "scrape_" + t["labels"]["job"], "passed": t["health"] == "up"}
            for t in targets
        ]
        checks.append({"check": "grafana_dashboard", "passed": dashboard.status_code == 200})
        metrics = {}
        for name, query in {
            "input_tokens_since_api_start": (
                'sum(smartrag_llm_tokens_total{job="api",direction="input"})'
            ),
            "output_tokens_since_api_start": (
                'sum(smartrag_llm_tokens_total{job="api",direction="output"})'
            ),
            "api_process_rss_bytes": 'process_resident_memory_bytes{job="api"}',
            "api_process_cpu_seconds": 'process_cpu_seconds_total{job="api"}',
            "query_embedding_cache_hit_rate": (
                'sum(smartrag_events_total{job="api",operation="embedding.cache",outcome="hit"})'
                ' / sum(smartrag_events_total{job="api",operation="embedding.cache"})'
            ),
        }.items():
            values = client.get(
                "http://localhost:9090/api/v1/query", params={"query": query}
            ).json()["data"]["result"]
            value = float(values[0]["value"][1]) if values else None
            metrics[name] = value if value is not None and math.isfinite(value) else None
    probe = (
        "import urllib.request,json; "
        "r=json.load(urllib.request.urlopen('http://tempo:3200/api/search?limit=20')); "
        "print(json.dumps({'trace_count':len(r.get('traces',[]))}))"
    )
    process = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    count = json.loads(process.stdout)["trace_count"] if process.returncode == 0 else 0
    checks.append({"check": "otlp_traces_reach_tempo", "passed": count > 0})
    result = {
        "executed_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "sampled_trace_count": count,
        "metrics_snapshot": metrics,
        "metrics_scope": (
            "last Prometheus scrape; counters since API start, not isolated UAT billing"
        ),
        "hosted_langfuse": "NOT VERIFIED: no hosted credentials/export consent configured",
    }
    output = Path("evaluation/release/monitoring.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if not checks or not all(check["passed"] for check in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
