#!/bin/bash
# sync-camera.sh
# 功能: 從 Android 手機的 DCIM/Camera 同步新檔案到本地資料夾

REMOTE_DIR="/sdcard/DCIM/Camera"
LOCAL_DIR="$HOME/Pictures/Camera"  # 修改成你要存放的路徑
CHECK_ONLY=0

show_help() {
    cat <<EOF
用法: $0 [選項]

選項:
  -h, --help     顯示本說明
  -c, --check    只檢查是否有新檔案，列出清單但不下載

說明:
  這個腳本會透過 adb 從手機的 $REMOTE_DIR 目錄
  同步新檔案到本地的 $LOCAL_DIR 目錄。

範例:
  $0
    -> 執行同步

  $0 --check
    -> 只檢查是否有新檔案，列出清單但不下載
EOF
}

# 處理選項
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -c|--check)
            CHECK_ONLY=1
            shift
            ;;
        *)
            echo "未知選項: $1"
            echo "使用 $0 --help 查看說明"
            exit 1
            ;;
    esac
done

# 檢查 adb 是否存在
if ! command -v adb &>/dev/null; then
    echo "錯誤: adb 未安裝或不在 PATH 中"
    exit 1
fi

# 檢查是否有連上裝置
if ! adb get-state 1>/dev/null 2>&1; then
    echo "錯誤: 沒有找到 adb 裝置，請確認已連線"
    exit 1
fi

# 檢查遠端 Camera 目錄是否存在
if ! adb shell "[ -d '$REMOTE_DIR' ]"; then
    echo "錯誤: 遠端目錄 $REMOTE_DIR 不存在"
    exit 1
fi

# 確保本地目錄存在
mkdir -p "$LOCAL_DIR"

# 獲取遠端檔案清單（相對路徑）
adb shell "cd '$REMOTE_DIR' && find . -type f -not -name '.trashed*' -printf '%P\n'" | sort > remote_files.txt

# 獲取本地檔案清單（相對路徑）
find "$LOCAL_DIR" -type f -printf "%P\n" | sort > local_files.txt

# 找出遠端有但本地沒有的檔案
comm -23 remote_files.txt local_files.txt > new_files.txt

if [[ $CHECK_ONLY -eq 1 ]]; then
    if [[ -s new_files.txt ]]; then
        echo "⚠️ 有新的檔案尚未同步："
        cat new_files.txt
    else
        echo "✅ 已經是最新狀態，沒有新檔案"
    fi
else
    # 下載新檔案
    while IFS= read -r file; do
        if [[ -n "$file" ]]; then
            mkdir -p "$LOCAL_DIR/$(dirname "$file")"
            adb pull "$REMOTE_DIR/$file" "$LOCAL_DIR/$file"
        fi
    done < new_files.txt
    echo "同步完成！"
fi

# 清理臨時檔案
rm -f remote_files.txt local_files.txt new_files.txt

