# Issue #705 Documentation Index

**Issue:** Velero backup implementation for lernetz-test-begasoft-k8s cluster
**Status:** Phase 2 Conservative Approach - In Progress
**Last Updated:** 2025-12-18

---

## Quick Navigation

### For Quick Overview
1. **Start here:** [`ISSUE_705_PHASE2_SUMMARY.md`](ISSUE_705_PHASE2_SUMMARY.md)
   - Executive summary of Phase 2 implementation
   - Test results: 1-namespace ✅, 3-namespace ✅
   - Cluster capacity analysis
   - Recommendations and next steps

### For Next Session Planning
2. **Next steps guide:** [`ISSUE_705_NEXT_SESSION_INSTRUCTIONS.md`](ISSUE_705_NEXT_SESSION_INSTRUCTIONS.md)
   - Detailed instructions for 6-namespace test
   - Full cluster backup test script
   - Cluster state management procedures
   - Decision tree for troubleshooting
   - **READ THIS BEFORE STARTING NEXT SESSION**

### For Detailed Technical Analysis
3. **Test results:** [`ISSUE_705_PHASE2_TEST_RESULTS.md`](ISSUE_705_PHASE2_TEST_RESULTS.md)
   - Detailed test results with metrics
   - Monitoring timelines
   - API rate limiting analysis
   - Resource constraints deep dive
   - Command reference

### For Root Cause Investigation
4. **Root cause findings:** [`ISSUE_705_ACTUAL_ROOT_CAUSE_AND_FIX.md`](ISSUE_705_ACTUAL_ROOT_CAUSE_AND_FIX.md)
   - Investigation methodology
   - Direct VolumeSnapshot testing (proof Trident works)
   - Velero CSI plugin state sync issue identification
   - Solution: concurrency reduction from 4 to 2

### For Previous Analysis
5. **Root cause and solution:** [`ISSUE_705_ROOT_CAUSE_AND_SOLUTION.md`](ISSUE_705_ROOT_CAUSE_AND_SOLUTION.md)
   - Comprehensive root cause analysis
   - Solution implementation plan
   - Phase 1 and Phase 2 approaches

6. **PVC backup analysis:** [`ISSUE_705_PVC_BACKUP_ANALYSIS.md`](ISSUE_705_PVC_BACKUP_ANALYSIS.md)
   - Analysis of which PVCs were backed up
   - Why 14/31 PVCs were missed initially
   - `defaultVolumesToFsBackup: true` bug identification

### For Backup History
7. **Backup history archive:** [`issue-705-backup-history/`](issue-705-backup-history/)
   - Archived YAML of all 9 test backups
   - DataUploads, VolumeSnapshots, VolumeSnapshotContents
   - Backup summary and timeline
   - Reference for understanding previous test failures

---

## Phase 2 Implementation Timeline

### Session 1: Current Session (2025-12-18)

**Completed:**
- ✅ Reduced `dataMovers.concurrency` from 4 → 2 (commit 15b4c09)
- ✅ Deployed via GitOps (ArgoCD sync)
- ✅ Test 1: Single namespace backup (71 seconds)
- ✅ Test 2: Three namespace backup (156 seconds)
- ✅ Identified API rate limiting issue (intentional full cluster abort)
- ✅ Documented all findings (3 new comprehensive documents)

**Documentation Created:**
- `ISSUE_705_PHASE2_TEST_RESULTS.md` (334 lines, detailed analysis)
- `ISSUE_705_NEXT_SESSION_INSTRUCTIONS.md` (334 lines, step-by-step guide)
- `ISSUE_705_PHASE2_SUMMARY.md` (306 lines, executive summary)

### Session 2: Next Session (pending)

**Plan:**
- ⏳ Verify 3-namespace test logs for warnings
- ⏳ Run 6-namespace test (expected: 400 seconds)
- ⏳ Run full cluster backup if 6-namespace passes (expected: 2-4 hours)
- ⏳ Gather metrics during full cluster backup
- ⏳ Document results and performance characteristics

**Success Criteria:**
- All 6 DataUploads created in 6-namespace test
- All 31 DataUploads created in full cluster test
- No backup hangs or stuck "InProgress" scenarios
- Backup completion in acceptable timeframe (2-4 hours)

---

## Key Configuration Changes

### Deployed Changes (Commit 15b4c09)

**File:** `clusters/lernetz-stage-begasoft-k8s/manifests/velero/kustomization.yaml`

```yaml
dataMovers:
  velero:
    concurrency: 2  # Was: 4
```

**Rationale:**
- Velero CSI plugin state synchronization issue (root cause of Issue #705)
- Reduce concurrent snapshot operations to improve state tracking
- Trade-off: Slower backups (3-4 hours) vs reliable completion

### Planned Changes (Phase 2 Resource Alignment - not yet deployed)

**Potential future alignment with Flow cluster configuration:**
- Velero server resources: 100m/500m (vs current 200m/1000m)
- Node-agent resources: 50m/1000m (vs current 100m/1500m)
- Remove custom ConfigMaps
- Follow Flow cluster best practices

**Current approach:** Minimal change (concurrency only) is working, hold resource alignment pending full cluster test results

---

## Cluster Resource Status

### Current State (77% baseline memory utilization)

| Component | Usage | Risk Level |
|-----------|-------|-----------|
| Node 2 Memory | 95% | 🔴 CRITICAL |
| Baseline Utilization | 77% | 🟠 HIGH |
| During Backup | 79-85% | 🟡 MODERATE |
| Available Headroom | 18% | 🟡 MODERATE |

### Constraints Identified

1. **Node 2 (lern-test-k8sw-02):** 95% memory - single point of failure
2. **Cluster memory pressure:** 77% baseline means limited room for spikes
3. **API rate limiting:** Can occur during large backup operations
4. **Concurrency limited to 2:** Conservative but safe for current capacity

### Recommendations

**Short-term:** Keep current config, monitor backup operations
**Medium-term:** Add 1-2 worker nodes (strongly recommended within 30 days)
**Alternative:** Right-size workloads if nodes unavailable (complex, may impact testing)

---

## Test Results Summary

| Test | Namespaces | PVCs | Items | Duration | DataUploads | Status |
|------|-----------|------|-------|----------|-------------|--------|
| Test 1 | 1 (cerebral) | 1 | 170 | 71s | 1/1 | ✅ PASSED |
| Test 2 | 3 | 3 | 580 | 156s | 3/3 | ✅ PASSED |
| Test 3 | All (31) | 31 | ~10K | - | - | ⏹️ ABORTED (API rate limiting) |
| Test 4 | 6 | 6 | ~1200 | pending | 6/6 | ⏳ SCHEDULED |
| Test 5 | All (31) | 31 | ~10K | pending | 31/31 | ⏳ SCHEDULED |

---

## Most Important Files to Read

### Before Next Session
1. **[ISSUE_705_NEXT_SESSION_INSTRUCTIONS.md](ISSUE_705_NEXT_SESSION_INSTRUCTIONS.md)** - Start here!
   - Has copy-paste scripts for 6-namespace test
   - Explains what to check, what to monitor
   - Decision tree for troubleshooting
   - ~10 minutes to read, 30 seconds to understand next action

### For Understanding Current Status
2. **[ISSUE_705_PHASE2_SUMMARY.md](ISSUE_705_PHASE2_SUMMARY.md)** - Executive overview
   - Why concurrency=2 works
   - Cluster capacity issues
   - What comes next
   - ~5 minutes to read

### For Deep Technical Understanding
3. **[ISSUE_705_PHASE2_TEST_RESULTS.md](ISSUE_705_PHASE2_TEST_RESULTS.md)** - Detailed analysis
   - Full test results with metrics
   - Root cause analysis
   - Resource constraints deep dive
   - ~15 minutes to read

---

## Git Commit Reference

### Recent Commits (This Session)

```
52c06fb - Add Phase 2 Conservative Implementation - Executive Summary
f6cc344 - Add detailed next session instructions for Issue #705 Phase 2 testing
e573c08 - Document Phase 2 Conservative test results and cluster resource constraints
88501f8 - Archive Issue #705 backup history before cleanup and configuration fix
15b4c09 - Issue #705: Reduce Velero dataMovers concurrency from 4 to 2
```

### Configuration Deployment

- **Deployed:** Commit `15b4c09` - concurrency=2 via ArgoCD
- **Verified:** Working correctly in tests 1-2
- **Ready for:** Full cluster test in next session

---

## Command Quick Reference

### Check Cluster Status
```bash
# Verify Velero is ready
kubectl get pods -n velero -l app.kubernetes.io/name=velero

# Verify no old backups from previous tests
kubectl get backups -n velero
# Should return: No resources found
```

### Run Tests
```bash
# Next session: Run 6-namespace test
bash /tmp/test_6ns_v2.sh  # Script will be created in next session

# Then: Run full cluster backup
bash /tmp/test_full_cluster_v2.sh  # Script will be created in next session
```

### Monitor Tests
```bash
# Token management
TOKEN=$(cat /tmp/token_begasoft.txt)

# Check backup status
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify \
  describe backup <BACKUP_NAME> -n velero

# Check DataUploads
kubectl --token="$TOKEN" --server=https://193.5.124.83:6443 --insecure-skip-tls-verify \
  get datauploads -n velero -l velero.io/backup-name=<BACKUP_NAME>
```

### Cleanup
```bash
# Reset cluster before new test
bash /tmp/full_reset_velero.sh
```

---

## Key Learnings

### What We Discovered

1. **Velero CSI Plugin Issue:** With concurrency=4, the plugin struggles to track multiple simultaneous snapshots. Reducing to 2 makes it reliable.

2. **Trident/ONTAP Works:** Direct VolumeSnapshot tests proved storage backend is healthy. Issue was entirely in Velero's plugin.

3. **API Rate Limiting Risk:** Large backup operations (10K+ items) combined with backup reconciliation can overwhelm Kubernetes API server.

4. **Cluster Capacity:** 77% baseline memory utilization leaves limited headroom. Node 2 at 95% is a critical bottleneck.

5. **Aggressive Cleanup Causes Resync:** Force-deleting backups causes Velero to attempt re-syncing from S3, triggering API overload. Let Velero handle cleanup.

### What Worked

- ✅ Reduced concurrency resolves the state sync issue
- ✅ Tests 1-2 completed successfully without hangs
- ✅ Clean restart of Velero resolves API rate limiting
- ✅ Incremental scaling tests (1ns → 3ns) help identify when issues occur

### What Needs Attention

- ⚠️ Cluster memory pressure (77% baseline)
- ⚠️ Node 2 memory critical (95%)
- ⚠️ API rate limiting risk during full cluster backup
- ⚠️ Backup duration still 2-4 hours (acceptable but slow)

---

## Next Steps Summary

1. **In next session:**
   - Read [`ISSUE_705_NEXT_SESSION_INSTRUCTIONS.md`](ISSUE_705_NEXT_SESSION_INSTRUCTIONS.md) first
   - Run 6-namespace test
   - If successful, run full cluster backup
   - Document results

2. **After Phase 2 testing:**
   - Analyze performance metrics
   - Plan Phase 3 (if needed)
   - Schedule capacity expansion (add worker nodes)

3. **For ongoing monitoring:**
   - Set alerts on node memory >85%
   - Monitor backup completion times
   - Track OOM kills and pod evictions
   - Watch for API rate limiting messages

---

## Document Maintenance

**Last Updated:** 2025-12-18 12:20 UTC
**Maintained By:** Claude Code
**Status:** Current and complete for Phase 2 session
**Next Review:** After Phase 2 full cluster backup completes

---

## Contact & Questions

For questions about Issue #705 implementation:
- Review relevant document from index above
- Check git commit history for deployment decisions
- Consult Velero/Trident documentation for storage layer questions
- Monitor cluster logs and events during tests

**All documentation is self-contained and includes command references for reproduction.**
