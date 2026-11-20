# Google Map Extractor (GME) — v3.0

> **AI-Powered Google Maps Business Lead Extractor & Autonomous Prospecting Co-Pilot**  
> *Developed & Maintained by [Brain Lead](https://brainlead.dev)*

[![Platform](https://img.shields.io/badge/Platform-Windows%2064--bit-blue.svg?style=flat-square)](https://brainlead.dev)
[![Architecture](https://img.shields.io/badge/Architecture-Native%20C%2FC%2B%2B%20(Nuitka)-orange.svg?style=flat-square)](https://brainlead.dev)
[![AI Engine](https://img.shields.io/badge/AI%20Autopilot-Gemini%20%7C%20Claude%20%7C%20OpenAI%20%7C%20Ollama-purple.svg?style=flat-square)](https://brainlead.dev)
[![Build Status](https://img.shields.io/badge/Build-Verified%20Release-brightgreen.svg?style=flat-square)](https://brainlead.dev)
[![License](https://img.shields.io/badge/License-Commercial%20%2F%20Trial-yellow.svg?style=flat-square)](https://t.me/BrainLeadBot)
[![Support](https://img.shields.io/badge/Support-Telegram%20%40brain__lead-blue.svg?style=flat-square)](https://t.me/brain_lead)

---

## ⚡ Overview

**Google Map Extractor (GME) v3.0** is an enterprise desktop intelligence platform that combines high-speed Google Maps scraping with an autonomous **AI Prospecting Co-Pilot & Autopilot**.

GME extracts verified local business leads across any geography, crawls target business websites to audit their technical stack and digital presence, and deploys intelligent multi-turn AI agents to identify high-revenue businesses with critical operational pain points (e.g. broken websites, missing mobile viewports, high OTA commission leakage) and automatically draft customized cold outreach pitches.

Compiled directly into native C/C++ machine code with **Nuitka** and digitally signed with Authenticode, GME runs as a high-performance local desktop application with zero external cloud dependencies or recurring per-query API bills.

---

## 🚀 Key Capabilities

### 1. 🤖 Autonomous AI Co-Pilot & Autopilot (BYOK)
- **Multi-Provider Bring-Your-Own-Key**: Seamlessly connect your choice of LLM:
  - **Google Gemini**: Gemini 2.5 Flash, 2.5 Flash-Lite, 2.5 Pro, 3.0 Flash (with official `thoughtSignature` support & `x-goog-api-key` auth header).
  - **Anthropic Claude**: Claude 3.5 Sonnet, 3.5 Haiku, 3 Opus (with ephemeral prompt caching).
  - **OpenAI**: GPT-4o, GPT-4o-mini, o1, o3-mini (with automatic reasoning token budgeting).
  - **Local Ollama**: 100% offline private local LLMs (`llama3`, `mistral`, `deepseek-r1`, `qwen2.5`).
- **Live Small → Big Model Selection**: Dynamically discover available models sorted by speed and capability.
- **Autonomous Tool-Calling Loop**: Built-in 20-tool agentic engine that executes natural conversational missions, queries datasets, triggers targeted keyword searches, reads customer reviews, performs technical audits, and shortlists top prospects.
- **Audited Execution Logs**: Full real-time SQLite and `ai_runs.log` audit traces tracking every tool invocation, latency, and model output.

### 2. 🗺️ High-Density Scraping & Polygon Area Scan
- **Polygon Boundary Mapping**: Draw custom polygon search areas on an interactive Leaflet map to extract 100% of businesses across cities, counties, and postal zones without missing blind spots.
- **Adaptive Grid Subdivision**: Automatically fragments large geographic areas into micro-tiles with intelligent zoom levels to capture exhaustive local directories.
- **Google Search Emulation**: High-speed asynchronous requests with automatic cookie generation, proxy pool rotation, and anti-detection headers.

### 3. 🔍 Deep Contact & Technical Enrichment
- **Complete Business Identity**: Extracts business name, address, latitude/longitude, primary category, phone numbers, website URL, Google review rating, and review counts.
- **Multi-Channel Contact Discovery**: Crawls business homepages, contact pages, and about pages to discover verified emails, phone numbers, and direct social links (Instagram, Facebook, LinkedIn, Twitter/X, YouTube).
- **Technical Stack & Viewport Audits**: Inspects target websites for responsive viewports, SSL encryption, platform CMS (WordPress, Shopify, Wix, Squarespace, PHP), and conversion tracking pixels.

### 4. 🎯 Automated Cold Outreach Pitches
- **Pain Point Detection**: Flags high-revenue businesses suffering from broken sites, zero online footprint, or lack of direct booking engines.
- **Tailored Pitch Angles**: Generates personalized email subject lines, custom pitch letters, and follow-up sequences mapped directly to each lead's specific technical weaknesses.

### 5. 📊 Dual-View Interactive Workspace
- **Adaptive UI**: Collapsible sidebar, expandable dual-pane views, and rich Markdown and HTML data tables.
- **Multi-Format Exports**: Export leads and AI audits to CSV, Excel (`.xlsx`), JSON, and standard CRM formats.

---

## 🖥️ Architecture & Free Tier vs. Licensed

| Feature | Free Trial Tier | Licensed (Full Version) |
|---|---|---|
| **Results Per Search** | Capped at 50 leads | **Unlimited** |
| **Area Scan Tiles** | Max 4 tiles | **Unlimited** |
| **AI Co-Pilot & Autopilot** | Enabled (BYOK) | **Unlimited** |
| **Website & Contact Crawl** | Enabled | **Unlimited** |
| **Data Exports (CSV/XLSX)** | Limited to 50 leads | **Unlimited** |
| **Updates & Priority Support**| Community | **Direct Telegram Support** |

---

## 📦 Getting Started

### Quick Start with Pre-Compiled Executable:
1. Download **`Google_Map_Extractor_v3.0.zip`** from the **[Releases](../../releases)** section.
2. Extract the archive to a folder on your Windows PC.
3. Right-click **`Trust_Certificate.bat`** and choose **Run as administrator** to register the Brain Lead Authenticode certificate.
4. Double-click **`Google_Map_Extractor.exe`**.
5. Your default browser will automatically open to `http://127.0.0.1:8000/`.

---

## 🛠️ Building From Source (Developers)

Compile directly to native C/C++ machine code using **Nuitka**:

```powershell
# 1. Install dependencies
pip install -r requirements.txt
pip install nuitka zstandard

# 2. Build React frontend
cd frontend
npm install
npm run build
cd ..

# 3. Compile native Windows binary & sign with Authenticode
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -Standalone
```

The compiled native executable, DLLs, Authenticode certificate, and clean release package will be generated inside `release\Google_Map_Extractor_v3.0\`.

---

## 🛒 Commercial Licensing & Upgrades

To activate unlimited leads, enterprise concurrency, and priority support:
- 🤖 **Automated Telegram Bot**: [@BrainLeadBot](https://t.me/BrainLeadBot)
- 💬 **Support & Custom Scripts**: [@brain_lead](https://t.me/brain_lead)
- 🌐 **Official Website**: [brainlead.dev](https://brainlead.dev)

---

## ⚖️ Legal Disclaimer

This software is developed strictly for **authorized business intelligence, lead generation, and CRM data hygiene**. Users are solely responsible for ensuring compliance with all applicable local and international regulations, including GDPR, CAN-SPAM, and relevant platform terms.
