#!/bin/bash
set -e

echo "🔍 Running CI checks locally..."
echo

echo "📝 1. Running linting (ruff)..."
uv run ruff check .
echo "✅ Linting passed!"
echo

echo "🔍 2. Running type checking (mypy)..."
uv run mypy espn_fantasy_basketball_mcp/
echo "✅ Type checking passed!"
echo

echo "🧪 3. Running tests with coverage..."
uv run pytest --cov=espn_fantasy_basketball_mcp --cov-report=term-missing
echo "✅ Tests passed!"
echo

echo "🎉 All CI checks passed! Ready to push to GitHub."