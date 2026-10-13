#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根目录 validate_submission.py 入口
"""
import sys
from scripts.validate_submission import main, SubmissionValidator

__all__ = ["main", "SubmissionValidator"]

if __name__ == "__main__":
    sys.exit(main())
