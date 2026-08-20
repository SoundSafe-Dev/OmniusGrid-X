# FS-821 (continued). BASE IMAGES ARE DIGEST-PINNED.
#
# Every FROM in this repository named an image with no digest, and three of them named it
# with NO TAG EITHER — which resolves to `:latest`. So two builds of the same release could
# be built on different base images, and "rebuild last month's release" was not a thing that
# could be done.
#
# The k8s manifests were pinned first; Dockerfiles are the other half of the same supply
# chain, and the half that decides what is IN the image rather than which image runs.
#
# Measured 2026-08-20 with trivy against this base: 6,139 vulnerabilities, of which 0
# CRITICAL and 193 HIGH (102 with a published fix). That is why the image gate in
# ci-cd.yml blocks on CRITICAL rather than HIGH — at HIGH it would fail on the first run,
# on findings whose fix is a Red Hat base-image bump we do not control the cadence of.
#
# PINNING WITHOUT A BUMP PROCESS TRADES ONE PROBLEM FOR ANOTHER: floating and
# unreproducible becomes frozen and stale. `.github/workflows/nightly-e2e.yml` runs
# `check_base_images_are_current.py`, which compares each digest below against what the tag
# resolves to today and fails when one has drifted — so the pin is deliberate and its
# staleness is visible.
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Expose port
EXPOSE 3000

# Start development server
CMD ["npm", "run", "dev"]
