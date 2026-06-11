#!/usr/bin/env python3
from __future__ import annotations

from voice_notes_cli import dispatch, parse_args
from voice_notes_config import load_dotenv


def main() -> None:
    load_dotenv()
    args = parse_args()
    dispatch(args)


if __name__ == "__main__":
    main()
