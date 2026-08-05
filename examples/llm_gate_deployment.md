# Staged deployment procedure

Deploy the candidate to a shadow environment before canary traffic.

## Preconditions

The rollback target and health threshold must be recorded before deployment.

## Failure handling

Rollback when the safety error rate exceeds the approved threshold.
