---
name: image-supply-chain
description: "Use to scan a built container image for CVEs, make SBOMs, and plan or verify cosign signing, provenance and Binary Authorization. Dockerfile edits go to $dockerfile-harden; pipelines to $ci-harden."
---

# Image scanning, SBOMs, signing and registry controls

Produce evidence about one image, and draft the pipeline and cloud changes that make the
evidence repeatable. This skill reads and scans. It never pushes, signs, attests or changes
cloud state: those run in CI under the pipeline's own identity, or by a human running the
commands this skill drafts.

## Steps

1. **Pin the image.** Get a digest reference `registry/repo@sha256:...`. Resolve a tag with
   `docker buildx imagetools inspect IMAGE:TAG | awk '/^Digest:/ {print $2; exit}'`. Every
   later step uses the digest, because a tag can move.
2. **Collect evidence.** Run the bundled script (execute it, do not read it):

   ```sh
   sh ${CODEX_HOME:-~/.codex}/skills/image-supply-chain/scripts/image_evidence.sh --fail-on HIGH IMAGE@sha256:... ./evidence
   ```

   It runs trivy (or `--scanner grype`) and syft, writes `trivy.json`, `sbom.cdx.json` and
   `sbom.spdx.json`, and prints a summary with `scripts/summarize_evidence.py`. A missing tool stops it with the tool's name; tell
   the user which tool to install (links are in `references/scan-and-sbom.md`) and continue
   with the steps that do not need it.
3. **Read the findings** with `references/scan-and-sbom.md`: group by package, separate
   base-image fixes from dependency fixes, treat any secret in a layer as compromised.
4. **Check signing** when asked. Verify an existing signature against a pinned identity:

   ```sh
   sh ${CODEX_HOME:-~/.codex}/skills/image-supply-chain/scripts/verify_image.sh --host github --identity "<full signer identity>" --attestation cyclonedx IMAGE@sha256:...
   ```

   Identities, issuers and the signing options are in `references/sign-and-attest.md`. Ask the
   user for the exact repository and workflow path. Do not guess an identity or use a wildcard.
5. **Draft, never apply**, anything that changes a registry, a project or production:
   Artifact Registry repository and IAM commands (`references/artifact-registry.md`),
   Binary Authorization policy and attestors (`references/binary-authorization.md`), and the
   pipeline stages (the reference pipelines are in `${CODEX_HOME:-~/.codex}/skills/ci-harden/templates/`).
   Show each command with the placeholders named, and wait for the user to run it.
6. **Report** under these headings: *Found* (counts, the worst findings, what the SBOMs
   hold), *Drafted* (commands and pipeline changes awaiting the user), *Not checked* (tools
   missing, signing not verified, cloud settings not read).

## Decisions to put to the user

- **Rekor visibility.** Keyless signatures are recorded in Sigstore's public transparency log,
  and the signing identity contains the repository path. A private government repository may
  not want that. The alternative is signing with a Cloud KMS key. Explain both and let the user
  pick; `references/sign-and-attest.md` has the table.
- **Which enforcement path** on GCP: Binary Authorization with a KMS-backed attestor, its
  Sigstore signature check, or an in-cluster keyless policy controller. Binary Authorization
  does not verify keyless identities itself. `references/binary-authorization.md` has the
  comparison.
- **Scan gate.** The severity that fails a build, and whether unfixed vulnerabilities count.
  Recommend a gate and record it; the team decides.

## Rules

- Evidence only. Never write that an image is secure, compliant, FIPS-validated or authorized.
  A person with the authority decides; this skill supplies the inputs.
- Quote a SLSA level only when the platform's own documentation states it for the setup in
  use, and give the source. The references say what each platform documents.
- Fetch fast-moving facts at run time: tool versions, action versions and pins, Binary
  Authorization check types, GitHub plan requirements for attestations. The references list
  their sources and the date they were read.
- Secrets never enter a prompt or a file. Registry credentials come from the environment's
  existing login or Workload Identity Federation.

## Related skills

- Source code, dependency and secret scans of the repository: `$security-scan`.
- Mapping this evidence to FedRAMP, SSDF or CMMC controls: `$compliance-map`.
- Editing the Dockerfile: `$dockerfile-harden`. Writing the pipeline that runs these steps: `$ci-harden`.
- Reviewing the GCP project that holds the registry: `$gcp-review`.

## Tools

`trivy` or `grype`, `syft`, `cosign`, `docker` with buildx, `gcloud`, `python3` 3.11+. Check
each with `command -v <tool>`; the scripts print the missing tool's name. All the scanners
and signers listed are free and open source.

## References

- `references/scan-and-sbom.md`: scanning, SBOM formats, reading results.
- `references/sign-and-attest.md`: signing options, identities, attestations, SLSA on GitHub and GitLab.
- `references/artifact-registry.md`: repository setup, authentication, immutable tags.
- `references/binary-authorization.md`: enforcement paths and rollout order.
