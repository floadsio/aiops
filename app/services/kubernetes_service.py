"""Kubernetes service for discovering and checking cluster connectivity.

This service uses kubeconfigs from yadm to:
- Discover available Kubernetes clusters
- Check connectivity to each cluster
- Provide cluster metadata (server URL, context name, etc.)
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .yadm_service import find_yadm_files_by_category

logger = logging.getLogger(__name__)


@dataclass
class KubeCluster:
    """Represents a Kubernetes cluster from a kubeconfig file."""

    name: str
    config_file: str
    server: str
    context: str
    user: str
    namespace: Optional[str] = None
    reachable: Optional[bool] = None
    error: Optional[str] = None
    version: Optional[str] = None


def get_kubeconfig_paths(user_home: str) -> list[str]:
    """Get full paths to kubeconfig files from yadm cache.

    Args:
        user_home: User's home directory path

    Returns:
        List of absolute paths to kubeconfig files
    """
    # Get relative paths from yadm cache
    relative_paths = find_yadm_files_by_category("kubeconfigs")

    full_paths = []
    for rel_path in relative_paths:
        full_path = os.path.join(user_home, rel_path)
        if os.path.isfile(full_path):
            full_paths.append(full_path)

    return full_paths


def parse_kubeconfig(
    config_path: str,
    linux_username: Optional[str] = None,
) -> list[KubeCluster]:
    """Parse a kubeconfig file and extract cluster information.

    Args:
        config_path: Path to the kubeconfig file
        linux_username: Optional username to read file as (via sudo)

    Returns:
        List of KubeCluster objects from this config
    """
    clusters = []

    try:
        # Read file content - use sudo if linux_username specified
        if linux_username:
            result = subprocess.run(
                ["sudo", "-u", linux_username, "cat", config_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                logger.warning(f"Failed to read kubeconfig {config_path}: {result.stderr}")
                return clusters
            config = yaml.safe_load(result.stdout)
        else:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

        if not config:
            return clusters

        # Build lookup maps
        cluster_map = {c["name"]: c.get("cluster", {}) for c in config.get("clusters", [])}
        user_map = {u["name"]: u.get("user", {}) for u in config.get("users", [])}

        # Extract from contexts
        for ctx in config.get("contexts", []):
            ctx_name = ctx.get("name", "")
            ctx_data = ctx.get("context", {})

            cluster_name = ctx_data.get("cluster", "")
            user_name = ctx_data.get("user", "")
            namespace = ctx_data.get("namespace")

            cluster_info = cluster_map.get(cluster_name, {})
            server = cluster_info.get("server", "unknown")

            # Create friendly name from filename
            config_filename = os.path.basename(config_path)
            friendly_name = config_filename.replace(".config", "").replace("-k8s", "")

            clusters.append(
                KubeCluster(
                    name=friendly_name,
                    config_file=config_path,
                    server=server,
                    context=ctx_name,
                    user=user_name,
                    namespace=namespace,
                )
            )

    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse kubeconfig {config_path}: {e}")
    except OSError as e:
        logger.warning(f"Failed to read kubeconfig {config_path}: {e}")

    return clusters


def check_cluster_connectivity(
    cluster: KubeCluster,
    timeout: int = 5,
    linux_username: Optional[str] = None,
) -> KubeCluster:
    """Check if a Kubernetes cluster is reachable.

    Args:
        cluster: KubeCluster object to check
        timeout: Connection timeout in seconds
        linux_username: Optional username to run kubectl as

    Returns:
        Updated KubeCluster with reachable status and version
    """
    try:
        # Build kubectl command with explicit context
        cmd = [
            "kubectl",
            "--kubeconfig",
            cluster.config_file,
            "--context",
            cluster.context,
            "version",
            "-o",
            "json",
        ]

        # Run as specific user if requested
        if linux_username:
            cmd = ["sudo", "-u", linux_username, "-H"] + cmd

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0:
            cluster.reachable = True
            # Extract server version from JSON output
            try:
                import json
                version_info = json.loads(result.stdout)
                server_info = version_info.get("serverVersion", {})
                if server_info:
                    cluster.version = server_info.get("gitVersion", "")
            except json.JSONDecodeError:
                # Fallback to parsing text output
                for line in result.stdout.split("\n"):
                    if "Server Version:" in line:
                        cluster.version = line.split(":", 1)[1].strip()
                        break
        else:
            cluster.reachable = False
            # Extract meaningful error
            error = result.stderr.strip() or result.stdout.strip()
            if "connection refused" in error.lower():
                cluster.error = "Connection refused"
            elif "no such host" in error.lower() or "could not resolve" in error.lower():
                cluster.error = "DNS resolution failed"
            elif "certificate" in error.lower():
                cluster.error = "Certificate error"
            elif "unauthorized" in error.lower() or "forbidden" in error.lower():
                cluster.error = "Authentication failed"
            elif "timeout" in error.lower() or "i/o timeout" in error.lower():
                cluster.error = "Connection timeout"
            else:
                # Truncate long errors
                cluster.error = error[:100] if len(error) > 100 else error

    except subprocess.TimeoutExpired:
        cluster.reachable = False
        cluster.error = "Connection timeout"
    except FileNotFoundError:
        cluster.reachable = False
        cluster.error = "kubectl not installed"
    except Exception as e:
        cluster.reachable = False
        cluster.error = str(e)[:100]

    return cluster


def discover_kubernetes_clusters(
    user_home: str,
    check_connectivity: bool = True,
    linux_username: Optional[str] = None,
    timeout: int = 5,
) -> list[KubeCluster]:
    """Discover all Kubernetes clusters from yadm kubeconfigs.

    Args:
        user_home: User's home directory
        check_connectivity: Whether to check if clusters are reachable
        linux_username: Username to run kubectl as
        timeout: Connection timeout per cluster

    Returns:
        List of KubeCluster objects with connectivity status
    """
    clusters = []

    # Get kubeconfig paths
    config_paths = get_kubeconfig_paths(user_home)
    logger.info(f"Found {len(config_paths)} kubeconfig files")

    # Parse each config
    for config_path in config_paths:
        parsed = parse_kubeconfig(config_path, linux_username=linux_username)
        clusters.extend(parsed)

    logger.info(f"Discovered {len(clusters)} Kubernetes clusters")

    # Check connectivity if requested
    if check_connectivity:
        for cluster in clusters:
            check_cluster_connectivity(
                cluster,
                timeout=timeout,
                linux_username=linux_username,
            )

    return clusters


def get_kubernetes_summary(clusters: list[KubeCluster]) -> dict:
    """Get summary statistics for discovered clusters.

    Args:
        clusters: List of KubeCluster objects

    Returns:
        Summary dict with counts
    """
    reachable = sum(1 for c in clusters if c.reachable is True)
    unreachable = sum(1 for c in clusters if c.reachable is False)
    unchecked = sum(1 for c in clusters if c.reachable is None)

    return {
        "total": len(clusters),
        "reachable": reachable,
        "unreachable": unreachable,
        "unchecked": unchecked,
    }
