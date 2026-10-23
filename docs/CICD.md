# CI/CD Guide

Setup, deployment flow, and troubleshooting for GitHub Actions, AWS (OIDC, ECR, EKS), and ArgoCD.

## Pipeline Overview

| Workflow | Trigger | Output |
|----------|---------|--------|
| `.github/workflows/ci.yaml` | Pull requests, pushes to `main` | Tests, then image `sha-<8 chars>` and `latest` pushed to ECR |
| `.github/workflows/release.yaml` | Tags matching `v[0-9]+.[0-9]+.[0-9]+*` | Tests, then image `<tag>` and `latest` pushed to ECR |

Known behavior: `ci.yaml` also builds and pushes on pull requests, and every run overwrites `latest`. Do not deploy from `latest`.

Environments:

| Environment | Namespace | ArgoCD Application | Image pin |
|-------------|-----------|--------------------|-----------|
| DEV | `dev` | `minimal-django-poc-dev` | `django.tag` in `chart/values-dev.yaml` |
| PROD | `prod` | `minimal-django-poc-prod` | `django.tag` in `chart/values-prod.yaml` |

Both Applications track `HEAD` of `main` and use manual sync.

## Setup

### 1. AWS account

- ECR repository (one-time):

  ```bash
  aws ecr create-repository \
    --repository-name skillregistry-poc/minimal-django-poc \
    --region eu-central-1
  ```

- GitHub OIDC identity provider: `token.actions.githubusercontent.com`.
- IAM role `github-actions` with ECR push permissions on `skillregistry-poc/minimal-django-poc`.

### 2. IAM trust policy for `github-actions`

The trust policy needs one `sub` entry per ref type that runs a workflow:

| Trigger | `sub` value |
|---------|-------------|
| Push to `main` (CI) | `repo:alois-chinyoka@307075542/minimal-django-poc@1429493341:ref:refs/heads/main` |
| Tag push (release) | `repo:alois-chinyoka@307075542/minimal-django-poc@1429493341:ref:refs/tags/v*` |

Use the numeric owner and repo IDs, as in the existing entries. Also set `aud` to `sts.amazonaws.com`. Add a new entry for each new trigger type; a tag entry does not cover branches.

### 3. GitHub repository secrets

| Secret | Value |
|--------|-------|
| `AWS_ROLE_TO_ASSUME` | ARN of the `github-actions` role |
| `DJANGO_TEST_SECRET_KEY` | Any random string, used only by test runs |

Both workflows map `DJANGO_TEST_SECRET_KEY` to `SECRET_KEY`. The Django settings have no default, so the variable must be set in every job that runs `manage.py`.

### 4. EKS

- Cluster: `minimal-django-poc`, region `eu-central-1`.
- Namespaces: `dev` and `prod`. ArgoCD creates them through `CreateNamespace=true`.

### 5. ArgoCD

Install ArgoCD in the `argocd` namespace, then apply the project and the Applications:

```bash
kubectl apply -f argocd/appproject.yaml
kubectl apply -f argocd/application-dev.yaml
kubectl apply -f argocd/application-prod.yaml
```

Open the UI locally:

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

### 6. Prod Secret and Postgres

The Secret is not managed by the chart. Create it once per namespace:

```bash
kubectl -n prod create secret generic django-secret \
  --from-literal=postgres-password='<password>' \
  --from-literal=secret-key='<django-secret-key>'
```

ArgoCD creates Postgres from the chart (`postgres:16` StatefulSet, 1Gi PVC, Service `postgres`, database from values). Before the first sync, delete any manually applied Postgres objects in the namespace. ArgoCD does not manage them, and deleting them removes their data.

Every key that a Secret reference uses must exist in the Secret.

## Deployment Flow

### DEV (trunk-based)

1. Merge to `main`. CI builds and pushes `sha-<commit:8>` to ECR.
2. Set `django.tag` in `chart/values-dev.yaml` to the new `sha-` tag. Commit and push to `main`.
3. In ArgoCD, refresh and sync `minimal-django-poc-dev`.
4. ArgoCD applies Postgres (wave -1), then runs the `minimal-django-poc-migrate` Job (wave 0), then rolls out the Deployment (wave 1). A failed migration stops the sync.

### PROD (semantic versioning)

1. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

   The release workflow runs tests and pushes `v0.1.0` and `latest` to ECR.

2. Set `django.tag` in `chart/values-prod.yaml` to `v0.1.0`. Commit and push to `main`. Prod changes only when this commit lands, because ArgoCD tracks `HEAD`.

3. Sync and wait for health:

   ```bash
   argocd app sync minimal-django-poc-prod
   argocd app wait minimal-django-poc-prod --health
   ```

4. Verify:

   ```bash
   kubectl -n prod get deploy minimal-django-poc \
     -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'   # expect :v0.1.0

   kubectl -n prod port-forward svc/minimal-django-poc 8081:80 &
   curl -i http://localhost:8081/health/      # expect 200 {"status": "healthy"}
   curl -i http://localhost:8081/api/tasks/   # expect 200 {"tasks": [...]}
   ```

### Rollback (PROD)

1. Set `django.tag` in `chart/values-prod.yaml` to the previous tag. Commit and push to `main`.
2. Sync and wait for health, as in step 3 above.

Schema changes are not rolled back by this. See Known Gaps.

## Migration History

How migrations ran, and why each change was made.

| Stage | Where it ran | Problem |
|-------|--------------|---------|
| 1. Init container | `django-migrate` init container in every Deployment pod | Each replica ran `migrate`. With `replicas: 2`, two pods raced on the same schema. Migrations also ran on every pod restart. |
| 2. PreSync Job | `minimal-django-poc-migrate` as an ArgoCD `PreSync` hook | Ran once per sync, and a failure stopped the rollout. PreSync runs before any other resource, so on a fresh namespace the Job ran before Postgres existed and failed. |
| 3. Sync waves (current) | Postgres at wave -1, Job as `Sync` hook at wave 0, Deployment at wave 1 | Postgres is healthy before the migration starts, and the migration finishes before new pods start. |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `decouple.UndefinedValueError: SECRET_KEY not found` | `SECRET_KEY` missing in the job environment | Add the `DJANGO_TEST_SECRET_KEY` repo secret and map it to `SECRET_KEY` in the workflow |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy has no `sub` for this ref | Add the matching `refs/heads/main` or `refs/tags/v*` entry (see Setup, step 2) |
| ArgoCD renders `:latest` | Live Application has inline `helm.values`, or lost `valueFiles` | Run `kubectl -n argocd get application minimal-django-poc-prod -o yaml`. Remove inline values, then re-apply `argocd/application-prod.yaml` |
| ArgoCD shows OutOfSync after a tag push | `values-prod.yaml` not committed to `main` | Commit and push the `django.tag` change |
| Pod stuck in `CreateContainerConfigError` | Secret or key missing in the namespace | Check `kubectl -n prod describe pod <pod>`. Create the Secret with both keys |
| Sync fails at migrate Job | Migration failed | Run `kubectl -n prod logs job/minimal-django-poc-migrate` |
| Database connection error | `postgres.*` values or Postgres pod wrong | Check `chart/values-*.yaml` and `kubectl -n prod get pods` |
| Image pull error from ECR | Tag not pushed, or workflow failed | Check the Actions run and `aws ecr describe-images --repository-name skillregistry-poc/minimal-django-poc` |

## Known Gaps

- Postgres has a PVC but no backups. Add backups or move to RDS.
- Rolling updates overlap old and new pods. Use expand/contract migrations: add columns first, drop old ones in a later release.
- `ci.yaml` pushes images on pull requests and overwrites `latest`.
