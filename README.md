# Minimal Django PoC

A minimal Django application designed to test core CI/CD pipeline requirements: GitHub Actions for building and testing, and ArgoCD for Kubernetes deployments with init containers for database migrations.

## Project Structure

```
minimal-django-poc/
├── .github/workflows/
│   ├── ci.yaml              # PR + main push tests, builds, and pushes to ECR
│   └── release.yaml         # Semantic version tags (v*.*.*) trigger production builds
├── argocd/
│   ├── appproject.yaml      # ArgoCD AppProject for resource boundaries
│   ├── application-dev.yaml # DEV environment GitOps application
│   └── application-prod.yaml # PROD environment GitOps application
├── chart/
│   ├── Chart.yaml
│   ├── values.yaml          # Base Helm values with init container config
│   ├── values-dev.yaml      # DEV environment overrides
│   ├── values-prod.yaml     # PROD environment overrides
│   └── templates/
│       └── deployment.yaml  # Deployment + Service with init container for migrations
├── config/
│   ├── settings.py          # Django configuration with PostgreSQL
│   ├── urls.py              # URL routing (health check, task endpoints)
│   └── wsgi.py              # WSGI application
├── tasks/
│   ├── models.py            # Task model for database
│   ├── views.py             # Views for health check and task CRUD
│   └── migrations/
│       └── 0001_initial.py  # Initial migration
├── Dockerfile               # Multi-stage build with Python 3.14
├── docker-compose.yml       # Local development setup (Django + PostgreSQL)
├── manage.py                # Django management script
└── requirements.txt         # Python dependencies
```

## Key Features

### Database Migrations
- Init containers run `python manage.py migrate --noinput` before Django starts
- Supports EXPAND&RETRACT pattern for zero-downtime migrations
- Runs in the same Pod environment (same secrets, config, networking)

### CI/CD Pipeline
- **CI Workflow** (`.github/workflows/ci.yaml`):
  - Triggered on PR commits and main branch pushes
  - Runs tests with PostgreSQL
  - Builds Docker image
  - Pushes to Amazon ECR with tag `sha-<commit-short>`

- **Release Workflow** (`.github/workflows/release.yaml`):
  - Triggered on semantic version tags (v*.*.*)
  - Runs tests
  - Builds and pushes image to ECR with version tag

- **AWS OIDC**: No static credentials; GitHub Actions uses federated identity

### Kubernetes Deployment
- Helm chart with base and environment-specific values files
- Init container for migrations before app startup
- Health check endpoints (`/health/`)
- ConfigMap for environment variables, Secrets for sensitive data

### ArgoCD GitOps
- Manual sync policy (no automatic deployments on code push)
- DEV environment: trunk-based (`HEAD` revision)
- PROD environment: image pinned by `django.tag` in `chart/values-prod.yaml`
- Automatic namespace creation

## Local Development

### Prerequisites
- Docker and docker-compose
- Python 3.14
- PostgreSQL (or use docker-compose)

### Run Locally
```bash
docker-compose up
```

This starts:
- PostgreSQL on localhost:5432
- Django on localhost:8000

The Django container automatically runs migrations before starting the server.

## API Endpoints

- `GET /health/` — Health check for Kubernetes probes
- `GET /api/tasks/` — List all tasks (JSON)
- `POST /api/tasks/create/` — Create a new task (JSON body: `{title, description}`)

## Deployment

Full setup, troubleshooting, and known gaps are in [docs/CICD.md](docs/CICD.md).

### DEV (trunk-based)
1. Merge to `main`. CI builds and pushes `sha-<commit:8>` to ECR.
2. Set `django.tag` in `chart/values-dev.yaml` to the new `sha-` tag. Commit and push to `main`.
3. In ArgoCD, refresh and sync `minimal-django-poc-dev`.
4. The migrate init container runs before the Django container starts.

### PROD (semantic versioning)
1. Tag and push: `git tag v0.1.0 && git push origin v0.1.0`. The release workflow pushes `v0.1.0` and `latest` to ECR.
2. Set `django.tag` in `chart/values-prod.yaml` to `v0.1.0`. Commit and push to `main`. ArgoCD tracks `HEAD`, so prod changes only when this commit lands.
3. Sync and wait for health:
   ```bash
   argocd app sync minimal-django-poc-prod
   argocd app wait minimal-django-poc-prod --health
   ```
4. Verify:
   ```bash
   kubectl -n prod port-forward svc/minimal-django-poc 8081:80 &
   curl -i http://localhost:8081/health/      # expect 200 {"status": "healthy"}
   curl -i http://localhost:8081/api/tasks/   # expect 200 {"tasks": [...]}
   ```

### Rollback (PROD)
Set `django.tag` in `chart/values-prod.yaml` to the previous tag, commit, push to `main`, then sync and wait for health.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| DEBUG | False | Django debug mode |
| SECRET_KEY | (required) | Django secret; app fails to start if unset |
| ALLOWED_HOSTS | localhost,127.0.0.1 | Comma-separated allowed hosts |
| POSTGRES_DB | tasks_db | Database name |
| POSTGRES_USER | postgres | Database user |
| POSTGRES_PASSWORD | (required in K8s) | Database password (from Secret) |
| POSTGRES_HOST | localhost | Database host |
| POSTGRES_PORT | 5432 | Database port |

## AWS Setup

### Create ECR Repository
```bash
aws ecr create-repository \
  --repository-name skillregistry-poc/minimal-django-poc \
  --region eu-central-1
```

### OIDC Setup (GitHub Actions)
- The IAM role `github-actions` already exists and is referenced by the `AWS_ROLE_TO_ASSUME` repository secret.
- Its trust policy must allow `repo:<org>/minimal-django-poc:*`.
- Its policy must allow ECR push to `skillregistry-poc/minimal-django-poc`.

## Troubleshooting

- **Init container fails**: Check logs with `kubectl describe pod -n dev minimal-django-poc-xxx`
- **Image not found in ECR**: Verify workflow completed successfully and ECR repository exists
- **Database connection error**: Check POSTGRES_* environment variables and pod logs