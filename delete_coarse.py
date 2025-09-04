#!/usr/bin/env python3
"""
Script to monitor logs folder for FINISH logs and delete scene files/directories when all stages are complete.

This script continuously monitors the outputs directory structure and deletes scene files and directories
(fine/scene.blend1 and savemesh_* directories) when all expected pipeline stages have completed 
(indicated by FINISH log files).

Usage:
    python delete_coarse.py [--outputs-dir OUTPUTS_DIR] [--check-interval SECONDS] [--dry-run]

Arguments:
    --outputs-dir: Path to the outputs directory (default: ./outputs)
    --check-interval: How often to check for completion in seconds (default: 30)
    --dry-run: Print what would be deleted without actually deleting
"""

import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Set, List, Optional
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Define the exact required FINISH log files that must exist before deletion
REQUIRED_FINISH_FILES = {
    'FINISH_coarse',
    'FINISH_fineterrain', 
    'FINISH_opengl_0_0_0048_0',
    'FINISH_opengl_1_0_0048_0',
    'FINISH_populate',
    'FINISH_rendershort_0_0_0048_0',
    'FINISH_savemesh_1_0_0048_0',
    'FINISH_rendershort_1_0_0048_0',
    'FINISH_savemesh_0_0_0048_0'
}


def find_all_logs_directories_in_outputs(base_path: Path) -> List[Path]:
    """Find all logs directories in the outputs structure across all job directories."""
    logs_dirs = []
    
    if not base_path.exists():
        logger.warning(f"Base path {base_path} does not exist")
        return logs_dirs
    
    logger.info(f"Scanning outputs directory: {base_path}")
    
    # Look for logs directories in outputs/{job_name}/{seed}/logs/
    for job_dir in base_path.iterdir():
        if job_dir.is_dir() and not job_dir.name.startswith('.'):
            logger.info(f"Scanning job directory: {job_dir.name}")
            for seed_dir in job_dir.iterdir():
                if seed_dir.is_dir() and not seed_dir.name.startswith('.'):
                    logs_dir = seed_dir / "logs"
                    if logs_dir.exists() and logs_dir.is_dir():
                        logs_dirs.append(logs_dir)
                        logger.debug(f"Found logs directory: {logs_dir}")
                    else:
                        logger.debug(f"No logs directory found in {seed_dir}")
    
    return logs_dirs

def get_finished_stages(logs_dir: Path) -> Set[str]:
    """Get the set of FINISH log files that exist in the given logs directory."""
    finished_stages = set()
    
    if not logs_dir.exists():
        return finished_stages
    
    for file_path in logs_dir.iterdir():
        if file_path.is_file() and file_path.name in REQUIRED_FINISH_FILES:
            finished_stages.add(file_path.name)
    
    return finished_stages

def get_expected_stages_for_logs(logs_dir: Path) -> Set[str]:
    """Return the fixed set of required FINISH files."""
    return REQUIRED_FINISH_FILES.copy()

def find_scene_files_and_dirs(logs_dir: Path) -> List[Path]:
    """Find the scene files and directories to delete."""
    # logs_dir is at outputs/{job_name}/{seed}/logs/
    # Files/dirs are at outputs/{job_name}/{seed}/fine/scene.blend1 and savemesh directories
    scene_dir = logs_dir.parent
    files_to_delete = []
    
    # coarse/scene.blend file
    coarse_blend = scene_dir / "coarse" / "scene.blend"
    if coarse_blend.exists():
        files_to_delete.append(coarse_blend)

    # fine/scene.blend1 file
    fine_blend = scene_dir / "fine" / "scene.blend1"
    if fine_blend.exists():
        files_to_delete.append(fine_blend)
    
    # savemesh directories
    savemesh_dirs = [
        scene_dir / "savemesh_0_0_0048_0",
        scene_dir / "savemesh_1_0_0048_0"
    ]
    
    for savemesh_dir in savemesh_dirs:
        if savemesh_dir.exists() and savemesh_dir.is_dir():
            files_to_delete.append(savemesh_dir)
    
    return files_to_delete

def check_and_delete_scene_files(logs_dir: Path, dry_run: bool = False) -> bool:
    """
    Check if all expected stages are finished and delete scene blend files if so.
    
    Returns:
        True if scene blend files were deleted (or would be deleted in dry run)
        False otherwise
    """
    expected_stages = get_expected_stages_for_logs(logs_dir)
    finished_stages = get_finished_stages(logs_dir)
    
    logger.debug(f"Logs dir: {logs_dir}")
    logger.debug(f"Expected stages: {expected_stages}")
    logger.debug(f"Finished stages: {finished_stages}")
    
    # Check if all expected stages are finished
    missing_stages = expected_stages - finished_stages
    if missing_stages:
        logger.debug(f"Missing stages: {missing_stages}")
        return False
    
    # All stages are finished, find and delete scene files and directories
    items_to_delete = find_scene_files_and_dirs(logs_dir)
    if not items_to_delete:
        logger.debug(f"No scene files/directories found for {logs_dir}")
        return False
    
    deleted_count = 0
    for item in items_to_delete:
        if dry_run:
            logger.info(f"[DRY RUN] Would delete: {item}")
            deleted_count += 1
        else:
            try:
                if item.is_file():
                    item.unlink()
                    logger.info(f"Deleted file: {item}")
                elif item.is_dir():
                    shutil.rmtree(item)
                    logger.info(f"Deleted directory: {item}")
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete {item}: {e}")
    
    return deleted_count > 0

def main():
    parser = argparse.ArgumentParser(description="Monitor logs and delete scene blend files when complete")
    parser.add_argument(
        "--outputs-dir", 
        type=Path, 
        default=Path("./outputs"),
        help="Path to the outputs directory (default: ./outputs)"
    )
    parser.add_argument(
        "--check-interval", 
        type=int, 
        default=30,
        help="How often to check for completion in seconds (default: 30)"
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true",
        help="Print what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--once", 
        action="store_true",
        help="Check once and exit (don't run continuously)"
    )

    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.dry_run:
        logger.info("Running in DRY RUN mode - no files will be deleted")
    
    # Find all logs directories across all job directories
    logs_dirs = find_all_logs_directories_in_outputs(args.outputs_dir)
    
    if not logs_dirs:
        logger.warning(f"No logs directories found in {args.outputs_dir}")
        if args.once:
            return 1
        logger.info("Will continue monitoring for new logs directories...")
    
    logger.info(f"Found {len(logs_dirs)} logs directories to monitor")
    
    deleted_count = 0
    
    def check_all_directories():
        nonlocal deleted_count
        current_deleted = 0
        
        # Re-scan for new directories if not running once
        if not args.once:
            current_logs_dirs = find_all_logs_directories_in_outputs(args.outputs_dir)
        else:
            current_logs_dirs = logs_dirs
        
        for logs_dir in current_logs_dirs:
            if check_and_delete_scene_files(logs_dir, args.dry_run):
                current_deleted += 1
        
        if current_deleted > 0:
            deleted_count += current_deleted
            logger.info(f"Deleted {current_deleted} scene file/directory sets this check")
        
        return current_deleted
    
    # Initial check
    initial_deleted = check_all_directories()
    deleted_count += initial_deleted
    
    if args.once:
        logger.info(f"One-time check complete. {'Would delete' if args.dry_run else 'Deleted'} {deleted_count} scene file/directory sets.")
        return 0
    
    # Continuous monitoring
    logger.info(f"Starting continuous monitoring (checking every {args.check_interval} seconds)")
    logger.info("Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(args.check_interval)
            check_all_directories()
            
    except KeyboardInterrupt:
        logger.info(f"\nMonitoring stopped. Total {'would delete' if args.dry_run else 'deleted'}: {deleted_count} scene file/directory sets")
        return 0

if __name__ == "__main__":
    sys.exit(main())
