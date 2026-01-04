DATE=$1
if [ -z "$DATE" ]; then
    DATE=$(date +'%Y%m%d')
else
    if [[ ! "$DATE" =~ ^[0-9]{8}$ ]]; then
        echo "錯誤: 日期格式不正確。"
        echo "請使用 YYYYMMDD 格式 (例如: 20260103)"
        exit 1
    fi
    
    if ! date -d "$DATE" "+%Y%m%d" >/dev/null 2>&1; then
        echo "錯誤: $DATE 不是一個有效的日期。"
        exit 1
    fi
fi
./camera.py --sync
./camera.py -m -f "${DATE}*"
./camera.py -s 179 -f ${DATE}-merge.mp4
