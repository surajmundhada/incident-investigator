# Deployment timing and causal investigation

## Timing is not causation

An error beginning near a deployment is a useful lead, not proof of a regression. Compare affected and unaffected services, request IDs, signatures, and observations before and after the change. Determine whether the deployed component is on the failing dependency path.

## Missing deployment history

This release has no deployment-history tool. If deployment events cannot be observed, state that limitation instead of inventing a timeline. A user's description of a change should be distinguished from independently collected deployment evidence.

## Applicability of guidance

Use guidance for the correct environment and release. Older architecture may describe dependencies that no longer exist. Cite the document revision and preserve the observation window. Relevant documentation suggests checks but cannot establish that a particular change caused this incident.

