# CI Scope v2 Gates rollback runbook

This is the Gates-local companion to the cross-repository rollback protocol in
`CI_SCOPE_V2_CROSS_REPOSITORY_PLAN.md`. It does not deploy, call GitHub or
Cloudflare, stop runners, or claim that an external rollback succeeded.

## Before activation

Validate the release manifest, caller workflow, and an evidence handoff created
by the release owner:

```sh
python3 scripts/release_enforcement.py \
  <release-manifest.json> \
  --environment production \
  --workflow <caller-workflow.yml> \
  --provenance <external-provenance.json>
```

The provenance file must contain independently obtained GitHub workflow SHA and
Cloudflare Worker deployment evidence. Do not replace it with the manifest,
shape-only values, the unresolved fixture, or a locally invented ID.

## Gates rollback

1. Stop new v2 claims and follow the cross-repository authority/fencing steps.
2. Reconcile active jobs and runners before changing workflow pins; quarantine
   anything with unresolved ownership.
3. Change the caller workflow `uses:` SHA and `gates-ref` to the last approved
   Gates commit. Keep both pins identical to the rollback manifest.
4. Re-run the local validator with the rollback manifest and fresh external
   provenance. Missing or unverifiable workflow/deployment evidence blocks the
   rollback release.
5. Publish the rollback manifest with actual repository SHAs, deployment ID,
   evidence IDs, routing generation, and rollback target.
6. Re-enable the previous routing generation only after the authority barrier is
   restored and the cross-repository owner confirms terminal evidence.

If Worker/DO or GitHub evidence is unavailable, mark rollback blocked or use an
explicitly approved break-glass procedure. A D1 snapshot, runner name, local
fixture, or successful structural test is not proof of external rollback.
