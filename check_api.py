import os
import time
from pathlib import Path

from dotenv import load_dotenv
from zhipuai import ZhipuAI

# 1. 加载环境变量（优先项目根目录 .env）
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)


def _load_api_key() -> str | None:
    """
    从环境或 .env 文件中读取智谱 API Key。

    优先读取环境变量，其次手动解析当前目录下的 .env 文件，兼容：
      - ZHIPUAI_API_KEY（推荐）
      - ZHIPU_API_KEY（旧版）
    """
    api_key = os.getenv("ZHIPUAI_API_KEY") or os.getenv("ZHIPU_API_KEY")
    if api_key:
        return api_key

    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return None

    try:
        # 不指定 encoding，使用系统默认编码（在你的 Windows 上通常是 gbk）
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("ZHIPUAI_API_KEY=") or line.startswith("ZHIPU_API_KEY="):
                name, value = line.split("=", 1)
                value = value.strip()
                if value:
                    os.environ[name] = value
                    return value
    except Exception:
        # 解析失败时静默返回 None
        return None

    return None


def test_zhipu_connection():
    # 从 .env 获取 Key，如果没有则提醒用户输入
    api_key = _load_api_key()

    # 避免 Windows GBK 终端的 emoji 编码问题，这里全部使用纯文本
    print("--- 智谱 AI 连通性测试开始 ---")

    if not api_key:
        print("错误：未能从环境变量或 .env 文件中读取 ZHIPUAI_API_KEY / ZHIPU_API_KEY")
        return

    print(f"正在尝试连接... (使用的 Key 前段: {api_key[:6]}******)")

    # 2. 核心测试逻辑
    try:
        # 设置较短的超时时间，快速反馈结果
        client = ZhipuAI(api_key=api_key)

        start_time = time.time()

        # 使用最轻量的 flash 模型进行低成本测试
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {"role": "user", "content": "你好，请回复'连接成功'四个字。"}
            ],
            timeout=10,  # 10秒超时
        )

        end_time = time.time()
        content = response.choices[0].message.content

        print("【成功】智谱 AI 响应正常！")
        print(f"响应耗时: {end_time - start_time:.2f} 秒")
        print(f"AI 回复: {content}")

    except Exception as e:
        print("\n【失败】无法连接到智谱 AI")
        error_msg = str(e)
        print(f"具体报错详情: {error_msg}")

        # 3. 针对性建议
        print("\n排错建议：")
        lower_msg = error_msg.lower()
        if "timeout" in lower_msg:
            print("   -> 检测到超时。请检查是否开启了全局 VPN？智谱是国内模型，建议关闭 VPN 后重试。")
        elif "401" in lower_msg or "unauthorized" in lower_msg:
            print("   -> 鉴权失败。请检查 API Key 是否复制完整，或是否已欠费/过期。")
        elif "connection" in lower_msg:
            print("   -> 网络连接中断。请检查你的本地网络是否正常。")
        else:
            print("   -> 请检查 .env 文件格式是否正确，Key 后面不要带引号或空格。")

def _load_serpapi_key() -> str | None:
    """从环境或 .env 读取 SERPAPI_KEY（兼容多种编码）"""
    api_key = os.getenv("SERPAPI_KEY") or os.getenv("SERPAPI_API_KEY")
    if api_key:
        return api_key
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            raw = env_path.read_text(encoding=enc)
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("SERPAPI_KEY=") or line.startswith("SERPAPI_API_KEY="):
                    _, val = line.split("=", 1)
                    val = val.strip().strip('"').strip("'")
                    if val:
                        return val
            break
        except Exception:
            continue
    return None


def test_serpapi_connection():
    """测试 SerpApi 连通性"""
    api_key = _load_serpapi_key()
    print("\n--- SerpApi 连通性测试 ---")

    if not api_key:
        print("错误: 未找到 SERPAPI_KEY (请检查 .env 中是否配置)")
        return

    print(f"Key 前段: {api_key[:8]}******")

    try:
        from serpapi import GoogleSearch

        # 使用最轻量的请求测试（Google 搜索一条简单查询）
        params = {
            "engine": "google",
            "q": "SerpApi test",
            "api_key": api_key,
        }
        search = GoogleSearch(params)
        result = search.get_dict()

        if result.get("search_metadata", {}).get("status") == "Success":
            print("【成功】SerpApi 连接正常！")
            print("可正常使用 Google Scholar、百度学术等检索。")
        elif "error" in result:
            print("【失败】SerpApi 返回错误:", result.get("error", "未知"))
        else:
            print("【异常】响应格式异常:", str(result)[:200])
    except Exception as e:
        print("【失败】无法连接 SerpApi")
        print(f"详情: {e}")
        err = str(e).lower()
        if "401" in err or "invalid" in err:
            print("建议: 检查 API Key 是否正确、是否已过期")
        elif "timeout" in err or "connection" in err:
            print("建议: 检查网络/代理，SerpApi 需访问 serpapi.com")


if __name__ == "__main__":
    test_zhipu_connection()
    test_serpapi_connection()