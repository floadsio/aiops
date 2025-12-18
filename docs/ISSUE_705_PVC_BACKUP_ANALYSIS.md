# Issue #705: PVC Backup Coverage Analysis - Phase 2 Test Results

## Executive Summary

Phase 2 conservative backup test revealed that **only 14 out of 39 PVCs received CSI snapshots/Kopia data uploads**, despite all 39 PVCs being eligible for backup based on the namespace configuration.

**Root Cause:** All 39 PVCs in the cluster use the `standard` storage class, which has `snapshots=none` parameter, meaning **CSI snapshots are not supported** for any volume in this cluster.

## Critical Findings

### Storage Class Configuration

**All 39 PVCs use: `standard` storage class**

```yaml
# standard storage class (does NOT support snapshots)
provisioner: csi.trident.netapp.io
parameters:
  backendType: ontap-nas
  fsType: nfs
  selector: snapshots=none  # <-- CSI snapshots disabled
```

**Available but unused:**
- `standard-snapshot`: Same provisioner with `snapshots=3d` (CSI snapshots enabled)
- `rwx-standard-snapshot`: RWX variant with `snapshots=3d`

### Backup Configuration

**Test Backup:** `test-full-cluster-phase2-1766027289`
- **Time:** 2025-12-18 03:08:09 - 03:22:23 UTC (14 minutes 14 seconds)
- **Phase:** Completed successfully
- **Items backed up:** 8,981/8,981 (100%)
- **Errors:** 0
- **Warnings:** 1
- **BackupItemOperations:** 14 attempted, 14 completed

**Configuration Settings:**
```yaml
snapshotVolumes: true
snapshotMoveData: true
defaultVolumesToFsBackup: true  # <-- Filesystem fallback enabled
```

### PVC Backup Coverage

**14 PVCs WITH DataUploads (Kopia filesystem backups):**
1. swisspeace/gender-elearning-v2
2. srk/rassismus-v2
3. lernetz/website
4. phbern/brennpunkt-landschaft-de
5. verlagskv/brennpunkt-wug
6. phbern/brennpunkt-landschaft-fr
7. lernetz/lernetz-schule-v2
8. lernetz/tasker
9. haldimann/kp-remake-v2
10. ssb/verhaltenskodex
11. phbern/brennpunkt-landschaft-it
12. swissvolley/escoresheet-v2
13. swisspeace/conflict-sensitivity-v2
14. luzern/luzern-nmg-test

**25 PVCs WITHOUT DataUploads/CSI snapshots:**

**Intentionally Excluded (8 PVCs - begasoft-* pattern):**
- begasoft-hosting-assets/api
- begasoft-hosting-keycloak/postgres-18-data
- begasoft-hosting-meilisearch/meilisearch-data
- begasoft-hosting-mongo/begasoft-hosting-mongo-volume-mongo-0
- begasoft-hosting-mongo/begasoft-hosting-mongo-volume-mongo-1
- begasoft-hosting-mongo/begasoft-hosting-mongo-volume-mongo-2
- begasoft-hosting-mysql/mysql
- begasoft-hosting-postgres/postgres-18-data

**Not Backed Up (17 PVCs - no DataUploads, should be included):**
- bafu/luftlabor-fr-v2
- bafu/luftlabor-it-v2
- bafu/luftlabor-v2
- berufscockpit-base/nextcloud
- cerebral/hilfsangebote-v2
- csi-snapshot-controller/cache-volume-snapshot-controller-0
- csi-snapshot-controller/cache-volume-snapshot-controller-1
- csi-snapshot-controller/cache-volume-snapshot-controller-2
- funvo/trainingsplaner-unihockey
- funvo/trainingsplaner-volleyball
- postfinance-moneyfit/moneyfit-2023-logs
- swiss-olympic/nextcloud
- tobias-friedli/sjo-eventmanager
- vbv/vbv-kursverwaltung-test
- zebis-oer/meilisearch-data
- zebis-oer-review/meilisearch-data-feature-ki-chatbot
- zebis-oer-review/meilisearch-data-master

## Why Only 14 PVCs Have DataUploads?

This is currently **UNEXPLAINED**. Possible explanations:

1. **Selective Volume Selection:** Velero may be filtering which volumes to back up based on criteria we haven't identified yet
2. **Storage Backend Limitations:** The ONTAP backend or Trident may be limiting concurrent operations
3. **Resource Constraints:** With Phase 2 conservative settings (loadConcurrency: 2), perhaps only 14 volumes are being selected
4. **Configuration Bug:** There may be a configuration issue causing Velero to skip certain PVCs
5. **Intentional Filtering:** Some PVCs might be excluded by labels or annotations we haven't checked

## Investigation Status

### What We Know ✅
- All 39 PVCs use `standard` storage class
- `standard` has `snapshots=none` (no CSI snapshot support)
- 14 DataUploads were created (Kopia filesystem backups)
- All 14 DataUploads completed successfully
- Backup completed with 0 errors
- 8,981 Kubernetes resource items backed up

### What We Don't Know ❓
- **Why only 14 PVCs were selected for DataUpload** (out of 39 eligible ones)
- Whether the other 25 PVCs are being backed up via filesystem fallback without DataUploads
- If there's filtering logic based on PVC size, labels, or annotations
- Whether this is expected behavior or a configuration issue

## Next Steps

### Immediate Investigation Required

1. **Check if 25 PVCs have filesystem backups without DataUploads**
   - Query the backup manifest to see if all volumes were included
   - Check if there are other backup mechanisms besides DataUploads

2. **Analyze PVC selection criteria**
   - Check if selected PVCs have common labels/annotations
   - Check if unselected PVCs have exclusion labels
   - Compare PVC sizes and volume types

3. **Review Velero logs**
   - Look for volume discovery and selection messages
   - Check for warnings or errors about skipped volumes

4. **Check storage class impact**
   - Verify if `snapshots=none` affects Velero's volume selection
   - Test if migrating PVCs to `standard-snapshot` changes behavior

### Potential Solutions

**Option A: Verify Full Coverage**
- Confirm all 39 PVCs (minus intentionally excluded begasoft-*) ARE backed up
- If yes, this is expected behavior and no action needed

**Option B: Migrate to Snapshot-Enabled Storage Class**
- Migrate PVCs from `standard` to `standard-snapshot`
- This would enable true CSI snapshot backups instead of filesystem fallback
- May improve backup performance and reliability

**Option C: Investigate and Fix Selection Logic**
- If only 14 should be backed up, document why in backup spec
- If all 31 should be backed up, identify and fix the filtering issue

## Recommendations

1. **Verify Data Integrity:** Check if the 25 PVCs without DataUploads are still being backed up through other mechanisms
2. **Document Behavior:** Once verified, document the expected PVC backup coverage in runbooks
3. **Consider Storage Class Migration:** If filesystem fallback is being used instead of CSI snapshots, consider migrating to `standard-snapshot` for better performance
4. **Monitor:** Track backup coverage in future backups to ensure it remains consistent

## References

- Test Backup: `test-full-cluster-phase2-1766027289`
- Cluster: `lernetz-test-begasoft-k8s`
- Phase 2 Configuration: Conservative settings with itemBlockWorkerCount: 2
- Backup Duration: 14 minutes 14 seconds
