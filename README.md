# Women's Health AI Agent

An AI-powered research and health assistant designed to provide evidence-based information on women's health topics (such as PCOS/PCOD, wellness habits, and general health awareness). Powered by LangChain, LangGraph, Groq, DuckDuckGo Search, and Wikipedia.

## Features

- **Tool-Calling Agent**: Uses DuckDuckGo Search and Wikipedia to research medical topics and health queries in real time.
- **Structured Health Insights**: Uses Pydantic to format outputs into structured responses (`topic`, `summary`, `Disease`, `HealthStatus`, `Habits`).
- **Research Logging**: Automatically logs research findings with timestamps to `research_output.txt`.

## Project Structure

```
├── main.py              # Main application script & agent pipeline
├── tools.py             # Custom LangChain tools (search, wikipedia, save)
├── REQUIREMENTS.txt     # Python package dependencies
├── research_output.txt  # Saved research outputs
├── .env.example         # Template for environment variables
└── .gitignore           # Git ignore patterns
```

## Setup & Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/KANAK0708/Women-s-Health-AI-AGENT.git
   cd Women-s-Health-AI-AGENT
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r REQUIREMENTS.txt
   ```

4. **Configure Environment Variables**:
   Create a `.env` file in the root directory (based on `.env.example`):
   ```bash
   cp .env.example .env
   ```
   Add your API keys:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   GEMINI_API_KEY=your_gemini_api_key_here
   GOOGLE_API_KEY=your_google_api_key_here
   ```

5. **Run the Agent**:
   ```bash
   python main.py
   ```

## Disclaimer

This agent is intended for informational and research purposes only. It is not a substitute for professional medical advice, diagnosis, or treatment. Always consult a qualified healthcare provider for any health-related concerns.
