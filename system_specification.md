# SPEC.md: Universal Autonomous Topic Digest Pipeline

## 1. Project Overview & Objective

Build an autonomous, serverless pipeline running on **GitHub Actions** that fetches RSS feeds weekly based on a selected profile, filters articles through a profile-driven LLM evaluation (using the official **Google AI Studio / Gemini API Free Tier** to strip out noise and surface high-signal insights), and compiles them into a structured Markdown artifact. This artifact is stored in the repository and optimized for direct ingestion into **Google NotebookLM**, newsletters, or personal knowledge bases.

## 2. Technical Stack & Constraints

* **Language:** Python 3.11+

* **Dependencies:** `feedparser`, `requests`, `PyYAML`, `google-genai` (or official Gemini SDK)

* **Execution Environment:** GitHub Actions (Scheduled Cron & Manual Dispatch with profile selection)

* **LLM Integration:** Official Google AI Studio API (`GEMINI_API_KEY` stored in GitHub Secrets) using reliable free-tier quotas.

* **Storage:** Local Git repository (`digests/YYYY-WW-<profile>.md`)

## 3. Project Structure

```
topic-digest-pipeline/
├── .github/
│   └── workflows/
│       └── digest-pipeline.yml
├── config/
│   └── profiles.yaml
├── src/
│   ├── __init__.py
│   ├── fetcher.py
│   ├── filter.py
│   └── compiler.py
├── digests/
│   └── (Generated Markdown files)
├── requirements.txt
└── SPEC.md

```

## 4. Universal Configuration File (`config/profiles.yaml`)

*The system is completely domain-agnostic. New topics (e.g., AI SDLC, Health, Finance, DevOps) can be added simply by defining a new profile block here.*

```
profiles:
  # Example 1: Your primary domain of interest
  ai-sdlc-architecture:
    description: "Focus on multi-agent systems, context engineering, state management, and verifiable anchors in SDLC."
    rss_sources:
      - name: "Anthropic Research"
        url: "https://www.anthropic.com/index.xml"
      - name: "GitHub Next"
        url: "https://githubnext.com/index.xml"
      - name: "arXiv cs.SE (Software Engineering)"
        url: "http://export.arxiv.org/rss/cs.SE"
    keywords:
      - "context drift"
      - "AST"
      - "memory graph"
      - "agentic workflow"
      - "verification"
      - "RAG"
    signal_threshold: 8
    system_prompt: |
      You are a Principal Software Architect and AI Transformation Consultant. Evaluate incoming technical articles strictly based on their engineering value for enterprise SDLC/PDLC. 
      Filter out marketing hype and superficial product releases. 
      Prioritize fundamental architectural shifts, context management patterns, and verifiable code anchors.

  # Example 2: Secondary interest profile (e.g., Health & Biohacking)
  health-biohacking:
    description: "Focus on evidence-based longevity, athletic performance, sleep architecture, and metabolic health."
    rss_sources:
      - name: "Stronger By Science"
        url: "https://www.strongerbyscience.com/feed/"
    keywords:
      - "HRV"
      - "sleep architecture"
      - "hypertrophy"
      - "recovery metrics"
      - "zone 2"
    signal_threshold: 8
    system_prompt: |
      You are a sports physiologist and evidence-based longevity expert. Evaluate articles and studies strictly on clinical and practical significance for training, recovery, and metabolic health. Filter out commercial wellness marketing.

```

## 5. Core Python Modules Specification

### A. `src/fetcher.py`

* Reads `config/profiles.yaml` dynamically based on the CLI argument (`--profile`).

* Parses RSS feeds using `feedparser`, filtering items published within the last 7 days.

* Applies keyword pre-filtering to eliminate irrelevant articles.

### B. `src/filter.py`

* Connects to the **Gemini API** using `os.environ["GEMINI_API_KEY"]`.

* Evaluates candidate articles using the active profile's `system_prompt`.

* Requests structured JSON containing: `signal_score` (1-10), `core_idea` (1-2 sentences), and `key_takeaways` (list of 3 bullet points).

* Discards articles below `signal_threshold`.

### C. `src/compiler.py`

* Aggregates accepted items into a clean Markdown artifact saved at `digests/YYYY-WW-<profile>.md`.

* Formats content for seamless ingestion into NotebookLM or markdown-based tools.

## 6. GitHub Actions Workflow (`.github/workflows/digest-pipeline.yml`)

```
name: Universal Topic Digest Pipeline

on:
  schedule:
    - cron: '0 23 * * 0' # Every Sunday at 23:00 UTC
  workflow_dispatch:
    inputs:
      profile:
        description: 'Select Analysis Profile from profiles.yaml'
        required: true
        default: 'ai-sdlc-architecture'
        type: string

jobs:
  run-digest:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Digest Generator
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          python src/main.py --profile ${{ github.event.inputs.profile || 'ai-sdlc-architecture' }}

      - name: Commit and Push Digest
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git add digests/
          git commit -m "chore(digest): automated weekly sync for profile '${{ github.event.inputs.profile || 'ai-sdlc-architecture' }}'" || echo "No changes to commit"
          git push

```