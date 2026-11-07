"""Plain-text watch replies: hard-coded prompt ban and Markdown stripping."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import app as app_module
from app import (
    DEFAULT_CONFIG,
    NO_MARKDOWN_RULE,
    _build_messages,
    _merge_system_prompt,
    markdown_to_plain,
)


PUNCT_SAMPLE = "你好，世界！这是（测试）：“引号”、分号；省略号……破折号——范围10～20。《书》【注】「引」·中点"


class MarkdownToPlainTest(unittest.TestCase):
    def test_chinese_punctuation_unchanged(self) -> None:
        self.assertEqual(markdown_to_plain(PUNCT_SAMPLE), PUNCT_SAMPLE)

    def test_keeps_math_and_identifiers(self) -> None:
        src = "计算 3*5=15，幂 2**10=1024。\n函数 __init__ 与 snake_case 保留。\na<b 且 C# 语言。"
        self.assertEqual(markdown_to_plain(src), src)

    def test_strips_common_markdown(self) -> None:
        src = (
            "# 标题\n"
            "**加粗** 和 *斜体*\n"
            "- 第一项\n"
            "1. 第二项\n"
            "> 引用\n"
            "`代码`\n"
            "[链接](https://example.com)\n"
            "~~删除~~"
        )
        plain = markdown_to_plain(src)
        self.assertNotIn("**", plain)
        self.assertNotIn("*", plain)
        self.assertNotIn("#", plain)
        self.assertNotIn("`", plain)
        self.assertNotIn("~~", plain)
        self.assertIn("标题", plain)
        self.assertIn("加粗", plain)
        self.assertIn("斜体", plain)
        self.assertIn("第一项", plain)
        self.assertIn("第二项", plain)
        self.assertIn("引用", plain)
        self.assertIn("代码", plain)
        self.assertIn("链接", plain)
        self.assertIn("删除", plain)
        self.assertNotIn("https://", plain)

    def test_lone_and_nested_emphasis(self) -> None:
        self.assertEqual(markdown_to_plain("这是**未闭合"), "这是未闭合")
        self.assertEqual(markdown_to_plain("**只有开头"), "只有开头")
        self.assertEqual(markdown_to_plain("结尾**"), "结尾")
        self.assertEqual(markdown_to_plain("***重点***"), "重点")
        self.assertEqual(markdown_to_plain("**外层 *内层* 文字**"), "外层 内层 文字")
        self.assertEqual(markdown_to_plain("**答案：** 42"), "答案： 42")
        self.assertNotIn("**", markdown_to_plain("hello ** world ** end"))

    def test_fullwidth_markers(self) -> None:
        self.assertEqual(markdown_to_plain("＊＊重点＊＊"), "重点")
        self.assertEqual(markdown_to_plain("＃ 标题"), "标题")
        self.assertEqual(markdown_to_plain("＃＃小结"), "小结")
        self.assertEqual(markdown_to_plain("＞ 引用一句"), "引用一句")
        self.assertEqual(markdown_to_plain("－ 项目"), "项目")

    def test_lists_do_not_eat_decimals(self) -> None:
        self.assertEqual(markdown_to_plain("3.14是圆周率"), "3.14是圆周率")
        self.assertEqual(markdown_to_plain("1、先算斜率"), "先算斜率")
        self.assertEqual(markdown_to_plain("10、20 之间"), "10、20 之间")
        self.assertEqual(markdown_to_plain("（1）集合 A={1,2,3}"), "（1）集合 A={1,2,3}")
        self.assertEqual(markdown_to_plain("·乔治·奥威尔"), "·乔治·奥威尔")
        self.assertEqual(markdown_to_plain("· 项目一"), "项目一")

    def test_table_code_and_html(self) -> None:
        src = (
            "| 列1 | 列2 |\n"
            "| --- | --- |\n"
            "| 甲 | 乙 |\n"
            "\n"
            "```python\n"
            "print(2**10)\n"
            "```\n"
            "<b>加粗</b><br>下一行"
        )
        plain = markdown_to_plain(src)
        self.assertIn("列1 列2", plain)
        self.assertIn("甲 乙", plain)
        self.assertNotIn("---", plain)
        self.assertIn("print(2**10)", plain)
        self.assertNotIn("```", plain)
        self.assertIn("加粗", plain)
        self.assertNotIn("<b>", plain)
        self.assertIn("下一行", plain)

    def test_keeps_inequalities_and_preprocessor(self) -> None:
        self.assertEqual(markdown_to_plain("当 a < b 且 a < b > c 时"), "当 a < b 且 a < b > c 时")
        self.assertEqual(markdown_to_plain("a<b>"), "a<b>")
        self.assertEqual(markdown_to_plain("#include <stdio.h>"), "#include <stdio.h>")
        self.assertEqual(markdown_to_plain("#标题"), "标题")
        self.assertEqual(markdown_to_plain("# 标题"), "标题")
        self.assertEqual(markdown_to_plain("普通*号 与 文件_名"), "普通*号 与 文件_名")
        self.assertEqual(markdown_to_plain("第一行<br>第二行"), "第一行\n第二行")

    def test_preserves_line_breaks(self) -> None:
        src = "结论：5/6。\n\n步骤：\n把 1/2 和 1/3 化成 3/6 和 2/6。"
        self.assertEqual(markdown_to_plain(src), src)


class SystemPromptTest(unittest.TestCase):
    def test_default_prompt_includes_rule(self) -> None:
        self.assertIn(NO_MARKDOWN_RULE, DEFAULT_CONFIG["system_prompt"])
        self.assertIn("手表小屏", DEFAULT_CONFIG["system_prompt"])

    def test_merge_always_appends_and_does_not_duplicate(self) -> None:
        self.assertEqual(_merge_system_prompt(""), NO_MARKDOWN_RULE)
        self.assertEqual(_merge_system_prompt("   "), NO_MARKDOWN_RULE)
        merged = _merge_system_prompt("只回答是")
        self.assertTrue(merged.startswith("只回答是"))
        self.assertIn(NO_MARKDOWN_RULE, merged)
        self.assertEqual(merged.count(NO_MARKDOWN_RULE), 1)
        self.assertEqual(_merge_system_prompt(merged), merged)
        self.assertEqual(_merge_system_prompt(DEFAULT_CONFIG["system_prompt"]), DEFAULT_CONFIG["system_prompt"].strip())

    def test_build_messages_injects_rule_even_if_prompt_omits_it(self) -> None:
        messages = _build_messages(
            {"system_prompt": "回答尽量短。"},
            {"messages": [{"role": "user", "content": "1+1"}]},
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("回答尽量短。", messages[0]["content"])
        self.assertIn(NO_MARKDOWN_RULE, messages[0]["content"])
        self.assertEqual(messages[1], {"role": "user", "content": "1+1"})

    def test_empty_prompt_still_sends_rule(self) -> None:
        messages = _build_messages(
            {"system_prompt": ""},
            {"prompt": "你好"},
        )
        self.assertEqual(messages[0]["content"], NO_MARKDOWN_RULE)
        self.assertEqual(messages[1]["role"], "user")

    def test_client_system_message_also_gets_rule(self) -> None:
        messages = _build_messages(
            {"system_prompt": "控制台提示"},
            {"messages": [{"role": "system", "content": "请用 markdown"}, {"role": "user", "content": "hi"}]},
        )
        self.assertEqual(messages[1]["role"], "system")
        self.assertIn(NO_MARKDOWN_RULE, messages[1]["content"])
        self.assertIn("请用 markdown", messages[1]["content"])


class ChatFormatTest(unittest.TestCase):
    """Watch plain path strips markers; the console markdown/stream path does not."""

    def setUp(self) -> None:
        self.client = TestClient(app_module.app)
        self.cfg = {
            "autodl_api_key": "test-key",
            "autodl_base_url": "https://example.invalid/api/v1",
            "model": "DeepSeek-V4-Flash",
            "system_prompt": "只回答短句。",
            "max_tokens": 200,
            "temperature": 0.2,
            "device_key": "device-test",
        }
        self.headers = {"X-WristAI-Key": "device-test"}
        self.upstream_payloads: list[dict] = []

    def _fake_post(self, content: str):
        async def fake(client, url, headers, payload):  # noqa: ARG001
            self.upstream_payloads.append(payload)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

        return fake

    def test_plain_strips_and_always_sends_rule(self) -> None:
        with patch.object(app_module, "_load_config", return_value=self.cfg), patch.object(
            app_module, "_post_autodl_json", self._fake_post("**答案：** 42")
        ):
            response = self.client.post(
                "/wristai/api/chat",
                headers=self.headers,
                json={"messages": [{"role": "user", "content": "1+1"}], "stream": False, "format": "plain"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["format"], "plain")
        self.assertEqual(body["content"], "答案： 42")
        self.assertEqual(body["content_markdown"], "**答案：** 42")
        system = self.upstream_payloads[0]["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("只回答短句。", system["content"])
        self.assertIn(NO_MARKDOWN_RULE, system["content"])

    def test_markdown_json_keeps_markers(self) -> None:
        with patch.object(app_module, "_load_config", return_value=self.cfg), patch.object(
            app_module, "_post_autodl_json", self._fake_post("**答案：** 42")
        ):
            response = self.client.post(
                "/wristai/api/chat",
                headers=self.headers,
                json={"messages": [{"role": "user", "content": "1+1"}], "stream": False, "format": "markdown"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["format"], "markdown")
        self.assertEqual(body["content"], "**答案：** 42")
        self.assertEqual(body["content_plain"], "答案： 42")

    def test_console_stream_passes_markdown_through(self) -> None:
        captured: list[dict] = []

        class FakeStream:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def aiter_text(self):
                event = {
                    "choices": [{"index": 0, "delta": {"content": "**加粗**"}, "finish_reason": "stop"}]
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            async def aread(self):
                return b""

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def stream(self, method, url, headers=None, json=None):  # noqa: A002, ARG002
                captured.append(json)
                return FakeStream()

        with patch.object(app_module, "_load_config", return_value=self.cfg), patch.object(
            app_module.httpx, "AsyncClient", FakeClient
        ):
            response = self.client.post(
                "/wristai/api/chat",
                headers=self.headers,
                json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn("**加粗**", response.text)
        self.assertIn(NO_MARKDOWN_RULE, captured[0]["messages"][0]["content"])

    def test_chat_still_requires_device_key(self) -> None:
        with patch.object(app_module, "_load_config", return_value=self.cfg):
            response = self.client.post(
                "/wristai/api/chat",
                json={"messages": [{"role": "user", "content": "hi"}], "stream": False},
            )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
