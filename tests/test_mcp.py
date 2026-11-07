import io
import json
import shutil
import unittest

from blastr import mcp
from support import AFTER, BEFORE, make_patch, make_repo


def roundtrip(payloads):
    stdin = io.StringIO("\n".join(json.dumps(item) for item in payloads) + "\n")
    stdout = io.StringIO()
    mcp.serve(stdin, stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


class McpTest(unittest.TestCase):
    def test_initialize_tools_list_and_notification(self):
        responses = roundtrip(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            ]
        )
        self.assertEqual(len(responses), 2, "notifications must not be answered")
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "blastr")
        self.assertEqual(responses[1]["result"]["tools"][0]["name"], "blast_radius")

    def test_tool_call_returns_markdown(self):
        root = make_repo(AFTER)
        self.addCleanup(shutil.rmtree, root, True)
        responses = roundtrip(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "blast_radius",
                        "arguments": {"diff": make_patch(BEFORE, AFTER), "root": str(root)},
                    },
                }
            ]
        )
        text = responses[0]["result"]["content"][0]["text"]
        self.assertIn("## blastr", text)
        self.assertIn("R002", text)

    def test_unknown_method_is_an_error(self):
        responses = roundtrip([{"jsonrpc": "2.0", "id": 9, "method": "does/not/exist"}])
        self.assertEqual(responses[0]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
