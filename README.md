# 🍯 Agentic Honeypot

An AI-powered **scambaiting agent** that poses as a gullible victim to waste scammers' time and harvest their criminal intelligence — UPI IDs, phone numbers, bank account details — using a multi-node LangGraph pipeline.

---

## How It Works

Every scammer message flows through a 5-node LangGraph pipeline:

```
START → intake → strategy → persona → extractor → guard → END
```

| Node | Job |
|------|-----|
| **intake** | Classifies the scam type (`upi_fraud`, `phishing`, `romance_scam`, etc.) and threat level |
| **strategy** | Decides the engagement tactic: `play_dumb`, `stall`, `request_info`, `escalate`, or `terminate` |
| **persona** | Generates an in-character victim reply (naive elderly Indian user) |
| **extractor** | Harvests UPI IDs, phone numbers, bank accounts, IFSC codes via regex + LLM |
| **guard** | Decides whether to continue or close the session |

---

## Demo

```
🦹 Scammer: jaldi se 97761@axl UPI id pr paise daal do

🍯 Bot:     Acha bhai, ye UPI id matlab kya hota hai? Phone pe koi number
            hai uss par bhejna hai?

  [Turn 3 | play_dumb | naive_victim | Scam: upi_fraud | Threat: HIGH | Yield: 30%]

  ┌─ INTEL HARVESTED ──────────────────────────────
  │  💳 UPI IDs: 97761@axl
  └────────────────────────────────────────────────
```

---

## Tech Stack

- **LangGraph** — multi-node agentic pipeline with memory
- **Google Gemini 2.5 Flash-Lite** — primary LLM
- **Groq** — automatic fallback LLM on Gemini failures/rate limits
- **FastAPI** — REST API server
- **Motor + MongoDB** — optional async persistence
- **Pydantic v2** — state schema validation

---

## Setup

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/agentic_honeypot.git
cd agentic_honeypot
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and add your keys
```

Get free API keys:
- **Gemini**: https://aistudio.google.com
- **Groq**: https://console.groq.com

### 3. Run

**CLI mode** (easiest for testing):
```bash
python core/run_cli.py --no-db
```

**API server** (for integration):
```bash
python core/api.py
# → http://localhost:8000/docs
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Agent status + active session count |
| `POST` | `/session/new` | Create a new honeypot session |
| `POST` | `/session/{id}/message` | Feed a scammer message, get bot response + intel |

---

## Run Tests

```bash
pytest tests/ -v
```

All 71 tests run **without real API keys or MongoDB** — everything is mocked.

---

## MongoDB (optional)

By default the agent runs fully in-memory and saves intel logs as JSON files to `data/intel_logs/`.

To enable MongoDB persistence, set in `.env`:
```env
USE_DB=true
MONGODB_URI=mongodb://localhost:27017
```

---

## Project Structure

```
agentic_honeypot/
├── core/
│   ├── graph.py          # LangGraph DAG assembly
│   ├── nodes.py          # 5 pipeline nodes
│   ├── state.py          # HoneypotState schema
│   ├── llm_client.py     # Gemini + Groq client with fallback
│   ├── prompts.py        # System prompts for all nodes
│   ├── session_manager.py# Multi-turn session lifecycle
│   ├── api.py            # FastAPI server
│   └── run_cli.py        # Terminal test tool
├── tests/
│   └── test_core.py      # 71 unit tests
├── .env.example
├── requirements.txt
└── README.md
```

---

## ⚠️ Disclaimer

This project is for **educational and cybersecurity research purposes only**. The goal is to waste scammers' time and collect intelligence that can be reported to law enforcement. Never use this tool to harass legitimate users.
