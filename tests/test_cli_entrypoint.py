from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import voice_notes_ai  # noqa: E402


class CliEntrypointTests(unittest.TestCase):
    def test_entrypoint_stays_small_and_orchestration_only(self) -> None:
        path = SRC / "voice_notes_ai.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = [
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        ]

        self.assertLessEqual(len(source.splitlines()), 100)
        self.assertEqual(functions, ["main"])

    def test_main_loads_config_parses_and_dispatches(self) -> None:
        args = object()
        with (
            patch.object(voice_notes_ai, "load_dotenv") as load_config,
            patch.object(voice_notes_ai, "parse_args", return_value=args) as parse,
            patch.object(voice_notes_ai, "dispatch") as dispatch,
        ):
            voice_notes_ai.main()

        load_config.assert_called_once_with()
        parse.assert_called_once_with()
        dispatch.assert_called_once_with(args)


if __name__ == "__main__":
    unittest.main()
