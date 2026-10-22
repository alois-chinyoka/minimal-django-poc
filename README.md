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
- PROD environment: tag-based (sync to specific git tag)
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

### DEV (Trunk-based)
1. Push to PR branch
2. GitHub Actions builds image with `sha-<commit:8>` tag
3. Update `chart/values-dev.yaml` with new image tag in GitHub UI
4. ArgoCD detects change → OutOfSync
5. Click "Sync" in ArgoCD UI
6. Init container runs migrations
7. Django pod starts

### PROD (Semantic Versioning)
1. Create and push tag: `git tag -a v0.1.0 && git push origin v0.1.0`
2. GitHub Actions builds image with `v0.1.0` tag
3. Update `chart/values-prod.yaml` with new version
4. ArgoCD syncs
5. Migrations run → pods restart with new image

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| DEBUG | False | Django debug mode |
| SECRET_KEY | dev-secret-key-not-for-production | Django secret (should be set in production) |
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
  --repository-name minimal-django-poc \
  --region eu-central-1
```

### OIDC Setup (GitHub Actions)
See `docs/CICD.md` for detailed OIDC configuration.

## Troubleshooting

- **Init container fails**: Check logs with `kubectl describe pod -n dev minimal-django-poc-xxx`
- **Image not found in ECR**: Verify workflow completed successfully and ECR repository exists
- **Database connection error**: Check POSTGRES_* environment variables and pod logs

## Next Steps

- Push to GitHub
- Create EKS clusters (dev/prod)
- Configure AWS OIDC for GitHub Actions
- Create PostgreSQL databases on RDS
- Install ArgoCD and register applications
- Run first deployment
