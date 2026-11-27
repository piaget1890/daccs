#!/usr/bin/env bash
# 分层依赖检查（NFR-3 / NFR-7 / NFR-5）
#
# 三条硬约束：
#   1. 只有 ui 层允许 import GUI 框架；
#   2. algorithm 层不得依赖其他内部层（只允许 core.types）；
#   3. 全局不得引入网络调用（NFR-5：不联网、不上传）。
#
# 用法：bash scripts/check_layering.sh

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

status=0

echo "== 1. GUI 框架依赖边界 =="
if grep -rnE "^[[:space:]]*(import|from)[[:space:]]+PySide6" daccs --include="*.py" \
    | grep -v "^daccs/ui/"; then
    echo "   ✗ ui 层之外出现了 PySide6 依赖"
    status=1
else
    echo "   ✓ 仅 daccs/ui/ 依赖 PySide6"
fi

echo "== 2. 算法层依赖边界 =="
if grep -rn "^from \.\." daccs/algorithm --include="*.py" | grep -v "core\.types"; then
    echo "   ✗ algorithm 层出现了越层依赖"
    status=1
else
    echo "   ✓ algorithm 层仅依赖 core.types"
fi

echo "== 3. 网络调用检查 =="
if grep -rnE "^[[:space:]]*(import|from)[[:space:]]+(requests|urllib|http|socket)" \
    daccs --include="*.py"; then
    echo "   ✗ 检测到网络调用，违反 NFR-5"
    status=1
else
    echo "   ✓ 无网络调用"
fi

echo "== 4. 存储写入只追加 =="
if grep -rn "open(.*['\"]w['\"]" daccs/storage --include="*.py" \
    | grep -v "report.py"; then
    echo "   ✗ storage 层出现覆盖式写入（原始数据只追加，NFR-5）"
    status=1
else
    echo "   ✓ storage 采样写入为追加式"
fi

if [ "$status" -eq 0 ]; then
    echo
    echo "分层依赖检查全部通过"
fi
exit "$status"
