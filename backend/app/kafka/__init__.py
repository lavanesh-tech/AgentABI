"""Kafka transport: the consumer loop (`consumer.py`), the worker
entrypoint (`worker.py`, `python -m app.kafka.worker`), and the one
`EventHandler` implementation that dispatches to `app.services.
github_pr_analysis_service.GitHubPullRequestAnalysisService`
(`analysis_handler.py`). No compatibility/risk logic lives here — Phase
13 spec §15: "do not reimplement compatibility/risk logic in the
worker."
"""
