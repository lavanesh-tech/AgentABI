"""Phase 13's transport-layer event package: a typed, versioned envelope
plus producer/consumer Protocol abstractions. No SQLAlchemy/FastAPI/
aiokafka import in this package's pure modules (`envelope`, `errors`,
`analysis_events`, `publisher`) — mirrors `app/github/*_models.py`'s
reason for existing, so `pytest --noconftest` can exercise the event
schema for real. Domain/business logic never lives here — see
`app/services/github_pr_analysis_service.py` for what Kafka transports.
"""
