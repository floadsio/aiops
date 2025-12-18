# Issue #705 - Velero Backup History & Investigation Results

**Date:** 2025-12-18  
**Cluster:** lernetz-test-begasoft-k8s  
**Status:** Root cause identified, proceeding with fix

## Investigation Summary

### Root Cause
**NOT a provider (ONTAP/Trident) issue**

The backup process was stuck due to **Velero CSI plugin state synchronization issue**, not storage layer problems.

**Evidence:**
- Direct VolumeSnapshot creation (without Velero): ✅ Succeeds in 4 seconds
- Velero-created VolumeSnapshot: ✅ Successfully created, but Velero doesn't detect completion
- Trident backend: ✅ Status = Success, Phase = Bound
- ONTAP storage: ✅ Responding normally

### Solution Implemented
- Reduced `dataMovers.velero.concurrency` from 4 to 2
- This reduces concurrency stress on Velero's snapshot state management

## Files in This Directory

### Backup Resources (Pre-cleanup)
- `all_backups.yaml` - Complete YAML of all Backup resources
- `backups_summary.txt` - Summary table of all backups
- `datauploads.yaml` - All DataUpload resources (59KB)
- `volumesnapshots.yaml` - All VolumeSnapshot resources
- `volumesnapshotcontents.yaml` - All VolumeSnapshotContent resources

### Analysis
- `BACKUP_HISTORY_SUMMARY.md` - High-level summary of backup history

## Test Results (Before Fix)

### Successful Backups
- Direct snapshot creation (no Velero): **PASS** - 4 seconds to ready
- Flow cluster backups: **PASS** - Working normally
- Individual backup phases: Some completed, but process stuck overall

### Failed/Stuck Backups
- test-2a-cerebral-single: Stuck after snapshot created, waiting indefinitely
- test-phase2-concurrency4-*: Stuck at 12/31 PVCs during full cluster attempt
- Earlier tests: Stuck at 8/10,284 items in discovery phase

## Key Timeline

| Time | Event |
|------|-------|
| 2025-12-18 08:00 | Investigation started |
| 2025-12-18 10:30 | Root cause identified as Velero CSI plugin issue |
| 2025-12-18 11:25 | Direct snapshot test proves ONTAP/Trident working |
| 2025-12-18 11:30 | Backup history saved before cleanup |
| 2025-12-18 11:35+ | Proceeding with concurrency reduction and re-test |

## Next Steps

1. Delete all old backups from cluster
2. Reduce concurrency to 2 in Velero config (via GitOps)
3. Test single namespace backup
4. If successful, test full cluster backup
5. Monitor 5 production backups for stability

## References

- **Investigation file:** This directory
- **Issue tracker:** Internal issue #705
- **Configuration:** `/home/michael/workspace/lnz/k8s-infra/clusters/lernetz-stage-begasoft-k8s/manifests/velero/`

