#!/bin/bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
pip install -r backend/requirements.txt
