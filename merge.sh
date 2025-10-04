#!/bin/bash
# 用法: ./merge.sh 20250816
# 會合併所有符合 pattern 的 mp4

prefix="$1"

# 清掉舊的清單
rm -f file_list.txt

# 依檔名排序，把符合的 mp4 加進清單
for f in Camera/${prefix}*.mp4; do
    echo "file '$PWD/$f'" >> file_list.txt
done

# 使用 concat 模式合併（不重新編碼）
ffmpeg -f concat -safe 0 -i file_list.txt -c copy "${prefix}_merged.mp4"

