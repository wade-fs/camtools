#!/usr/bin/env python3
import os
import sys
import argparse
import re
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import shutil

def check_ffmpeg():
    """Check if ffmpeg is installed."""
    if not shutil.which("ffmpeg"):
        print("Error: ffmpeg is not installed")
        sys.exit(1)

def validate_directories(src, dst):
    """Validate source and destination directories."""
    if not os.path.isdir(src):
        print(f"Error: Source directory '{src}' does not exist")
        sys.exit(1)
    mp4_files = list(Path(src).glob("*.mp4"))
    if not mp4_files:
        print(f"Error: No *.mp4 files found in '{src}'")
        sys.exit(1)
    os.makedirs(dst, exist_ok=True)

def extract_date(filename):
    """Extract YYYYMMDD from filename."""
    match = re.match(r'^(\d{8})', filename)
    return match.group(1) if match else None

def process_file(file, dst, quiet_mode):
    """Process a single file with ffmpeg."""
    filename = file.name
    date_part = extract_date(filename)
    if not date_part:
        print(f"Warning: Skipping '{filename}' - no valid YYYYMMDD date found")
        return

    # Create output directory
    output_dir = Path(dst) / date_part
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / filename

    # Skip if output file exists
    if output_file.exists():
        print(f"Skipping '{filename}' - output file '{output_file}' already exists")
        return

    # Build ffmpeg command
    ffmpeg_cmd = [
        "ffmpeg", "-i", str(file),
        "-c:v", "libvpx-vp9", "-b:v", "4000k",
        "-vf", "scale=720:1280,transpose=1",
        "-c:a", "aac", "-b:a", "152k", "-ar", "44100", "-r", "30",
        "-f", "mp4", str(output_file), "-y"
    ]
    if quiet_mode:
        ffmpeg_cmd.extend(["-loglevel", "quiet"])
    else:
        ffmpeg_cmd.extend(["-loglevel", "error", "-progress", "pipe:1"])

    # Run ffmpeg
    print(f"Converting '{filename}' to '{output_file}'...")
    try:
        process = subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.PIPE if not quiet_mode else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True
        )
        if process.returncode == 0:
            print(f"Successfully converted '{filename}'")
        else:
            print(f"Error: Failed to convert '{filename}' - {process.stderr}")
    except subprocess.CalledProcessError as e:
        print(f"Error: Failed to convert '{filename}' - {e.stderr}")

def main():
    # Check Python version
    if sys.version_info < (3, 6):
        print("Error: Python 3.6 or higher is required")
        sys.exit(1)

    cpu_cores = os.cpu_count() or 4

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Convert MP4 files using ffmpeg with multi-threading")
    parser.add_argument("-s", "--source", required=True, help="Source directory containing *.mp4 files")
    parser.add_argument("-d", "--destination", required=True, help="Destination directory for converted files")
    parser.add_argument("-t", "--threads", type=int, default=cpu_cores, help="Number of concurrent threads")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress all ffmpeg output")
    parser.add_argument("-D", "--date", help="Only convert files starting with this YYYYMMDD date")  # ✅ 新增
    args = parser.parse_args()

    # Validate inputs
    check_ffmpeg()
    validate_directories(args.source, args.destination)

    # Collect all mp4 files
    mp4_files = list(Path(args.source).glob("*.mp4"))

    # ✅ 過濾指定日期
    if args.date:
        mp4_files = [f for f in mp4_files if extract_date(f.name) == args.date]
        if not mp4_files:
            print(f"No files found with date {args.date}")
            sys.exit(0)

    # Process files using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = [
            executor.submit(process_file, file, args.destination, args.quiet)
            for file in mp4_files
        ]
        for future in futures:
            future.result()

    print("Conversion completed!")

if __name__ == "__main__":
    main()

