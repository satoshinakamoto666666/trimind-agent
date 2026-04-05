# AlphaAgentX

> Autonomous AI DeFi Agent for OKX X Layer | Build-X Hackathon 2026

## What is AlphaAgentX?

An autonomous AI-powered agent deployed on X Layer that leverages OnchainOS skills to detect opportunities, assess risks, and execute DeFi strategies -- all with near-zero gas costs.

## Features

- Multi-AI consensus engine (Claude + GPT + Grok)
- Real-time signal intelligence via OnchainOS
- Automated DeFi execution on X Layer
- Security scanning before every interaction
- Self-learning risk assessment
- Discord dashboard with live monitoring

## Tech Stack

- **Chain**: OKX X Layer (chain 196)
- **Skills**: OnchainOS (13 skills, 72 features)
- **AI**: Claude Opus 4.6, GPT 5.4, Grok 4.20
- **Runtime**: Python 3.12, VPS 24/7
- **Interface**: Discord bot with rich embeds

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in your keys
python src/agent.py
```

## OnchainOS Skills Used

| Skill | Usage |
|-------|-------|
| okx-agentic-wallet | Wallet management, auth, balance |
| okx-dex-swap | Trade execution on X Layer |
| okx-dex-signal | Smart money / KOL tracking |
| okx-dex-trenches | Token scanning, dev reputation |
| okx-dex-token | Token metadata, rankings |
| okx-dex-market | Real-time pricing |
| okx-security | Token risk scanning |
| okx-defi-invest | Aave V3 interactions |
| okx-defi-portfolio | Cross-protocol positions |
| okx-wallet-portfolio | Address balance queries |
| okx-onchain-gateway | Gas estimation, tx simulation |
| okx-x402-payment | Gas-free transactions |
| okx-audit-log | Transaction audit trail |

## Hackathon

- **Track**: X Layer Arena
- **Competition**: OKX Build-X Hackathon (April 1-15, 2026)
- **Prize Pool**: 14,000 USDT

## License

MIT
