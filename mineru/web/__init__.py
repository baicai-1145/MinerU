# SPDX-FileCopyrightText: 2024 MinerU Contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Web service utilities for MinerU.

This package hosts reusable components that power higher level web
experiences (e.g. task orchestration for the upcoming Vue Web UI).
The implementation follows the project's KISS/SOLID guidelines by
keeping responsibilities focused and decoupled from FastAPI glue code.
"""

__all__ = ["task_service"]
