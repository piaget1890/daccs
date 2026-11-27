#!/usr/bin/env bash
# 跑单元测试 + 分层依赖检查
#
# 测试使用标准库 unittest 编写（无需额外测试框架），
# pytest 亦可直接收集同一批用例。

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

echo "=== 单元测试 ==="
python -m unittest discover -s tests -t . -v
test_rc=$?

echo
echo "=== 分层依赖检查 ==="
bash scripts/check_layering.sh
layer_rc=$?

echo
if [ "$test_rc" -eq 0 ] && [ "$layer_rc" -eq 0 ]; then
    echo "全部检查通过"
    exit 0
fi
echo "存在失败项（测试 rc=$test_rc，分层 rc=$layer_rc）"
exit 1
