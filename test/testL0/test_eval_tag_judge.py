import sys
import os
import re
import openpyxl

# 获取当前文件所在目录的上三层（到达 a 的父目录）
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(BASE_DIR)
from src import L0_tag_judge



def convert_messages(text):
    if not text or not isinstance(text, str):
        return []

    # 匹配 [用户] 或 [客服] 及其后面的内容，直到下一个标记或文本末尾
    pattern = r'\[(用户|客服)\]\s*(.*?)(?=\n\[(?:用户|客服)\]|$)'
    matches = re.findall(pattern, text, re.DOTALL)

    role_map = {'用户': 'user', '客服': 'assistant'}
    messages = []
    for role_label, content in matches:
        messages.append({
            "role": role_map[role_label],
            "content": content.strip()
        })

    return messages


# ============================================================
# 批量测试 & 结果保存
# ============================================================

# 标签顺序（与 test.xlsx 第2~6列、tag_judge 返回值对齐）
TAG_NAMES = ['manual', 'angry', 'sad', 'urgent', 'non_biz']

# manual 返回 bool，其余 4 个标签返回 [0,1] 概率值
PROB_TAGS = {'angry', 'sad', 'urgent', 'non_biz'}


def _pred_matches_gt(pred_value, ground_truth, tag_name):
    """
    判断单个标签的预测值是否与真值一致。

    - manual: bool vs bool，直接比较
    - angry/sad/urgent/non_biz: float 概率 vs bool，≥0.5 视为 True 后比较
    - 若 pred_value 为 None（异常），返回 False
    """
    if pred_value is None:
        return False
    if tag_name == 'manual':
        return bool(pred_value) == ground_truth
    else:
        return (float(pred_value) >= 0.5) == ground_truth


def process_and_save(input_path=None, output_path=None):
    """
    读取 test.xlsx，逐行转换并调用 tag_judge，将结果保存到 result.xlsx。

    result.xlsx 格式：
        messages | manual | manual' | angry | angry' | sad | sad' |
        urgent | urgent' | non_biz | non_biz' | passed

    其中：
        - manual       = tag_judge 预测值（bool）
        - angry/sad/urgent/non_biz = tag_judge 预测值（float [0,1] 概率）
        - tag'         = test.xlsx 中的标注真值（0/1 → bool）
        - passed       = 当前行全部 5 个标签预测与真值一致则为 True
                        （概率标签以 ≥0.5 为阈值转为 bool 后比较）

    Args:
        input_path:  str, test.xlsx 路径，默认为当前目录下的 test.xlsx
        output_path: str, result.xlsx 路径，默认为当前目录下的 result.xlsx
    """
    if input_path is None:
        input_path = os.path.join(os.path.dirname(__file__), 'test.xlsx')
    if output_path is None:
        output_path = os.path.join(os.path.dirname(__file__), 'result.xlsx')

    # --- 1. 读取 test.xlsx ---
    wb = openpyxl.load_workbook(input_path)
    ws = wb.active

    rows_data = []
    for row in ws.iter_rows(min_row=2, values_only=True):  # 跳过表头
        if row[0] is None:
            continue
        msg_text = str(row[0])
        ground_truth = [bool(v) for v in row[1:6]]  # 第2~6列为真值
        rows_data.append((msg_text, ground_truth))

    print(f"共读取 {len(rows_data)} 条测试数据")

    # --- 2. 逐行检测 ---
    results = []
    for idx, (msg_text, ground_truth) in enumerate(rows_data, 1):
        print(f"\n{'='*60}")
        print(f"处理第 {idx}/{len(rows_data)} 条...")
        print(f"原文预览: {msg_text[:100]}...")

        # 转换格式
        messages = convert_messages(msg_text)
        print(f"  转换后消息数: {len(messages)}")

        # 调用 tag_judge
        try:
            pred = L0_tag_judge.tag_judge_v2(messages)
        except Exception as e:
            print(f"  [ERROR] tag_judge 调用失败: {e}")
            pred = {tag: None for tag in TAG_NAMES}

        # 整理预测结果
        pred_values = [pred.get(tag, None) for tag in TAG_NAMES]

        # 计算 passed：概率标签 ≥0.5 视为 True 后与真值比较
        passed = all(
            _pred_matches_gt(p, g, tag)
            for p, g, tag in zip(pred_values, ground_truth, TAG_NAMES)
        )

        results.append((msg_text, pred_values, ground_truth, passed))

        print(f"  预测: {dict(zip(TAG_NAMES, pred_values))}")
        print(f"  真值: {dict(zip(TAG_NAMES, ground_truth))}")
        print(f"  passed: {passed}")

    # --- 3. 写入 result.xlsx ---
    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active

    # 表头
    headers = ['messages']
    for tag in TAG_NAMES:
        headers.append(tag)       # 预测值列
        headers.append(f"{tag}'")  # 真值列
    headers.append('passed')
    ws_out.append(headers)

    # 数据行
    for msg_text, pred_values, ground_truth, passed in results:
        row = [msg_text]
        for p, g in zip(pred_values, ground_truth):
            row.append(p)
            row.append(g)
        row.append(passed)
        ws_out.append(row)

    # 调整列宽
    ws_out.column_dimensions['A'].width = 60
    for col_letter in ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K']:
        ws_out.column_dimensions[col_letter].width = 12
    ws_out.column_dimensions['L'].width = 10

    wb_out.save(output_path)
    print(f"\n结果已保存到 {output_path}")

    # --- 4. 汇总统计 ---
    total = len(results)
    passed_count = sum(1 for _, _, _, p in results if p)
    print(f"\n总计: {total} 条, 全部通过: {passed_count} 条, 通过率: {passed_count/total*100:.1f}%")

    # --- 5. 错误样本输出 ---
    error_samples = [(msg, pred, gt) for msg, pred, gt, p in results if not p]
    if error_samples:
        print(f"\n{'='*60}")
        print(f"错误样本 ({len(error_samples)} 条):")
        print(f"{'='*60}")
        for i, (msg_text, pred_values, ground_truth) in enumerate(error_samples, 1):
            # 找出不一致的标签（概率标签以 ≥0.5 阈值化后比较）
            mismatch_tags = [
                tag for tag, p, g in zip(TAG_NAMES, pred_values, ground_truth)
                if not _pred_matches_gt(p, g, tag)
            ]
            print(f"\n{'─'*60}")
            print(f"【错误样本 {i}】")
            print(f"样本内容:\n{msg_text}")
            print(f"真值:     {dict(zip(TAG_NAMES, ground_truth))}")
            print(f"预测值:   {dict(zip(TAG_NAMES, pred_values))}")
            print(f"不一致标签: {mismatch_tags}")
    else:
        print(f"\n全部通过，无错误样本。")


# ============================================================
# 直接运行入口
# ============================================================

if __name__ == '__main__':
    process_and_save()

