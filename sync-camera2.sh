#!/bin/bash

# 設定路徑
REMOTE_DIR="/sdcard/DCIM/Camera"
LOCAL_DIR="$HOME/Pictures/Camera"  # 替換成你的本地路徑

# 確保本地目錄存在
mkdir -p "$LOCAL_DIR"

# 獲取遠端檔案清單（相對路徑）
adb shell "find $REMOTE_DIR -type f -not -name '.trashed*' -printf '%P\n'" | sort > remote_files.txt

# 獲取本地檔案清單（相對路徑）
find "$LOCAL_DIR" -type f -printf "%P\n" | sort > local_files.txt

# 找出遠端有但本地沒有的檔案
comm -23 remote_files.txt local_files.txt > new_files.txt

# 下載新檔案
while IFS= read -r file; do
    if [ -n "$file" ]; then
        adb pull "$REMOTE_DIR/$file" "$LOCAL_DIR/$file"
    fi
done < new_files.txt

# 清理臨時檔案
rm remote_files.txt local_files.txt new_files.txt

echo "同步完成！"
