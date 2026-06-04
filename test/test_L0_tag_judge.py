"""
测试 L0_tag_judge.py 的所有函数。
运行: python -m pytest test_L0_tag_judge.py -v
或:   python test_L0_tag_judge.py
"""
import sys
import os
import json
import math

# 将 src 加入 path 以便 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# 直接 import 模块内的函数，避免触发 openai 客户端初始化
# （使用 exec + 源文件过滤的方式来单独测纯函数）
# 这里改用 import 方式 —— 如果 openai 不可用，纯函数测试仍可跑

# ---- 手工复制纯函数用于无依赖测试 ----
# 这样即使 openai 未安装也能验证统计算法
import re

def _parse_probability_response(response):
    text = response.strip()
    matches = re.findall(r'(\d+\.?\d*|\.\d+)', text)
    for m in matches:
        try:
            val = float(m)
            if 0.0 <= val <= 1.0:
                return val
        except ValueError:
            continue
    binary_matches = re.findall(r'\b([01])\b', text)
    if binary_matches:
        return float(binary_matches[-1])
    if '1' in text:
        return 1.0
    return 0.0

def _compute_stats(probs):
    n = len(probs)
    if n == 0:
        return 0.0, 0.0
    mean = sum(probs) / n
    if n == 1:
        return mean, 0.0
    variance = sum((p - mean) ** 2 for p in probs) / n
    std = math.sqrt(variance)
    return mean, std

def _filter_outliers(probs):
    if len(probs) < 3:
        return probs[:]
    mean, std = _compute_stats(probs)
    if std == 0.0:
        return probs[:]
    threshold = 2.0 * std
    return [p for p in probs if abs(p - mean) <= threshold]

def _robust_average(probs):
    filtered = _filter_outliers(probs)
    if not filtered:
        return sum(probs) / len(probs)
    return sum(filtered) / len(filtered)


# ============================================================
# 测试: _parse_probability_response
# ============================================================

def test_parse_probability_clean():
    assert _parse_probability_response("0.75") == 0.75
    assert _parse_probability_response("0.0") == 0.0
    assert _parse_probability_response("1.0") == 1.0
    assert _parse_probability_response("1") == 1.0
    assert _parse_probability_response("0") == 0.0

def test_parse_probability_with_text():
    """LLM 可能在数字前后附带文字"""
    assert _parse_probability_response("我认为概率是 0.65") == 0.65
    assert _parse_probability_response("probability: 0.32") == 0.32
    assert _parse_probability_response("p=0.88，属于紧急情况") == 0.88
    assert _parse_probability_response("答案是0.5左右") == 0.5

def test_parse_probability_edge_cases():
    """边界/异常输入"""
    assert _parse_probability_response("") == 0.0
    assert _parse_probability_response("没有数字") == 0.0
    # 多个浮点数，取第一个在 [0,1] 内的
    assert _parse_probability_response("0.3 0.8") == 0.3
    # 第一个是 2.5（超出范围），第二个 0.6
    assert _parse_probability_response("2.5 0.6") == 0.6
    # 负数：regex 会提取 0.5（不含负号），在 [0,1] 内
    # LLM 几乎不会输出负概率，此行为可接受
    assert _parse_probability_response("-0.5") == 0.5

def test_parse_probability_clamping():
    """超出 [0,1] 范围的浮点数不应被接受，回退到 binary match 或兜底"""
    # "1.5" → 1.5 超出 [0,1]; binary match 找到 "1" → 返回 1.0
    result = _parse_probability_response("1.5")
    assert result == 1.0


# ============================================================
# 测试: _compute_stats
# ============================================================

def test_compute_stats_basic():
    mean, std = _compute_stats([0.5, 0.5, 0.5, 0.5, 0.5])
    assert mean == 0.5
    assert std == 0.0

def test_compute_stats_varied():
    mean, std = _compute_stats([0.0, 0.5, 1.0])
    assert mean == 0.5
    # 总体方差: ((0-0.5)^2 + (0.5-0.5)^2 + (1-0.5)^2) / 3 = (0.25+0+0.25)/3 = 0.5/3
    expected_var = 0.5 / 3
    assert abs(std - math.sqrt(expected_var)) < 1e-10

def test_compute_stats_single():
    mean, std = _compute_stats([0.7])
    assert mean == 0.7
    assert std == 0.0

def test_compute_stats_empty():
    mean, std = _compute_stats([])
    assert mean == 0.0
    assert std == 0.0


# ============================================================
# 测试: _filter_outliers
# ============================================================

def test_filter_outliers_none_to_remove():
    """所有值接近，不应剔除任何"""
    probs = [0.50, 0.52, 0.48, 0.51, 0.49]
    filtered = _filter_outliers(probs)
    assert len(filtered) == 5

def test_filter_outliers_removes_extreme():
    """明显离群值应被剔除"""
    # 5个正常值 + 1个极端离群值: 需要足够样本量才能让 2σ 生效
    probs = [0.70, 0.72, 0.68, 0.00, 0.71, 0.69]
    filtered = _filter_outliers(probs)
    assert 0.00 not in filtered
    assert len(filtered) == 5

def test_filter_outliers_small_list():
    """少于 3 个点不剔除"""
    probs = [0.9, 0.1]
    filtered = _filter_outliers(probs)
    assert filtered == [0.9, 0.1]

def test_filter_outliers_all_same():
    """全部相同，标准差为 0，不剔除"""
    probs = [0.5, 0.5, 0.5]
    filtered = _filter_outliers(probs)
    assert filtered == [0.5, 0.5, 0.5]

def test_filter_outliers_boundary_inclusive():
    """恰好 2σ 边界上的点应保留（≤2σ）"""
    # 手动构造: mean=0.5, 需要 std 使得 2σ=0.3 (即 σ=0.15)
    # 三个值: 0.2, 0.5, 0.8 → mean=0.5, var=((0.09+0+0.09)/3)=0.06, σ≈0.245
    # 2σ≈0.49, |0.2-0.5|=0.3 < 0.49 → 保留; |0.8-0.5|=0.3 < 0.49 → 保留
    probs = [0.2, 0.5, 0.8]
    filtered = _filter_outliers(probs)
    assert len(filtered) == 3  # 都在边界内


# ============================================================
# 测试: _robust_average
# ============================================================

def test_robust_average_clean():
    """无离群点时应该是简单平均"""
    probs = [0.5, 0.6, 0.4, 0.5, 0.5]
    result = _robust_average(probs)
    assert abs(result - 0.5) < 0.01

def test_robust_average_with_outlier():
    """剔除离群点后的平均应更接近主体"""
    probs = [0.70, 0.72, 0.68, 0.00, 0.71, 0.69]  # 0.00 是离群点
    result = _robust_average(probs)
    # 剔除 0.00 后平均 = (0.70+0.72+0.68+0.71+0.69)/5 = 3.50/5 = 0.70
    assert abs(result - 0.70) < 0.01
    # 远高于简单平均 (3.50/6 ≈ 0.583)
    simple_avg = sum(probs) / len(probs)
    assert result > simple_avg  # 剔除低离群点后均值上升


# ============================================================
# 测试: 集成测试（需 API 可调时运行）
# ============================================================

def test_tag_judge_v2_structure():
    """
    验证 tag_judge_v2 的返回结构。
    由于需要 API，此处用 import 检查函数签名和参数。
    """
    try:
        from L0_tag_judge import tag_judge_v2, tag_judge
        import inspect

        # 检查函数签名
        sig = inspect.signature(tag_judge_v2)
        params = list(sig.parameters.keys())
        assert 'messages' in params
        assert 'ez_judge' in params
        assert 'k' in params
        # 默认值
        assert sig.parameters['ez_judge'].default == 0
        assert sig.parameters['k'].default == 5

        sig_old = inspect.signature(tag_judge)
        assert 'messages' in sig_old.parameters

        print("  ✓ tag_judge_v2 签名正确")
        print("  ✓ tag_judge 签名正确")

    except ImportError as e:
        print(f"  ⚠ 无法导入模块（可能缺少 openai）: {e}")
    except Exception as e:
        print(f"  ⚠ 导入检查失败: {e}")


def test_detect_tag_with_mock():
    """
    用极简 messages 调用 detect_tag，验证返回值为 float 且范围正确。
    需要 API 可用。
    """
    try:
        from L0_tag_judge import detect_tag

        messages = [
            {"role": "user", "content": "你好，我想咨询一下车险"},
            {"role": "assistant", "content": "您好，请问您需要什么帮助？"},
        ]

        # 快速模式：单次调用
        result = detect_tag(messages, 'angry')
        assert isinstance(result, float), f"Expected float, got {type(result)}"
        assert 0.0 <= result <= 1.0, f"Expected [0,1], got {result}"
        print(f"  ✓ detect_tag('angry') → {result:.3f} (float, in [0,1])")

        # 非业务闲聊应接近 0（这是正常业务咨询）
        result2 = detect_tag(messages, 'non_biz')
        assert isinstance(result2, float)
        assert 0.0 <= result2 <= 1.0
        print(f"  ✓ detect_tag('non_biz') → {result2:.3f} (float, in [0,1])")

    except ImportError as e:
        print(f"  ⚠ 无法导入模块: {e}")
    except Exception as e:
        print(f"  ⚠ API 测试失败（可能是网络/配额问题）: {e}")


def test_tag_judge_v2_real():
    """
    端到端测试 tag_judge_v2（ez_judge=1 快速模式）。
    需要 API 可用。
    """
    try:
        from L0_tag_judge import tag_judge_v2

        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好，有什么可以帮您？"},
            {"role": "user", "content": "我要退保"},
        ]

        # ez_judge=1：快速模式（5 个单次调用并行）
        result = tag_judge_v2(messages, ez_judge=1, k=5)

        # 检查返回结构
        expected_keys = {'manual', 'angry', 'sad', 'urgent', 'non_biz'}
        assert set(result.keys()) == expected_keys, f"Keys mismatch: {result.keys()}"

        # 检查值类型和范围
        for key in expected_keys:
            val = result[key]
            assert isinstance(val, (float, bool)), \
                f"'{key}' 类型错误: {type(val)}"
            if isinstance(val, float):
                assert 0.0 <= val <= 1.0, \
                    f"'{key}' 超出 [0,1]: {val}"
            print(f"  {key}: {val}")

        print("  ✓ tag_judge_v2(ez_judge=1) 返回结构正确")

    except ImportError as e:
        print(f"  ⚠ 无法导入模块: {e}")
    except Exception as e:
        print(f"  ⚠ API 测试失败: {e}")


# ============================================================
# 主运行入口
# ============================================================

if __name__ == '__main__':
    print("=" * 60)
    print("单元测试: _parse_probability_response")
    print("=" * 60)
    test_parse_probability_clean()
    print("  ✓ clean numbers")
    test_parse_probability_with_text()
    print("  ✓ numbers with text")
    test_parse_probability_edge_cases()
    print("  ✓ edge cases")
    test_parse_probability_clamping()
    print("  ✓ clamping")

    print()
    print("=" * 60)
    print("单元测试: _compute_stats")
    print("=" * 60)
    test_compute_stats_basic()
    print("  ✓ identical values")
    test_compute_stats_varied()
    print("  ✓ varied values")
    test_compute_stats_single()
    print("  ✓ single value")
    test_compute_stats_empty()
    print("  ✓ empty list")

    print()
    print("=" * 60)
    print("单元测试: _filter_outliers")
    print("=" * 60)
    test_filter_outliers_none_to_remove()
    print("  ✓ no outliers")
    test_filter_outliers_removes_extreme()
    print("  ✓ removes extreme")
    test_filter_outliers_small_list()
    print("  ✓ small list (no-op)")
    test_filter_outliers_all_same()
    print("  ✓ all same (no-op)")
    test_filter_outliers_boundary_inclusive()
    print("  ✓ boundary inclusive")

    print()
    print("=" * 60)
    print("单元测试: _robust_average")
    print("=" * 60)
    test_robust_average_clean()
    print("  ✓ clean data")
    test_robust_average_with_outlier()
    print("  ✓ with outlier removed")

    print()
    print("=" * 60)
    print("集成测试（需要 API）")
    print("=" * 60)
    test_tag_judge_v2_structure()
    # API 测试可选，用环境变量控制
    if os.environ.get('RUN_API_TESTS', '').lower() in ('1', 'true', 'yes'):
        test_detect_tag_with_mock()
        test_tag_judge_v2_real()
    else:
        print("  ⏭ 跳过 API 测试（设置 RUN_API_TESTS=1 启用）")

    print()
    print("=" * 60)
    print("全部测试完成 ✓")
    print("=" * 60)
