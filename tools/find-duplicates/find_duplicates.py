#!/usr/bin/env python3
"""
Find duplicate files by content hash and report them sorted by modification time.
Handles all file types: md, html, csv, images, mp4, pdf, etc.
"""

import os
import hashlib
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# ===== CONFIGURATION =====
# Change this to your directory path
TARGET_DIRECTORY = "/path/to/your/directory"

# Hash algorithm (MD5 is fast for this use case; SHA256 if you want more security)
HASH_ALGO = "md5"

# File extensions to include (empty list = all files; add extensions to filter)
# Example: ["md", "html", "csv", "pdf"] to skip videos/images
FILE_EXTENSIONS = ["md", "html", "csv", "pdf"]  # Skip mp4s, images in first run

# Use creation date (birthtime) instead of modification date?
# Note: birthtime is more reliable for exported files
USE_BIRTHTIME = True

# =====================

def hash_file(filepath, algo="md5"):
    """Compute hash of file content."""
    hasher = hashlib.new(algo)
    try:
        with open(filepath, "rb") as f:
            # Read in chunks to handle large files efficiently
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        print(f"  ⚠️  Error hashing {filepath}: {e}")
        return None


def get_file_info(filepath):
    """Get file metadata."""
    try:
        stat = os.stat(filepath)

        # Use birthtime (creation) if available, otherwise mtime
        if USE_BIRTHTIME and hasattr(stat, 'st_birthtime'):
            timestamp = stat.st_birthtime
            time_type = "created"
        else:
            timestamp = stat.st_mtime
            time_type = "modified"

        size = stat.st_size
        return {
            "path": filepath,
            "size": size,
            "timestamp": timestamp,
            "timestamp_readable": datetime.fromtimestamp(timestamp).isoformat(),
            "time_type": time_type,
        }
    except Exception as e:
        print(f"  ⚠️  Error getting info for {filepath}: {e}")
        return None


def find_duplicates(directory):
    """Scan directory recursively and find duplicate files by content."""
    if not os.path.isdir(directory):
        print(f"❌ Directory not found: {directory}")
        return {}

    print(f"🔍 Scanning: {directory}")
    time_type = "creation" if USE_BIRTHTIME else "modification"
    ext_filter = f"extensions: {FILE_EXTENSIONS}" if FILE_EXTENSIONS else "all files"
    print(f"   Using {HASH_ALGO.upper()} hashing, {time_type} dates")
    print(f"   Filtering: {ext_filter}\n")

    hash_map = defaultdict(list)  # hash -> list of file info dicts
    total_files = 0
    skipped_files = 0

    for root, dirs, files in os.walk(directory):
        for filename in files:
            filepath = os.path.join(root, filename)

            # Filter by extension if specified
            if FILE_EXTENSIONS:
                file_ext = os.path.splitext(filename)[1].lstrip('.').lower()
                if file_ext not in [ext.lower() for ext in FILE_EXTENSIONS]:
                    skipped_files += 1
                    continue

            total_files += 1

            # Show progress for large directories
            if total_files % 50 == 0:
                print(f"   Processing... ({total_files} files scanned)")

            file_info = get_file_info(filepath)
            if not file_info:
                skipped_files += 1
                continue

            file_hash = hash_file(filepath, HASH_ALGO)
            if file_hash:
                hash_map[file_hash].append(file_info)
            else:
                skipped_files += 1

    print(f"\n✅ Scan complete: {total_files} files, {skipped_files} skipped\n")
    return hash_map


def report_duplicates(hash_map):
    """Print and return duplicates grouped and sorted by mtime."""
    duplicates = {k: v for k, v in hash_map.items() if len(v) > 1}

    if not duplicates:
        print("✨ No duplicates found!")
        return duplicates

    print(f"📋 Found {len(duplicates)} duplicate groups:\n")
    print("=" * 80)

    for idx, (file_hash, files) in enumerate(sorted(duplicates.items()), 1):
        # Sort by timestamp (oldest to newest)
        files_sorted = sorted(files, key=lambda f: f["timestamp"])
        time_label = files_sorted[0]["time_type"].upper()

        print(f"\n🔗 Group {idx} ({len(files)} files, {HASH_ALGO.upper()}: {file_hash[:16]}...)")
        print(f"   File size: {files[0]['size']} bytes")
        print(f"   {'─' * 76}")

        for file_info in files_sorted:
            age_indicator = "📌 NEWEST" if file_info == files_sorted[-1] else "   "
            print(f"   {age_indicator}")
            print(f"      Path: {file_info['path']}")
            print(f"      {time_label}: {file_info['timestamp_readable']}")

        print()

    return duplicates


def save_report_json(duplicates, output_file="duplicate_report.json"):
    """Save detailed report as JSON for further processing."""
    report = []

    for file_hash, files in sorted(duplicates.items()):
        files_sorted = sorted(files, key=lambda f: f["timestamp"])

        group = {
            "hash": file_hash,
            "count": len(files),
            "size_bytes": files[0]["size"],
            "newest": files_sorted[-1],
            "all_files": files_sorted,
        }
        report.append(group)

    with open(output_file, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"📄 Report saved to: {output_file}")


def main():
    if TARGET_DIRECTORY == "/path/to/your/directory":
        print("⚠️  Please set TARGET_DIRECTORY in the script first!")
        print("   Edit the line: TARGET_DIRECTORY = '...'")
        return

    hash_map = find_duplicates(TARGET_DIRECTORY)
    duplicates = report_duplicates(hash_map)

    if duplicates:
        # Save JSON report for reference
        save_report_json(
            duplicates,
            output_file=os.path.join(TARGET_DIRECTORY, "duplicates_report.json"),
        )


if __name__ == "__main__":
    main()
