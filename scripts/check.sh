#!/bin/bash
# Run the same checks as .github/workflows/test.yml locally.
set -e

echo "🔍 Running CI checks locally..."
echo

echo "📝 1. Linting (ruff check)..."
uv run ruff check .
echo "✅ Lint passed!"
echo

echo "🎨 2. Formatting (ruff format --check)..."
uv run ruff format --check .
echo "✅ Formatting passed!"
echo

echo "🔍 3. Type checking (mypy)..."
uv run mypy espn_fantasy_basketball_mcp/ espn_fantasy_basketball.py
echo "✅ Type checking passed!"
echo

echo "🧪 4. Tests with coverage (pytest)..."
uv run pytest --cov=espn_fantasy_basketball_mcp --cov-report=term-missing
echo "✅ Tests passed!"
echo

echo "🎉 All CI checks passed! Ready to push to GitHub."
