# Schema Audit Tool & Lead Generator

A comprehensive tool to discover local businesses, audit their technical SEO (Schema.org), and manage leads through a modern web interface.

## Quick Start

### 1. Prerequisites
- Python 3.12+
- Node.js & npm
- Google Places API Key

### 2. Setup
**Backend**
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your GOOGLE_PLACES_API_KEY
```

**Frontend**
```bash
cd client
npm install
cd ..
```

### 3. Running the App
To start both the backend API and the frontend web app with a single command:
```bash
./start.sh
```
- **Web App**: http://localhost:5173 (or 5174/5175 if busy)
- **API Docs**: http://localhost:8000/docs

## Features & Usage

### 🔍 Discovery
1.  Navigate to the **Discovery** tab in the web app.
2.  Enter a query like _"Landscapers in Boise, ID"_.
3.  The system uses the Google Places API to find businesses and save them to the database.

### 📋 Leads & Audits
1.  Go to the **Leads** tab to see all discovered businesses.
2.  **Run Audit**: Click the "Play" button to audit a website's Schema markup.
    - **Pass/Fail Criteria**:
        - **Schema Exists**: Does the site have JSON-LD?
        - **sameAs**: Does it link back to the Google Map profile?
        - **Category**: Do the schema types match Google Categories?
        - **NAP**: Is Name, Address, Phone consistent?
3.  **Score**: Leads are scored 0-5. Lower score = Hotter lead (more issues found).

### 📞 Contact Tracking
- Use the dropdown on each lead card to update status:
    - **NEW**: Fresh lead.
    - **CONTACTED**: Outreach sent.
    - **REPLIED**: Conversation started.
    - **CLOSED**: Deal won/lost.

## Project Structure
- `api.py`: FastAPI backend.
- `client/`: React + Vite frontend source code.
- `db.py`: Database models and SQLite logic.
- `analyzer.py`: Core audit logic.
- `discovery.py`: Google Places integration.
- `leads.db`: SQLite database file (auto-created).

## Advanced Usage (CLI)
You can still use the command line tools if preferred:
```bash
python main.py discover "Query"
python main.py audit-all
python main.py status
```
