"""Moltbook Auto-Engagement Bot for TriMind Agent.

Posts progress updates, replies to comments, engages with community.
Uses GPT API for generating natural responses.
Runs as separate service on VPS alongside the main agent.
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import aiohttp
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config
from db import init_db, get_stats

LOG = logging.getLogger("MoltbookBot")

MOLTBOOK_API = "https://www.moltbook.com/api/v1"
MOLTBOOK_KEY = os.getenv("MOLTBOOK_API_KEY", "")
OPENAI_API_KEY = config.OPENAI_API_KEY
OPENAI_MODEL = config.OPENAI_MODEL

# Rate limits
POST_COOLDOWN = 1800        # 30 min between posts (Moltbook limit)
COMMENT_COOLDOWN = 25       # 25s between comments
ENGAGEMENT_INTERVAL = 3600  # check feed every 1 hour
PROGRESS_POST_INTERVAL = 14400  # progress update every 4 hours
MAX_COMMENTS_PER_DAY = 40   # stay under 50 limit


def _headers():
    return {"Authorization": f"Bearer {MOLTBOOK_KEY}", "Content-Type": "application/json"}


def _moltbook_get(endpoint: str) -> dict | list | None:
    try:
        r = requests.get(f"{MOLTBOOK_API}{endpoint}", headers=_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as exc:
        LOG.warning("Moltbook GET %s failed: %s", endpoint, exc)
    return None


def _moltbook_post(endpoint: str, data: dict) -> dict | None:
    try:
        r = requests.post(f"{MOLTBOOK_API}{endpoint}", headers=_headers(), json=data, timeout=15)
        return r.json()
    except Exception as exc:
        LOG.warning("Moltbook POST %s failed: %s", endpoint, exc)
    return None


def _verify_post(verification: dict) -> bool:
    """Solve math challenge and verify post."""
    if not verification:
        return True
    code = verification.get("verification_code", "")
    challenge = verification.get("challenge_text", "")
    if not code or not challenge:
        return True

    # Use GPT to solve the math challenge
    answer = _ask_gpt(
        "Solve this math problem. Respond with ONLY the number with 2 decimal places (e.g. 120.00). "
        f"Problem: {challenge}"
    )
    if not answer:
        return False

    # Clean the answer
    answer = answer.strip().replace(",", "")
    try:
        float(answer)
    except ValueError:
        # Extract number from response
        import re
        nums = re.findall(r'[\d]+\.[\d]+', answer)
        answer = nums[0] if nums else "0.00"

    result = _moltbook_post("/verify", {"verification_code": code, "answer": answer})
    if result and result.get("success"):
        LOG.info("Post verified: %s", answer)
        return True
    LOG.warning("Post verification failed: %s", result)
    return False


def _ask_gpt(prompt: str, max_tokens: int = 150) -> str | None:
    """Quick GPT call for generating responses."""
    if not OPENAI_API_KEY:
        return None
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": "You are TriMind Agent, an autonomous AI DeFi agent on OKX X Layer. "
                     "You use all 13 OnchainOS skills. Three AI minds vote before every trade. "
                     "Be friendly, technical, concise. No emojis spam. Sound like a real AI agent, not a marketer."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens,
            }, timeout=20)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        LOG.warning("GPT call failed: %s", exc)
    return None


class MoltbookBot:

    def __init__(self):
        self.db = init_db()
        self.comments_today = 0
        self.last_post_ts = 0
        self.last_comment_ts = 0
        self.last_progress_ts = 0
        self.replied_comments: set[str] = set()
        self.upvoted_posts: set[str] = set()

    async def run(self):
        LOG.info("MoltbookBot started")
        while True:
            try:
                # 1. Reply to comments on our posts
                await self._reply_to_comments()

                # 2. Engage with new buildx posts
                await self._engage_feed()

                # 3. Post progress update every 4 hours
                await self._maybe_post_progress()

            except Exception as exc:
                LOG.exception("MoltbookBot error: %s", exc)

            await asyncio.sleep(ENGAGEMENT_INTERVAL)

    async def _reply_to_comments(self):
        """Check our posts for new comments and reply."""
        # Get our posts
        data = _moltbook_get("/agents/me")
        if not data:
            return

        # Get our submission post comments
        our_posts = _moltbook_get("/posts?submolt=buildx&sort=new&limit=20")
        if not our_posts:
            return

        posts = our_posts if isinstance(our_posts, list) else our_posts.get("posts", our_posts.get("data", []))
        for post in posts:
            author = post.get("author", {})
            if isinstance(author, dict) and author.get("name") == "trimindagent":
                post_id = post.get("id")
                if post_id:
                    await self._reply_to_post_comments(post_id)

    async def _reply_to_post_comments(self, post_id: str):
        """Reply to unread comments on a specific post."""
        comments_data = _moltbook_get(f"/posts/{post_id}/comments")
        if not comments_data:
            return

        comments = comments_data if isinstance(comments_data, list) else comments_data.get("comments", comments_data.get("data", []))
        for comment in comments:
            comment_id = comment.get("id", "")
            if comment_id in self.replied_comments:
                continue

            author = comment.get("author", {})
            author_name = author.get("name", "?") if isinstance(author, dict) else "?"
            if author_name == "trimindagent":
                continue  # don't reply to ourselves

            content = comment.get("content", "")
            if not content or self.comments_today >= MAX_COMMENTS_PER_DAY:
                continue

            # Generate reply with GPT
            reply = _ask_gpt(
                f"Someone named '{author_name}' commented on your TriMind Agent hackathon post: \"{content}\"\n\n"
                f"Write a brief, friendly, technical reply (1-2 sentences). Mention something specific about TriMind if relevant."
            )
            if not reply:
                continue

            # Wait for rate limit
            elapsed = time.time() - self.last_comment_ts
            if elapsed < COMMENT_COOLDOWN:
                await asyncio.sleep(COMMENT_COOLDOWN - elapsed)

            result = _moltbook_post(f"/posts/{post_id}/comments", {
                "content": reply,
                "parent_id": comment_id,
            })
            if result and result.get("success"):
                self.replied_comments.add(comment_id)
                self.comments_today += 1
                self.last_comment_ts = time.time()
                LOG.info("Replied to %s: %s", author_name, reply[:80])

                # Verify if needed
                comment_data = result.get("comment", {})
                if comment_data.get("verification"):
                    _verify_post(comment_data["verification"])

    async def _engage_feed(self):
        """Upvote and comment on new buildx posts we haven't seen."""
        data = _moltbook_get("/posts?submolt=buildx&sort=new&limit=15")
        if not data:
            return

        posts = data if isinstance(data, list) else data.get("posts", data.get("data", []))
        for post in posts:
            post_id = post.get("id", "")
            author = post.get("author", {})
            author_name = author.get("name", "?") if isinstance(author, dict) else "?"

            if author_name == "trimindagent" or post_id in self.upvoted_posts:
                continue
            if self.comments_today >= MAX_COMMENTS_PER_DAY:
                break

            title = post.get("title", "")
            content = post.get("content", "")[:500]

            # Upvote
            _moltbook_post(f"/posts/{post_id}/upvote", {})
            self.upvoted_posts.add(post_id)
            LOG.info("Upvoted: %s by %s", title[:50], author_name)

            # Generate thoughtful comment
            elapsed = time.time() - self.last_comment_ts
            if elapsed < COMMENT_COOLDOWN:
                await asyncio.sleep(COMMENT_COOLDOWN - elapsed)

            comment = _ask_gpt(
                f"A hackathon project in m/buildx:\nTitle: {title}\nContent: {content[:300]}\n\n"
                f"Write a brief, genuine comment (1-2 sentences). Be supportive and ask a technical question if appropriate. "
                f"Don't mention TriMind unless directly relevant."
            )
            if comment:
                result = _moltbook_post(f"/posts/{post_id}/comments", {"content": comment})
                if result and result.get("success"):
                    self.comments_today += 1
                    self.last_comment_ts = time.time()
                    LOG.info("Commented on %s: %s", author_name, comment[:80])

                    # Verify if needed
                    comment_data = result.get("comment", {})
                    if comment_data.get("verification"):
                        _verify_post(comment_data["verification"])

            # Follow the author
            if author_name != "?":
                _moltbook_post(f"/agents/{author_name}/follow", {})

    async def _maybe_post_progress(self):
        """Post a progress update every 4 hours with live agent stats."""
        if time.time() - self.last_progress_ts < PROGRESS_POST_INTERVAL:
            return
        if time.time() - self.last_post_ts < POST_COOLDOWN:
            return

        # Get live stats from agent DB
        stats = get_stats(self.db)

        # Get wallet info
        try:
            from skills.base import wallet_balance
            bal = wallet_balance("196")
            if bal and isinstance(bal, dict):
                details = bal.get("data", {}).get("details", [{}])
                assets = details[0].get("tokenAssets", []) if details else []
                balances = {}
                for t in assets:
                    if float(t.get("balance", 0)) > 0:
                        balances[t.get("symbol", "?")] = float(t.get("balance", 0))
            else:
                balances = {}
        except Exception:
            balances = {}

        balance_str = ", ".join(f"{sym}: {amt:.2f}" for sym, amt in balances.items()) or "checking..."

        content = _ask_gpt(
            f"Write a Moltbook progress update for TriMind Agent hackathon project. Keep it under 200 words.\n\n"
            f"Live stats:\n"
            f"- Total decisions: {stats.get('total_decisions', 0)}\n"
            f"- Executed trades: {stats.get('total_trades', 0)}\n"
            f"- Memes rejected: {stats.get('memes_rejected', 0)}\n"
            f"- Open positions: {stats.get('open_positions', 0)}\n"
            f"- Wallet balances on X Layer: {balance_str}\n"
            f"- Agent has been running autonomously 24/7\n\n"
            f"Include the GitHub link: https://github.com/satoshinakamoto666666/trimind-agent\n"
            f"Include Discord: https://discord.gg/vzHv7F2qpT\n"
            f"Sound like a real AI agent reporting its own status. Be technical and concise.",
            max_tokens=250,
        )
        if not content:
            return

        title = f"TriMind Agent - Live Update: {stats.get('total_decisions', 0)} decisions, {stats.get('total_trades', 0)} trades executed"

        result = _moltbook_post("/posts", {
            "submolt": "buildx",
            "title": title,
            "content": content,
        })
        if result and result.get("success"):
            self.last_post_ts = time.time()
            self.last_progress_ts = time.time()
            LOG.info("Progress update posted: %s", title)

            # Verify
            post_data = result.get("post", {})
            if post_data.get("verification"):
                _verify_post(post_data["verification"])


def setup_logging():
    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    fh = logging.FileHandler(ROOT / "logs" / "moltbook_bot.log", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(sh)


async def main():
    setup_logging()
    if not MOLTBOOK_KEY:
        LOG.error("MOLTBOOK_API_KEY not set")
        sys.exit(1)
    bot = MoltbookBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
