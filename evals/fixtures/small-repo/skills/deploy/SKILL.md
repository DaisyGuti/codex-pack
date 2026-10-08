---
name: deploy
description: Deploys the service.
---

# Deploy

Run `scripts/deploy.sh staging`, wait for the health check, then run it for production.
Roll back with `scripts/deploy.sh rollback` if the health check fails twice.
