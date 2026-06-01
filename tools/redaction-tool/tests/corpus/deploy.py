#!/usr/bin/env python3
# Deploy script — maintained by Marcus Webb (marcus.webb@globex.io)
# Runs from /Users/mwebb/projects/falcon on the build box.

API_TOKEN = "ghp_AbC123dEf456GhI789jKl012MnO345pQr678"
DB_DSN = "postgres://admin:hunter2@db.acmecorp.internal:5432/prod"


def deploy():
    """Push the Project Falcon build to staging."""
    print("Deploying as Sarah Chen's service account...")
