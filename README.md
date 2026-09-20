# AgentABI

**Agent Compatibility & Upgrade Intelligence Platform**

AgentABI is a production-oriented platform for evaluating whether changes to AI agents, tools, schemas, prompts, and service dependencies are safe to release.

Instead of asking an LLM to decide whether a change is compatible, AgentABI uses deterministic software to calculate structural differences, dependency impact, replay results, and release risk. The LLM is used only after the evidence has been produced, where it can explain the result in human-readable terms.

The engineering question behind the project is simple:

> **If an AI agent or one of its dependencies changes, what can break, how can we prove it, and should the release be allowed?**

---

## Why AgentABI Exists

Modern AI applications are rarely isolated model calls. Production systems can include autonomous agents, tool integrations, structured input/output contracts, APIs, microservices, message queues, shared state, databases, retrieval systems, external providers, and multiple model or prompt versions.

A small change in one component can introduce failures elsewhere. Examples include:

- removing or renaming a required schema field
- changing a tool request or response contract
- modifying an enum used by downstream consumers
- changing an agent configuration
- introducing a breaking dependency
- shipping a change that passes static validation but fails during execution
- releasing a change without understanding its downstream blast radius

AgentABI treats compatibility as an engineering problem rather than an LLM judgment problem.

---

## Core Design Principle

AgentABI separates **decision-making** from **explanation**.

### Deterministic systems decide

The platform uses deterministic code for:

- schema normalization
- schema and configuration diffing
- compatibility classification
- dependency traversal
- blast-radius analysis
- replay execution
- differential comparison
- risk scoring
- PASS / WARN / BLOCK decisions

### The LLM explains

The LLM receives already-structured evidence and generates an explanation of:

- what changed
- which components are affected
- what differed during replay
- why the risk score changed
- what an engineer should review

The LLM does **not** calculate compatibility, graph dependencies, replay metrics, risk score, or the final release decision.

This boundary makes the system easier to test, audit, and reason about.

---

## Architecture

```text
                         ┌─────────────────────┐
                         │   GitHub / CI/CD    │
                         └─────────┬───────────┘
                                   │
                                   ▼
                         ┌─────────────────────┐
                         │ Change / PR Intake  │
                         └─────────┬───────────┘
                                   │
                                   ▼
                    ┌────────────────────────────┐
                    │ Baseline + Candidate Build │
                    └──────────────┬─────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
     ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐
     │ Schema / Config│  │ Dependency Graph │  │ Historical Replay│
     │ Diff Engine    │  │ + Blast Radius   │  │ Engine           │
     └───────┬────────┘  └────────┬─────────┘  └────────┬─────────┘
             │                    │                     │
             └────────────────────┼─────────────────────┘
                                  ▼
                       ┌─────────────────────┐
                       │ Differential Engine │
                       └─────────┬───────────┘
                                 │
                                 ▼
                       ┌─────────────────────┐
                       │ Deterministic Risk  │
                       │ Engine              │
                       └─────────┬───────────┘
                                 │
                         PASS / WARN / BLOCK
                                 │
                                 ▼
                       ┌─────────────────────┐
                       │ LLM Explanation     │
                       │ Layer               │
                       └─────────────────────┘
```

---

## Key Capabilities

### Component Registry

AgentABI maintains a registry of versioned components that participate in an AI system.

A component can represent an agent, tool, API, service, prompt-driven capability, model-backed function, or another versioned dependency. The registry provides a consistent source of metadata for compatibility analysis and dependency tracking.

### Schema & Configuration Diff Engine

The compatibility engine compares baseline and candidate definitions after normalization.

It is designed to detect meaningful contract changes such as:

- required field additions or removals
- type changes
- enum changes
- nested object changes
- property additions and removals
- configuration changes
- potentially breaking interface modifications

The output is structured evidence that can be tested and consumed by later stages of the pipeline.

### Dependency Graph & Blast Radius

AgentABI stores relationships between components in Neo4j.

The graph layer answers questions such as:

- Which components depend on this service?
- What downstream agents may be affected by this change?
- How far does the impact propagate?
- Which paths connect the changed component to affected consumers?

Blast-radius traversal is deterministic and implemented as application logic rather than delegated to an LLM.

### Historical Trajectories

The platform stores execution trajectories so previous behavior can be used as evidence during an upgrade evaluation.

A trajectory can represent a sequence of agent actions, tool calls, inputs and outputs, state transitions, execution results, and relevant metadata.

### Replay Engine

AgentABI can replay historical trajectories against baseline and candidate configurations.

This makes it possible to detect runtime behavior changes that may not be visible from a static schema comparison alone.

### Differential Analysis

The differential layer compares baseline and candidate replay results and can identify changes in:

- execution success
- tool behavior
- outputs
- errors
- state transitions
- relevant execution metadata

The result becomes a deterministic input to release risk evaluation.

### Deterministic Risk Engine

AgentABI combines evidence from multiple subsystems into a structured risk assessment.

Inputs can include:

- compatibility findings
- severity of contract changes
- graph blast radius
- replay differences
- affected components
- execution failures

The engine produces an explicit release decision:

```text
PASS
WARN
BLOCK
```

The decision is produced by application logic, not by a model prompt.

### LLM-Assisted Explanation

After the release decision is calculated, AgentABI can use an LLM to explain the evidence. The explanation layer is intentionally downstream of deterministic analysis, so model variability cannot control release safety.

### Authentication & Authorization

The platform includes:

- JWT authentication
- GitHub OAuth
- `/auth/me`
- organization-aware access
- role-based authorization
- `OWNER > ADMIN > MEMBER` permission hierarchy
- onboarding flow for first-time users
- protected frontend routes

### Application Security

Security controls include:

- CORS configuration
- security response headers
- request-size enforcement
- rate limiting
- correlation IDs
- centralized error handling
- JWT-based API protection
- GitHub OAuth state handling
- AWS Secrets Manager integration
- Kubernetes secret injection
- CI security scanning

---

## User Interface

The frontend includes dedicated views for:

- Dashboard
- Projects
- Components
- Compatibility
- Dependency Graph
- Trajectories
- Replays
- Differential Analysis
- Risk
- Integrations
- Audit

The application includes GitHub authentication, onboarding, organization-aware navigation, and protected application routes.

---

## Technology Stack

### Backend

- Python
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- asyncio
- httpx

### Frontend

- Next.js
- React
- TypeScript

### Data & Messaging

- PostgreSQL
- Redis / Valkey
- Neo4j
- Apache Kafka

### AI

- OpenAI API

The model is used for explanation only. Compatibility and release decisions remain deterministic.

### Cloud & Platform

- AWS
- Amazon EKS
- Amazon ECR
- Amazon RDS for PostgreSQL
- Amazon ElastiCache / Valkey
- AWS Secrets Manager
- IAM / IRSA
- Amazon VPC
- Amazon EBS
- Docker
- Kubernetes
- Helm
- Terraform

### CI/CD & Observability

- GitHub Actions
- OpenID Connect (OIDC)
- OpenTelemetry
- Prometheus
- Grafana

---

## AWS Deployment Architecture

The AWS environment is managed as infrastructure rather than manually configured servers.

```text
GitHub Actions
      │
      │ OIDC
      ▼
AWS IAM
      │
      ├──────────────► Amazon ECR
      │                    │
      │                    ▼
      │              Container Images
      │
      ▼
Amazon EKS
      │
      ├── AgentABI API
      ├── AgentABI Frontend
      ├── AgentABI Worker
      ├── Kafka
      └── Neo4j
      │
      ├──────────────► Amazon RDS PostgreSQL
      ├──────────────► Amazon ElastiCache / Valkey
      └──────────────► AWS Secrets Manager
```

Infrastructure provisioning is managed with Terraform, while application deployment is managed with Helm.

GitHub Actions uses AWS OIDC-based authentication for deployment rather than storing long-lived AWS access keys in the repository.

---

## AWS Demo Lifecycle

The AWS environment is intentionally operated as a recruiter/demo environment rather than a continuously running public service.

To control cloud cost, AgentABI supports a reversible sleep/wake workflow.

### Sleep mode

During an extended idle period:

- AgentABI Kubernetes workloads are scaled to zero
- EKS managed worker nodes are scaled to zero
- RDS PostgreSQL is stopped
- persistent volumes remain preserved
- ECR images remain preserved
- Secrets Manager secrets remain preserved
- Terraform state remains preserved
- Helm configuration remains preserved

### Wake mode

Before a demonstration:

1. Start PostgreSQL.
2. Restore the EKS managed node group.
3. Restore AgentABI workloads through Helm.
4. Wait for API, graph, and Kafka readiness.
5. Start the required local access path when public ingress is disabled.

This keeps the environment recoverable without leaving all compute resources running continuously.

---

## Kubernetes Workloads

The Kubernetes deployment contains:

```text
agentabi-api
agentabi-worker
agentabi-frontend
agentabi-kafka
agentabi-neo4j
```

Persistent storage is used for stateful services, including Kafka and Neo4j.

---

## Local Development

### Prerequisites

- Git
- Docker
- Docker Compose
- Python
- Node.js
- AWS CLI
- kubectl
- Helm
- Terraform

Clone the repository:

```bash
git clone https://github.com/lavanesh-tech/AgentABI.git
cd AgentABI
```

Review the environment template before running the application:

```bash
cp .env.example .env
```

Do not commit secrets to source control.

---

## Database Migrations

Database schema changes are managed with Alembic.

A typical development command is:

```bash
alembic upgrade head
```

Exact execution can vary depending on whether the command is run directly from the backend environment or through containers.

---

## Docker Development Environment

AgentABI includes Docker-based local infrastructure for development. Supporting services include PostgreSQL, Redis, Neo4j, Kafka, and backend services.

Validate the Compose configuration with:

```bash
docker compose config
```

Then start the required services according to the repository configuration.

---

## API Health & Readiness

AgentABI separates basic health from dependency readiness.

Example endpoints:

```text
GET /api/v1/health
GET /api/v1/ready
```

The readiness endpoint is designed to verify dependencies required by the application, including the database, graph service, and Kafka.

---

## GitHub OAuth Flow

```text
AgentABI Login
      │
      ▼
GitHub Authorization
      │
      ▼
Frontend OAuth Callback
      │
      ▼
Backend Token Exchange
      │
      ▼
JWT Session
      │
      ├──► Onboarding
      └──► Dashboard
```

New users can be routed through organization onboarding before entering the main application.

---

## CI/CD

The GitHub Actions deployment pipeline follows this flow:

```text
Push / manual deployment
        │
        ▼
GitHub Actions
        │
        ▼
AWS authentication through OIDC
        │
        ▼
Build backend/frontend images
        │
        ▼
Push images to Amazon ECR
        │
        ▼
Deploy with Helm to Amazon EKS
        │
        ▼
Verify application readiness
```

Using OIDC avoids storing long-lived AWS credentials in GitHub repository secrets.

---

## Infrastructure as Code

Terraform manages AWS infrastructure required by the project, including networking, EKS, managed node groups, IAM roles, RDS, ElastiCache, ECR, storage, secrets integration, and deployment permissions.

Terraform state is stored remotely in AWS rather than relying on a developer laptop as the source of truth.

---

## Testing Strategy

AgentABI is structured so that the most important release-safety logic can be tested without depending on nondeterministic LLM output.

Testable areas include:

- schema normalization
- compatibility rules
- graph traversal
- blast-radius calculation
- replay execution
- differential comparison
- authorization behavior
- security controls
- risk logic

The project contains extensive pure unit tests for deterministic core behavior in addition to deployment and infrastructure validation.

---

## Engineering Decisions

### Deterministic release decisions

A model cannot directly decide whether a release passes or fails.

### Versioned database changes

Alembic migrations are used instead of ad-hoc schema mutation.

### Graph-based dependency analysis

Dependency impact is modeled explicitly rather than inferred from text at request time.

### Replay before explanation

Historical execution evidence is produced before the LLM sees the upgrade context.

### Infrastructure as code

AWS infrastructure is reproducible through Terraform.

### Declarative application deployment

Kubernetes workloads are deployed through Helm.

### Short-lived cloud authentication

GitHub Actions uses OIDC for AWS access instead of long-lived AWS access keys.

### Cost-aware demo infrastructure

The AWS environment can be placed into a reversible sleep state when the project is not being demonstrated.

---

## Repository Structure

```text
AgentABI/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── repositories/
│   │   ├── services/
│   │   └── ...
│   ├── migrations/
│   └── tests/
│
├── frontend/
│   ├── app/
│   ├── features/
│   ├── lib/
│   └── ...
│
├── deploy/
│   └── helm/
│       └── agentabi/
│
├── infrastructure/
├── scripts/
│   ├── aws-demo-up.sh
│   ├── aws-demo-down.sh
│   └── aws-demo-status.sh
├── docs/
├── docker-compose.yml
└── README.md
```

---

## Example Release Evaluation

Consider a tool contract that changes from:

```json
{
  "customer_id": "string",
  "amount": "number"
}
```

to:

```json
{
  "customer_id": "string",
  "amount": "number",
  "currency": "string"
}
```

If `currency` becomes required, AgentABI can:

1. normalize the baseline and candidate schemas
2. identify the required-field change
3. determine which agents depend on the tool
4. calculate the downstream blast radius
5. replay historical trajectories against the candidate
6. compare baseline and candidate behavior
7. calculate deterministic release risk
8. produce PASS, WARN, or BLOCK
9. generate a human-readable explanation from the already-computed evidence

The LLM never substitutes for steps 1–8.

---

## What This Project Demonstrates

AgentABI was built to demonstrate engineering skills relevant to backend, platform, distributed-systems, cloud, and AI-infrastructure roles.

The project covers:

- API design
- asynchronous Python
- backend architecture
- relational data modeling
- graph databases
- event streaming
- caching
- deterministic analysis
- AI integration
- authentication
- authorization
- application security
- replay systems
- infrastructure as code
- containerization
- Kubernetes
- Helm
- AWS
- CI/CD
- observability
- cloud cost management

It is intentionally more than a chatbot wrapper. The AI model is one component inside a larger software system with deterministic control boundaries.

---

## Current Status

The project currently includes working implementations across the core platform, including:

- component registry
- dependency graph
- blast-radius analysis
- compatibility/schema-diff engine
- trajectory and replay infrastructure
- differential analysis
- deterministic risk workflow
- authentication and authorization
- GitHub OAuth
- security middleware
- frontend application
- Docker-based development infrastructure
- Kubernetes and Helm deployment
- Terraform-managed AWS infrastructure
- GitHub Actions deployment pipeline
- AWS EKS deployment
- reversible recruiter/demo sleep and wake lifecycle

The AWS environment is intentionally not kept running continuously. It can be restored when a live demonstration is required.

---

## Future Work

- public HTTPS ingress and custom domain
- richer replay scenario management
- additional compatibility rule packs
- expanded audit history
- policy-as-code integrations
- richer observability dashboards
- release-gate integrations with additional CI providers
- multi-provider model explanation support
- larger-scale replay scheduling
- more granular organization and project permissions

---

## Security Notes

Do not commit:

- AWS credentials
- GitHub client secrets
- GitHub App private keys
- JWT signing keys
- OpenAI API keys
- database passwords
- production `.env` files

Secrets for the AWS deployment are stored through AWS Secrets Manager and injected into workloads through deployment configuration.

---

## Author

**Lavanesh Thirukonda Mahendran**  
M.S. Computer Science, George Mason University  
GitHub: [lavanesh-tech](https://github.com/lavanesh-tech)

---

## Project Summary

AgentABI is a cloud-deployed engineering platform for detecting compatibility risk in evolving AI-agent systems.

It combines deterministic schema analysis, dependency graphs, blast-radius calculation, historical replay, differential analysis, and release-risk evaluation with an LLM explanation layer.

The system is built with Python, FastAPI, Next.js, PostgreSQL, Neo4j, Kafka, Redis/Valkey, Docker, Kubernetes, Helm, Terraform, GitHub Actions, and AWS services including EKS, ECR, RDS, ElastiCache, IAM, Secrets Manager, EBS, and VPC networking.

The project demonstrates backend engineering, distributed systems, AI infrastructure, cloud deployment, security, DevOps, CI/CD, and production-oriented system design without delegating critical release decisions to an LLM.
