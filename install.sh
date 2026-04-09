#!/bin/bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
ln -s $HOME/.cargo/bin/uv /usr/local/bin/uv || true
ln -s $HOME/.local/bin/uv /usr/local/bin/uv || true
