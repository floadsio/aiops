# Velero Backup History Summary

This directory contains complete records of all backups and related resources from lernetz-test-begasoft-k8s cluster before cleanup on 2025-12-18.

## Files Included

- `all_backups.yaml` - Complete YAML of all Backup resources
- `backups_summary.txt` - Human-readable summary of all backups
- `backup_describe_*.txt` - Detailed description of each backup
- `datauploads.yaml` - All DataUpload resources
- `datauploads_summary.txt` - DataUpload summary
- `volumesnapshots.yaml` - All VolumeSnapshot resources
- `volumesnapshotcontents.yaml` - All VolumeSnapshotContent resources
- `velero_events.txt` - Cluster events from velero namespace
- `velero_logs_at_*_time.txt` - Velero server logs at time of each backup

## Key Findings Before Cleanup

1. **Test Backups Status**: Multiple test backups with varying success rates
2. **Root Cause**: Identified as Velero CSI plugin state synchronization issue (not ONTAP/Trident)
3. **Resolution**: Reducing dataMovers concurrency from 4 to 2
4. **Next Step**: Clean delete and re-test with reduced concurrency

## Investigation Details

See internal issue #705 for full investigation:
- Root cause analysis: ONTAP/Trident working correctly
- Issue identified: Velero backup stuck waiting for snapshot state updates
- Direct snapshot test: Successful (4 seconds to ready)
- Velero snapshot test: Stuck indefinitely
- Conclusion: Velero CSI plugin issue, not provider issue

