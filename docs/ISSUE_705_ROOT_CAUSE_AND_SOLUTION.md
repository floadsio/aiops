# Issue #705: Root Cause Analysis and Solution for PVC Backup Coverage

## Executive Summary

**Root Cause Identified:** Only 14 out of 39 PVCs are being backed up because those 14 PVCs are **NOT mounted by any running pods**. The other 25 PVCs are actively mounted by running pods, which prevents Velero's data mover (with `snapshotMoveData: true`) from backing them up.

**Impact:** 64% of cluster PVCs (25 out of 39) are NOT being backed up in the current configuration.

**Solution:** Either (A) use `snapshotMoveData: false` to enable CSI snapshots for mounted volumes, or (B) implement pod-volume backup using Velero node-agent for in-use volumes.

---

## Detailed Root Cause Analysis

### Discovery Process

During Phase 2 conservative backup testing, we discovered:

| Category | Count | Description |
|----------|-------|-------------|
| **PVCs WITH DataUploads** | 14 | Successfully backed up |
| **PVCs WITHOUT DataUploads** | 8 | Intentionally excluded (begasoft-* namespaces) |
| **PVCs WITHOUT DataUploads** | 17 | Should be backed up but weren't |
| **Total PVCs in cluster** | 39 | |

### Critical Finding: Pod Mount Status

When analyzing the PVC backup pattern, we discovered **100% correlation** between pod mount status and backup success:

**ALL 14 backed-up PVCs: NOT mounted by any pods**
- swisspeace/gender-elearning-v2: 0 pods
- srk/rassismus-v2: 0 pods
- lernetz/website: 0 pods
- phbern/brennpunkt-landschaft-de: 0 pods
- verlagskv/brennpunkt-wug: 0 pods
- phbern/brennpunkt-landschaft-fr: 0 pods
- lernetz/lernetz-schule-v2: 0 pods
- lernetz/tasker: 0 pods
- haldimann/kp-remake-v2: 0 pods
- ssb/verhaltenskodex: 0 pods
- phbern/brennpunkt-landschaft-it: 0 pods
- swissvolley/escoresheet-v2: 0 pods
- swisspeace/conflict-sensitivity-v2: 0 pods
- luzern/luzern-nmg-test: 0 pods

**ALL 17 not-backed-up PVCs: Mounted by running pods**
- bafu/luftlabor-fr-v2: 1 pod (Running)
- bafu/luftlabor-it-v2: 1 pod (Running)
- bafu/luftlabor-v2: 1 pod (Running)
- berufscockpit-base/nextcloud: 1 pod (Running)
- cerebral/hilfsangebote-v2: 1 pod (Running)
- csi-snapshot-controller/cache-volume-snapshot-controller-0: 1 pod (Running)
- csi-snapshot-controller/cache-volume-snapshot-controller-1: 1 pod (Running)
- csi-snapshot-controller/cache-volume-snapshot-controller-2: 1 pod (Running)
- funvo/trainingsplaner-unihockey: 1 pod (Running)
- funvo/trainingsplaner-volleyball: 1 pod (Running)
- postfinance-moneyfit/moneyfit-2023-logs: 1 pod (Running)
- swiss-olympic/nextcloud: 1 pod (Running)
- tobias-friedli/sjo-eventmanager: 1 pod (Running)
- vbv/vbv-kursverwaltung-test: 1 pod (Running)
- zebis-oer/meilisearch-data: 1 pod (Running)
- zebis-oer-review/meilisearch-data-feature-ki-chatbot: 1 pod (Running)
- zebis-oer-review/meilisearch-data-master: 1 pod (Running)

### Why `snapshotMoveData: true` Requires Unmounted PVCs

**Current Configuration:**
```yaml
snapshotVolumes: true
snapshotMoveData: true
defaultVolumesToFsBackup: true
```

**How Velero's CSI Snapshot Data Movement Works:**

1. **Snapshot Creation**: Velero creates a CSI VolumeSnapshot of the PVC
2. **Temporary PVC Creation**: Velero creates a temporary PVC in the `velero` namespace from the snapshot
3. **Data Movement**: Velero mounts this temporary PVC to a data mover pod (Kopia)
4. **Upload to S3**: Kopia reads the volume data and uploads it to object storage
5. **Cleanup**: Temporary resources are deleted

**The Problem**: When the source PVC is mounted by a running pod, the CSI driver (Trident) may prevent creating a writable snapshot or the data mover cannot attach the temporary PVC due to access conflicts with the original pod's mount.

From Velero documentation ([CSI Snapshot Data Movement](https://velero.io/docs/main/csi-snapshot-data-movement/)):
> "During backup, you may see some intermediate objects (i.e., pods, PVCs, PVs) created in Velero namespace or the cluster scope to help data movers move data."

### Storage Class Configuration

**Current Storage Class: `standard`**
```yaml
provisioner: csi.trident.netapp.io
parameters:
  backendType: ontap-nas
  fsType: nfs
  selector: snapshots=none
```

**Note**: The `selector: snapshots=none` parameter is a Trident backend selector (filters which ONTAP backend to use) and does NOT prevent CSI VolumeSnapshot creation. CSI snapshots are controlled by the VolumeSnapshotClass, which is correctly configured:

```yaml
# VolumeSnapshotClass (correctly configured)
driver: csi.trident.netapp.io
deletionPolicy: Retain
labels:
  velero.io/csi-volumesnapshot-class: "true"
```

---

## Solutions

### Solution A: Use `snapshotMoveData: false` (RECOMMENDED for production)

**Approach:** Create CSI snapshots without data movement, keeping snapshots in the storage backend.

**Configuration Change:**
```yaml
configuration:
  snapshotVolumes: true
  snapshotMoveData: false  # Changed from true
  defaultVolumesToFsBackup: false  # Optional: disable filesystem fallback
```

**Advantages:**
✅ **Backs up ALL PVCs** regardless of pod mount status
✅ Snapshots can be created while pods are running (no downtime)
✅ Fast backup operations (snapshots are instant on ONTAP)
✅ No data movement overhead (no S3 uploads of volume data)
✅ Works with the current `standard` storage class

**Disadvantages:**
❌ Snapshots remain in ONTAP storage backend (not portable)
❌ Cannot restore to different clusters/storage backends
❌ Dependent on ONTAP snapshot retention policies
❌ Snapshots consume space in ONTAP backend

**When to use:**
- **Single cluster DR** within the same storage infrastructure
- **Short-term backups** (days/weeks, not months/years)
- **Performance-critical environments** where S3 upload overhead is unacceptable
- **Production systems** that cannot tolerate PVC unmounting

**Best Practices:**
- Configure ONTAP snapshot retention policies
- Monitor ONTAP snapshot usage
- Test restore procedures within the same cluster
- Consider periodic full cluster backups with data movement for long-term archival

---

### Solution B: Enable Pod-Volume Backup for Mounted PVCs

**Approach:** Use Velero's File System Backup (formerly Restic) via node-agent for PVCs mounted by running pods.

**Configuration Change:**
```yaml
# Keep current settings
snapshotVolumes: true
snapshotMoveData: true
defaultVolumesToFsBackup: true

# Add pod annotation for volumes that need filesystem backup
# On pods using PVCs:
metadata:
  annotations:
    backup.velero.io/backup-volumes: volume-name-1,volume-name-2
```

**Advantages:**
✅ Backs up mounted PVCs while pods are running
✅ Volume data is uploaded to S3 (portable across clusters)
✅ Can mix CSI snapshots (unmounted) and filesystem backup (mounted)

**Disadvantages:**
❌ Requires manual pod annotations for each pod/volume
❌ Slower than CSI snapshots (reads entire filesystem)
❌ Higher resource usage (node-agent pods, network bandwidth)
❌ Does not support all volume types (hostPath, local, etc.)

**Implementation Steps:**

1. **Ensure node-agent is running:**
   ```bash
   kubectl get daemonset -n velero node-agent
   ```

2. **Annotate pods that use PVCs:**
   ```yaml
   apiVersion: v1
   kind: Pod
   metadata:
     annotations:
       # Comma-separated list of volume names to backup
       backup.velero.io/backup-volumes: data,logs
   spec:
     volumes:
     - name: data
       persistentVolumeClaim:
         claimName: my-pvc
     - name: logs
       persistentVolumeClaim:
         claimName: logs-pvc
   ```

3. **Or use opt-out annotation** (backup all volumes by default):
   ```yaml
   configuration:
     defaultVolumesToFsBackup: true  # Already set

   # Exclude specific volumes:
   metadata:
     annotations:
       backup.velero.io/backup-volumes-excludes: temp,cache
   ```

**When to use:**
- Need portable backups (restore to different clusters)
- Long-term archival requirements
- Mixed environment (some PVCs mounted, some unmounted)

From Velero documentation ([File System Backup](https://velero.io/docs/v1.10/file-system-backup/)):
> "Velero's File System Backup reads/writes data from volumes by accessing the node's filesystem, on which the pod is running. For this reason, FSB can only backup volumes that are mounted by a pod."

---

### Solution C: Hybrid Approach (RECOMMENDED for comprehensive coverage)

**Approach:** Combine CSI snapshots (fast) with filesystem backup (comprehensive).

**Configuration:**
```yaml
configuration:
  snapshotVolumes: true
  snapshotMoveData: false  # CSI snapshots stay in ONTAP
  defaultVolumesToFsBackup: true  # Enable filesystem backup for mounted PVCs

nodeAgent:
  # Already configured
  podConfig:
    ttlSecondsAfterFinished: 3600
```

**Backup Strategy:**

1. **Daily Backups**: Use CSI snapshots (`snapshotMoveData: false`)
   - Fast, near-instant snapshots
   - All 39 PVCs backed up
   - Snapshots stored in ONTAP

2. **Weekly Archival**: Use data movement (`snapshotMoveData: true`) during maintenance window
   - Schedule during off-hours when pods can be scaled down
   - Portable backups uploaded to S3
   - Long-term retention

3. **Continuous Protection**: Enable filesystem backup for critical workloads
   - Add pod annotations for databases, stateful apps
   - Complements CSI snapshots
   - Ensures data consistency for applications

---

## Storage Class Migration (Optional Enhancement)

### Consider Migrating to Snapshot-Enabled Storage Class

**Current Storage Class:**
```yaml
name: standard
parameters:
  selector: snapshots=none
```

**Snapshot-Enabled Storage Class:**
```yaml
name: standard-snapshot
parameters:
  selector: snapshots=3d  # 3-day snapshot retention
```

**Benefits:**
- ONTAP-level snapshot policies (automatic snapshots every N hours)
- Faster snapshot operations
- Better integration with storage backend features

**Migration Process:**
1. Create new PVCs using `standard-snapshot` storage class
2. Copy data from old PVCs to new PVCs
3. Update pod specifications to use new PVCs
4. Verify and delete old PVCs

**Note**: This is a **manual migration** with application downtime. Only recommended if storage-level snapshots are required.

---

## Recommended Action Plan

### Immediate Actions (Issue #705 Resolution)

1. **Decision Point**: Choose Solution A (recommended) or Solution B

2. **For Solution A (snapshotMoveData: false):**
   ```bash
   # Edit the Velero configuration
   vi clusters/lernetz-stage-begasoft-k8s/manifests/velero/kustomization.yaml

   # Change line 75:
   # FROM: snapshotMoveData: true
   # TO:   snapshotMoveData: false

   # Commit and push
   git add clusters/lernetz-stage-begasoft-k8s/manifests/velero/kustomization.yaml
   git commit -m "Set snapshotMoveData=false to enable backup of mounted PVCs"
   git push

   # Sync with ArgoCD
   argocd app sync lern-velero
   ```

3. **Test Full Backup:**
   ```bash
   velero backup create test-all-pvcs-snapshot-only \
     --include-namespaces '*' \
     --exclude-namespaces velero,kube-system,kube-public,kube-node-lease,begasoft-* \
     --snapshot-volumes=true \
     --wait
   ```

4. **Verify Coverage:**
   ```bash
   # Should show 31 VolumeSnapshots (39 total - 8 begasoft excluded)
   kubectl get volumesnapshot -A | grep -E "(bafu|lernetz|phbern)" | wc -l
   ```

### Long-Term Improvements

1. **Implement Backup Monitoring:**
   - Alert if PVC count in backup < expected count
   - Monitor ONTAP snapshot usage
   - Track backup duration trends

2. **Document Backup Strategy:**
   - Daily: CSI snapshots (fast, local)
   - Weekly: Data movement backups (portable, S3)
   - Monthly: Full cluster export

3. **Test Restore Procedures:**
   - Single PVC restore
   - Full namespace restore
   - Disaster recovery runbook

4. **Consider Storage Class Migration:**
   - Evaluate `standard-snapshot` for new applications
   - Plan migration for critical workloads

---

## Verification Checklist

After implementing the solution:

- [ ] All 31 eligible PVCs (39 minus 8 begasoft-*) have VolumeSnapshots created
- [ ] Backup completes with 0 errors, minimal warnings
- [ ] Backup duration is acceptable (< 30 minutes for snapshot-only)
- [ ] ONTAP snapshot usage monitored
- [ ] Restore test successful for at least 3 PVCs
- [ ] Documentation updated with new backup strategy
- [ ] Monitoring/alerting configured

---

## References

### Velero Documentation
- [CSI Snapshot Data Movement](https://velero.io/docs/main/csi-snapshot-data-movement/) - Official documentation explaining how `snapshotMoveData` works
- [File System Backup](https://velero.io/docs/v1.10/file-system-backup/) - Documentation on backing up mounted volumes using node-agent

### Related GitHub Issues
- [Issue #8341 - PVC data snapshotting issues](https://github.com/vmware-tanzu/velero/issues/8341)
- [Issue #7388 - DataDownload failures with snapshotMoveData](https://github.com/vmware-tanzu/velero/issues/7388)
- [Issue #7233 - Backup failures for unused PVCs](https://github.com/vmware-tanzu/velero/issues/7233)

### NetApp Trident Documentation
- [Work with Snapshots](https://docs.netapp.com/us-en/trident/trident-use/vol-snapshots.html) - Trident CSI snapshot capabilities
- [ONTAP NAS Examples](https://docs.netapp.com/us-en/trident/trident-use/ontap-nas-examples.html) - Storage class configuration examples

---

## Conclusion

**Root Cause:** Velero with `snapshotMoveData: true` cannot backup PVCs that are mounted by running pods due to access conflicts during data movement operations.

**Recommended Solution:** Set `snapshotMoveData: false` to enable CSI snapshot backups for all PVCs, regardless of mount status. This provides immediate protection for all 31 eligible PVCs with near-zero backup time.

**Trade-offs:** Snapshots remain in ONTAP storage backend (not portable to other clusters), but this is acceptable for single-cluster DR scenarios with proper ONTAP snapshot retention policies.

**Next Steps:** Implement Solution A, verify all PVCs are backed up, and document the backup/restore procedures.
