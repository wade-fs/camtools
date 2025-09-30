#!/usr/bin/python3
import os
import subprocess
import argparse
import hashlib
import time
from pathlib import Path

def run_adb_command(command, check=True):
    """執行 ADB 命令並返回結果"""
    try:
        result = subprocess.run(['adb'] + command, 
                              capture_output=True, text=True, check=check)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"ADB command failed: {' '.join(command)}")
        print(f"Error: {e.stderr}")
        return None

def list_remote_dir(remote_path, recursive=False):
    """列出 Android 設備上的遠端目錄內容"""
    cmd = ['shell', 'ls', '-la', remote_path]
    output = run_adb_command(cmd)
    if not output:
        print(f"No output from ls command for {remote_path}")
        return []
    
    lines = output.split('\n')[1:]  # 跳過第一行 (總計)
    files = []
    for line in lines:
        if line.strip():
            parts = line.split(maxsplit=8)
            if len(parts) >= 8:
                permissions = parts[0]
                size = parts[4]
                name = parts[7] if len(parts) == 8 else ' '.join(parts[7:])  # 處理檔名中有空格
                if name in ('.', '..'):
                    continue
                files.append({
                    'name': name,
                    'size': int(size) if size.isdigit() else 0,
                    'permissions': permissions,
                    'mtime': parts[5] + ' ' + parts[6] + ' ' + parts[7] if len(parts) >= 8 else '',
                    'path': os.path.join(remote_path, name).replace('\\', '/')
                })
    
    # 如果需要遞歸，處理子目錄
    if recursive:
        sub_files = []
        for file_info in files:
            if file_info['permissions'].startswith('d'):
                sub_files.extend(list_remote_dir(file_info['path'], recursive=True))
        files.extend(sub_files)
    
    return files

def get_remote_file_hash(remote_path):
    """獲取遠端檔案的 MD5 雜湊值"""
    output = run_adb_command(['shell', 'md5sum', remote_path])
    if output and not output.startswith('No such'):
        return output.split()[0]
    return None

def get_local_file_hash(local_path):
    """獲取本地檔案的 MD5 雜湊值"""
    hasher = hashlib.md5()
    try:
        with open(local_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except FileNotFoundError:
        return None

def create_local_dir(local_path):
    """創建本地目錄"""
    Path(local_path).mkdir(parents=True, exist_ok=True)

def sync_file(remote_path, local_path):
    """同步單個檔案"""
    print(f"  Syncing: {os.path.basename(remote_path)}")
    
    # 檢查本地檔案是否存在且雜湊值相同
    if os.path.exists(local_path):
        remote_hash = get_remote_file_hash(remote_path)
        local_hash = get_local_file_hash(local_path)
        
        if remote_hash and local_hash and remote_hash == local_hash:
            print(f"  Up-to-date: {os.path.basename(remote_path)}")
            return True
    
    # 使用 adb pull 同步檔案
    result = run_adb_command(['pull', remote_path, local_path], check=False)
    if result is None:
        print(f"  Failed to pull: {os.path.basename(remote_path)}")
        return False
    
    print(f"  Successfully pulled: {os.path.basename(remote_path)}")
    return True

def sync_directory(remote_dir, local_dir, verbose=False):
    """遞歸同步目錄"""
    create_local_dir(local_dir)
    
    if verbose:
        print(f"Scanning: {remote_dir}")
    
    # 獲取遠端目錄內容
    remote_files = list_remote_dir(remote_dir)
    
    if not remote_files:
        print(f"No files found in {remote_dir}")
        return False
    
    success_count = 0
    total_count = 0
    
    for file_info in remote_files:
        remote_file_path = file_info['path']
        local_file_path = os.path.join(local_dir, file_info['name'])
        
        total_count += 1
        
        if file_info['permissions'].startswith('d'):  # 目錄
            if verbose:
                print(f"  Entering directory: {file_info['name']}")
            if not sync_directory(remote_file_path, local_file_path, verbose):
                print(f"  Failed to sync directory: {file_info['name']}")
            else:
                success_count += 1
        else:  # 檔案
            if not sync_file(remote_file_path, local_file_path):
                print(f"  Failed to sync file: {file_info['name']}")
            else:
                success_count += 1
    
    if verbose:
        print(f"Directory {remote_dir}: {success_count}/{total_count} items synced successfully")
    
    return success_count == total_count

def get_remote_dir_size(remote_dir):
    """獲取遠端目錄總大小（近似）"""
    output = run_adb_command(['shell', 'du', '-sh', remote_dir])
    if output:
        parts = output.split('\t')
        if len(parts) >= 2:
            size_str = parts[0]
            try:
                if size_str.endswith('K'):
                    size = float(size_str[:-1]) * 1024
                elif size_str.endswith('M'):
                    size = float(size_str[:-1]) * 1024 * 1024
                elif size_str.endswith('G'):
                    size = float(size_str[:-1]) * 1024 * 1024 * 1024
                else:
                    size = float(size_str)
                return size
            except ValueError:
                print(f"Failed to parse size: {size_str}")
                return 0
    return 0

def main():
    parser = argparse.ArgumentParser(
        description="ADB-based rsync-like tool: Sync Android folder to local folder"
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
    
    if args.dry_run or args.list_only:
        print(f"\n--- {'Dry run' if args.dry_run else 'List'} mode ---")
        print(f"Would sync from: {args.remote_dir}")
        print(f"         to: {args.local_dir}")
        print("Files that would be synced:")
        
        # 遞歸列出所有檔案
        files_to_sync = list_remote_dir(args.remote_dir, recursive=True)
        if not files_to_sync:
            print("  (No files found)")
        else:
            for file_info in files_to_sync:
                if not file_info['permissions'].startswith('d'):
                    print(f"  {file_info['path']}")
        
        if args.dry_run:
            print("\nNo files were actually synced.")
        return 0
    
    # 開始同步
    start_time = time.time()
    print(f"\nStarting sync from '{args.remote_dir}' to '{args.local_dir}'...")
    
    if sync_directory(args.remote_dir, args.local_dir, args.verbose):
        elapsed = time.time() - start_time
        print(f"\nSync completed successfully in {elapsed:.1f} seconds")
        return 0
    else:
        print("\nSync completed with errors")
        return 1

if __name__ == "__main__":
    exit(main())
