#!/bin/bash

echo "Creating Python virtual environment named 'eraneos'..."
python3 -m venv eraneos

echo "Activating virtual environment..."
source eraneos/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing dependencies (with Apple Metal support)..."
pip install -r requirements.txt

echo "===================================================="
echo "Setup complete!"
echo "To activate the environment, run: source eraneos/bin/activate"
echo "To inspect the server in a browser UI, run: fastmcp dev inspector src/mcp_server.py"
echo "To call a tool directly, run: fastmcp call src/mcp_server.py ask_csv question=\"which columns exist\""
echo "To launch the Streamlit chat UI, run: python -m streamlit run src/app.py"
echo "===================================================="