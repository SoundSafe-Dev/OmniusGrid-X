#!/bin/sh
# Backup-bucket immutability: create one correctly, or verify a live one (FS-811).
#
# WHAT THIS REPLACES. `docs/runbooks/database-backup-restore.md` said:
#
#     "Set a bucket lifecycle policy for retention (the job does not prune) and enable
#      versioning + object lock so a compromised key cannot erase history."
#
# One sentence, in a runbook, describing the control that decides whether an attacker who
# obtains the backup credentials can delete every backup you have. Nothing applied it and
# nothing checked it. That is the shape this whole sprint keeps finding, and it is worse here
# than usual: the failure is invisible until somebody is actively destroying your data.
#
# The threat is specific. `backup-credentials` holds an access key that can write to the
# bucket — so it can also overwrite and delete, unless the bucket forbids it. Versioning alone
# is not enough: a delete creates a marker and the old versions survive, but a holder of the
# key can still delete the versions themselves. **Object Lock in COMPLIANCE mode is what makes
# that impossible**, including for the account root, for the retention period.
#
# COMPLIANCE, NOT GOVERNANCE, and it is a real trade. GOVERNANCE mode can be bypassed by a
# principal holding `s3:BypassGovernanceRetention` — which is exactly the privilege an attacker
# who has compromised your account is likely to grant themselves. COMPLIANCE cannot be
# bypassed or shortened by anyone, which also means **a mistakenly locked object cannot be
# removed until its retention expires**, and you pay storage for it. 35 days is chosen to
# comfortably exceed the 24-hour backup cadence and the 30-day CNPG retention while keeping
# that cost bounded.
#
# USAGE
#     infrastructure/k8s/base/scripts/bucket-immutability.sh verify     # read-only check
#     infrastructure/k8s/base/scripts/bucket-immutability.sh bootstrap  # CREATE a new bucket
#
# It lives under base/scripts/ so the CronJob's configMapGenerator can read it: base is built
# without `--load-restrictor LoadRestrictionsNone`, which refuses a file above the
# kustomization. One copy in an odd place beats two that drift.
#
# Requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION, BACKUP_S3_BUCKET.
#
# `verify` is what the weekly `backup-immutability-check` CronJob runs, with the credentials
# the cluster already holds — so this is not a script anybody has to remember to run.

set -eu

: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET is not set}"
: "${AWS_DEFAULT_REGION:?AWS_DEFAULT_REGION is not set}"

B="$BACKUP_S3_BUCKET"
RETENTION_DAYS="${OBJECT_LOCK_RETENTION_DAYS:-35}"

fail() { echo "FAIL: $*" >&2; FAILED=1; }
FAILED=0

verify() {
    echo "verifying s3://$B"

    # 1. Versioning. Without it, an overwrite destroys the previous object outright and
    #    Object Lock cannot be enabled at all — it is the prerequisite, not an extra.
    V=$(aws s3api get-bucket-versioning --bucket "$B" --output text --query 'Status' 2>/dev/null || echo NONE)
    if [ "$V" = "Enabled" ]; then
        echo "  ok    versioning: Enabled"
    else
        fail "versioning is '$V'. An overwrite or delete destroys the object, and Object Lock cannot be enabled without it."
    fi

    # 2. Object Lock. This is the control that survives a compromised key.
    L=$(aws s3api get-object-lock-configuration --bucket "$B" --output text \
          --query 'ObjectLockConfiguration.ObjectLockEnabled' 2>/dev/null || echo NONE)
    if [ "$L" = "Enabled" ]; then
        M=$(aws s3api get-object-lock-configuration --bucket "$B" --output text \
              --query 'ObjectLockConfiguration.Rule.DefaultRetention.Mode' 2>/dev/null || echo NONE)
        D=$(aws s3api get-object-lock-configuration --bucket "$B" --output text \
              --query 'ObjectLockConfiguration.Rule.DefaultRetention.Days' 2>/dev/null || echo 0)
        echo "  ok    object lock: Enabled, mode=$M, days=$D"
        [ "$M" = "COMPLIANCE" ] || fail "object lock mode is '$M'. GOVERNANCE can be bypassed by a principal holding s3:BypassGovernanceRetention — which is what an attacker who has compromised the account grants themselves."
        [ "$D" -ge 2 ] 2>/dev/null || fail "default retention is $D days; anything under the backup cadence protects nothing."
    else
        fail "object lock is '$L'. A holder of the backup credentials can delete every backup, including old versions. Enabling it on an existing bucket needs versioning first and may require a new bucket depending on account/region — see bootstrap below."
    fi

    # 3. Public access. A backup bucket readable by the internet is a different incident with
    #    the same root cause: nobody checked.
    P=$(aws s3api get-public-access-block --bucket "$B" --output text \
          --query 'PublicAccessBlockConfiguration.BlockPublicAcls' 2>/dev/null || echo NONE)
    [ "$P" = "True" ] && echo "  ok    public access: blocked" || fail "public access block is '$P'."

    # 4. Encryption at rest. The upload passes --sse AES256 per object; a bucket default means
    #    an object written by any other path is covered too.
    E=$(aws s3api get-bucket-encryption --bucket "$B" --output text \
          --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' 2>/dev/null || echo NONE)
    [ "$E" != "NONE" ] && echo "  ok    default encryption: $E" || fail "no default bucket encryption."

    if [ "$FAILED" -ne 0 ]; then
        echo "" >&2
        echo "s3://$B is NOT immutable. A compromised backup credential can erase history." >&2
        echo "Run './bucket-immutability.sh bootstrap' against a NEW bucket and copy the" >&2
        echo "existing objects into it; see docs/runbooks/database-backup-restore.md." >&2
        exit 1
    fi
    echo "s3://$B is versioned, locked, private and encrypted."
}

bootstrap() {
    echo "creating s3://$B with object lock enabled"
    # Object Lock is enabled AT CREATION. AWS has since allowed turning it on for an existing
    # versioned bucket, but support varies by account and region — creating the bucket
    # correctly is the path that always works, and copying objects into it is cheap.
    if [ "$AWS_DEFAULT_REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$B" --object-lock-enabled-for-bucket
    else
        aws s3api create-bucket --bucket "$B" --object-lock-enabled-for-bucket \
            --create-bucket-configuration "LocationConstraint=$AWS_DEFAULT_REGION"
    fi
    aws s3api put-bucket-versioning --bucket "$B" \
        --versioning-configuration Status=Enabled
    aws s3api put-object-lock-configuration --bucket "$B" \
        --object-lock-configuration "{\"ObjectLockEnabled\":\"Enabled\",\"Rule\":{\"DefaultRetention\":{\"Mode\":\"COMPLIANCE\",\"Days\":$RETENTION_DAYS}}}"
    aws s3api put-public-access-block --bucket "$B" \
        --public-access-block-configuration \
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    aws s3api put-bucket-encryption --bucket "$B" \
        --server-side-encryption-configuration \
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
    # The backup job does not prune, so retention lives here. Noncurrent versions expire
    # AFTER the lock period — expiring them sooner would be refused by the lock anyway.
    aws s3api put-bucket-lifecycle-configuration --bucket "$B" \
        --lifecycle-configuration '{"Rules":[{
            "ID":"expire-old-backups","Status":"Enabled","Filter":{"Prefix":"postgres/"},
            "NoncurrentVersionExpiration":{"NoncurrentDays":90},
            "Expiration":{"Days":90}}]}'
    echo "created. verifying:"
    verify
}

case "${1:-verify}" in
    verify)    verify ;;
    bootstrap) bootstrap ;;
    *) echo "usage: $0 [verify|bootstrap]" >&2; exit 2 ;;
esac
