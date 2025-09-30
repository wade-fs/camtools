#!/usr/bin/python3
import os
import subprocess
import argparse
import time
from pathlib import Path
from collections import defaultdict

def run_adb_command(command, check=True):
    """執行 ADB 命令並返回結果"""
    try:
        result = subprocess.run(['adb'] + command, capture_output=True, text=True, check=check)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"ADB command failed: {' '.join(command)}")
        print(f"Error: {e.stderr}")
        return None

def list_remote_dir(remote_path, recursive=True):
    """遞歸列出 Android 設備上的遠端目錄內容"""
    cmd = ['shell', 'find', remote_path, '-type', 'f', '-exec', 'ls', '-l', '{}', '\\;']
    output = run_adb_command(cmd)
    if not output:
        print(f"No output from find command for {remote_path}")
        return []

    files = []
    lines = output.split('\n')
    for line in lines:
        if line.strip():
            parts = line.split(maxsplit=8)
            if len(parts) >= 8:
                size = parts[4] if parts[4].isdigit() else '0'
                path = parts[8] if len(parts) == 9 else ' '.join(parts[8:])
                if path.startswith(remote_path):
                    rel_path = path[len(remote_path):].lstrip('/')
                    files.append({
                        'path': path,
                        'rel_path': rel_path,
                        'size': int(size),
                        'mtime': parts[5] + ' ' + parts[6] + ' ' + parts[7]
                    })

    return files

def list_local_dir(local_path):
    """遞歸列出本地目錄內容"""
    files = []
    local_path = Path(local_path)
    try:
        for item in local_path.rglob('*'):
            if item.is_file():
                rel_path = str(item.relative_to(local_path))
                stat = item.stat()
                files.append({
                    'path': str(item),
                    'rel_path': rel_path,
                    'size': stat.st_size,
                    'mtime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))
                })
    except Exception as e:
        print(f"Error listing local directory {local_path}: {e}")
    return files

def create_local_dir(local_path):
    """創建本地目錄"""
    Path(local_path).mkdir(parents=True, exist_ok=True)

def compare_files(remote_files, local_files):
    """比較遠端和本地檔案清單，僅使用大小和修改時間"""
    remote_dict = {f['rel_path']: f for f in remote_files}
    local_dict = {f['rel_path']: f for f in local_files}
    
    files_to_sync = []
    total_size = 0

    for rel_path, remote_file in remote_dict.items():
        local_file = local_dict.get(rel_path)
        if not local_file:
            # 本地缺少檔案，需要同步
            files_to_sync.append(remote_file)
            total_size += remote_file['size']
        else:
            # 比較大小和修改時間
            if remote_file['size'] != local_file['size'] or remote_file['mtime'] != local_file['mtime']:
                files_to_sync.append(remote_file)
                total_size += remote_file['size']

    return files_to_sync, total_size

def sync_file(remote_path, local_path):
    """同步單個檔案"""
    print(f"  Syncing: {os.path.basename(remote_path)}")
    result = run_adb_command(['pull', remote_path, local_path], check=False)
    if result is None:
        print(f"  Failed to pull: {os.path.basename(remote_path)}")
        return False
    print(f"  Successfully pulled: {os.path.basename(remote_path)}")
    return True

def sync_files(files_to_sync, remote_dir, local_dir, verbose=False):
    """同步指定的檔案清單"""
    success_count = 0
    total_count = len(files_to_sync)
    
    for file_info in files_to_sync:
        remote_path = file_info['path']
        local_path = os.path.join(local_dir, file_info['rel_path'])
        create_local_dir(os.path.dirname(local_path))
        
        if sync_file(remote_path, local_path):
            success_count += 1
    
    if verbose:
        print(f"Sync completed: {success_count}/{total_count} files synced successfully")
    
    return success_count == total_count

def get_remote_dir_size(remote_dir):
    """獲取遠端目錄總大小"""
    output = run_adb_command(['shell', 'du', '-sb', remote_dir])
    if output:
        try:
            size = int(output.split()[0])
            return size
        except (ValueError, IndexError):
            print(f"Failed to parse size: {output}")
            return 0
    return 0

def main():
    parser = argparse.ArgumentParser(
        description="ADB-based rsync-like tool: Sync Android folder to local folder (size and mtime only)"
    )
    parser.add_argument('remote_dir', help="Remote Android directory path (e.g., /sdcard/DCIM/Camera)")
    parser.add_argument('local_dir', help="Local destination directory")
    parser.add_argument('-v', '--verbose', action='store_true', help="Verbose output")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be synced without actually doing it")
    parser.add_argument('--list-only', action='store_true', help="Only list files that would be synced")
    
    args = parser.parse_args()
    
    # 驗證 ADB 連接
    devices = run_adb_command(['devices'])
    if not devices or 'device' not in devices:
        print("Error: No Android device connected or ADB not working")
        return 1
    
    print(f"Connected devices: {devices}")
    
    # 驗證遠端目錄存在
    if run_adb_command(['shell', 'test', '-d', args.remote_dir]) is None:
        print(f"Error: Remote directory '{args.remote_dir}' does not exist")
        return 1
    
    # 獲取遠端目錄大小
    dir_size = get_remote_dir_size(args.remote_dir)
    print(f"Remote directory size: {dir_size / (1024*1024):.1f} MB")
    
    # 收集檔案資訊
    print(f"\nCollecting file information...")
    start_time = time.time()
    remote_files = list_remote_dir(args.remote_dir)
    local_files = list_local_dir(args.local_dir)
    
    # 比較檔案
    files_to_sync, total_size = compare_files(remote_files, local_files)
    
    if args.dry_run or args.list_only:
        print(f"\n--- {'Dry run' if args.dry_run else 'List'} mode ---")
        print(f"Would sync from: {args.remote_dir}")
        print(f"         to: {args.local_dir}")
        print(f"Files that would be synced ({len(files_to_sync)} files, {total_size / (1024*1024):.1f} MB):")
        
        if not files_to_sync:
            print("  (No files need to be synced)")
        else:
            for file_info in files_to_sync:
                print(f"  {file_info['path']} ({file_info['size'] / 1024:.1f} KB, mtime: {file_info['mtime']})")
        
        if args.dry_run:
            print("\nNo files were actually synced.")
        return 0
    
    # 開始同步
    print(f"\nStarting sync from '{args.remote_dir}' to '{args.local_dir}'...")
    print(f"Files to sync: {len(files_to_sync)} ({total_size / (1024*1024):.1f} MB)")
    
    start_time = time.time()
    if sync_files(files_to_sync, args.remote_dir, args.local_dir, args.verbose):
        elapsed = time.time() - start_time
        print(f"\nSync completed successfully in {elapsed:.1f} seconds")
        return 0
    else:
        print("\nSync completed with errors")
        return 1

if __name__ == "__main__":
    exit(main())
