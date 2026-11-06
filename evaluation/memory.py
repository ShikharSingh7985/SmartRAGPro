"""Each vectorizer runs in a fresh process; sampled total RSS and Python allocations."""

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time
import tracemalloc
from pathlib import Path

import psutil


def worker(kind, count):
    from sklearn.feature_extraction.text import HashingVectorizer, TfidfVectorizer

    process = psutil.Process()
    baseline = process.memory_info().rss
    corpus = [
        f"Synthetic document token{i} code{i} value{i} policy revenue training model calibration "
        * 4
        for i in range(count)
    ]
    samples = []
    stopped = threading.Event()

    def sample():
        while not stopped.wait(0.01):
            samples.append(process.memory_info().rss)

    thread = threading.Thread(target=sample)
    thread.start()
    tracemalloc.start()
    cpu = process.cpu_times()
    started = time.perf_counter()
    vectorizer = (
        TfidfVectorizer()
        if kind == "tfidf"
        else HashingVectorizer(n_features=2**18, alternate_sign=False)
    )
    matrix = vectorizer.fit_transform(corpus)
    seconds = time.perf_counter() - started
    _, allocated = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    stopped.set()
    thread.join()
    final = process.memory_info().rss
    cpu_after = process.cpu_times()
    return {
        "method": kind,
        "documents": count,
        "baseline_rss_bytes": baseline,
        "peak_sampled_rss_bytes": max([baseline, final, *samples]),
        "final_rss_bytes": final,
        "python_peak_allocated_bytes": allocated,
        "feature_columns": matrix.shape[1],
        "csr_bytes": matrix.data.nbytes + matrix.indices.nbytes + matrix.indptr.nbytes,
        "seconds": seconds,
        "cpu_seconds": cpu_after.user + cpu_after.system - cpu.user - cpu.system,
        "sample_interval_ms": 10,
        "rss_samples": len(samples),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=["tfidf", "hashing"])
    parser.add_argument("--documents", type=int, default=20000)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker, args.documents)))
        return
    rows = []
    for repeat in range(3):
        for kind in ["tfidf", "hashing"]:
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "evaluation.memory",
                    "--worker",
                    kind,
                    "--documents",
                    str(args.documents),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            rows.append({"repeat": repeat, **json.loads(run.stdout)})
    Path("evaluation/results").mkdir(exist_ok=True)
    Path("evaluation/results/memory.json").write_text(
        json.dumps(
            {
                "platform": platform.platform(),
                "logical_cpus": os.cpu_count(),
                "physical_memory_bytes": psutil.virtual_memory().total,
                "methodology": "fresh processes; imports included in baseline RSS; "
                "synthetic corpus; concurrency one",
                "results": rows,
            },
            indent=2,
        )
    )
    print(json.dumps(rows), flush=True)


if __name__ == "__main__":
    main()
