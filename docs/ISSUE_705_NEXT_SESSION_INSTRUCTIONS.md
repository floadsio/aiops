# Issue #705: Next Session Instructions

**Current Status:** Phase 2 Conservative testing paused
**Last Session:** 2025-12-18 12:00 UTC
**Tests Completed:** Single namespace ✅, 3-namespace ✅
**Tests Pending:** 6-namespace ⏳, Full cluster ⏳

---

## Critical Information for Next Session

### 1. 3-Namespace Test Warning Analysis

**Test Name:** `test-3ns-final-1766059374`

The 3-namespace test **PASSED successfully** (phase: Completed, all 3 DataUploads created).

However, we need to investigate potential warnings that may have occurred during the test:

**To Check in Next Session:**
```bash
# Get fresh token
curl -s -X POST \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password&client_id=kubernetes&username=mturko&password=8G26laIySSqzfD" \
  https://auth.sso.paas.begasoft.ch/realms/b82ud9/protocol/openid-connect/token | \
  grep -o '"access_token":"[^"]*' | cut -d'"' -f4 > /tmp/token_begasoft.txt

TOKEN=$(cat /tmp/token_begasoft.txt)

# Check backup description for warnings
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify \
  describe backup test-3ns-final-1766059374 -n velero | grep -A 50 "Status:"

# Check Velero logs around the test time (11:57-12:04 UTC)
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify \
  logs -n velero deployment/velero --tail=200 | grep -E "(test-3ns-final|WARNING|ERROR|PartiallyFailed)"
```

**Expected Outcome:**
- Backup phase should be "Completed"
- Warnings section may contain ONTAP snapshot retry messages (normal)
- No errors about DataUploads or state synchronization

**If Warnings Found:**
- Document them in issue tracking
- Assess if they impact backup reliability
- Proceed with 6-namespace test unless warnings indicate failure

---

### 2. Immediate Action: 6-Namespace Test

**Run this in next session:**

```bash
# Step 1: Ensure cluster is clean (if needed)
bash /tmp/full_reset_velero.sh

# Step 2: Create 6-namespace test
cat > /tmp/test_6ns_v2.sh << 'SCRIPT'
#!/bin/bash
TOKEN=$(cat /tmp/token_begasoft.txt)

BACKUP_NAME="test-6ns-final-$(date +%s)"

cat > /tmp/backup_6ns_v2.yaml <<YAML
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: $BACKUP_NAME
  namespace: velero
spec:
  includedNamespaces:
  - cerebral
  - funvo
  - trident
  - haldimann-default
  - postfinance-moneyfit-default
  - zebis-oer-default
  snapshotVolumes: true
  snapshotMoveData: true
  csiSnapshotTimeout: 1h
  ttl: 24h
YAML

echo "Creating backup: $BACKUP_NAME"
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify apply -f /tmp/backup_6ns_v2.yaml

echo ""
echo "=== Monitoring (allow up to 10 minutes) ==="
START=$(date +%s)
for i in {1..40}; do
  ELAPSED=$(($(date +%s) - START))
  STATUS=$(kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get backup "$BACKUP_NAME" -n velero -o jsonpath='{.status.phase}' 2>/dev/null || echo "NEW")
  ITEMS=$(kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get backup "$BACKUP_NAME" -n velero -o jsonpath='{.status.progress.itemsBackedUp}' 2>/dev/null || echo "0")
  TOTAL=$(kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get backup "$BACKUP_NAME" -n velero -o jsonpath='{.status.progress.totalItems}' 2>/dev/null || echo "?")
  DUS=$(kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get datauploads -n velero -l velero.io/backup-name="$BACKUP_NAME" --no-headers 2>&1 | wc -l)

  printf "[%2d] %3ds | Phase: %-25s | Items: %6s/%-6s | DUs: %2d\n" $i $ELAPSED "$STATUS" "$ITEMS" "$TOTAL" "$DUS"

  if [ "$STATUS" = "Completed" ] || [ "$STATUS" = "Failed" ] || [ "$STATUS" = "PartiallyFailed" ]; then
    echo ""
    echo "✅ Backup $STATUS"
    break
  fi

  sleep 15
done

echo ""
echo "BACKUP_NAME=$BACKUP_NAME" >> /tmp/last_test.txt
SCRIPT

chmod +x /tmp/test_6ns_v2.sh
bash /tmp/test_6ns_v2.sh
```

**Expected Results:**
- **Phase:** Completed (✅ success) or PartiallyFailed (⚠️ warning)
- **Items:** Should see 1000-1200 items total (6 namespaces)
- **DataUploads:** Should create 6 (one per PVC)
- **Duration:** 300-400 seconds (5-7 minutes)
- **Status:** All DataUploads should be "Completed"

**Success Criteria:**
- ✅ All 6 DataUploads created
- ✅ Phase is "Completed" or "PartiallyFailed" (not stuck in "InProgress")
- ✅ No API rate limiting errors in Velero logs
- ✅ No "rate: Wait(n=1) would exceed context deadline" messages

**If Test Fails:**
- Check Velero logs immediately
- Document error messages
- Consider reducing namespaces to 4 before attempting full cluster backup

---

### 3. If 6-Namespace Test Passes: Full Cluster Backup

**Only proceed if 6-namespace test completes successfully.**

```bash
# Create full cluster backup (31 PVCs)
cat > /tmp/test_full_cluster_v2.sh << 'SCRIPT'
#!/bin/bash
TOKEN=$(cat /tmp/token_begasoft.txt)

BACKUP_NAME="test-full-cluster-final-$(date +%s)"

cat > /tmp/backup_full_v2.yaml <<YAML
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: $BACKUP_NAME
  namespace: velero
spec:
  includedNamespaces:
  - '*'
  excludedNamespaces:
  - velero
  - kube-system
  - kube-public
  - kube-node-lease
  - begasoft-*
  snapshotVolumes: true
  snapshotMoveData: true
  csiSnapshotTimeout: 1h
  ttl: 24h
YAML

echo "Creating full cluster backup: $BACKUP_NAME"
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify apply -f /tmp/backup_full_v2.yaml

echo ""
echo "=== Monitoring (allow up to 4 hours) ==="
START=$(date +%s)
LAST_UPDATE=$START
for i in {1..960}; do  # 960 * 15s = 14400s = 4 hours
  ELAPSED=$(($(date +%s) - START))
  STATUS=$(kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get backup "$BACKUP_NAME" -n velero -o jsonpath='{.status.phase}' 2>/dev/null || echo "UNKNOWN")
  ITEMS=$(kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get backup "$BACKUP_NAME" -n velero -o jsonpath='{.status.progress.itemsBackedUp}' 2>/dev/null || echo "0")
  TOTAL=$(kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get backup "$BACKUP_NAME" -n velero -o jsonpath='{.status.progress.totalItems}' 2>/dev/null || echo "?")
  DUS=$(kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get datauploads -n velero -l velero.io/backup-name="$BACKUP_NAME" --no-headers 2>&1 | wc -l)

  # Print update every minute (4 iterations)
  NOW=$(date +%s)
  if [ $((NOW - LAST_UPDATE)) -ge 60 ]; then
    printf "[%4d] %4ds | Phase: %-25s | Items: %6s/%-6s | DUs: %2d\n" $i $ELAPSED "$STATUS" "$ITEMS" "$TOTAL" "$DUS"
    LAST_UPDATE=$NOW
  fi

  if [ "$STATUS" = "Completed" ] || [ "$STATUS" = "Failed" ] || [ "$STATUS" = "PartiallyFailed" ]; then
    FINAL=$(($(date +%s) - START))
    echo ""
    echo "✅ Backup $STATUS in $((FINAL / 60))m $((FINAL % 60))s"
    echo "BACKUP_NAME=$BACKUP_NAME" >> /tmp/last_test.txt
    break
  fi

  sleep 15
done
SCRIPT

chmod +x /tmp/test_full_cluster_v2.sh
bash /tmp/test_full_cluster_v2.sh
```

**Expected Results:**
- **Duration:** 2-4 hours depending on cluster load
- **Items:** ~10,000 Kubernetes objects
- **DataUploads:** 31 (one per eligible PVC)
- **Phase:** Completed (success) or PartiallyFailed (with errors listed)

---

## Cluster State Management for Next Session

### Before Starting Tests

1. **Verify cluster is clean:**
```bash
TOKEN=$(cat /tmp/token_begasoft.txt)
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get backups -n velero
# Should return: No resources found in velero namespace
```

2. **Verify Velero is ready:**
```bash
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get pods -n velero -l app.kubernetes.io/name=velero
# Should show: velero pod in Running state (READY 1/1)
```

3. **If not clean, run cleanup:**
```bash
bash /tmp/full_reset_velero.sh
```

### Important: Avoid Previous Mistakes

- ❌ **Don't use aggressive cleanup during active backups** - it causes Velero to re-sync from S3
- ✅ **Let Velero garbage collect naturally** - delete old backups after they expire
- ✅ **If immediate cleanup needed:** Delete from both cluster AND S3 storage location, then restart Velero
- ✅ **Monitor API server rate limiting** - if seen, restart Velero immediately

---

## Monitoring & Metrics

### During Full Cluster Backup: Run Grafana Diagnostics

```bash
# Terminal 1: Monitor Velero logs
TOKEN=$(cat /tmp/token_begasoft.txt)
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify logs -n velero deployment/velero -f

# Terminal 2: Monitor DataUploads progress
watch "kubectl --token=\"\$TOKEN\" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify get datauploads -n velero | tail -20"

# Terminal 3: Monitor cluster node memory (if metrics API available)
watch "kubectl --token=\"\$TOKEN\" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify top nodes"
```

### Document Observations

- Node memory peaks and dips
- DataUpload creation rate
- Any API rate limiting messages
- Overall backup progression

---

## Quick Reference: File Locations

**Test Scripts:**
- `/tmp/test_6ns_v2.sh` - 6-namespace test (create fresh)
- `/tmp/test_full_cluster_v2.sh` - Full cluster test (create fresh)
- `/tmp/full_reset_velero.sh` - Cleanup script (ready to use)

**Token Management:**
- `/tmp/token_begasoft.txt` - Current OIDC token (refresh if Unauthorized errors)

**Last Test Info:**
- `/tmp/last_test.txt` - Backup name from last test (useful for checking status)

**Configuration:**
- `/home/michael/workspace/lnz/k8s-infra/clusters/lernetz-stage-begasoft-k8s/manifests/velero/kustomization.yaml` - Deployed config (concurrency=2)

---

## Decision Tree for Next Session

```
START
  ↓
Check 3-namespace warnings? → Document if any
  ↓
Run 6-namespace test
  ├─ PASS (Completed with 6 DataUploads)
  │   ↓
  │   Run full cluster backup (31 PVCs)
  │   ├─ PASS → Document results, SUCCESS
  │   └─ FAIL → Investigate, adjust config, retest
  │
  └─ FAIL (API rate limiting or other errors)
      ↓
      Restart Velero, check logs, try again
      ├─ PASS on retry → Proceed to full cluster
      └─ FAIL again → Reduce concurrency to 1, investigate root cause
```

---

## Success Criteria for Phase 2

✅ **Must Have (for Phase 2 to be successful):**
1. Single namespace backup: Completed ✅
2. Three namespace backup: Completed ✅
3. Six namespace backup: Must complete
4. Full cluster backup: Must complete with all 31 DataUploads created
5. Zero backup hangs (no stuck "InProgress" phases)

⚠️ **Nice to Have (for optimization):**
1. Document warning messages and their causes
2. Gather metrics on backup performance
3. Analyze cluster memory pressure during backup
4. Verify backup completion speed is acceptable (2-4 hours for 31 PVCs)

---

**Document Status:** Ready for next session
**Last Updated:** 2025-12-18 12:00 UTC
**Configuration Deployed:** concurrency=2 via commit 15b4c09
**Next Action:** Run 6-namespace test, then full cluster backup
